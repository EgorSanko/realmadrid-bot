"""Удаление аккаунта (DELETE /api/auth/me) и вход для проверки магазином приложений (POST /api/auth/review)."""
import sqlite3
from datetime import timedelta

import pytest

from app import auth, auth_api, avatars

from .conftest import T0, mk_match, predict, tma
from .test_login import as_cookie, as_header, login, sign_widget

REVIEW = "RS-7K4P-Q9TX-M2"


@pytest.fixture(autouse=True)
def clean_env(env, monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "111")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("REVIEW_LOGIN_CODE", raising=False)
    monkeypatch.delenv("REVIEW_USER_ID", raising=False)


def rows(svc, sql, *args):
    c = sqlite3.connect(svc.db_path)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def delete(client, headers, body=None):
    return client.request("DELETE", "/api/auth/me", json={"confirm": True} if body is None else body, headers=headers)


# ---------- удаление аккаунта ----------

def test_delete_account_removes_everything(client, svc, provider, clock, env):
    provider.put(mk_match(1))
    provider.put(mk_match(2, kickoff=T0 + timedelta(days=7)))
    tok = login(client, sign_widget(7)).json()["token"]
    other = login(client, sign_widget(8)).json()["token"]
    assert predict(client, 7, 1, 2, 1).status_code == 200
    assert predict(client, 8, 1, 1, 1).status_code == 200
    own = client.post("/api/predict/leagues", json={"name": "Моя"}, headers=as_cookie(tok)).json()
    theirs = client.post("/api/predict/leagues", json={"name": "Чужая"}, headers=as_cookie(other)).json()
    assert client.post("/api/predict/leagues/join", json={"code": own["code"]}, headers=as_cookie(other)).status_code == 200
    assert client.post("/api/predict/leagues/join", json={"code": theirs["code"]}, headers=as_cookie(tok)).status_code == 200
    # матч сыгран и рассчитан — оба в рейтинге
    clock.set(T0 + timedelta(hours=3))
    provider.update(1, status="finished", score={"home": 2, "away": 1})
    svc.settle_pending()
    assert rows(svc, "SELECT COUNT(*) FROM standings WHERE user_id=7")[0][0] > 0
    # итог игры, заявка на вход, файл аватара
    c = sqlite3.connect(svc.db_path)
    c.execute("INSERT INTO game_results(user_id, game, level, score, week, created_at) VALUES (7,'quiz','easy',5,'2026-10-12','x')")
    c.execute("INSERT INTO login_codes(token, code, nonce_hash, created_at, expires_at, user_id) "
              "VALUES ('t'||hex(randomblob(8)), '123456', 'h', 'x', 'x', 7)")
    c.commit()
    c.close()
    avatars.avatars_dir().mkdir(parents=True, exist_ok=True)
    (avatars.avatars_dir() / "7.jpg").write_bytes(b"\xff\xd8\xff")

    r = delete(client, as_cookie(tok))
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "deleted": True}
    sc = r.headers["set-cookie"].lower()
    assert sc.startswith("rm_session=") and ("max-age=0" in sc or "expires=" in sc)

    for table in ("users WHERE id=7", "predictions WHERE user_id=7", "standings WHERE user_id=7",
                  "game_results WHERE user_id=7", "login_codes WHERE user_id=7", "league_members WHERE user_id=7",
                  "leagues WHERE owner_id=7", "avatar_queue WHERE user_id=7"):
        assert rows(svc, f"SELECT COUNT(*) FROM {table}")[0][0] == 0, table
    assert not (avatars.avatars_dir() / "7.jpg").exists()
    # сессия больше не действует
    assert client.get("/api/predict/me", headers=as_cookie(tok)).status_code == 401
    assert client.get("/api/auth/me", headers=as_header(tok)).json()["user"] is None
    # второй пользователь цел; рейтинг не ломается, он теперь первый
    lb = client.get("/api/predict/leaderboard", headers=as_cookie(other))
    assert lb.status_code == 200, lb.text
    top = lb.json()["top"]
    assert len(top) == 1 and top[0]["is_me"] is True and top[0]["rank"] == 1
    mine = client.get("/api/predict/leagues", headers=as_cookie(other)).json()["leagues"]
    assert [lg["name"] for lg in mine] == ["Чужая"] and mine[0]["members"] == 1
    assert rows(svc, "SELECT COUNT(*) FROM predictions WHERE user_id=8")[0][0] == 1


def test_delete_needs_auth_and_confirm(client, svc):
    assert delete(client, {}).status_code == 401
    tok = login(client, sign_widget(7)).json()["token"]
    assert delete(client, as_cookie(tok), body={}).status_code == 422
    assert delete(client, as_cookie(tok), body={"confirm": "yes"}).status_code == 422
    assert rows(svc, "SELECT COUNT(*) FROM users WHERE id=7")[0][0] == 1


def test_delete_cross_site_rejected(client, svc):
    tok = login(client, sign_widget(7)).json()["token"]
    r = delete(client, {**as_cookie(tok), "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 401
    assert rows(svc, "SELECT COUNT(*) FROM users WHERE id=7")[0][0] == 1


def test_old_session_does_not_revive_after_reregistration(client, svc):
    old = login(client, sign_widget(7)).json()["token"]
    assert delete(client, as_cookie(old)).status_code == 200
    new = login(client, sign_widget(7)).json()["token"]  # тот же человек зарегистрировался снова
    assert client.get("/api/predict/me", headers=as_cookie(new)).status_code == 200
    assert client.get("/api/predict/me", headers=as_cookie(old)).status_code == 401


def test_delete_from_mini_app(client, svc):
    assert client.get("/api/predict/me", headers=tma(42)).status_code == 200
    r = client.request("DELETE", "/api/auth/me", json={"confirm": True}, headers=tma(42))
    assert r.status_code == 200 and r.json()["deleted"] is True


# ---------- вход для проверки магазином ----------

def review(client, code, **headers):
    return client.post("/api/auth/review", json={"code": code}, headers=headers)


def test_review_disabled_by_default(client, svc, monkeypatch):
    assert review(client, REVIEW).status_code == 404
    monkeypatch.setenv("REVIEW_LOGIN_CODE", "short")  # слишком короткий — тоже выключено
    assert review(client, "short").status_code == 404


def test_review_login(client, svc, monkeypatch):
    monkeypatch.setenv("REVIEW_LOGIN_CODE", REVIEW)
    assert review(client, "RS-0000-0000-00").status_code == 401
    r = review(client, " rs 7k4p-q9tx-m2 ")  # регистр, пробелы и дефисы не важны
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["via"] == "review" and j["is_admin"] is False
    assert j["user"]["name"] == "RuStore Проверка" and j["user"]["id"] == auth_api.REVIEW_USER_ID_DEFAULT
    assert r.headers["set-cookie"].startswith("rm_session=")
    # сессия работает: профиль и прогнозы
    assert client.get("/api/auth/me", headers=as_header(j["token"])).json()["user"]["name"] == "RuStore Проверка"
    assert client.get("/api/predict/me", headers=as_header(j["token"])).status_code == 200


def test_review_saves_prediction(client, svc, provider, monkeypatch):
    monkeypatch.setenv("REVIEW_LOGIN_CODE", REVIEW)
    provider.put(mk_match(1))
    tok = review(client, REVIEW).json()["token"]
    r = client.put("/api/predict/matches/1", json={"home": 3, "away": 0}, headers=as_header(tok))
    assert r.status_code == 200, r.text
    assert rows(svc, "SELECT home, away FROM predictions WHERE user_id=?", auth_api.REVIEW_USER_ID_DEFAULT) == [(3, 0)]


def test_review_never_admin(client, svc, monkeypatch):
    monkeypatch.setenv("REVIEW_LOGIN_CODE", REVIEW)
    monkeypatch.setenv("REVIEW_USER_ID", "111")  # совпал с админом — вход не выдаётся
    assert review(client, REVIEW).status_code == 503


def test_review_rate_limited(client, svc, monkeypatch, mono):
    monkeypatch.setenv("REVIEW_LOGIN_CODE", REVIEW)
    for _ in range(10):
        assert review(client, "WRONG-CODE-123").status_code == 401
    assert review(client, REVIEW).status_code == 429  # даже верный код — после лимита
    mono.t += 601
    assert review(client, REVIEW).status_code == 200


def test_review_cross_site_and_bad_body(client, svc, monkeypatch):
    monkeypatch.setenv("REVIEW_LOGIN_CODE", REVIEW)
    assert review(client, REVIEW, **{"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/auth/review", content=b"nope", headers={"Content-Type": "application/json"}).status_code == 422
    assert client.post("/api/auth/review", json={"code": 123}).status_code == 401
    assert client.post("/api/auth/review", json=["x"]).status_code == 401


def test_review_user_can_be_deleted_and_comes_back(client, svc, monkeypatch):
    monkeypatch.setenv("REVIEW_LOGIN_CODE", REVIEW)
    tok = review(client, REVIEW).json()["token"]
    assert delete(client, as_header(tok)).json()["deleted"] is True
    assert client.get("/api/auth/me", headers=as_header(tok)).json()["user"] is None
    assert review(client, REVIEW).status_code == 200


def test_session_epoch_of_new_user_is_random():
    assert auth  # импорт для единообразия
    from app.predictions.service import first_epoch
    vals = {first_epoch() for _ in range(20)}
    assert all(v > 0 for v in vals) and len(vals) > 1
