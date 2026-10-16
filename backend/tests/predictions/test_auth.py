"""initData: без него, поддельный, просроченный; создание пользователя."""
import sqlite3
import time
from urllib.parse import parse_qsl, urlencode

import pytest

from .conftest import mk_match, sign_init_data, tma

PROTECTED = [
    ("put", "/api/predict/matches/1", {"home": 1, "away": 0}),
    ("get", "/api/predict/me", None),
    ("get", "/api/predict/leagues", None),
    ("post", "/api/predict/leagues", {"name": "x"}),
    ("post", "/api/predict/leagues/join", {"code": "AAAAAAAA"}),
    ("delete", "/api/predict/leagues/1/membership", None),
    ("patch", "/api/predict/leagues/1", {"name": "x"}),
    ("delete", "/api/predict/leagues/1", None),
]


def _call(client, method, url, body, headers=None):
    kw = {"headers": headers or {}}
    if body is not None:
        kw["json"] = body
    return client.request(method.upper(), url, **kw)


def _tampered() -> str:
    pairs = dict(parse_qsl(sign_init_data(1)))
    pairs["user"] = pairs["user"].replace('"id":1', '"id":2')
    return urlencode(pairs)


BAD = {
    "без заголовка": None,
    "не tma": {"Authorization": "Bearer abc"},
    "чужой бот": {"Authorization": "tma " + sign_init_data(1, bot_token="999:other")},
    "подменён id": {"Authorization": "tma " + _tampered()},
    "просрочен (25 ч)": {"Authorization": "tma " + sign_init_data(1, auth_date=int(time.time()) - 25 * 3600)},
    "мусор": {"Authorization": "tma garbage"},
}


@pytest.mark.parametrize("case", list(BAD))
@pytest.mark.parametrize("method,url,body", PROTECTED)
def test_protected_need_valid_init_data(client, provider, case, method, url, body):
    provider.put(mk_match(1))
    r = _call(client, method, url, body, BAD[case])
    assert r.status_code == 401, (case, url, r.text)
    j = r.json()
    assert j["error"] == "unauthorized" and j["message"]


def test_messages(client):
    assert client.get("/api/predict/me").json()["message"] == "Нужна авторизация"
    assert client.get("/api/predict/me", headers=BAD["чужой бот"]).json()["message"] == \
        "Подпись Telegram не прошла проверку"


def test_bot_token_not_configured(client, monkeypatch):
    monkeypatch.delenv("BOT_TOKEN")
    r = client.get("/api/predict/me", headers=tma(1))
    assert r.status_code == 401 and r.json()["message"] == "Вход через Telegram не настроен"


def test_read_only_without_init_data(client, provider):
    provider.put(mk_match(1))
    assert client.get("/api/predict/leaderboard").status_code == 200
    m = client.get("/api/predict/matches")
    assert m.status_code == 200 and m.json()["next"]["my_prediction"] is None
    assert client.get("/api/predict/matches", headers=BAD["чужой бот"]).status_code == 200


def test_user_created_from_init_data(client, svc):
    r = client.get("/api/predict/me", headers=tma(42, first_name="Карим", username="karim9",
                                                   photo_url="https://t.me/i/userpic/320/k.jpg", last_name="Т"))
    assert r.status_code == 200
    u = r.json()["user"]
    assert u == {"id": 42, "name": "Карим Т.", "username": "karim9", "photo_url": "https://t.me/i/userpic/320/k.jpg"}
    client.get("/api/predict/me", headers=tma(42, first_name="Карим", username="karim10"))
    c = sqlite3.connect(svc.db_path)
    row = c.execute("SELECT first_name, last_name, username, photo_url FROM users WHERE id=42").fetchone()
    c.close()
    assert row == ("Карим", None, "karim10", None)


def test_starts_with_clean_db(svc):
    import os

    from app.predictions import db
    assert not os.path.exists(svc.db_path)  # база создаётся при первом обращении
    conn = db.connect(svc.db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        for t in ("users", "matches", "predictions", "standings", "leagues", "league_members", "settle_audit"):
            assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
        conn.execute("INSERT INTO users(id, created_at, updated_at) VALUES (1, 'x', 'x')")
        with pytest.raises(sqlite3.IntegrityError):  # внешний ключ: матча 'nope' нет
            conn.execute("INSERT INTO predictions(user_id, match_id, home, away, created_at, updated_at) "
                         "VALUES (1, 'nope', 1, 0, 'x', 'x')")
        conn.execute("INSERT INTO matches(id, kickoff_utc, rm_is_home, status, season, month, updated_at) "
                     "VALUES ('m', 'x', 1, 'scheduled', 2026, '2026-10', 'x')")
        conn.execute("INSERT INTO predictions(user_id, match_id, home, away, created_at, updated_at) "
                     "VALUES (1, 'm', 1, 0, 'x', 'x')")
        with pytest.raises(sqlite3.IntegrityError):  # уникальность (user, match)
            conn.execute("INSERT INTO predictions(user_id, match_id, home, away, created_at, updated_at) "
                         "VALUES (1, 'm', 2, 0, 'x', 'x')")
        with pytest.raises(sqlite3.IntegrityError):  # CHECK 0..20
            conn.execute("UPDATE predictions SET home = 21")
        assert db.migrate(conn) == db.SCHEMA_VERSION  # повторная миграция — no-op
    finally:
        conn.close()
