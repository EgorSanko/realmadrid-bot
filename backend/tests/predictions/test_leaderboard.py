"""Рейтинги: порядок мест при равенстве, место вне топа, месяц/сезон по МСК."""
from datetime import datetime, timedelta, timezone

from app.predictions.service import month_of, period_info, season_of

from .conftest import T0, mk_match, predict, sign_init_data, tma

M2_KO = T0 + timedelta(days=3)


def _play(client, provider, clock, svc):
    provider.put(mk_match(1))
    provider.put(mk_match(2, kickoff=M2_KO))
    t1, t2, t3 = (T0 - timedelta(hours=h) for h in (30, 20, 10))
    plan = [  # (uid, время, прогноз М1, прогноз М2)
        (50, t1, (2, 1), (0, 1)),   # A: 5 + 0 = 5, точных 1
        (40, t1, (3, 2), (1, 0)),   # B: 3 + 2 = 5, точных 0
        (30, t1, (3, 2), (0, 3)),   # C: 3, последний прогноз раньше
        (20, t2, (3, 2), (0, 3)),   # D: 3, последний прогноз позже
        (11, t3, (2, 0), (0, 1)),   # E: 2, всё одинаково с F, id больше
        (10, t3, (2, 0), (0, 1)),   # F: 2
    ]
    for uid, t, p1, p2 in plan:
        clock.set(t)
        assert predict(client, uid, 1, *p1, first_name=f"U{uid}").status_code == 200
        assert predict(client, uid, 2, *p2, first_name=f"U{uid}").status_code == 200
    provider.update(1, status="finished", score={"home": 2, "away": 1})
    provider.update(2, status="finished", score={"home": 2, "away": 0})
    clock.set(M2_KO + timedelta(hours=3))
    assert [r["result"] for r in svc.settle_pending()] == ["settled", "settled"]


def test_tie_breaks_and_order(client, provider, clock, svc):
    _play(client, provider, clock, svc)
    lb = client.get("/api/predict/leaderboard?period=season", headers=tma(20, first_name="U20")).json()
    assert [(r["rank"], r["name"], r["points"], r["exact"]) for r in lb["top"]] == [
        (1, "U50", 5, 1), (2, "U40", 5, 0), (3, "U30", 3, 0), (4, "U20", 3, 0), (5, "U10", 2, 0), (6, "U11", 2, 0)]
    assert lb["total"] == 6 and lb["key"] == "S2026" and lb["label"] == "2026/27"
    assert [r["is_me"] for r in lb["top"]].index(True) == 3


def test_me_outside_top(client, provider, clock, svc):
    _play(client, provider, clock, svc)
    lb = client.get("/api/predict/leaderboard?period=season&limit=2", headers=tma(11, first_name="U11")).json()
    assert [r["name"] for r in lb["top"]] == ["U50", "U40"]
    assert lb["me"] == {"rank": 6, "points": 2, "exact": 0, "played": 2}
    me = client.get("/api/predict/me", headers=tma(20, first_name="U20")).json()
    assert (me["rank"], me["points"], me["exact"], me["predictions"]) == (4, 3, 0, 2)
    assert len(me["history"]) == 2 and me["history"][0]["match"]["id"] == "2"
    assert me["history"][0]["state"] == "settled" and me["history"][0]["points"]["kind"] == "miss"


def test_new_user_has_no_place(client, provider, clock, svc):
    _play(client, provider, clock, svc)
    lb = client.get("/api/predict/leaderboard", headers=tma(777)).json()
    assert lb["me"] == {"rank": None, "points": 0, "exact": 0, "played": 0}


def test_anonymous_and_forged_read_only(client, provider, clock, svc):
    _play(client, provider, clock, svc)
    anon = client.get("/api/predict/leaderboard")
    assert anon.status_code == 200 and anon.json()["me"] is None and len(anon.json()["top"]) == 6
    forged = client.get("/api/predict/leaderboard",
                        headers={"Authorization": "tma " + sign_init_data(20, bot_token="999:other-bot")})
    assert forged.status_code == 200 and forged.json()["me"] is None
    assert not any(r["is_me"] for r in forged.json()["top"])


def test_leaderboard_validation(client):
    r = client.get("/api/predict/leaderboard?period=year")
    assert r.status_code == 422 and r.json() == {"error": "validation", "message": "period: season или month"}
    assert client.get("/api/predict/leaderboard?limit=0").status_code == 422
    assert client.get("/api/predict/leaderboard?limit=101").status_code == 422


def test_month_boundary_msk(client, provider, clock, svc):
    oct_ko = datetime(2026, 10, 31, 20, 30, tzinfo=timezone.utc)  # 31 окт 23:30 МСК
    nov_ko = datetime(2026, 10, 31, 21, 30, tzinfo=timezone.utc)  # 1 ноя 00:30 МСК (в UTC ещё октябрь)
    assert month_of(oct_ko) == "2026-10" and month_of(nov_ko) == "2026-11"
    provider.put(mk_match(1, kickoff=oct_ko))
    provider.put(mk_match(2, kickoff=nov_ko))
    clock.set(oct_ko - timedelta(hours=1))
    assert predict(client, 1, 1, 1, 0).status_code == 200  # 5 очков в октябре
    assert predict(client, 2, 2, 1, 0).status_code == 200  # 5 очков в ноябре
    provider.update(1, status="finished", score={"home": 1, "away": 0})
    provider.update(2, status="finished", score={"home": 1, "away": 0})
    clock.set(datetime(2026, 10, 31, 20, 59, 59, tzinfo=timezone.utc))  # 23:59:59 МСК 31 окт
    svc.settle("1"), svc.settle("2")
    oct_lb = client.get("/api/predict/leaderboard?period=month").json()
    assert oct_lb["key"] == "M2026-10" and [r["name"] for r in oct_lb["top"]] == ["Тест"]
    assert client.get("/api/predict/leaderboard?period=month", headers=tma(1)).json()["me"]["rank"] == 1
    assert client.get("/api/predict/leaderboard?period=month", headers=tma(2)).json()["me"]["rank"] is None
    clock.set(datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc))  # 00:00 МСК 1 ноя
    nov = client.get("/api/predict/leaderboard?period=month", headers=tma(2)).json()
    assert nov["key"] == "M2026-11" and nov["me"]["rank"] == 1 and nov["total"] == 1
    assert nov["from"] == "2026-10-31T21:00:00Z" and nov["to"] == "2026-11-30T21:00:00Z"
    season = client.get("/api/predict/leaderboard?period=season").json()
    assert season["total"] == 2


def test_season_boundary_msk():
    assert season_of(datetime(2027, 6, 30, 20, 59, tzinfo=timezone.utc)) == 2026  # 30 июня 23:59 МСК
    assert season_of(datetime(2027, 6, 30, 21, 0, tzinfo=timezone.utc)) == 2027   # 1 июля 00:00 МСК
    assert season_of(datetime(2027, 1, 15, tzinfo=timezone.utc)) == 2026
    info = period_info("season", datetime(2026, 12, 31, 21, 0, tzinfo=timezone.utc))
    assert info["label"] == "2026/27" and info["from"] == "2026-06-30T21:00:00Z"
    dec = period_info("month", datetime(2026, 12, 15, tzinfo=timezone.utc))
    assert dec["to"] == "2026-12-31T21:00:00Z"
