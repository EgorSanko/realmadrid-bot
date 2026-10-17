"""Карточка игрока: нормализаторы на сохранённых ответах FotMob/SofaScore, заявки API → сборщик,
резерв SofaScore, лимит запросов в минуту, сопоставление id игроков."""
import asyncio
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import config, store
from app.collector import Collector
from app.sources import fotmob, sofascore

from .conftest import load

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


def fm_player(pid):
    return load(f"fotmob_player_{pid}.json")


# ---------- нормализатор FotMob ----------

def test_fotmob_mbappe_bio_and_season():
    p = fotmob.normalize_player(fm_player(701154), now=NOW)
    assert p["id"] == 701154 and p["name"] == "Kylian Mbappé"  # латиница как у источника
    assert p["photo"] == "/img/player/701154.png"
    assert p["number"] == 10 and p["position"] == "ST" and p["positions"] == ["ST", "LW"] and p["role"] == "FW"
    assert p["team"] == {"id": 8633, "name": "Real Madrid", "logo": "/img/team/8633.png", "on_loan": False}
    assert p["country"]["flag"] == "/img/flag/fr.svg" and p["country"]["code"] == "FRA"
    assert p["birth"] == "1998-12-20" and p["age"] == 27 and p["height"] == 178 and p["foot"] == "right"
    assert p["value_eur"] == 120694930 and p["contract_until"] == "2029-06-30"
    assert p["status"] is None and "status" not in p["available"]
    s = p["season"]
    assert s["name"] == "2026/2027" and s["team"]["id"] == 8633
    ll = next(t for t in s["tournaments"] if t["league"]["id"] == 87)
    ucl = next(t for t in s["tournaments"] if t["league"]["id"] == 42)
    # Ла Лига — из блока mainLeague (точно)
    assert (ll["matches"], ll["started"], ll["minutes"], ll["goals"], ll["assists"], ll["yellow"]) == (8, 8, 720, 7, 2, 1)
    assert ll["rating"] == 8.1 and ll["league"]["logo"] == "/img/league/87.png"
    # ЛЧ — из карьеры + сумма последних матчей (они покрывают оба матча)
    assert (ucl["matches"], ucl["goals"], ucl["minutes"]) == (2, 2, 179)
    assert s["totals"]["matches"] == 10 and s["totals"]["goals"] == 9 and s["totals"]["minutes"] == 899


def test_fotmob_recent_matches_and_career():
    p = fotmob.normalize_player(fm_player(701154), now=NOW)
    r = p["recent"]
    assert 5 <= len(r) <= 10 and all(x["played"] for x in r)
    assert [x["kickoff"] for x in r] == sorted((x["kickoff"] for x in r), reverse=True)
    roma = r[0]
    assert roma["match_id"] == 6106274 and roma["opponent"] == {"id": 8686, "name": "Roma", "logo": "/img/team/8686.png"}
    assert roma["score"] == [3, 4] and roma["home"] is False and roma["result"] == "W"
    assert roma["goals"] == 1 and roma["rating"] == 8.2 and roma["tournament"]["logo"] == "/img/league/42.png"
    # сборная тоже в последних матчах (Лига наций), со своим соперником
    assert any(x["tournament"]["id"] == 9806 for x in r)
    clubs = [c["team"]["name"] for c in p["career"]]
    assert clubs[:2] == ["Real Madrid", "Paris Saint-Germain"] and p["career"][0]["active"] and p["career"][0]["end"] is None
    assert any(c["loan"] for c in p["career"])  # ПСЖ 2017/18 — аренда
    assert p["national"][0]["team"]["name"] == "France"


def test_fotmob_bellingham_england_flag_and_positions():
    p = fotmob.normalize_player(fm_player(1077894), now=NOW)
    assert p["name"] == "Jude Bellingham" and p["number"] == 5
    assert p["position"] == "AM" and p["role"] == "MF"
    assert p["country"]["flag"] == "/img/flag/gb-eng.svg"
    assert p["age"] == 23


def test_fotmob_keeper_clean_sheets_and_saves():
    p = fotmob.normalize_player(fm_player(170323), now=NOW)
    assert p["role"] == "GK" and p["position"] == "GK"
    ll = next(t for t in p["season"]["tournaments"] if t["league"]["id"] == 87)
    assert ll["clean_sheets"] == 2 and ll["conceded"] == 8 and ll["saves"] == 25
    ucl = next(t for t in p["season"]["tournaments"] if t["league"]["id"] == 42)
    assert ucl["clean_sheets"] == 0 and ucl["saves"] is None  # сейвы FotMob даёт только по основной лиге
    assert p["season"]["totals"]["clean_sheets"] == 2


def test_fotmob_injury_and_old_season():
    p = fotmob.normalize_player(fm_player(895362), now=NOW)  # Rodrygo: крестообразная связка
    assert p["status"]["type"] == "injury" and p["status"]["expected_return"] == "Late December 2026"
    assert "status" in p["available"]
    # с марта не играл: сезон — прошлый, минут по ЛЧ нет (последние матчи не покрывают турнир) — None, не 0
    assert p["season"]["name"] == "2025/2026"
    ucl = next(t for t in p["season"]["tournaments"] if t["league"]["id"] == 42)
    assert ucl["minutes"] is None and p["season"]["totals"]["minutes"] is None


def test_fotmob_foreign_player():
    p = fotmob.normalize_player(fm_player(325916), now=NOW)  # Dybala, Рома
    assert p["team"]["id"] == 8686 and p["team"]["logo"] == "/img/team/8686.png"
    assert p["status"]["expected_return"] == "Doubtful"
    assert p["season"]["tournaments"][0]["league"]["id"] == 55


def test_fotmob_empty_reply_is_not_found(monkeypatch):
    from app.sources.base import NotFound
    f = fotmob.FotMob()

    async def fetch(url, params):
        return None  # FotMob на неизвестный id отвечает 200 и `null`

    monkeypatch.setattr(f, "_fetch", fetch)
    with pytest.raises(NotFound):
        run(f.player(999999999))
    assert f.state == "closed" and f.errors == 0  # не поломка источника
    run(f.close())


# ---------- нормализатор SofaScore ----------

def test_sofascore_player_fallback_shape():
    ctx = {"fotmob_id": 701154, "teams": {"2702": "8686"}, "matches": {"16938872": "6106274"}}
    p = sofascore.normalize_player(load("sofa_player_826643.json"), load("sofa_player_826643_last.json"), ctx, now=NOW)
    assert p["id"] == 701154 and p["ids"]["sofascore"] == 826643 and p["photo"] == "/img/player/701154.png"
    assert p["source"] == "sofascore" and p["position"] == "ST" and p["number"] == 10
    assert p["team"]["id"] == 8633 and p["country"]["flag"] == "/img/flag/fr.svg"
    assert p["birth"] == "1998-12-20" and p["age"] == 27 and p["contract_until"] == "2029-06-30"
    roma = p["recent"][0]
    assert roma["match_id"] == 6106274 and roma["opponent"]["logo"] == "/img/team/8686.png"
    assert roma["goals"] == 1 and roma["rating"] == 7.7
    # соперник без сопоставления — без эмблемы и без ссылки, но со счётом
    vill = p["recent"][1]
    assert vill["opponent"]["logo"] is None and vill["match_id"] is None and vill["score"] == [1, 0]
    s = p["season"]
    assert s["partial"] and s["name"] == "2026/2027"
    assert s["totals"]["matches"] == 10 and s["totals"]["goals"] == 9 and s["totals"]["minutes"] == 899
    assert not p["career"] and "career" not in p["available"]


# ---------- API + сборщик ----------

@pytest.fixture()
def env(tmp_db):
    conn = store.connect()
    store.put(conn, "team", "fotmob", fotmob.normalize_team(load("fotmob_team_8633.json")))
    c = Collector(conn)
    calls = {"fotmob": 0, "sofascore": 0}

    async def fm_fetch(url, params):
        calls["fotmob"] += 1
        pid = str(params["id"])
        try:
            return fm_player(pid)
        except FileNotFoundError:
            return None

    async def ss_fetch(url, params):
        calls["sofascore"] += 1
        return load("sofa_player_826643_last.json") if url.endswith("/events/last/0") else load("sofa_player_826643.json")

    c.fm._fetch = fm_fetch
    c.ss._fetch = ss_fetch
    from app.main import app
    yield TestClient(app), conn, c, calls
    run(c.close())
    conn.close()


def test_foreign_player_pending_then_data(env):
    api, conn, c, calls = env
    r = api.get("/api/player/325916")
    b = r.json()
    assert r.status_code == 200 and b["pending"] is True and b["available"] == [] and b["id"] == 325916
    assert r.headers["cache-control"] == "no-store"
    assert store.peek_player_demand(conn) == ["325916"]
    assert calls["fotmob"] == 0  # API сам во внешние источники не ходит

    done = run(c.tick_players(time.time(), squad=False))
    assert done == ["325916"] and calls["fotmob"] == 1 and store.peek_player_demand(conn) == []

    b = api.get("/api/player/325916").json()
    assert b["pending"] is False and b["name"] == "Paulo Dybala" and b["source"] == "fotmob"
    assert b["age_s"] < 5 and b["stale"] is False and "updated_at" in b
    assert "season" in b["available"] and "fallback_errors" not in b


def test_foreign_cache_24h_then_refresh(env):
    api, conn, c, calls = env
    run(c.refresh_player("325916"))
    snap = store.get(conn, "player:325916")
    # 23 ч — ещё свежий, заявки нет
    store.put(conn, "player:325916", "fotmob", snap["data"], fetched_at=time.time() - 23 * 3600)
    assert api.get("/api/player/325916").json()["stale"] is False
    assert store.peek_player_demand(conn) == []
    # 25 ч — отдаём старый снимок (stale) и просим сборщика обновить
    store.put(conn, "player:325916", "fotmob", snap["data"], fetched_at=time.time() - 25 * 3600)
    b = api.get("/api/player/325916").json()
    assert b["name"] == "Paulo Dybala" and b["stale"] is True and b["age_s"] > 24 * 3600
    assert store.peek_player_demand(conn) == ["325916"]
    run(c.tick_players(time.time(), squad=False))
    assert api.get("/api/player/325916").json()["age_s"] < 5


def test_squad_prefetch_respects_rate_limit(env, monkeypatch):
    api, conn, c, calls = env
    monkeypatch.setattr(config, "PLAYER_RATE_PER_MIN", 3)
    due = c.players_due(time.time())
    assert len(due) >= 20 and "701154" in due  # весь состав Реала из снимка команды
    run(c.tick_players(time.time(), per_tick=100))
    assert calls["fotmob"] == 3  # лимит в минуту
    run(c.tick_players(time.time(), per_tick=100))
    assert calls["fotmob"] == 3  # в ту же минуту — больше ни одного
    c.player_req.clear()  # «прошла минута»
    run(c.tick_players(time.time(), per_tick=100))
    assert calls["fotmob"] == 6
    # демо-ответы есть не на всех: у кого ответа нет — запомнили отказ, повторно 10 мин не просим
    assert all(store.get(conn, f"player:{p}") or store.get(conn, f"player_fail:{p}") for p in due[:6])


def test_own_player_refreshed_every_6h_and_status_from_team(env):
    api, conn, c, calls = env
    run(c.refresh_player("1367619"))  # Huijsen: в playerData травмы нет, дисквалификация — в лазарете команды
    b = api.get("/api/player/1367619").json()
    assert b["status"]["type"] == "suspension" and "status" in b["available"]
    snap = store.get(conn, "player:1367619")
    store.put(conn, "player:1367619", "fotmob", snap["data"], fetched_at=time.time() - 7 * 3600)
    assert "1367619" in c.players_due(time.time())
    b = api.get("/api/player/1367619").json()
    assert b["stale"] is False  # свой игрок «устаревает» только после трёх пропущенных обновлений
    assert store.peek_player_demand(conn) == ["1367619"]


def test_not_found_and_bad_ids(env):
    api, conn, c, calls = env
    assert api.get("/api/player/abc").status_code == 404
    assert api.get("/api/player/0").status_code == 404
    assert store.peek_player_demand(conn) == []
    assert api.get("/api/player/999999999").json()["pending"] is True
    run(c.tick_players(time.time(), squad=False))
    r = api.get("/api/player/999999999")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert calls["sofascore"] == 0  # у FotMob такого id нет — резерв не ищем


def test_fallback_sofascore_with_mapping(env, tmp_db):
    api, conn, c, calls = env
    (tmp_db / "disabled_sources").write_text("fotmob")
    store.map_set(conn, "player", "sofascore", 826643, 701154, "squad")
    store.map_set(conn, "match", "sofascore", 16938872, 6106274)
    store.map_set(conn, "team", "sofascore", 2702, 8686)
    p = run(c.refresh_player("701154"))
    assert p["source"] == "sofascore" and calls == {"fotmob": 0, "sofascore": 2}
    b = api.get("/api/player/701154").json()
    assert b["source"] == "sofascore" and b["name"] == "Kylian Mbappé" and b["season"]["partial"]
    assert b["recent"][0]["match_id"] == 6106274


def test_no_mapping_no_fallback_honest_error(env, tmp_db):
    api, conn, c, calls = env
    (tmp_db / "disabled_sources").write_text("fotmob")
    assert api.get("/api/player/325916").json()["pending"] is True
    run(c.tick_players(time.time(), squad=False))
    assert calls["sofascore"] == 0  # id у SofaScore неизвестен — резерва нет
    fail = store.get(conn, "player_fail:325916")["data"]
    assert fail["errors"] == {"fotmob": "disabled", "sofascore": "no id mapping"}
    r = api.get("/api/player/325916")
    assert r.status_code == 503 and r.json()["error"] == "unavailable"
    # прошлый удачный снимок не трогаем: при сбое отдаётся он
    (tmp_db / "disabled_sources").write_text("")
    run(c.refresh_player("325916"))
    (tmp_db / "disabled_sources").write_text("fotmob")
    assert run(c.refresh_player("325916")) is None
    assert api.get("/api/player/325916").json()["source"] == "fotmob"


def test_map_squad_players_by_name_and_birth(tmp_db):
    conn = store.connect()
    store.put(conn, "team", "fotmob", fotmob.normalize_team(load("fotmob_team_8633.json")))
    c = Collector(conn)
    raw = {"players": [
        {"player": {"id": 826643, "name": "Kylian Mbappé", "dateOfBirthTimestamp": 914112000}},
        {"player": {"id": 1, "name": "Kylian Mbappé", "dateOfBirthTimestamp": 0}},   # другая дата — нет
        {"player": {"id": 2, "name": "Somebody Unknown"}},
    ]}
    assert c._map_squad_players(raw) == 1
    assert store.from_fotmob(conn, "player", "sofascore", 701154) == "826643"
    assert store.to_fotmob(conn, "player", "sofascore", 1) is None
    run(c.close())


def test_sofascore_match_lineups_map_players(tmp_db, monkeypatch):
    """Резервный матч SofaScore заодно сопоставляет id игроков обеих команд (по номеру из состава FotMob)."""
    from .conftest import sofa_bundle
    conn = store.connect()
    c = Collector(conn)
    fm_raw = load("fotmob_match_6106274.json")
    sb = sofa_bundle()

    async def fm_fetch(url, params):
        return fm_raw

    async def ss_fetch(url, params):
        part = url.rsplit("/16938872", 1)[-1].strip("/") or "event"
        return {"event": sb["event"], "incidents": sb["incidents"], "lineups": sb["lineups"],
                "statistics": sb["statistics"], "shotmap": sb["shotmap"], "graph": sb["graph"],
                "best-players/summary": sb["best"]}[part]

    monkeypatch.setattr(c.fm, "_fetch", fm_fetch)
    monkeypatch.setattr(c.ss, "_fetch", ss_fetch)
    store.map_set(conn, "match", "sofascore", "16938872", "6106274")
    run(c.refresh_match("6106274"))  # FotMob — контекст номеров
    monkeypatch.setattr(config, "disabled_sources", lambda: {"fotmob"})
    m = run(c.refresh_match("6106274"))
    assert m["source"] == "sofascore"
    n = store.map_count(conn).get("player/sofascore", 0)
    assert n >= 22  # стартовые обеих команд как минимум
    assert store.from_fotmob(conn, "player", "sofascore", 325916)  # Dybala (Рома)
    run(c.close())
