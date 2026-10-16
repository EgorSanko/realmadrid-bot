"""Расчёт очков: идемпотентность, исправление результата, отмена/перенос, settle_pending."""
import sqlite3
from datetime import timedelta

from .conftest import T0, mk_match, predict, tma


def _finish(provider, mid, h, a, scorer=None, **kw):
    provider.update(mid, status="finished", score={"home": h, "away": a}, first_rm_scorer_player_id=scorer, **kw)


def _points(svc):
    c = sqlite3.connect(svc.db_path)
    try:
        return dict(c.execute("SELECT user_id, points FROM predictions ORDER BY user_id").fetchall())
    finally:
        c.close()


def _audit(svc):
    c = sqlite3.connect(svc.db_path)
    try:
        return c.execute("SELECT kind, old_result, new_result, predictions, changed FROM settle_audit ORDER BY id").fetchall()
    finally:
        c.close()


def _season(client, uid):
    return client.get("/api/predict/me", headers=tma(uid)).json()["season"]


def _setup(client, provider, clock):
    provider.put(mk_match(1))
    assert predict(client, 1, 1, 2, 1, 701).status_code == 200   # точный + бомбардир = 7
    assert predict(client, 2, 1, 3, 2).status_code == 200        # разница = 3
    assert predict(client, 3, 1, 3, 0, 702).status_code == 200   # исход = 2
    assert predict(client, 4, 1, 0, 2).status_code == 200        # промах = 0
    clock.set(T0 + timedelta(hours=2))


def test_settle_idempotent(client, provider, clock, svc):
    _setup(client, provider, clock)
    assert svc.settle("1")["result"] == "pending"  # ещё не завершён
    _finish(provider, 1, 2, 1, 701)
    r = svc.settle("1")
    assert r["result"] == "settled" and r["predictions"] == 4 and r["changed"] == 4
    assert _points(svc) == {1: 7, 2: 3, 3: 2, 4: 0}
    for _ in range(3):
        assert svc.settle("1")["result"] == "unchanged"
    assert svc.settle_pending()[0]["result"] == "unchanged"
    assert _points(svc) == {1: 7, 2: 3, 3: 2, 4: 0}
    assert _season(client, 1)["points"] == 7 and _season(client, 1)["exact"] == 1
    assert len(_audit(svc)) == 1


def test_resettle_after_correction(client, provider, clock, svc):
    _setup(client, provider, clock)
    _finish(provider, 1, 2, 1, 701)
    svc.settle("1")
    _finish(provider, 1, 3, 2, 703)  # результат исправили: 3:2, первым забил другой
    r = svc.settle("1")
    assert r["result"] == "resettled"
    assert _points(svc) == {1: 3, 2: 5, 3: 2, 4: 0}
    assert _season(client, 2) == {**_season(client, 2), "points": 5, "exact": 1, "rank": 1}
    kinds = _audit(svc)
    assert [k[0] for k in kinds] == ["settle", "resettle"]
    assert '"home": 2' in kinds[1][1] and '"home": 3' in kinds[1][2]
    assert svc.settle("1")["result"] == "unchanged"
    assert len(_audit(svc)) == 2


def test_scorer_filled_later_triggers_resettle(client, provider, clock, svc):
    _setup(client, provider, clock)
    _finish(provider, 1, 2, 1, None)  # бомбардир пока неизвестен
    svc.settle("1")
    assert _points(svc)[1] == 5
    _finish(provider, 1, 2, 1, 701)
    assert svc.settle("1")["result"] == "resettled"
    assert _points(svc)[1] == 7


def test_cancelled_match_no_points(client, provider, clock, svc):
    _setup(client, provider, clock)
    provider.update(1, status="cancelled")
    assert svc.settle("1")["result"] == "cancelled"
    assert set(_points(svc).values()) == {None}
    assert _season(client, 1)["points"] == 0 and _season(client, 1)["rank"] is None


def test_cancel_after_settle_voids_points(client, provider, clock, svc):
    _setup(client, provider, clock)
    _finish(provider, 1, 2, 1, 701)
    svc.settle("1")
    provider.update(1, status="cancelled", score=None)
    r = svc.settle("1")
    assert r["result"] == "voided" and r["changed"] == 4
    assert set(_points(svc).values()) == {None}
    assert _season(client, 1)["points"] == 0
    assert [k[0] for k in _audit(svc)] == ["settle", "void"]
    assert svc.settle("1")["result"] == "cancelled"  # повтор — без новых записей
    assert len(_audit(svc)) == 2


def test_postponed_then_played(client, provider, clock, svc):
    _setup(client, provider, clock)
    new_ko = T0 + timedelta(days=3)
    provider.update(1, status="postponed", kickoff_utc=new_ko.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert svc.settle("1")["result"] == "postponed"
    assert predict(client, 4, 1, 2, 1, 701).status_code == 200  # приём продолжается до нового начала
    clock.set(new_ko + timedelta(hours=2))
    assert predict(client, 4, 1, 0, 0).status_code == 409
    _finish(provider, 1, 2, 1, 701, kickoff_utc=new_ko.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert svc.settle_pending()[0]["result"] == "settled"
    assert _points(svc) == {1: 7, 2: 3, 3: 2, 4: 7}


def test_settle_pending_and_unknown(client, provider, clock, svc):
    _setup(client, provider, clock)
    provider.put(mk_match(2, kickoff=T0 + timedelta(days=5)))  # без прогнозов — не трогаем
    assert svc.settle("2")["result"] == "no_predictions"
    assert svc.settle("404")["result"] == "unknown"
    assert [r["result"] for r in svc.settle_pending()] == ["pending"]
    _finish(provider, 1, 2, 1, 701)
    assert [r["result"] for r in svc.settle_pending()] == ["settled"]
    assert [r["result"] for r in svc.settle_pending()] == ["unchanged"]
    # через 15 дней матч выпадает из локальной выборки, но остаётся в provider.recent() — проверяется, без изменений
    clock.set(T0 + timedelta(days=15))
    assert [r["result"] for r in svc.settle_pending()] == ["unchanged"]
    provider.matches.clear()  # и из recent() пропал — больше не трогаем
    assert svc.settle_pending() == []


def test_month_moves_with_kickoff(client, provider, clock, svc):
    """Перенос на другой месяц после расчёта — очки переезжают в рейтинг нового месяца."""
    ko = T0.replace(day=31, hour=12)  # 31 окт 15:00 МСК
    provider.put(mk_match(1, kickoff=ko))
    assert predict(client, 1, 1, 1, 0).status_code == 200
    clock.set(ko + timedelta(hours=3))
    _finish(provider, 1, 1, 0)
    svc.settle("1")
    assert client.get("/api/predict/leaderboard?period=month").json()["total"] == 1
    moved = ko + timedelta(days=2)
    _finish(provider, 1, 1, 0, kickoff_utc=moved.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert svc.settle("1")["result"] == "resettled"  # результат тот же, период другой — пересчёт
    assert client.get("/api/predict/leaderboard?period=month").json()["total"] == 0
    clock.set(moved + timedelta(hours=3))
    assert client.get("/api/predict/leaderboard?period=month").json()["total"] == 1
