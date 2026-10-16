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
    assert len(lb["top"]) == 1 and lb["me"] == {"rank": 3, "points": 0, "exact": 0, "played": 0}
    r = client.get(f"/api/predict/leaderboard?league={lg['id']}", headers=tma(1))
    assert r.status_code == 403 and r.json()["error"] == "not_member"
    assert client.get(f"/api/predict/leaderboard?league={lg['id']}").status_code == 401
    assert client.get("/api/predict/leaderboard?league=9999", headers=tma(1)).status_code == 404


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
