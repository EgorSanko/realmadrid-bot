"""Лиги с друзьями."""
import re
from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.predictions import api
from app.predictions.service import CODE_ALPHABET

from .conftest import T0, mk_match, predict, tma

L = "/api/predict/leagues"


def _create(client, uid, name="Друзья с работы"):
    return client.post(L, json={"name": name}, headers=tma(uid))


def test_create_league(client):
    r = _create(client, 1)
    assert r.status_code == 201, r.text
    lg = r.json()
    assert lg["name"] == "Друзья с работы" and lg["is_owner"] is True and lg["members"] == 1
    assert len(lg["code"]) >= 8 and set(lg["code"]) <= set(CODE_ALPHABET)
    assert lg["invite_link"] == f"https://t.me/madridista_bot?startapp=league_{lg['code']}"
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", "league_" + lg["code"])  # формат start_param Telegram
    codes = {_create(client, 1, f"Лига {i}").json()["code"] for i in range(5)}
    assert len(codes) == 5 and lg["code"] not in codes


def test_league_name_validation(client):
    assert _create(client, 1, "x" * 40).status_code == 201
    for bad in ("x" * 41, "", "   ", "a\x00b"):
        r = _create(client, 1, bad)
        assert r.status_code == 422 and r.json()["error"] == "validation", bad
    r = client.post(L, json={"name": 5}, headers=tma(1))
    assert r.status_code == 422
    assert _create(client, 1, "  Мадрид   навсегда  ").json()["name"] == "Мадрид навсегда"


def test_join_leave_and_list(client):
    lg = _create(client, 1).json()
    r = client.post(f"{L}/join", json={"code": lg["code"].lower()}, headers=tma(2))
    assert r.status_code == 200 and r.json()["joined"] is True and r.json()["is_owner"] is False
    r = client.post(f"{L}/join", json={"code": "league_" + lg["code"]}, headers=tma(2))
    assert r.json()["joined"] is False and r.json()["members"] == 2  # повторно — без дублей
    mine = client.get(L, headers=tma(2)).json()["leagues"]
    assert [x["id"] for x in mine] == [lg["id"]] and mine[0]["invite_link"] == lg["invite_link"]
    assert client.delete(f"{L}/{lg['id']}/membership", headers=tma(2)).json() == {"ok": True}
    assert client.get(L, headers=tma(2)).json()["leagues"] == []
    r = client.delete(f"{L}/{lg['id']}/membership", headers=tma(2))
    assert r.status_code == 404 and r.json()["error"] == "not_member"
    r = client.delete(f"{L}/{lg['id']}/membership", headers=tma(1))
    assert r.status_code == 409 and r.json()["error"] == "owner_cannot_leave"


def test_wrong_code(client):
    _create(client, 1)
    r = client.post(f"{L}/join", json={"code": "ZZZZZZZZZZ"}, headers=tma(2))
    assert r.status_code == 404 and r.json() == {"error": "invalid_code", "message": "Неверный код приглашения"}
    assert client.post(f"{L}/join", json={"code": ""}, headers=tma(2)).status_code == 422


def test_join_bruteforce_limited(client, mono):
    for _ in range(20):
        assert client.post(f"{L}/join", json={"code": "AAAAAAAAAA"}, headers=tma(2)).status_code == 404
    assert client.post(f"{L}/join", json={"code": "AAAAAAAAAA"}, headers=tma(2)).status_code == 429
    mono.t += 61
    assert client.post(f"{L}/join", json={"code": "AAAAAAAAAA"}, headers=tma(2)).status_code == 404


def test_rename_and_delete_owner_only(client):
    lg = _create(client, 1).json()
    client.post(f"{L}/join", json={"code": lg["code"]}, headers=tma(2))
    r = client.patch(f"{L}/{lg['id']}", json={"name": "Чужое"}, headers=tma(2))
    assert r.status_code == 403 and r.json()["error"] == "not_owner"
    r = client.delete(f"{L}/{lg['id']}", headers=tma(2))
    assert r.status_code == 403 and r.json()["error"] == "not_owner"
    r = client.patch(f"{L}/{lg['id']}", json={"name": "Новое имя"}, headers=tma(1))
    assert r.status_code == 200 and r.json()["name"] == "Новое имя"
    assert client.delete(f"{L}/{lg['id']}", headers=tma(1)).json() == {"ok": True}
    assert client.get(L, headers=tma(2)).json()["leagues"] == []
    assert client.delete(f"{L}/{lg['id']}", headers=tma(1)).status_code == 404
    assert client.patch(f"{L}/{lg['id']}", json={"name": "x"}, headers=tma(1)).status_code == 404


def test_league_leaderboard(client, provider, clock, svc):
    provider.put(mk_match(1))
    for uid, p in ((1, (2, 1)), (2, (1, 0)), (3, (3, 0)), (4, (2, 1))):
        assert predict(client, uid, 1, *p, first_name=f"U{uid}").status_code == 200
    lg = client.post(L, json={"name": "Друзья"}, headers=tma(2, first_name="U2")).json()
    client.post(f"{L}/join", json={"code": lg["code"]}, headers=tma(3, first_name="U3"))
    client.post(f"{L}/join", json={"code": lg["code"]}, headers=tma(9, first_name="U9"))  # без прогнозов
    provider.update(1, status="finished", score={"home": 2, "away": 1})
    clock.set(T0 + timedelta(hours=3))
    svc.settle("1")
    lb = client.get(f"/api/predict/leaderboard?league={lg['id']}", headers=tma(3, first_name="U3")).json()
    assert lb["league"] == {"id": lg["id"], "name": "Друзья"} and lb["total"] == 3
    assert [(r["rank"], r["name"], r["points"]) for r in lb["top"]] == [(1, "U2", 3), (2, "U3", 2), (3, "U9", 0)]
    assert lb["me"]["rank"] == 2
    lb = client.get(f"/api/predict/leaderboard?league={lg['id']}&limit=1", headers=tma(9, first_name="U9")).json()
    assert len(lb["top"]) == 1 and lb["me"] == {"rank": 3, "place": 3, "points": 0, "exact": 0, "played": 0}
    r = client.get(f"/api/predict/leaderboard?league={lg['id']}", headers=tma(1))
    assert r.status_code == 403 and r.json()["error"] == "not_member"
    assert client.get(f"/api/predict/leaderboard?league={lg['id']}").status_code == 401
    assert client.get("/api/predict/leaderboard?league=9999", headers=tma(1)).status_code == 404


def test_league_header_access(client):
    lg = _create(client, 1).json()
    assert client.get(f"{L}/{lg['id']}").status_code == 401
    r = client.get(f"{L}/{lg['id']}", headers=tma(2))
    assert r.status_code == 403 and r.json()["error"] == "not_member"
    r = client.get(f"{L}/9999", headers=tma(1))
    assert r.status_code == 404 and r.json()["error"] == "league_not_found"
    assert client.get(f"{L}/abc", headers=tma(1)).status_code == 422


def test_league_header_people_and_next(client, provider, clock):
    provider.put(mk_match(1))
    provider.put(mk_match(2, kickoff=T0 + timedelta(days=4)))
    lg = client.post(L, json={"name": "Бомжи"}, headers=tma(1697882482, first_name="Егор")).json()
    client.post(f"{L}/join", json={"code": lg["code"]}, headers=tma(55, first_name="artur"))
    client.post(f"{L}/join", json={"code": lg["code"]}, headers=tma(66, first_name="Вика", last_name="Петрова"))
    assert predict(client, 55, 1, 3, 1, first_name="artur").status_code == 200
    assert predict(client, 66, 2, 2, 2, first_name="Вика", last_name="Петрова").status_code == 200  # не ближайший
    r = client.get(f"{L}/{lg['id']}", headers=tma(1697882482, first_name="Егор"))
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["name"] == "Бомжи" and h["members"] == 3 and h["is_owner"] is True
    assert h["next_match"] == {"id": "1", "kickoff_utc": "2026-10-18T19:00:00Z", "home": {"id": "8633", "name": "Реал Мадрид"},
                               "away": {"id": "8302", "name": "Севилья"}, "rm_side": "home"}
    assert [(p["name"], p["is_me"], p["is_owner"], p["predicted_next"]) for p in h["people"]] == [
        ("Егор", True, True, False), ("artur", False, False, True), ("Вика П.", False, False, False)]
    assert h["predicted_next_count"] == 1
    assert [f["name"] for f in h["faces"]] == ["Егор", "artur", "Вика П."]
    # ни id пользователей, ни счёта чужих прогнозов
    body = r.text
    assert "1697882482" not in body and '"user_id"' not in body and '"home":3' not in body and '"away":1' not in body
    for p in h["people"]:
        assert set(p) == {"name", "avatar", "is_me", "is_owner", "predicted_next"}
    # список лиг — те же лица
    mine = client.get(L, headers=tma(55, first_name="artur")).json()["leagues"][0]
    assert mine["faces"] == h["faces"] and mine["is_owner"] is False
    # матч начался — приём закрыт: ближайший открытый — следующий, прогноз на него у Вики
    clock.set(T0 + timedelta(minutes=5))
    provider.update(1, status="live")
    h = client.get(f"{L}/{lg['id']}", headers=tma(55, first_name="artur")).json()
    assert h["next_match"]["id"] == "2" and h["predicted_next_count"] == 1
    assert [p["predicted_next"] for p in h["people"]] == [False, False, True]
    assert [p["is_me"] for p in h["people"]] == [False, True, False]


def test_league_header_without_matches(client, provider):
    lg = _create(client, 1).json()
    h = client.get(f"{L}/{lg['id']}", headers=tma(1)).json()
    assert h["next_match"] is None and h["predicted_next_count"] == 0
    assert [p["predicted_next"] for p in h["people"]] == [False]
    provider.put(mk_match(7, status="cancelled"))
    assert client.get(f"{L}/{lg['id']}", headers=tma(1)).json()["next_match"] is None


def test_invite_link_from_env(env, provider, clock, monkeypatch):
    monkeypatch.setenv("BOT_USERNAME", "@RealFanBot")
    api.configure(provider=provider, db_path=str(env / "p.db"), clock=clock)
    try:
        lg = TestClient(app).post(L, json={"name": "Лига"}, headers=tma(1)).json()
        assert lg["invite_link"] == f"https://t.me/RealFanBot?startapp=league_{lg['code']}"
        monkeypatch.delenv("BOT_USERNAME")
        assert TestClient(app).get(L, headers=tma(1)).json()["leagues"][0]["invite_link"] is None
    finally:
        api._service = None
