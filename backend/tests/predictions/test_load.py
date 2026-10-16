"""Нагрузка в процессе: 10 000 пользователей × 30 матчей (300 000 прогнозов), SQLite-файл во временной папке.

Время печатается (pytest -s). Пропустить: PREDICT_SKIP_LOAD=1.
"""
import os
import random
import statistics
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.predictions.service import iso

from .conftest import mk_match, tma

USERS = 10_000
MATCHES = 30

pytestmark = pytest.mark.skipif(os.environ.get("PREDICT_SKIP_LOAD") == "1", reason="PREDICT_SKIP_LOAD=1")


def _ms(f, n=1):
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        f()
        ts.append((time.perf_counter() - t) * 1000)
    return ts


def test_load_10k_users_30_matches(client, provider, clock, svc):
    rnd = random.Random(10)
    start = datetime(2026, 8, 16, 19, 0, tzinfo=timezone.utc)
    kos = [start + timedelta(days=3 * i) for i in range(MATCHES)]  # 16 авг — 13 ноя: 4 месяца
    clock.set(start - timedelta(days=1))
    for i, ko in enumerate(kos):
        provider.put(mk_match(i + 1, kickoff=ko, rm_home=i % 2 == 0))

    t = time.perf_counter()
    with svc.tx() as c:
        c.executemany("INSERT INTO users(id, first_name, created_at, updated_at) VALUES (?,?,?,?)",
                      [(u, f"U{u}", "2026-08-01T00:00:00.000000Z", "2026-08-01T00:00:00.000000Z")
                       for u in range(1, USERS + 1)])
        for i in range(MATCHES):
            svc._sync_match(c, provider.get_match(str(i + 1)))
        rows = []
        for i, ko in enumerate(kos):
            base = ko - timedelta(days=2)
            for u in range(1, USERS + 1):
                h, a = rnd.randint(0, 4), rnd.randint(0, 3)
                rm_goals = h if i % 2 == 0 else a
                sc = str(rnd.choice((701, 702, 703, 704))) if rm_goals and rnd.random() < 0.7 else None
                at = iso(base + timedelta(seconds=rnd.randint(0, 86400)))
                rows.append((u, str(i + 1), h, a, sc, at, at))
        c.executemany("INSERT INTO predictions(user_id, match_id, home, away, first_scorer, created_at, updated_at) "
                      "VALUES (?,?,?,?,?,?,?)", rows)
    fill_s = time.perf_counter() - t

    for i in range(MATCHES):
        provider.update(i + 1, status="finished", score={"home": rnd.randint(0, 4), "away": rnd.randint(0, 3)},
                        first_rm_scorer_player_id=rnd.choice((701, 702, 703)))
    clock.set(kos[-1] + timedelta(hours=3))

    one = _ms(lambda: svc.settle("1"))[0]                       # первый матч: 10 000 прогнозов
    again = _ms(lambda: svc.settle("1"))[0]                     # идемпотентный повтор
    t = time.perf_counter()
    res = svc.settle_pending()
    pending_ms = (time.perf_counter() - t) * 1000
    assert sum(r["result"] == "settled" for r in res) == MATCHES - 1  # матч 1 уже рассчитан и старше 14 дней
    resettle_pending = _ms(svc.settle_pending)[0]                # всё уже рассчитано — только проверка
    provider.update(15, score={"home": 9, "away": 9})            # исправили результат одного матча
    resettle_one = _ms(lambda: svc.settle("15"))[0]

    h = tma(USERS // 2, first_name=f"U{USERS // 2}")
    lb_season = _ms(lambda: client.get("/api/predict/leaderboard?period=season", headers=h), 20)
    lb_month = _ms(lambda: client.get("/api/predict/leaderboard?period=month", headers=h), 20)
    lb_anon = _ms(lambda: client.get("/api/predict/leaderboard?period=season&limit=100"), 20)
    me = _ms(lambda: client.get("/api/predict/me", headers=h), 20)

    body = client.get("/api/predict/leaderboard?period=season", headers=h).json()
    assert body["total"] == USERS and len(body["top"]) == 50 and body["me"]["rank"] is not None
    pts = [r["points"] for r in body["top"]]
    assert pts == sorted(pts, reverse=True)

    # лига на 1000 участников
    lg = client.post("/api/predict/leagues", json={"name": "Большая"}, headers=h).json()
    with svc.tx() as c:
        c.executemany("INSERT OR IGNORE INTO league_members(league_id, user_id, joined_at) VALUES (?,?,?)",
                      [(lg["id"], u, "2026-08-01T00:00:00.000000Z") for u in range(1, 1001)])
    lb_league = _ms(lambda: client.get(f"/api/predict/leaderboard?league={lg['id']}", headers=h), 20)

    report = {
        "наполнение (10k пользователей, 300k прогнозов), с": round(fill_s, 2),
        "settle(1 матч, 10k прогнозов), мс": round(one, 1),
        "settle повтор (без изменений), мс": round(again, 1),
        "settle_pending (29 матчей), мс": round(pending_ms, 1),
        "settle_pending повтор (всё рассчитано), мс": round(resettle_pending, 1),
        "settle после исправления результата, мс": round(resettle_one, 1),
        "GET /leaderboard season (с me), мс медиана/макс": (round(statistics.median(lb_season), 1), round(max(lb_season), 1)),
        "GET /leaderboard month (с me), мс медиана/макс": (round(statistics.median(lb_month), 1), round(max(lb_month), 1)),
        "GET /leaderboard season limit=100 аноним, мс медиана/макс": (round(statistics.median(lb_anon), 1), round(max(lb_anon), 1)),
        "GET /leaderboard league (1000 участников), мс медиана/макс": (round(statistics.median(lb_league), 1), round(max(lb_league), 1)),
        "GET /me, мс медиана/макс": (round(statistics.median(me), 1), round(max(me), 1)),
    }
    print("\nНАГРУЗКА:")
    for k, v in report.items():
        print(f"  {k}: {v}")
    assert statistics.median(lb_season) < 300
    assert one < 5000
