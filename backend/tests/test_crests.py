"""Прогрев кэша эмблем: id из таблиц и календаря, повторы, заглушка FotMob не считается прогревом."""
import asyncio

from app import config, crests, store
from app.collector import Collector
from app.sources import fotmob
from tests.conftest import load

DAY = 86400


def _fake(responses: dict, calls: list):
    async def fetch(url):
        calls.append(url)
        tid = int(url.rsplit("/", 1)[1].split(".")[0])
        return responses.get(tid, (200, {}))
    return fetch


def test_team_ids_from_tables_and_fixtures(tmp_db):
    conn = store.connect()
    raw = load("fotmob_team_8633.json")
    store.put(conn, "tables", "fotmob", fotmob.normalize_tables(raw))
    store.put(conn, "fixtures", "fotmob", fotmob.normalize_fixtures(raw))
    ids = crests.team_ids(conn)
    assert config.TEAM_ID in ids
    assert len(ids) >= 20 and ids == sorted(set(ids))


def test_team_ids_empty_without_snapshots(tmp_db):
    assert crests.team_ids(store.connect()) == []


def test_warm_once_then_rewarm_after_week():
    calls = []
    w = crests.CrestWarmer(base="https://x.test/", fetch=_fake({}, calls))
    assert asyncio.run(w.warm([1, 2, 3], 1000.0)) == {"warmed": 3, "failed": 0}
    assert calls == [f"https://x.test/img/team/{i}.png" for i in (1, 2, 3)]
    assert asyncio.run(w.warm([1, 2, 3, 4], 1000.0 + DAY)) == {"warmed": 1, "failed": 0}
    assert calls[-1].endswith("/4.png")
    assert asyncio.run(w.warm([1], 1000.0 + config.CREST_REWARM)) == {"warmed": 1, "failed": 0}


def test_blank_fallback_and_errors_retry_later():
    calls = []
    w = crests.CrestWarmer(base="https://x.test", fetch=_fake({7: (200, {"x-img-fallback": "blank"}), 8: (502, {})}, calls))
    assert asyncio.run(w.warm([7, 8, 9], 0.0)) == {"warmed": 1, "failed": 2}
    assert asyncio.run(w.warm([7, 8, 9], 60.0)) == {"warmed": 0, "failed": 0}   # рано
    assert asyncio.run(w.warm([7, 8, 9], config.CREST_RETRY)) == {"warmed": 0, "failed": 2}


def test_network_error_is_failure_not_crash():
    async def boom(url):
        raise OSError("down")
    w = crests.CrestWarmer(base="https://x.test", fetch=boom)
    assert asyncio.run(w.warm([5], 0.0)) == {"warmed": 0, "failed": 1}


def test_collector_tick_crests_throttled(tmp_db):
    conn = store.connect()
    store.put(conn, "tables", "fotmob", fotmob.normalize_tables(load("fotmob_team_8633.json")))
    col = Collector(conn)
    calls = []
    col.crests = crests.CrestWarmer(base="https://x.test", fetch=_fake({}, calls))
    first = asyncio.run(col.tick_crests(100.0))
    assert first["warmed"] == len(calls) > 0
    assert asyncio.run(col.tick_crests(130.0)) is None          # не чаще раза в минуту
    assert asyncio.run(col.tick_crests(200.0)) == {"warmed": 0, "failed": 0}
    asyncio.run(col.close())
