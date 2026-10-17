"""Полнота снимка матча: завершённый — бедный не затирает полный; идущий — недостающие блоки из прошлого."""
import asyncio
import copy
import time

from app import config, store
from app.collector import borrow_live_blocks, keep_fuller
from app.model import status
from app.sources import espn, fotmob

from .conftest import load
from .test_failover import _fake_collector


def run(coro):
    return asyncio.run(coro)


def _fm():
    return fotmob.normalize_match(load("fotmob_match_6106274.json"))


def _es():
    return espn.normalize_match(load("espn_summary_401915414.json"), {})


def _snap(m, age_s, source=None):
    return {"source": source or m["source"], "fetched_at": time.time() - age_s, "data": m}


def _live(m, minute=60):
    m["status"] = status("live", minute)
    return m


# ---------- завершённый матч ----------

def test_finished_full_snapshot_not_replaced_by_poorer(tmp_db, monkeypatch):
    """FotMob дал 18 пунктов, потом FotMob выключен и ESPN приносит 6 — в базе остаётся FotMob."""
    conn = store.connect()
    c, calls = _fake_collector(conn, monkeypatch)
    m = run(c.refresh_match("6106274"))
    assert m["source"] == "fotmob" and len(m["available"]) == 18
    (tmp_db / "disabled_sources").write_text("fotmob,sofascore")
    got = run(c.refresh_match("6106274"))
    assert calls["espn"] == 1                       # ESPN спросили, но его снимок беднее
    assert got["source"] == "fotmob"
    snap = store.get(conn, "match:6106274")
    assert snap["source"] == "fotmob" and len(snap["data"]["available"]) == 18
    run(c.close())


def test_finished_poorer_replaces_when_score_changed():
    now = time.time()
    prev = _snap(_fm(), 3600)
    new = _es()
    assert keep_fuller(prev, new, now)              # тот же счёт и статус — оставляем полный
    new["home"]["score"] += 1                       # исправили счёт — новый снимок важнее полноты
    assert not keep_fuller(prev, new, now)
    new = _es()
    new["status"] = status("abandoned")
    assert not keep_fuller(prev, new, now)          # сменился статус


def test_finished_poorer_replaces_after_14_days():
    now = time.time()
    new = _es()
    assert keep_fuller(_snap(_fm(), (config.KEEP_FULL_DAYS - 1) * 86400), new, now)
    assert not keep_fuller(_snap(_fm(), (config.KEEP_FULL_DAYS + 1) * 86400), new, now)


def test_finished_richer_or_superset_replaces():
    now = time.time()
    assert not keep_fuller(_snap(_es(), 60), _fm(), now)     # полный заменяет бедный
    assert not keep_fuller(_snap(_fm(), 60), _fm(), now)     # тот же набор — обычное обновление
    assert not keep_fuller(None, _es(), now)                  # прежнего нет
    prev_live = _snap(_live(_fm()), 60)
    assert not keep_fuller(prev_live, _es(), now)             # прежний не завершён — статус сменился


# ---------- идущий матч ----------

def test_live_borrows_missing_blocks_from_recent_full():
    now = time.time()
    prev = _snap(_live(_fm()), 120)
    m = _live(_es())
    assert not {"ratings", "xg", "momentum", "shotmap"} & set(m["available"])
    got = borrow_live_blocks(prev, m, now)
    assert {"ratings", "xg", "momentum", "shotmap"} <= set(got)
    assert {"ratings", "xg", "momentum", "shotmap"} <= set(m["available"])
    assert m["borrowed"]["xg"] == {"source": "fotmob", "at": prev["fetched_at"]}
    assert m["shots"] == prev["data"]["shots"] and m["momentum"] == prev["data"]["momentum"]
    # свежие поля — из нового снимка: события и составы ESPN не подменены
    assert m["source"] == "espn" and m["events"] == _es()["events"]
    rated = [p for side in ("home", "away") for p in m["lineups"][side]["starters"] if p.get("rating") is not None]
    assert rated, "оценки перенесены в составы ESPN по имени"


def test_live_does_not_borrow_stale_blocks():
    now = time.time()
    prev = _snap(_live(_fm()), config.LIVE_BORROW_MAX_AGE + 60)
    m = _live(_es())
    before = copy.deepcopy(m)
    assert borrow_live_blocks(prev, m, now) == []
    assert m == before and "borrowed" not in m


def test_live_borrow_keeps_original_age_through_chain():
    """Заимствованный блок не «молодеет»: возраст считается от снимка, где он был на самом деле."""
    now = time.time()
    full = _snap(_live(_fm()), 300)
    m1 = _live(_es())
    borrow_live_blocks(full, m1, now - 200)                # цикл 200 с назад: блоки взяты
    second = _snap(m1, 200, source="espn")
    m2 = _live(_es())
    borrow_live_blocks(second, m2, now)
    assert m2["borrowed"]["momentum"]["at"] == full["fetched_at"]
    assert m2["borrowed"]["momentum"]["source"] == "fotmob"
    # через LIVE_BORROW_MAX_AGE от исходного полного — уже не берём
    m3 = _live(_es())
    assert borrow_live_blocks(_snap(m2, 10, source="espn"), m3, full["fetched_at"] + config.LIVE_BORROW_MAX_AGE + 1) == []


def test_live_full_snapshot_is_not_touched():
    now = time.time()
    prev = _snap(_live(_es()), 30)
    m = _live(_fm())
    assert borrow_live_blocks(prev, m, now) == [] and "borrowed" not in m


def test_finished_never_borrows():
    prev = _snap(_live(_fm()), 30)
    m = _es()                                          # finished
    assert borrow_live_blocks(prev, m, time.time()) == []
