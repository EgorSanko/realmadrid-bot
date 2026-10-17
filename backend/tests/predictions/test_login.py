"""Вход: /api/auth/* — initData, Login Widget, сессия (cookie и заголовок), выход, админка, CSRF."""
import hashlib
import hmac
import sqlite3
import time
from urllib.parse import parse_qsl, urlencode

import pytest

from app import auth

from .conftest import BOT_TOKEN, sign_init_data, tma

ADMIN = 111


def sign_widget(user_id: int = 7, bot_token: str = BOT_TOKEN, auth_date: int | None = None, **extra) -> dict:
    """Данные Login Widget, подписанные по официальному алгоритму (секрет = SHA256(token))."""
    data = {"id": user_id, "first_name": "Лука", "auth_date": auth_date if auth_date is not None else int(time.time()),
            **extra}
    dcs = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    data["hash"] = hmac.new(hashlib.sha256(bot_token.encode()).digest(), dcs.encode(), hashlib.sha256).hexdigest()
    return data


@pytest.fixture(autouse=True)
def admins(env, monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", f"{ADMIN}")
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret-token")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)


def login(client, body):
    return client.post("/api/auth/telegram", json=body)


def cookie_of(r) -> str:
    sc = r.headers["set-cookie"]
    assert sc.startswith("rm_session=")
    return sc.split(";", 1)[0].split("=", 1)[1].strip('"')


def as_cookie(token: str) -> dict:
    return {"Cookie": f"rm_session={token}"}


def as_header(token: str) -> dict:
    return {"Authorization": f"Session {token}"}


# ---------- вход через Login Widget ----------

def test_widget_login_sets_cookie_and_returns_token(client, svc):
    r = login(client, sign_widget(7, last_name="Модрич", username="lm10",
                                  photo_url="https://t.me/i/userpic/320/lm10.jpg"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["user"] == {"id": 7, "name": "Лука М.", "first_name": "Лука", "last_name": "Модрич",
                         "username": "lm10", "avatar": None}
    assert j["is_admin"] is False and j["via"] == "widget" and j["expires_at"].endswith("Z")
    sc = r.headers["set-cookie"].lower()
    for flag in ("httponly", "secure", "samesite=lax", "path=/", "max-age=2592000"):
        assert flag in sc, sc
    assert cookie_of(r) == j["token"]
    assert r.headers["cache-control"] == "no-store"
    c = sqlite3.connect(svc.db_path)
    row = c.execute("SELECT first_name, last_name, username, photo_url FROM users WHERE id=7").fetchone()
    q = c.execute("SELECT url FROM avatar_queue WHERE user_id=7").fetchone()
    c.close()
    assert row == ("Лука", "Модрич", "lm10", "https://t.me/i/userpic/320/lm10.jpg")
    assert q == ("https://t.me/i/userpic/320/lm10.jpg",)  # заявка сборщику на аватар


def _tamper(data: dict, **changes) -> dict:
    return {**data, **changes}


WIDGET_BAD = {
    "поддельный hash": lambda: _tamper(sign_widget(7), hash="0" * 64),
    "подменён id": lambda: _tamper(sign_widget(7), id=8),
    "подменено имя": lambda: _tamper(sign_widget(7), first_name="Злоумышленник"),
    "добавлено поле": lambda: _tamper(sign_widget(7), username="admin"),
    "чужой бот": lambda: sign_widget(7, bot_token="999:other"),
    "подпись initData-алгоритмом": lambda: _widget_signed_like_webapp(),
    "без hash": lambda: {k: v for k, v in sign_widget(7).items() if k != "hash"},
    "просрочен (25 ч)": lambda: sign_widget(7, auth_date=int(time.time()) - 25 * 3600),
    "из будущего (1 ч)": lambda: sign_widget(7, auth_date=int(time.time()) + 3600),
    "вложенный объект": lambda: _tamper(sign_widget(7), first_name={"x": 1}),
    "без auth_date": lambda: _resign({"id": 7, "first_name": "Лука"}),
}


def _resign(data: dict) -> dict:
    dcs = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    return {**data, "hash": hmac.new(hashlib.sha256(BOT_TOKEN.encode()).digest(), dcs.encode(),
                                     hashlib.sha256).hexdigest()}


def _widget_signed_like_webapp() -> dict:
    data = {"id": 7, "first_name": "Лука", "auth_date": int(time.time())}
    dcs = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    return {**data, "hash": hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()}


@pytest.mark.parametrize("case", list(WIDGET_BAD))
def test_widget_rejected(client, svc, case):
    r = login(client, WIDGET_BAD[case]())
    assert r.status_code == 401, (case, r.text)
    assert r.json()["error"] == "unauthorized" and r.json()["message"]
    assert "set-cookie" not in r.headers
    c = sqlite3.connect(svc.db_path)
    try:
        n = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    except sqlite3.OperationalError:
        n = 0
    c.close()
    assert n == 0


def test_widget_expired_message(client, svc):
    r = login(client, sign_widget(7, auth_date=int(time.time()) - 25 * 3600))
    assert r.json()["message"] == "Данные входа устарели — войдите ещё раз"


def test_widget_string_fields_accepted(client, svc):
    """Виджет может прислать id/auth_date строками — data-check-string от этого не меняется."""
    d = sign_widget(9)
    d = {**d, "id": str(d["id"]), "auth_date": str(d["auth_date"])}
    assert login(client, d).status_code == 200


def test_login_not_configured(client, svc, monkeypatch):
    monkeypatch.delenv("BOT_TOKEN")
    r = login(client, sign_widget(7))
    assert r.status_code == 503 and r.json()["message"] == "Вход через Telegram не настроен"


@pytest.mark.parametrize("body", [[], "x", {"initData": 5}, {"initData": ""}])
def test_login_bad_body(client, svc, body):
    r = client.post("/api/auth/telegram", json=body)
    assert r.status_code in (401, 422), r.text
    assert "set-cookie" not in r.headers


def test_login_not_json(client, svc):
    r = client.post("/api/auth/telegram", content=b"not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_login_rate_limited(client, svc):
    for _ in range(30):
        assert login(client, sign_widget(7)).status_code == 200
    r = login(client, sign_widget(7))
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"


# ---------- вход из мини-аппа (initData) ----------

def test_init_data_login(client, svc):
    r = login(client, {"initData": sign_init_data(42, first_name="Карим", username="k9")})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["user"]["id"] == 42 and j["user"]["username"] == "k9" and j["via"] == "tma"
    assert client.get("/api/predict/me", headers=as_cookie(j["token"])).json()["user"]["id"] == 42


def test_init_data_start_param_returned(client, svc):
    raw = sign_init_data(42)
    pairs = dict(parse_qsl(raw))
    pairs.pop("hash")
    pairs["start_param"] = "league_ABCD"
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    r = login(client, {"initData": urlencode(pairs)})
    assert r.status_code == 200 and r.json()["start_param"] == "league_ABCD"


@pytest.mark.parametrize("raw", [
    sign_init_data(42, bot_token="999:other"),
    sign_init_data(42, auth_date=int(time.time()) - 25 * 3600),
    "garbage",
])
def test_init_data_login_rejected(client, svc, raw):
    r = login(client, {"initData": raw})
    assert r.status_code == 401 and "set-cookie" not in r.headers


# ---------- /api/auth/me ----------

def test_me_anonymous(client, svc):
    r = client.get("/api/auth/me")
    assert r.status_code == 200 and r.json() == {"user": None, "is_admin": False}


def test_me_by_cookie_header_and_tma(client, svc):
    tok = login(client, sign_widget(7)).json()["token"]
    assert client.get("/api/auth/me", headers=as_cookie(tok)).json()["user"]["id"] == 7
    assert client.get("/api/auth/me", headers=as_header(tok)).json()["user"]["id"] == 7
    j = client.get("/api/auth/me", headers=tma(42)).json()
    assert j["user"]["id"] == 42 and j["is_admin"] is False


def test_me_bad_cookie_is_cleared(client, svc):
    r = client.get("/api/auth/me", headers=as_cookie("s1.7.9999999999.0.bad"))
    assert r.json() == {"user": None, "is_admin": False}
    sc = r.headers.get("set-cookie", "")
    assert sc.startswith("rm_session=") and ("max-age=0" in sc.lower() or "expires=" in sc.lower())


def test_me_admin_flag(client, svc):
    assert login(client, sign_widget(ADMIN)).json()["is_admin"] is True


# ---------- сессия: подделка и срок ----------

def _forge(tok: str, **parts) -> str:
    p = tok.split(".")
    for i, k in ((1, "uid"), (2, "exp"), (3, "epoch"), (4, "sig")):
        if k in parts:
            p[i] = str(parts[k])
    return ".".join(p)


def test_session_forgery_and_expiry(client, svc, monkeypatch):
    tok = login(client, sign_widget(7)).json()["token"]
    login(client, sign_widget(8))
    monkeypatch.setenv("SESSION_SECRET", "другой-секрет")
    other_secret, _ = auth.issue_session(7)
    monkeypatch.delenv("SESSION_SECRET")
    expired, _ = auth.issue_session(7, now=time.time() - auth.SESSION_TTL - 10)
    bad = {
        "подменён id": _forge(tok, uid=8),
        "продлён срок": _forge(tok, exp=int(time.time()) + 10 * auth.SESSION_TTL),
        "чужая подпись": _forge(tok, sig="A" * 43),
        "другой секрет": other_secret,
        "просрочена": expired,
        "мусор": "abc",
        "пусто": "",
        "лишняя часть": tok + ".x",
    }
    for case, t in bad.items():
        for h in (as_cookie(t), as_header(t)):
            r = client.get("/api/predict/me", headers=h)
            assert r.status_code == 401, (case, r.text)
    assert client.get("/api/predict/me", headers=as_cookie(tok)).status_code == 200
    r = client.get("/api/predict/me", headers=as_header(expired))
    assert r.json()["message"] == "Сессия истекла — войдите снова"


def test_session_secret_env(client, svc, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "s")
    tok = login(client, sign_widget(7)).json()["token"]
    assert client.get("/api/predict/me", headers=as_header(tok)).status_code == 200
    monkeypatch.setenv("SESSION_SECRET", "t")  # смена секрета — все сессии недействительны
    assert client.get("/api/predict/me", headers=as_header(tok)).status_code == 401


def test_session_for_deleted_user(client, svc):
    tok = login(client, sign_widget(7)).json()["token"]
    c = sqlite3.connect(svc.db_path)
    c.execute("DELETE FROM avatar_queue")
    c.execute("DELETE FROM users WHERE id=7")
    c.commit()
    c.close()
    assert client.get("/api/predict/me", headers=as_cookie(tok)).status_code == 401
    assert client.get("/api/auth/me", headers=as_cookie(tok)).json()["user"] is None


def test_bad_authorization_header_does_not_fall_back_to_cookie(client, svc):
    tok = login(client, sign_widget(7)).json()["token"]
    h = {**as_cookie(tok), "Authorization": "tma garbage"}
    assert client.get("/api/predict/me", headers=h).status_code == 401


# ---------- защищённые эндпоинты прогнозов принимают сессию ----------

def test_predict_endpoints_accept_session(client, svc):
    tok = login(client, sign_widget(7)).json()["token"]
    lg = client.post("/api/predict/leagues", json={"name": "Друзья"}, headers=as_cookie(tok))
    assert lg.status_code == 201, lg.text
    tok2 = login(client, sign_widget(8)).json()["token"]
    j = client.post("/api/predict/leagues/join", json={"code": lg.json()["code"]}, headers=as_header(tok2))
    assert j.status_code == 200 and j.json()["joined"] is True
    assert len(client.get("/api/predict/leagues", headers=as_cookie(tok2)).json()["leagues"]) == 1
    assert client.get("/api/predict/leaderboard", headers=as_cookie(tok)).status_code == 200


# ---------- CSRF ----------

def test_cookie_mutations_from_other_site_rejected(client, svc):
    tok = login(client, sign_widget(7)).json()["token"]
    for extra in ({"Sec-Fetch-Site": "cross-site"}, {"Origin": "https://evil.example"}, {"Origin": "null"}):
        r = client.post("/api/predict/leagues", json={"name": "x"}, headers={**as_cookie(tok), **extra})
        assert r.status_code == 401, (extra, r.text)
    ok = {"Sec-Fetch-Site": "same-origin", "Origin": "http://testserver"}
    assert client.post("/api/predict/leagues", json={"name": "x"}, headers={**as_cookie(tok), **ok}).status_code == 201
    # заголовок Session браузер сам на чужой сайт не подставит — проверка Origin не нужна
    r = client.post("/api/predict/leagues", json={"name": "y"},
                    headers={**as_header(tok), "Origin": "https://evil.example"})
    assert r.status_code == 201
    # чтение по cookie с чужого сайта не опасно и не ломается
    assert client.get("/api/predict/me", headers={**as_cookie(tok), "Sec-Fetch-Site": "cross-site"}).status_code == 200


# ---------- выход ----------

def test_logout_revokes_sessions(client, svc):
    tok = login(client, sign_widget(7)).json()["token"]
    tok_other_device = login(client, sign_widget(7)).json()["token"]
    r = client.post("/api/auth/logout", headers=as_cookie(tok))
    assert r.status_code == 200 and r.json() == {"ok": True, "revoked": True}
    sc = r.headers["set-cookie"].lower()
    assert sc.startswith("rm_session=") and ("max-age=0" in sc or "expires=" in sc)
    for t in (tok, tok_other_device):
        assert client.get("/api/predict/me", headers=as_cookie(t)).status_code == 401
        assert client.get("/api/auth/me", headers=as_header(t)).json()["user"] is None
    new = login(client, sign_widget(7)).json()["token"]  # войти снова можно
    assert client.get("/api/predict/me", headers=as_cookie(new)).status_code == 200


def test_logout_anonymous_and_tma(client, svc):
    assert client.post("/api/auth/logout").json() == {"ok": True, "revoked": False}
    tok = login(client, {"initData": sign_init_data(42)}).json()["token"]
    assert client.post("/api/auth/logout", headers=tma(42)).json()["revoked"] is False
    assert client.get("/api/predict/me", headers=as_cookie(tok)).status_code == 200


def test_logout_cross_site_does_not_revoke(client, svc):
    tok = login(client, sign_widget(7)).json()["token"]
    client.post("/api/auth/logout", headers={**as_cookie(tok), "Sec-Fetch-Site": "cross-site"})
    assert client.get("/api/predict/me", headers=as_cookie(tok)).status_code == 200


# ---------- админка эфира ----------

STREAM = "https://edge.example.org/hls/live/chunks.m3u8?sid=1"


def test_admin_by_session(client, svc):
    adm = login(client, sign_widget(ADMIN)).json()["token"]
    usr = login(client, sign_widget(7)).json()["token"]
    assert client.get("/api/admin/stream", headers=as_cookie(adm)).status_code == 200
    assert client.get("/api/admin/stream", headers=as_header(adm)).status_code == 200
    r = client.post("/api/admin/stream/start", json={"url": STREAM}, headers=as_cookie(adm))
    assert r.status_code == 200 and r.json()["live"] is True
    assert client.get("/api/admin/stream", headers=as_cookie(usr)).status_code == 403
    assert client.get("/api/admin/stream", headers=as_cookie("s1.111.9999999999.0.x")).status_code == 401
    r = client.post("/api/admin/stream/stop", headers={**as_cookie(adm), "Origin": "https://evil.example"})
    assert r.status_code == 401
    # прежние способы работают
    assert client.get("/api/admin/stream", headers=tma(ADMIN)).status_code == 200
    assert client.get("/api/admin/stream", headers={"X-Admin-Token": "s3cret-token"}).status_code == 200
    assert client.get("/api/admin/stream").status_code == 401
    client.post("/api/auth/logout", headers=as_cookie(adm))
    assert client.get("/api/admin/stream", headers=as_cookie(adm)).status_code == 401


def test_admin_session_needs_bot_token_and_ids(client, svc, monkeypatch):
    adm = login(client, sign_widget(ADMIN)).json()["token"]
    monkeypatch.setenv("ADMIN_IDS", "")
    r = client.get("/api/admin/stream", headers=as_cookie(adm))
    assert r.status_code == 401 and r.json()["detail"] == "Вход через Telegram не настроен"
