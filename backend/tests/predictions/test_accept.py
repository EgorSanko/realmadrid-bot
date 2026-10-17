"""Приём прогнозов: серверное время, валидация, ограничение частоты."""
from datetime import timedelta

from .conftest import T0, mk_match, predict, tma


def test_before_kickoff_accepted_and_editable(client, provider, clock):
    provider.put(mk_match(1))
    r = predict(client, 10, 1, 2, 1, 701)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["home"] == 2 and first["away"] == 1 and first["first_scorer_id"] == "701"
    assert first["revisions"] == 1 and first["closes_at"] == "2026-10-18T19:00:00Z"

    clock.set(T0 - timedelta(seconds=1))  # за секунду до начала — ещё можно
    r = predict(client, 10, 1, 3, 3)
    assert r.status_code == 200
    last = r.json()
    assert (last["home"], last["away"], last["first_scorer_id"], last["revisions"]) == (3, 3, None, 2)
    assert last["created_at"] == first["created_at"] and last["updated_at"] > first["updated_at"]

    m = client.get("/api/predict/matches", headers=tma(10)).json()["next"]
    assert m["my_prediction"]["home"] == 3 and m["accepting"] is True


def test_closed_at_kickoff_by_server_clock(client, provider, clock):
    provider.put(mk_match(1))
    assert predict(client, 10, 1, 1, 0).status_code == 200
    clock.set(T0)  # ровно в момент начала — уже нельзя, статус у провайдера ещё «scheduled»
    r = predict(client, 10, 1, 5, 0)
    assert r.status_code == 409
    assert r.json() == {"error": "closed", "message": "Приём закрыт: матч уже начался"}
    r = predict(client, 11, 1, 1, 0)  # и создать новый тоже нельзя
    assert r.status_code == 409
    nxt = client.get("/api/predict/matches", headers=tma(10)).json()["next"]
    assert nxt["accepting"] is False and nxt["my_prediction"]["home"] == 1


def test_closed_when_live_even_if_clock_before(client, provider, clock):
    provider.put(mk_match(1, status="live"))
    assert predict(client, 10, 1, 1, 0).status_code == 409


def test_cancelled_rejected(client, provider):
    provider.put(mk_match(1, status="cancelled"))
    r = predict(client, 10, 1, 1, 0)
    assert r.status_code == 409 and r.json()["error"] == "match_cancelled"


def test_unknown_match(client):
    r = predict(client, 10, 999, 1, 0)
    assert r.status_code == 404 and r.json()["error"] == "match_not_found"


def test_goal_validation(client, provider):
    provider.put(mk_match(1))
    for body in ({"home": -1, "away": 0}, {"home": 21, "away": 0}, {"home": 1.5, "away": 0},
                 {"home": "2", "away": 0}, {"home": True, "away": 0}, {"home": 1}, {"away": 1},
                 {"home": 1, "away": 0, "extra": 1}):
        r = client.put("/api/predict/matches/1", json=body, headers=tma(10))
        assert r.status_code == 422, body
        assert r.json()["error"] == "validation" and r.json()["message"], body
    assert client.put("/api/predict/matches/1", json={"home": 20, "away": 0}, headers=tma(10)).status_code == 200
    assert client.put("/api/predict/matches/1", json={"home": 0, "away": 0}, headers=tma(10)).status_code == 200


def test_scorer_must_be_in_squad(client, provider):
    provider.put(mk_match(1))
    r = predict(client, 10, 1, 2, 0, 999)
    assert r.status_code == 422 and r.json()["error"] == "scorer_not_in_squad"
    assert predict(client, 10, 1, 2, 0, "702").status_code == 200  # строковый id тоже годится


def test_no_scorer_if_real_does_not_score_home(client, provider):
    provider.put(mk_match(1, rm_home=True))
    r = predict(client, 10, 1, 0, 2, 701)  # Реал дома, home=0
    assert r.status_code == 422 and r.json()["error"] == "scorer_without_goal"
    assert predict(client, 10, 1, 1, 2, 701).status_code == 200


def test_no_scorer_if_real_does_not_score_away(client, provider):
    provider.put(mk_match(2, rm_home=False))
    r = predict(client, 10, 2, 2, 0, 701)  # Реал в гостях, away=0
    assert r.status_code == 422 and r.json()["error"] == "scorer_without_goal"
    assert predict(client, 10, 2, 0, 1, 701).status_code == 200  # home=0, но Реал в гостях — можно


def test_rate_limit_30_per_minute(client, provider, mono):
    provider.put(mk_match(1))
    for i in range(30):
        assert predict(client, 10, 1, i % 5, 0).status_code == 200
    r = predict(client, 10, 1, 1, 1)
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"
    assert predict(client, 11, 1, 1, 1).status_code == 200  # лимит — на пользователя
    mono.t += 60.1
    assert predict(client, 10, 1, 1, 1).status_code == 200


def test_postponed_new_date_reopens(client, provider, clock):
    provider.put(mk_match(1))
    assert predict(client, 10, 1, 1, 0).status_code == 200
    clock.set(T0 + timedelta(minutes=5))
    assert predict(client, 10, 1, 2, 0).status_code == 409
    provider.update(1, status="postponed", kickoff_utc="2026-10-25T19:00:00Z")  # перенос на неделю
    r = predict(client, 10, 1, 2, 0)
    assert r.status_code == 200 and r.json()["closes_at"] == "2026-10-25T19:00:00Z"
    provider.update(1, status="scheduled")
    clock.set(T0 + timedelta(days=7) - timedelta(seconds=1))
    assert predict(client, 10, 1, 3, 0).status_code == 200
    clock.set(T0 + timedelta(days=7))
    assert predict(client, 10, 1, 4, 0).status_code == 409


def test_postponed_without_new_date_closed_after_old_kickoff(client, provider, clock):
    provider.put(mk_match(1, status="postponed"))
    clock.set(T0 + timedelta(hours=1))
    assert predict(client, 10, 1, 1, 0).status_code == 409


def test_matches_view(client, provider, svc, clock):
    provider.put(mk_match(1, kickoff=T0 - timedelta(days=7)))
    provider.put(mk_match(2))
    provider.put(mk_match(3, kickoff=T0 + timedelta(days=4)))
    clock.set(T0 - timedelta(days=8))
    assert predict(client, 10, 1, 2, 0, 701).status_code == 200
    provider.update(1, status="finished", score={"home": 2, "away": 0}, first_rm_scorer_player_id=701)
    clock.set(T0 - timedelta(days=1))
    svc.settle("1")
    body = client.get("/api/predict/matches", headers=tma(10)).json()
    assert body["next"]["id"] == "2" and body["next"]["accepting"] is True
    assert len(body["next"]["rm_squad"]) == 4 and body["next"]["rm_side"] == "home"
    rec = body["recent"][0]
    assert rec["id"] == "1" and rec["my_points"] == {"total": 7, "score": 5, "scorer": 2, "kind": "exact"}
    anon = client.get("/api/predict/matches").json()
    assert anon["next"]["my_prediction"] is None and anon["recent"][0]["my_points"] is None


def test_provider_not_connected(env):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.predictions import api
    from app.predictions.snapshot_provider import SnapshotProvider
    # снимков сборщика ещё нет (пустая rm.sqlite3) — «данные о матчах не подключены»
    api.configure(provider=SnapshotProvider(db_path=str(env / "rm.sqlite3")), db_path=str(env / "p.db"))
    try:
        r = TestClient(app).get("/api/predict/matches")
        assert r.status_code == 503 and r.json()["error"] == "matches_unavailable"
    finally:
        api._service = None
