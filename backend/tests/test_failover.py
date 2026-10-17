"""Breaker, флаги блокировки и цепочка переключения источников (без сети: ответы — из fixtures)."""
import asyncio
import time

import pytest

from app import config, store
from app.collector import Collector
from app.sources.base import CircuitOpen, Source, SourceDisabled, SourceError

from .conftest import load, ls_bundle, sofa_bundle


class Flaky(Source):
    name = "flaky"

    def __init__(self, fail=True):
        super().__init__()
        self.fail = fail
        self.calls = 0

    async def _fetch(self, url, params):
        self.calls += 1
        if self.fail:
            raise TimeoutError("timeout")
        return {"ok": True}


def run(coro):
    return asyncio.run(coro)


def test_breaker_opens_after_threshold_and_recovers(monkeypatch):
    monkeypatch.setattr(config, "BREAKER_THRESHOLD", 3)
    monkeypatch.setattr(config, "BREAKER_COOLDOWN", 60)
    s = Flaky()
    for _ in range(3):
        with pytest.raises(SourceError):
            run(s.get("x"))
    assert s.state == "open" and s.calls == 3
    with pytest.raises(CircuitOpen):  # пока открыт — в сеть не ходим
        run(s.get("x"))
    assert s.calls == 3 and s.skipped_open == 1
    s.open_until = time.time() - 1      # пауза вышла → half_open → пробный запрос
    s.fail = False
    assert run(s.get("x")) == {"ok": True}
    assert s.state == "closed" and s.consecutive_failures == 0
    snap = s.snapshot()
    assert snap["requests"] == 4 and snap["errors"] == 3 and snap["trips"] == 1 and snap["last_ok"]


def test_half_open_failure_doubles_cooldown(monkeypatch):
    monkeypatch.setattr(config, "BREAKER_THRESHOLD", 1)
    monkeypatch.setattr(config, "BREAKER_COOLDOWN", 60)
    s = Flaky()
    with pytest.raises(SourceError):
        run(s.get("x"))
    first = s.open_until - time.time()
    s.open_until = time.time() - 1
    with pytest.raises(SourceError):
        run(s.get("x"))
    assert s.state == "open" and (s.open_until - time.time()) > first * 1.9


def test_disabled_by_env_and_file(tmp_db, monkeypatch):
    s = Flaky(fail=False)
    s.name = "fotmob"
    monkeypatch.setenv("DISABLED_SOURCES", "fotmob")
    with pytest.raises(SourceDisabled):
        run(s.get("x"))
    monkeypatch.delenv("DISABLED_SOURCES")
    assert run(s.get("x")) == {"ok": True}
    (tmp_db / "disabled_sources").write_text("sofascore\nfotmob\n")
    with pytest.raises(SourceDisabled):
        run(s.get("x"))
    assert s.calls == 1


# ---------- цепочка матча ----------

def _fake_collector(conn, monkeypatch):
    c = Collector(conn)
    fm_raw = load("fotmob_match_6106274.json")
    sb = sofa_bundle()
    calls = {"fotmob": 0, "sofascore": 0, "espn": 0, "livescore": 0}

    async def fm_fetch(url, params):
        calls["fotmob"] += 1
        return fm_raw

    async def ss_fetch(url, params):
        calls["sofascore"] += 1
        part = url.rsplit("/16938872", 1)[-1].strip("/") or "event"
        return {"event": sb["event"], "incidents": sb["incidents"], "lineups": sb["lineups"],
                "statistics": sb["statistics"], "shotmap": sb["shotmap"], "graph": sb["graph"],
                "best-players/summary": sb["best"]}[part]

    async def es_fetch(url, params):
        calls["espn"] += 1
        return load("espn_summary_401915414.json")

    async def ls_fetch(url, params):
        calls["livescore"] += 1
        part = url.split("/app/")[1].split("/")[0]
        return ls_bundle()[part]

    monkeypatch.setattr(c.fm, "_fetch", fm_fetch)
    monkeypatch.setattr(c.ss, "_fetch", ss_fetch)
    monkeypatch.setattr(c.es, "_fetch", es_fetch)
    monkeypatch.setattr(c.ls, "_fetch", ls_fetch)
    store.map_set(conn, "match", "sofascore", "16938872", "6106274")
    store.map_set(conn, "match", "espn", "401915414", "6106274", "uefa.champions")
    store.map_set(conn, "match", "livescore", "1882774", "6106274")
    return c, calls


def test_match_chain_failover(tmp_db, monkeypatch):
    conn = store.connect()
    c, calls = _fake_collector(conn, monkeypatch)
    flag = tmp_db / "disabled_sources"

    def drop():  # проверяем саму цепочку: прежний полный снимок не должен перекрывать резерв
        conn.execute("DELETE FROM snapshots WHERE key='match:6106274'")

    m = run(c.refresh_match("6106274"))
    assert m["source"] == "fotmob" and calls["sofascore"] == 0
    assert store.get(conn, "ctx:match:6106274")  # номера/имена FotMob для фото у резервов

    flag.write_text("fotmob")
    drop()
    m = run(c.refresh_match("6106274"))
    assert m["source"] == "sofascore"
    assert {"ratings", "shotmap", "momentum", "player_photos"} <= set(m["available"])
    assert m["id"] == 6106274 and m["fallback_errors"]["fotmob"] == "disabled"

    flag.write_text("fotmob,sofascore")
    drop()
    m = run(c.refresh_match("6106274"))
    assert m["source"] == "espn"
    assert not {"ratings", "xg", "shotmap", "momentum"} & set(m["available"])

    flag.write_text("fotmob,sofascore,espn")
    drop()
    m = run(c.refresh_match("6106274"))
    assert m["source"] == "livescore"

    before = store.get(conn, "match:6106274")
    flag.write_text("fotmob,sofascore,espn,livescore")
    assert run(c.refresh_match("6106274")) is None
    after = store.get(conn, "match:6106274")
    assert after == before  # все упали — последний снимок не тронут

    flag.write_text("")
    assert run(c.refresh_match("6106274"))["source"] == "fotmob"
    run(c.close())


def test_breaker_open_skips_to_next_source(tmp_db, monkeypatch):
    conn = store.connect()
    c, calls = _fake_collector(conn, monkeypatch)

    async def boom(url, params):
        calls["fotmob"] += 1
        raise ConnectionError("down")

    monkeypatch.setattr(c.fm, "_fetch", boom)
    monkeypatch.setattr(config, "BREAKER_THRESHOLD", 2)
    for _ in range(4):
        assert run(c.refresh_match("6106274"))["source"] == "sofascore"
    assert calls["fotmob"] == 2 and c.fm.state == "open"  # после 2 ошибок FotMob больше не дёргаем
    run(c.close())


def test_live_cycles_spare_sofascore(tmp_db, monkeypatch):
    """В лайве SofaScore: event+incidents каждый цикл, тяжёлые части — раз в 3 цикла."""
    conn = store.connect()
    c, calls = _fake_collector(conn, monkeypatch)
    (tmp_db / "disabled_sources").write_text("fotmob")
    for _ in range(6):
        run(c.refresh_match("6106274", live=True))
    by = c.ss.by_kind
    assert by["event"] == 6 and by["incidents"] == 6 and by["statistics"] == 2 and by["shotmap"] == 2
    run(c.close())


def test_mapping_by_kickoff_when_names_differ(tmp_db):
    """«Racing Santander» (FotMob) / «Real Racing Club» (SofaScore): матч Реала находится по времени."""
    from app.model import ts
    from app.sources import fotmob
    conn = store.connect()
    c = Collector(conn)
    fixtures = fotmob.normalize_fixtures(load("fotmob_team_8633.json"))
    evs = load("sofa_team_last.json")["events"] + load("sofa_team_next.json")["events"]
    items = [(str(e["id"]), e["startTimestamp"], e["homeTeam"]["name"], e["awayTeam"]["name"],
              e["homeTeam"]["id"], e["awayTeam"]["id"], None) for e in evs]
    n = c._map_list(fixtures, "sofascore", items)
    racing = next(f for f in fixtures if f["home"]["name"] == "Racing Santander")
    assert store.from_fotmob(conn, "match", "sofascore", racing["id"])
    assert store.from_fotmob(conn, "match", "sofascore", 6106274) == "16938872"
    assert store.to_fotmob(conn, "team", "sofascore", 2702) == "8686"  # Рома
    # всё, что SofaScore отдаёт в двух страницах (до ноября), сопоставлено
    horizon = max(e["startTimestamp"] for e in evs)
    assert n == sum(1 for f in fixtures if ts(f["kickoff"]) <= horizon + 3600)
    run(c.close())
