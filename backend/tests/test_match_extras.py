"""Экран матча, новые блоки: «О матче» (стадион, погода, судья), расширенная статистика и зоны атак,
«Интересные факты», матчи тура, «Кто победит?» — нормализаторы на сырых ответах
FotMob (fixtures), расписание сборщика, API и отсутствие данных."""
import asyncio
import copy
import time

import pytest
from fastapi.testclient import TestClient

from app import config, store
from app.collector import Collector, borrow_static_blocks
from app.model import STAT_CATALOG, status, ts
from app.sources import espn, fotmob, sofascore

from .conftest import load, sofa_bundle

MID = "5868098"           # Real Madrid — Sevilla, Ла Лига, 9-й тур (лайв, 46′)
KICKOFF = ts("2026-10-18T19:00:00Z")


def run(coro):
    return asyncio.run(coro)


def _live_raw():
    return load("fotmob_match_5868098_live.json")


# ================= нормализаторы =================

def test_info_box_venue_weather_referee():
    m = fotmob.normalize_match(_live_raw())
    assert m["venue"] == {"name": "Estadio Bernabéu", "city": "Madrid", "country": "Spain",
                          "flag": "/img/flag/es.svg", "capacity": 83186, "surface": "grass"}
    # ветер не берём — единицы в ответе не указаны
    assert m["weather"] == {"temp": 10, "key": "weather_condition_cloudy", "text": "Cloudy", "humidity": 78,
                            "cloud": 92, "precip": 0, "icon": 26, "at": "2026-10-18T20:00:00Z"}
    ri = m["referee_info"]
    assert m["referee"] == "Mateo Busquets Ferrer" and m["referee_country"]["flag"] == "/img/flag/es.svg"
    assert ri["id"] == 1001070988 and ri["photo"] == "/img/player/1001070988.png"
    assert ri["matches"] == 37 and ri["red"] == 8 and ri["pens"] == 10
    assert ri["league"] == {"id": 87, "name": "LaLiga"}
    assert ri["yellow"] == {"per_match": 5.51, "avg": 4.46, "total": 204, "level": "above", "fill": 100, "avg_fill": 50}
    assert ri["fouls"]["level"] == "average" and ri["fouls"]["avg"] == 24.99 and ri["fouls"]["fill"] == 44.88
    assert {"venue_details", "weather", "referee_stats", "zones"} <= set(m["available"])


def test_referee_without_stats_and_missing_blocks():
    raw = _live_raw()
    info = raw["content"]["matchFacts"]["infoBox"]
    info["Referee"] = {"text": "Some Ref", "country": "Spain", "countryCode": "ESP"}
    info["Stadium"] = {"name": "Estadio Bernabéu", "city": "Madrid", "country": "Spain"}
    raw["content"].pop("weather")
    raw["content"].pop("attackingZones")
    m = fotmob.normalize_match(raw)
    assert m["referee"] == "Some Ref" and m["referee_info"] is None
    assert "capacity" not in m["venue"] and m["weather"] is None and m["zones"] is None
    assert not {"venue_details", "weather", "referee_stats", "zones"} & set(m["available"])


def test_full_stats_37_keys_with_percentages():
    m = fotmob.normalize_match(_live_raw())
    keys = [x["key"] for x in m["stats"]["all"]]
    assert len(keys) == 37 == len(STAT_CATALOG) and len(set(keys)) == 37
    by = {x["key"]: x for x in m["stats"]["all"]}
    assert by["passes_accurate"] == {"key": "passes_accurate", "group": "passes", "home": 273, "away": 156,
                                     "home_pct": 90, "away_pct": 83}
    assert (by["ground_duels_won"]["home"], by["ground_duels_won"]["home_pct"]) == (17, 52)
    assert (by["aerials_won"]["away"], by["aerials_won"]["away_pct"]) == (4, 44)
    assert (by["dribbles"]["home_pct"], by["dribbles"]["away_pct"]) == (60, 63)
    assert by["xg_open_play"]["home"] == 1.46 and by["xg_set_play"]["home"] == 0.03 and by["xg_non_penalty"]["away"] == 0.21
    assert by["big_chances_missed"]["away"] == 1 and by["passes_own_half"]["home"] == 155
    assert by["passes_opp_half"]["away"] == 93 and by["throws"]["home"] == 8 and by["blocks"]["away"] == 2
    assert by["duels_won"]["home"] == 22 and "home_pct" not in by["duels_won"]
    # по таймам — то же: в лайве на 46′ есть только первый тайм
    assert len(m["stats"]["first_half"]) == 37 and m["stats"]["second_half"] == []


def test_attacking_zones_by_period():
    m = fotmob.normalize_match(_live_raw())
    assert m["zones"]["all"] == {"home": {"left": 59, "center": 21, "right": 20},
                                 "away": {"left": 42, "center": 24, "right": 34}}
    assert set(m["zones"]) == {"all", "first_half"}
    full = fotmob.normalize_match(load("fotmob_match_6106274.json"))
    assert set(full["zones"]) == {"all", "first_half", "second_half"}
    assert full["zones"]["second_half"]["away"] == {"left": 46, "center": 28, "right": 26}


def test_sofascore_stats_duels_with_percentages():
    m = sofascore.normalize_match(sofa_bundle(), {})
    by = {x["key"]: x for x in m["stats"]["all"]}
    assert (by["ground_duels_won"]["home"], by["ground_duels_won"]["home_pct"]) == (26, 38)
    assert by["long_balls_accurate"]["home_pct"] == 62 and by["big_chances_missed"]["away"] == 2
    assert "home_pct" not in by["possession"]          # «54%» без скобок — это не точность


def test_match_meta_urls():
    meta = fotmob.match_meta(_live_raw())
    assert meta["round_key"] == "round:87:9" and meta["league_id"] == 87 and meta["round"] == "9"
    assert meta["insights_url"] == "https://data.fotmob.com/generated-match-insights/87/5868098/matchinsights_{lang}.json"
    assert "en" in meta["ltc_langs"] and "ru" not in meta["ltc_langs"]
    assert meta["ltc_teams"] == ["Real Madrid", "Sevilla"] and (meta["home_id"], meta["away_id"]) == (8633, 8302)
    # ЛЧ: файл фактов — по родительскому турниру (42)
    cl = fotmob.match_meta(load("fotmob_match_6106274.json"))
    assert "/42/6106274/" in cl["insights_url"] and cl["round_key"].startswith("round:42:")


def test_insights_ru():
    ins = fotmob.normalize_insights(load("fotmob_insights_5868098_ru.json"), 8633, 8302)
    assert ins["lang"] == "ru" and ins["main"].startswith("Real Madrid выиграл 19 из 20")
    assert [t["team_id"] for t in ins["teams"]] == [8633, 8302]
    assert ins["teams"][0]["items"][1] == "Real Madrid забил 13 голов в последних пяти матчах"
    # чужой матч: хозяева первыми, даже если в ответе гости идут раньше
    other = fotmob.normalize_insights(load("fotmob_insights_5868095_ru.json"), 8305, 8370)
    assert [t["team_id"] for t in other["teams"]] == [8305, 8370] and other["main"]


def test_insights_betting_words_and_empty():
    raw = {"teamInsights": {"8633": ["Коэффициент на победу 1.5", "Обычный факт"]},
           "bettingInsight": "Лучшая ставка — обе забьют"}
    ins = fotmob.normalize_insights(raw, 8633, 8302)
    assert ins["main"] is None and ins["teams"] == [{"team_id": 8633, "items": ["Обычный факт"]}]
    assert fotmob.normalize_insights(None) is None
    assert fotmob.normalize_insights({"teamInsights": {}, "bettingInsight": None}) is None


def test_round_matches():
    r = fotmob.normalize_round(load("fotmob_round_87_9.json"), 87)
    assert r["league"] == {"id": 87, "name": "LaLiga", "logo": "/img/league/87.png"}
    assert r["round"] == "9" and r["season"] == "2026/2027"
    assert len(r["matches"]) == 10 and r["live"] == 1 and r["finished"] == 8
    kick = [x["kickoff"] for x in r["matches"]]
    assert kick == sorted(kick)
    ours = [x for x in r["matches"] if x["is_ours"]]
    assert len(ours) == 1 and ours[0]["id"] == 5868098 and ours[0]["status"]["state"] == "live"
    assert ours[0]["status"]["minute"] == 46 and (ours[0]["home"]["score"], ours[0]["away"]["score"]) == (2, 0)
    last = r["matches"][-1]                              # Getafe — Rayo, ещё не начался
    assert last["status"]["state"] == "scheduled" and last["home"]["score"] is None
    assert last["home"]["logo"] == "/img/team/8305.png"
    assert fotmob.normalize_round({"matchesInRound": [], "playoff": {"rounds": []}}, 42) is None


def test_vote_only_1x2():
    v = fotmob.normalize_vote(load("fotmob_vote_5868098.json"))
    assert v == {"home": 176727, "draw": 49376, "away": 37025, "total": 263128}
    assert fotmob.normalize_vote(load("fotmob_vote_5868095.json"))["total"] == 9257
    assert fotmob.normalize_vote({"Votes": [{"Name": "bts", "Votes": [77, 19]}]}) is None
    assert fotmob.normalize_vote({"Votes": [{"Name": "1x2", "Votes": [0, 0, 0]}]}) is None
    assert fotmob.normalize_vote(None) is None



# ================= сборщик: смена источника не теряет блоки =================

def test_static_blocks_survive_fallback_source():
    now = time.time()
    fm = fotmob.normalize_match(load("fotmob_match_6106274.json"))
    prev = {"source": "fotmob", "fetched_at": now - 600, "data": fm}
    es = espn.normalize_match(load("espn_summary_401915414.json"), {"match_id": 6106274})
    got = borrow_static_blocks(prev, es, now)
    assert set(got) == {"venue_details", "referee_stats", "weather"}
    assert es["venue"]["capacity"] == 70634 and es["referee_info"]["id"] == fm["referee_info"]["id"]
    assert es["weather"] == fm["weather"] and es["borrowed"]["weather"]["source"] == "fotmob"
    assert {"venue_details", "referee_stats", "weather"} <= set(es["available"])
    # погода старше 6 ч не тянется
    es2 = espn.normalize_match(load("espn_summary_401915414.json"), {"match_id": 6106274})
    assert "weather" not in borrow_static_blocks({**prev, "fetched_at": now - 7 * 3600}, es2, now)


def test_zones_borrowed_in_live():
    from app.collector import borrow_live_blocks
    now = time.time()
    fm = fotmob.normalize_match(_live_raw())
    prev = {"source": "fotmob", "fetched_at": now - 30, "data": fm}
    ss = sofascore.normalize_match(sofa_bundle(), {})
    ss["status"] = status("live", 47)
    assert "zones" in borrow_live_blocks(prev, ss, now) and ss["zones"] == fm["zones"]


# ================= сборщик: расписание редких запросов =================

def _collector(conn, live_state="live", minute=46):
    c = Collector(conn)
    team = load("fotmob_team_8633.json")
    store.put(conn, "fixtures", "fotmob", fotmob.normalize_fixtures(team))
    raw = _live_raw()
    m = fotmob.normalize_match(raw)
    if live_state != "live":
        m["status"] = status(live_state, None)
    m["finished_seen_at"] = None
    store.put(conn, f"match:{MID}", "fotmob", m)
    store.put(conn, f"ctx:fm:{MID}", "fotmob", fotmob.match_meta(raw))
    return c


def _set_status(conn, state, fin_seen=None):
    s = store.get(conn, f"match:{MID}")
    s["data"]["status"] = status(state, 60 if state == "live" else None)
    s["data"]["finished_seen_at"] = fin_seen
    store.put(conn, f"match:{MID}", s["source"], s["data"], fetched_at=s["fetched_at"])


def _kinds(plan, fid=MID):
    return sorted(k for k, f, _ in plan if f == fid)


def _put_at(conn, key, data, at):
    store.put(conn, key, "fotmob", data, fetched_at=at)


def test_plan_live_frequencies(tmp_db):
    conn = store.connect()
    c = _collector(conn)
    now = KICKOFF + 50 * 60
    assert _kinds(c.extras_plan(now)) == ["insights", "round", "vote"]
    # всё только что скачано — ничего не пора
    rnd = fotmob.normalize_round(load("fotmob_round_87_9.json"), 87)
    for key, data in ((f"insights:{MID}", {"main": "x"}), (f"vote:{MID}", {"total": 1}),
                      ("round:87:9", rnd)):
        _put_at(conn, key, data, now)
    assert c.extras_plan(now + 10) == []
    # тур (есть live) — раз в минуту, голоса — 5 мин, факты — час
    assert _kinds(c.extras_plan(now + config.ROUND_LIVE_INTERVAL + 1)) == ["round"]
    assert _kinds(c.extras_plan(now + config.VOTE_LIVE_INTERVAL + 1)) == ["round", "vote"]
    assert _kinds(c.extras_plan(now + config.INSIGHTS_LIVE_INTERVAL + 1)) == ["insights", "round", "vote"]
    conn.close()


def test_plan_round_idle_and_finished_round(tmp_db):
    c = Collector(store.connect())
    rnd = fotmob.normalize_round(load("fotmob_round_87_9.json"), 87)
    snap = {"data": rnd, "fetched_at": 0}
    now = KICKOFF + 50 * 60
    assert c.round_interval(snap, now) == config.ROUND_LIVE_INTERVAL     # наш матч идёт
    idle = copy.deepcopy(rnd)
    for r in idle["matches"]:
        if r["status"]["live"]:
            r["status"] = status("finished")
    # следующий матч тура (Getafe — Rayo) только завтра в 22:00 МСК — раз в 2 ч
    assert c.round_interval({"data": idle}, now + 3600) == config.ROUND_IDLE_INTERVAL
    getafe = ts(idle["matches"][-1]["kickoff"])
    assert c.round_interval({"data": idle}, getafe - 30 * 60) == config.ROUND_LIVE_INTERVAL
    done = copy.deepcopy(idle)
    for r in done["matches"]:
        r["status"] = status("finished")
    assert c.round_interval({"data": done}, now) is None              # тур доигран — больше не ходим
    assert c.round_interval(None, now) == 0
    c.conn.close()


def test_plan_before_match(tmp_db):
    conn = store.connect()
    c = _collector(conn, live_state="scheduled")
    # за сутки до матча: факты, голоса, тур
    assert _kinds(c.extras_plan(KICKOFF - 24 * 3600)) == ["insights", "round", "vote"]
    # за двое суток: фактов ещё нет — не ходим; голоса — за 3 дня
    assert _kinds(c.extras_plan(KICKOFF - 48 * 3600)) == ["round", "vote"]
    conn.close()


def test_plan_after_final_whistle_one_final_snapshot(tmp_db):
    conn = store.connect()
    c = _collector(conn)
    fin = KICKOFF + 115 * 60
    _set_status(conn, "finished", fin_seen=fin)
    _put_at(conn, f"vote:{MID}", {"total": 1}, fin - 100)
    # сразу после свистка — ждём EXTRA_FINAL_DELAY; фактов после матча не качаем
    assert _kinds(c.extras_plan(fin + 30)) == ["round"]
    now = fin + config.EXTRA_FINAL_DELAY + 5
    assert _kinds(c.extras_plan(now)) == ["round", "vote"]
    _put_at(conn, f"vote:{MID}", {"total": 1}, now)
    assert _kinds(c.extras_plan(now + 600)) == ["round"]               # дальше — заморозка
    conn.close()


def test_extras_disabled_source_and_feature(tmp_db, monkeypatch):
    conn = store.connect()
    c = _collector(conn)
    calls = []

    async def fetch(url, params):
        calls.append(url)
        return {}

    monkeypatch.setattr(c.fx, "_fetch", fetch)
    now = KICKOFF + 50 * 60
    (tmp_db / "disabled_sources").write_text("fotmob")
    assert run(c.tick_extras(now)) == [] and calls == []
    (tmp_db / "disabled_sources").write_text("fotmob_extra")
    assert run(c.tick_extras(now)) == [] and calls == []
    (tmp_db / "disabled_sources").write_text("fotmob_ltc\nfotmob_vote")
    assert _kinds(c.extras_plan(now)) == ["insights", "round"]
    conn.close()


def _fake_fx(c, monkeypatch, fail=()):
    calls = []

    async def fetch(url, params):
        calls.append((url, dict(params or {})))
        for f in fail:
            if f in url:
                raise ConnectionError("403 Forbidden")
        if "matchInsights" in url:
            return load("fotmob_insights_5868098_ru.json")
        if "leagueDataForMatch" in url:
            return load("fotmob_round_87_9.json")
        if "/vote" in url:
            return load("fotmob_vote_5868098.json")
        raise AssertionError(url)

    monkeypatch.setattr(c.fx, "_fetch", fetch)
    return calls


def test_tick_extras_writes_snapshots(tmp_db, monkeypatch):
    conn = store.connect()
    c = _collector(conn)
    calls = _fake_fx(c, monkeypatch)
    monkeypatch.setattr(config, "EXTRA_PER_TICK", 10)
    now = KICKOFF + 50 * 60
    done = run(c.tick_extras(now))
    assert sorted(k for k, _, ok in done if ok) == ["insights", "round", "vote"]
    ins = next(p for u, p in calls if "matchInsights" in u)
    assert ins["language"] == "ru" and "{lang}" in ins["urlTemplate"] and "ru" in ins["languages"]
    rnd = next(p for u, p in calls if "leagueDataForMatch" in u)
    assert rnd == {"matchId": MID, "leagueId": 87}
    assert store.get(conn, f"insights:{MID}")["data"]["main"]
    assert store.get(conn, "round:87:9")["data"]["match_ids"][0] == 5868093
    assert store.get(conn, f"vote:{MID}")["data"]["total"] == 263128
    # счётчики — у своего клиента, в source_state
    c.write_state()
    st = store.source_states(conn)["fotmob_extra"]
    assert st["requests"] == 3 and st["by_kind"] == {"insights": 1, "round": 1, "vote": 1}
    # за такт — не больше EXTRA_PER_TICK
    monkeypatch.setattr(config, "EXTRA_PER_TICK", 2)
    assert len(run(c.tick_extras(now + 4000))) == 2
    run(c.close())


def test_extra_endpoint_failure_does_not_touch_main_source(tmp_db, monkeypatch):
    conn = store.connect()
    c = _collector(conn)
    _fake_fx(c, monkeypatch, fail=("/vote",))
    monkeypatch.setattr(config, "EXTRA_PER_TICK", 10)
    now = KICKOFF + 50 * 60
    res = {k: ok for k, _, ok in run(c.tick_extras(now))}
    assert res["vote"] is None and res["round"] is True
    assert store.get(conn, f"vote:{MID}") is None
    # основной клиент FotMob (matchDetails) не тронут
    assert c.fm.errors == 0 and c.fm.state == "closed" and c.fx.errors == 1
    # не ответил — повтор не раньше EXTRA_FAIL_BACKOFF, даже если по частоте пора
    assert "vote" not in _kinds(c.extras_plan(now + config.VOTE_LIVE_INTERVAL + 1))
    assert "vote" in _kinds(c.extras_plan(now + config.EXTRA_FAIL_BACKOFF + 1))
    run(c.close())


def test_extra_not_found_is_no_data(tmp_db, monkeypatch):
    from app.sources.base import NotFound
    conn = store.connect()
    c = _collector(conn)

    async def fetch(url, params):
        raise NotFound("404")

    monkeypatch.setattr(c.fx, "_fetch", fetch)
    assert run(c.refresh_extra("insights", MID, f"insights:{MID}")) is False
    assert store.get(conn, f"insights:{MID}") is None and c.fx.state == "closed"
    # FotMob ответил null — тоже «нет данных», без ошибки
    async def null(url, params):
        return None
    monkeypatch.setattr(c.fx, "_fetch", null)
    assert run(c.refresh_extra("vote", MID, f"vote:{MID}")) is False
    run(c.close())


def test_no_extras_without_fotmob_meta(tmp_db):
    conn = store.connect()
    c = _collector(conn)
    conn.execute("DELETE FROM snapshots WHERE key=?", (f"ctx:fm:{MID}",))
    assert c.extras_plan(KICKOFF + 50 * 60) == []
    conn.close()


def test_collector_writes_fotmob_meta(tmp_db, monkeypatch):
    conn = store.connect()
    c = Collector(conn)

    async def fetch(url, params):
        return _live_raw()

    monkeypatch.setattr(c.fm, "_fetch", fetch)
    run(c.refresh_match(MID, live=True))
    assert store.get(conn, f"ctx:fm:{MID}")["data"]["round_key"] == "round:87:9"
    run(c.close())


# ================= API =================

@pytest.fixture()
def api(tmp_db):
    from app import main
    from app.predictions import api as papi
    from app.predictions.provider import FakeProvider
    conn = store.connect()
    store.put(conn, "fixtures", "fotmob", fotmob.normalize_fixtures(load("fotmob_team_8633.json")))
    raw = _live_raw()
    m = fotmob.normalize_match(raw)
    m["finished_seen_at"] = None
    store.put(conn, f"match:{MID}", "fotmob", m)
    store.put(conn, f"ctx:fm:{MID}", "fotmob", fotmob.match_meta(raw))
    prev = papi._service
    svc = papi.configure(provider=FakeProvider(), db_path=str(tmp_db / "predictions.db"))
    main._POLL_CACHE.clear()
    yield TestClient(main.app), conn, svc
    papi._service = prev
    main._POLL_CACHE.clear()
    conn.close()


def _predict(svc, n, score=(2, 1), start=1):
    now = "2026-10-18T10:00:00Z"
    with svc.conn() as c:
        c.execute("INSERT OR IGNORE INTO matches(id, kickoff_utc, home_name, away_name, rm_is_home, status, season, "
                  "month, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (MID, "2026-10-18T19:00:00Z", "Real Madrid", "Sevilla", 1, "scheduled", 2026, "2026-10", now))
        for uid in range(start, start + n):
            c.execute("INSERT INTO users(id, first_name, created_at, updated_at) VALUES (?,?,?,?)", (uid, "u", now, now))
            c.execute("INSERT INTO predictions(user_id, match_id, home, away, created_at, updated_at) "
                      "VALUES (?,?,?,?,?,?)", (uid, MID, score[0], score[1], now, now))


def test_api_match_without_extras_hides_blocks(api):
    c, _, _ = api
    b = c.get(f"/api/match/{MID}").json()
    assert b["insights"] is None and b["round"] is None and b["poll"] is None
    assert not {"insights", "round", "poll"} & set(b["available"])
    # блоки из matchDetails — на месте
    assert b["venue"]["capacity"] == 83186 and b["weather"]["temp"] == 10 and b["referee_info"]["matches"] == 37
    assert b["zones"]["all"]["home"]["left"] == 59 and "zones" in b["available"]
    assert "finished_seen_at" not in b


def test_api_match_with_extras(api):
    c, conn, _ = api
    store.put(conn, f"insights:{MID}", "fotmob",
              fotmob.normalize_insights(load("fotmob_insights_5868098_ru.json"), 8633, 8302))
    rnd = fotmob.normalize_round(load("fotmob_round_87_9.json"), 87)
    rnd["match_ids"] = [1]
    store.put(conn, "round:87:9", "fotmob", rnd)
    store.put(conn, f"vote:{MID}", "fotmob", fotmob.normalize_vote(load("fotmob_vote_5868098.json")))
    b = c.get(f"/api/match/{MID}").json()
    assert {"insights", "round", "poll"} <= set(b["available"])
    assert b["insights"]["teams"][0]["team_id"] == 8633 and b["insights"]["updated_at"]
    assert len(b["round"]["matches"]) == 10 and "match_ids" not in b["round"]
    assert b["poll"]["fotmob"]["total"] == 263128 and b["poll"]["ours"] is None and b["poll"]["ours_count"] == 0


def test_api_poll_threshold(api):
    from app import main
    c, _, svc = api
    _predict(svc, config.POLL_MIN_PREDICTIONS - 1, (2, 1))
    p = c.get(f"/api/match/{MID}").json()["poll"]
    # ниже порога — без распределения, только число (у FotMob голосов ещё нет)
    assert p["fotmob"] is None and p["ours"] is None and p["ours_count"] == config.POLL_MIN_PREDICTIONS - 1
    assert p["threshold"] == config.POLL_MIN_PREDICTIONS
    _predict(svc, 1, (1, 1), start=100)
    _predict(svc, 2, (0, 2), start=200)
    main._POLL_CACHE.clear()
    p = c.get(f"/api/match/{MID}").json()["poll"]
    assert p["ours"] == {"home": config.POLL_MIN_PREDICTIONS - 1, "draw": 1, "away": 2,
                         "total": config.POLL_MIN_PREDICTIONS + 2}
    # агрегат — без имён и id пользователей
    assert "user" not in str(p)


def test_api_poll_survives_broken_predictions(api, monkeypatch):
    from app import main
    c, conn, svc = api

    def boom(_):
        raise RuntimeError("db locked")

    monkeypatch.setattr(svc, "outcome_counts", boom)
    store.put(conn, f"vote:{MID}", "fotmob", {"home": 1, "draw": 1, "away": 1, "total": 3})
    main._POLL_CACHE.clear()
    r = c.get(f"/api/match/{MID}")
    assert r.status_code == 200 and r.json()["poll"]["fotmob"]["total"] == 3 and r.json()["poll"]["ours"] is None


def test_api_round_only_laliga_and_ucl(api):
    c, conn, _ = api
    rnd = fotmob.normalize_round(load("fotmob_round_87_9.json"), 87)
    store.put(conn, "round:87:9", "fotmob", rnd)
    s = store.get(conn, f"match:{MID}")
    s["data"]["tournament"]["id"] = 138                    # Кубок Испании — блока тура нет
    store.put(conn, f"match:{MID}", "fotmob", s["data"])
    assert c.get(f"/api/match/{MID}").json()["round"] is None


def test_api_home_round_in_live(api):
    c, conn, _ = api
    fx = store.get(conn, "fixtures")["data"]
    for f in fx:
        if str(f["id"]) == MID:
            f["status"] = status("live", 46)
    store.put(conn, "fixtures", "fotmob", fx)
    assert c.get("/api/home").json()["round"] is None           # снимка тура нет — блока нет
    store.put(conn, "round:87:9", "fotmob", fotmob.normalize_round(load("fotmob_round_87_9.json"), 87))
    b = c.get("/api/home").json()
    assert b["round"]["round"] == "9" and len(b["round"]["matches"]) == 10 and "round" in b["available"]


def test_api_pending_match_has_empty_extras(api):
    c, conn, _ = api
    conn.execute("DELETE FROM snapshots WHERE key=?", (f"match:{MID}",))
    b = c.get(f"/api/match/{MID}").json()
    assert b["pending"] is True and b["poll"] is None and b["weather"] is None and b["available"] == []

