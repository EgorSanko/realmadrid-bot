import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.stream import token_expiry

BOT_TOKEN = "123456:TEST-fake-bot-token"
ADMIN_ID = 111
OTHER_ID = 222
STREAM = "https://edge.example.org/hls/live/chunks.m3u8?sid=1&token=abc.def"

client = TestClient(app)


def sign_init_data(user_id: int, bot_token: str = BOT_TOKEN, auth_date: int | None = None) -> str:
    """initData, подписанный по алгоритму Telegram (WebAppData → HMAC-SHA256)."""
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAEtest",
        "user": json.dumps({"id": user_id, "first_name": "Тест"}, separators=(",", ":"), ensure_ascii=False),
    }
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def tma(user_id: int, **kw) -> dict:
    return {"Authorization": "tma " + sign_init_data(user_id, **kw)}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("ADMIN_IDS", f"{ADMIN_ID}, 999")
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret-token")
    return tmp_path


def test_public_get_default_offline():
    r = client.get("/api/stream")
    assert r.status_code == 200
    assert r.json() == {"live": False, "url": None, "title": None, "started_at": None}
    assert r.headers["cache-control"] == "no-store"


def test_start_stop_with_telegram_init_data(env):
    r = client.post("/api/admin/stream/start", json={"url": STREAM, "title": "Реал — Севилья"}, headers=tma(ADMIN_ID))
    assert r.status_code == 200, r.text
    pub = client.get("/api/stream").json()
    assert pub["live"] is True
    assert pub["url"] == STREAM  # query-строка сохраняется как есть
    assert pub["title"] == "Реал — Севилья"
    assert pub["started_at"]
    saved = json.loads((env / "stream.json").read_text(encoding="utf-8"))
    assert saved["live"] is True and saved["url"] == STREAM
    assert not list(env.glob(".stream-*"))  # временные файлы не остаются

    r = client.post("/api/admin/stream/stop", headers=tma(ADMIN_ID))
    assert r.status_code == 200
    assert client.get("/api/stream").json() == {"live": False, "url": None, "title": None, "started_at": None}


def test_invalid_signature_rejected():
    headers = tma(ADMIN_ID, bot_token="999:other-bot")
    r = client.post("/api/admin/stream/start", json={"url": STREAM}, headers=headers)
    assert r.status_code == 401
    assert client.get("/api/stream").json()["live"] is False


def test_tampered_init_data_rejected():
    init = sign_init_data(ADMIN_ID).replace(f"%22id%22%3A{ADMIN_ID}", "%22id%22%3A999")
    r = client.post("/api/admin/stream/start", json={"url": STREAM}, headers={"Authorization": "tma " + init})
    assert r.status_code == 401


def test_expired_init_data_rejected():
    old = int(time.time()) - 25 * 3600
    r = client.post("/api/admin/stream/start", json={"url": STREAM}, headers=tma(ADMIN_ID, auth_date=old))
    assert r.status_code == 401


def test_foreign_user_forbidden():
    r = client.post("/api/admin/stream/start", json={"url": STREAM}, headers=tma(OTHER_ID))
    assert r.status_code == 403
    assert client.get("/api/stream").json()["live"] is False


def test_admin_token_access():
    h = {"X-Admin-Token": "s3cret-token"}
    assert client.get("/api/admin/stream", headers=h).status_code == 200
    assert client.post("/api/admin/stream/start", json={"url": STREAM}, headers=h).status_code == 200
    assert client.get("/api/stream").json()["live"] is True
    assert client.post("/api/admin/stream/stop", headers=h).status_code == 200
    assert client.get("/api/stream").json()["live"] is False


def test_wrong_admin_token():
    r = client.post("/api/admin/stream/start", json={"url": STREAM}, headers={"X-Admin-Token": "nope"})
    assert r.status_code == 401


def test_no_credentials():
    assert client.post("/api/admin/stream/start", json={"url": STREAM}).status_code == 401
    assert client.post("/api/admin/stream/stop").status_code == 401
    assert client.get("/api/admin/stream").status_code == 401


def test_admin_closed_without_env(monkeypatch):
    for k in ("BOT_TOKEN", "ADMIN_IDS", "ADMIN_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert client.post("/api/admin/stream/start", json={"url": STREAM}, headers={"X-Admin-Token": ""}).status_code == 403
    assert client.post("/api/admin/stream/start", json={"url": STREAM}, headers=tma(ADMIN_ID)).status_code == 403


def test_telegram_disabled_without_admin_ids(monkeypatch):
    monkeypatch.delenv("ADMIN_IDS")
    r = client.post("/api/admin/stream/start", json={"url": STREAM}, headers=tma(ADMIN_ID))
    assert r.status_code == 401


@pytest.mark.parametrize(
    "url",
    ["", "   ", "ftp://x.org/a.m3u8", "javascript:alert(1)", "x.org/a.m3u8", "https://", "https://a.org/" + "a" * 2000, "https://a.org/a b.m3u8"],
)
def test_url_validation(url):
    r = client.post("/api/admin/stream/start", json={"url": url}, headers={"X-Admin-Token": "s3cret-token"})
    assert r.status_code == 422
    assert client.get("/api/stream").json()["live"] is False


def test_http_url_accepted():
    r = client.post("/api/admin/stream/start", json={"url": "http://a.org/x.m3u8"}, headers={"X-Admin-Token": "s3cret-token"})
    assert r.status_code == 200


def test_corrupted_state_file_is_offline(env):
    (env / "stream.json").write_text("{not json", encoding="utf-8")
    assert client.get("/api/stream").json()["live"] is False


# --- разбор срока действия ссылки (Nimble Streamer token) ---

def _nimble_url(payload: dict) -> str:
    import base64

    head = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"https://edge1.hayuhi.online/hls/fut2/chunks.m3u8?nimblesessionid=160194540&token={head}.SiGnAtUrE_-"


def test_token_expiry_nimble_example():
    url = _nimble_url({"ch": "fut2", "edge": "bulbikjoe", "sid": "abc", "exp": 1789521902})
    assert token_expiry(url) == "2026-09-16T01:25:02+00:00"


def test_token_expiry_returned_to_admin():
    url = _nimble_url({"ch": "fut2", "exp": 1789521902})
    r = client.post("/api/admin/stream/start", json={"url": url}, headers={"X-Admin-Token": "s3cret-token"})
    assert r.json()["expires_at"] == "2026-09-16T01:25:02+00:00"
    assert client.get("/api/stream").json()["url"] == url


@pytest.mark.parametrize(
    "url",
    [STREAM, "https://a.org/x.m3u8", "https://a.org/x.m3u8?token=%%%.x", _nimble_url({"ch": "x"}), _nimble_url({"exp": "soon"})],
)
def test_token_expiry_unparseable(url):
    assert token_expiry(url) is None
