"""Сборщик начисляет очки прогнозов: матч стал «завершён» → settle_pending; повтор ничего не удваивает;
исправление итога → пересчёт; фоновый проход — раз в SETTLE_INTERVAL."""
import asyncio
import copy
import time
from datetime import datetime, timedelta, timezone

import pytest

from app import config, store
from app.collector import Collector
from app.predictions import db
from app.predictions.service import PredictionService
from app.predictions.snapshot_provider import SnapshotProvider
from app.sources import fotmob

from ..conftest import load

KO = datetime(2026, 10, 14, 19, 0, tzinfo=timezone.utc)  # Рома — Реал
MBAPPE, VINI = 701154, 846033


def _scheduled(row):
    row["status"] = {"state": "scheduled", "live": False, "finished": False, "minute": None, "added": None,
                     "label": None}
    row["home"]["score"] = row["away"]["score"] = None


@pytest.fixture()
def world(tmp_db, env):
    conn = store.connect()
    raw = load("fotmob_team_8633.json")
    fx = fotmob.normalize_fixtures(raw)
    _scheduled(next(f for f in fx if f["id"] == 6106274))
    store.put(conn, "fixtures", "fotmob", fx)
    store.put(conn, "team", "fotmob", fotmob.normalize_team(raw))
    # прогнозы до начала матча
    before = KO - timedelta(hours=1)
    svc = PredictionService(SnapshotProvider(clock=lambda: before.timestamp()), clock=lambda: before)
    for uid in (1, 2, 3):
        svc.upsert_user({"id": uid, "first_name": f"U{uid}"})
    svc.put_prediction(1, "6106274", 3, 4, MBAPPE)   # точный счёт + бомбардир = 7
    svc.put_prediction(2, "6106274", 1, 2, VINI)     # разница мячей = 3
    svc.put_prediction(3, "6106274", 2, 0)           # мимо = 0
    c = Collector(conn)
    c.predict_clock = lambda: KO + timedelta(hours=3)
    full = fotmob.normalize_match(load("fotmob_match_6106274.json"))
    state = {"m": full}

    async def fake_fotmob(fid, full_):
        return copy.deepcopy(state["m"])

    c._match_fotmob = fake_fotmob
    yield c, conn, state
    asyncio.run(c.close())
    conn.close()


def points(path=None):
    conn = db.connect(path)
    try:
        return {r["user_id"]: (r["points"], r["points_score"], r["points_scorer"])
                for r in conn.execute("SELECT * FROM predictions ORDER BY user_id")}, \
            conn.execute("SELECT COUNT(*) FROM settle_audit").fetchone()[0], \
            {r["user_id"]: r["points"] for r in conn.execute("SELECT * FROM standings WHERE period='S2026'")}
    finally:
        conn.close()


def test_collector_settles_once(world):
    c, conn, state = world

    async def go():
        now = time.time()
        await c.tick_settle(now)                       # первый проход: матч ещё не сыгран — очков нет
        assert points()[0][1] == (None, None, None)
        m = await c.refresh_match("6106274", live=True)  # сборщик увидел «завершён»
        assert m["status"]["finished"] and c.settle_due is True
        res = await c.tick_settle(now + 1)             # вне очереди, не дожидаясь 10 мин
        assert [r["result"] for r in res if r["match_id"] == "6106274"] == ["settled"]
        first = points()
        assert first[0] == {1: (7, 5, 2), 2: (3, 3, 0), 3: (0, 0, 0)} and first[1] == 1
        assert first[2] == {1: 7, 2: 3, 3: 0}
        # повторный снимок того же итога: вне очереди не считаем; принудительный проход — unchanged
        await c.refresh_match("6106274", live=True)
        assert c.settle_due is False and await c.tick_settle(now + 2) is None
        res = await c.tick_settle(now + 3, force=True)
        assert {r["result"] for r in res if r["match_id"] == "6106274"} == {"unchanged"}
        assert points() == first                       # ничего не удвоилось
        # фоновый проход — по интервалу
        assert await c.tick_settle(now + 3 + config.SETTLE_INTERVAL - 5) is None
        assert await c.tick_settle(now + 3 + config.SETTLE_INTERVAL + 1) is not None
        assert points() == first
        # исправление итога в течение 14 дней: первым забил Винисиус (а не Мбаппе)
        fixed = copy.deepcopy(state["m"])
        g = next(e for e in fixed["events"] if e["type"] == "goal" and e["side"] == "away")
        g["player"] = {"id": VINI, "name": "Vinícius Júnior", "photo": None}
        state["m"] = fixed
        await c.refresh_match("6106274", live=True)
        assert c.settle_due is True
        res = await c.tick_settle(now + 4000)
        assert [r["result"] for r in res if r["match_id"] == "6106274"] == ["resettled"]
        after = points()
        assert after[0] == {1: (5, 5, 0), 2: (5, 3, 2), 3: (0, 0, 0)} and after[1] == 2
        assert after[2] == {1: 5, 2: 5, 3: 0}

    asyncio.run(go())


def test_fixture_result_change_is_noticed(world):
    c, conn, _ = world
    before = c._results_sig()
    fx = store.get(conn, "fixtures")["data"]
    row = next(f for f in fx if f["id"] == 6106274)
    row["status"] = {"state": "finished", "live": False, "finished": True, "minute": None, "added": None,
                     "label": "FT"}
    row["home"]["score"], row["away"]["score"] = 3, 4
    store.put(conn, "fixtures", "fotmob", fx)
    assert c._results_sig() != before
    # только календарь (снимка матча нет): счёт есть, автор первого гола неизвестен — бонуса нет
    res = asyncio.run(c.tick_settle(time.time(), force=True))
    assert [r["result"] for r in res if r["match_id"] == "6106274"] == ["settled"]
    assert points()[0] == {1: (5, 5, 0), 2: (3, 3, 0), 3: (0, 0, 0)}


def test_daemon_loop_settles(world, monkeypatch):
    """Цикл демона целиком: матч в окне → снимок «завершён» → очки в том же такте; следующие такты — без изменений."""
    c, conn, _ = world
    monkeypatch.setattr(config, "DEBUG_LIVE_MATCHES", [6106274])
    monkeypatch.setattr(config, "LIVE_INTERVAL", 0)

    async def noop(*a, **k):
        return {}

    async def no_players(*a, **k):
        return []

    for name in ("refresh_team", "refresh_mapping", "refresh_news", "refresh_videos"):
        monkeypatch.setattr(c, name, noop)
    monkeypatch.setattr(c, "tick_players", no_players)
    c.last_team = c.last_mapping = c.last_news = c.last_videos = time.time() + 3600
    calls = []
    orig = c.tick_settle

    async def spy(now, force=False):
        r = await orig(now, force)
        if r is not None:
            calls.append([x["result"] for x in r if x["match_id"] == "6106274"])
        return r

    monkeypatch.setattr(c, "tick_settle", spy)

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(c.run(stop))
        await asyncio.sleep(3.5)  # ~3 такта по 1 с
        stop.set()
        await task

    asyncio.run(go())
    # 1-й такт: проход по старту (матч ещё «не начался» в базе прогнозов → pending) или сразу settled
    flat = [r for call in calls for r in call]
    assert "settled" in flat and flat.count("settled") == 1
    assert all(r in ("pending", "unchanged") for r in flat if r != "settled")
    assert points()[0] == {1: (7, 5, 2), 2: (3, 3, 0), 3: (0, 0, 0)} and points()[1] == 1
