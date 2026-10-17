"""Вход на сайте по коду через бота: /api/auth/code, /api/auth/code/status и обработчик апдейтов бота.

Telegram Bot API подменён фейковым транспортом (FakeTelegram): он отдаёт заготовленные getUpdates
и записывает всё, что бот пытался вызвать, — так проверяем, что бот пишет только отправителю.
"""
import asyncio
import re
import sqlite3
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import avatars, bot as botmod, login_codes
from app.bot import MSG_BAD, MSG_HELLO, MSG_LIMIT, MSG_OK, TelegramBot
from app.main import app

from .conftest import BOT_TOKEN

SITE = "https://testserver"
LUKA = {"id": 7001, "is_bot": False, "first_name": "Лука", "last_name": "Модрич", "username": "lm10"}
TONI = {"id": 7002, "is_bot": False, "first_name": "Тони", "username": "tk8"}


class FakeTelegram:
    """Подмена Bot API: очередь ответов на getUpdates, журнал вызовов, сбои по желанию."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.updates: list[list[dict]] = []
        self.fail_with: Exception | None = None
        self.photos: dict[int, dict] = {}

    async def __call__(self, method: str, payload: dict, timeout: float) -> dict:
        self.calls.append((method, payload))
        if self.fail_with is not None:
            raise self.fail_with
        if method == "getUpdates":
            return {"ok": True, "result": self.updates.pop(0) if self.updates else []}
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": len(self.calls)}}
        if method == "getUserProfilePhotos":
            return {"ok": True, "result": self.photos.get(payload["user_id"], {"total_count": 0, "photos": []})}
        if method == "getFile":
            return {"ok": True, "result": {"file_id": payload["file_id"], "file_path": "photos/file_1.jpg"}}
        return {"ok": False, "error_code": 400, "description": "Bad Request: unknown method"}

    def sent(self) -> list[dict]:
        return [p for m, p in self.calls if m == "sendMessage"]


@pytest.fixture()
def site(svc, monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("ADMIN_IDS", raising=False)
    return TestClient(app, base_url=SITE)


@pytest.fixture()
def tg():
    return FakeTelegram()


@pytest.fixture()
def bot(svc, clock, mono, tg):
    return TelegramBot(BOT_TOKEN, transport=tg, db_path=svc.db_path, clock=clock, mono=mono,
                       api_base="https://api.telegram.org", site_url="https://realmadridfan.ru/")


_uid = iter(range(500_000, 10**9))


def msg(sender: dict, text: str, chat: dict | None = None, date: int | None = None, clock=None) -> dict:
    return {"update_id": next(_uid), "message": {
        "message_id": 1, "from": sender, "chat": chat or {"id": sender["id"], "type": "private"},
        "date": date if date is not None else int(clock().timestamp() if clock else time.time()),
        "text": text}}


def run(coro):
    return asyncio.run(coro)


def get_code(client) -> dict:
    r = client.post("/api/auth/code")
    assert r.status_code == 200, r.text
    return r.json()


def token_of(j: dict) -> str:
    return j["deep_link"].split("?start=login_", 1)[1]


def send(bot, sender, text, clock):
    return run(bot.handle_update(msg(sender, text, clock=clock)))


# ---------- выдача кода ----------

def test_issue_code(site, svc):
    r = site.post("/api/auth/code")
    assert r.status_code == 200, r.text
    j = r.json()
    assert re.fullmatch(r"\d{6}", j["code"])
    assert j["ttl"] == 300 and j["expires_at"].endswith("Z") and j["bot"] == "madridista_bot"
    m = re.fullmatch(r"https://t\.me/madridista_bot\?start=login_([A-Za-z0-9_-]+)", j["deep_link"])
    assert m and len(m.group(1)) >= 16
    assert j["code"] not in j["deep_link"]
    # nonce — только в HttpOnly-cookie этого браузера: ни в ответе, ни в ссылке
    sc = r.headers["set-cookie"]
    nonce = re.search(r"rm_login=([^;]+)", sc).group(1)
    low = sc.lower()
    for flag in ("httponly", "secure", "samesite=lax", "path=/api/auth/code", "max-age=300"):
        assert flag in low, sc
    assert nonce not in r.text and nonce not in j["deep_link"] and len(nonce) >= 32
    assert r.headers["cache-control"] == "no-store"
    c = sqlite3.connect(svc.db_path)
    row = c.execute("SELECT token, code, nonce_hash, user_id FROM login_codes").fetchone()
    c.close()
    assert row[0] == m.group(1) and row[1] == j["code"] and row[3] is None
    assert row[2] == login_codes.nonce_hash(nonce) and nonce not in row  # в базе — только хэш


def test_new_code_replaces_previous_in_same_browser(site, svc):
    a = get_code(site)
    b = get_code(site)
    assert a["code"] != b["code"] or token_of(a) != token_of(b)
    c = sqlite3.connect(svc.db_path)
    tokens = [r[0] for r in c.execute("SELECT token FROM login_codes")]
    c.close()
    assert tokens == [token_of(b)]


def test_issue_cross_site_rejected(site):
    r = site.post("/api/auth/code", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "cross_site"
    r = site.post("/api/auth/code", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert site.post("/api/auth/code", headers={"Origin": SITE}).status_code == 200


def test_issue_not_configured(site, monkeypatch):
    monkeypatch.delenv("BOT_TOKEN")
    assert site.post("/api/auth/code").status_code == 503


def test_issue_rate_limited_by_ip(site, mono):
    for _ in range(10):
        assert site.post("/api/auth/code").status_code == 200
    r = site.post("/api/auth/code")
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"
    # другой IP (за nginx — X-Real-IP) — свой лимит
    assert site.post("/api/auth/code", headers={"X-Real-IP": "203.0.113.9"}).status_code == 200
    mono.t += 601
    assert site.post("/api/auth/code").status_code == 200


# ---------- подтверждение ботом и сессия ----------

def test_deep_link_login(site, svc, bot, tg, clock):
    j = get_code(site)
    assert site.get("/api/auth/code/status").json()["status"] == "pending"
    sent = send(bot, LUKA, f"/start login_{token_of(j)}", clock)
    assert sent == [{"chat_id": LUKA["id"], "text": MSG_OK}]
    assert tg.sent() == sent
    r = site.get("/api/auth/code/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["via"] == "code" and body["token"]
    assert body["user"]["id"] == LUKA["id"] and body["user"]["name"] == "Лука М."
    sc = r.headers["set-cookie"]
    assert f"rm_session={body['token']}" in sc and 'rm_login=""' in sc  # сессия выдана, nonce стёрт
    # сессия рабочая: /me по cookie и по заголовку
    me = site.get("/api/auth/me").json()
    assert me["user"]["id"] == LUKA["id"]
    other = TestClient(app, base_url=SITE)
    assert other.get("/api/auth/me", headers={"Authorization": f"Session {body['token']}"}).json()["user"]["id"] == 7001
    # заявка удалена: забрать второй раз нельзя
    c = sqlite3.connect(svc.db_path)
    assert c.execute("SELECT COUNT(*) FROM login_codes").fetchone()[0] == 0
    c.close()


def test_six_digit_login(site, bot, tg, clock):
    j = get_code(site)
    spaced = f"{j['code'][:3]} {j['code'][3:]}"
    assert send(bot, TONI, spaced, clock) == [{"chat_id": TONI["id"], "text": MSG_OK}]
    body = site.get("/api/auth/code/status").json()
    assert body["status"] == "ok" and body["user"]["id"] == TONI["id"] and body["user"]["name"] == "Тони"


def test_wrong_code(site, bot, tg, clock):
    j = get_code(site)
    wrong = f"{(int(j['code']) + 1) % 10**6:06d}"
    assert send(bot, LUKA, wrong, clock) == [{"chat_id": LUKA["id"], "text": MSG_BAD}]
    assert send(bot, LUKA, "/start login_AAAAAAAAAAAAAAAAAAAAAA", clock) == [{"chat_id": LUKA["id"], "text": MSG_BAD}]
    assert site.get("/api/auth/code/status").json()["status"] == "pending"


def test_expired_code(site, bot, clock):
    j = get_code(site)
    clock.set(clock.t + timedelta(minutes=5, seconds=1))
    assert send(bot, LUKA, j["code"], clock) == [{"chat_id": LUKA["id"], "text": MSG_BAD}]
    assert send(bot, LUKA, f"/start login_{token_of(j)}", clock) == [{"chat_id": LUKA["id"], "text": MSG_BAD}]
    r = site.get("/api/auth/code/status")
    assert r.json() == {"status": "expired"} and "rm_session" not in r.headers.get("set-cookie", "")


def test_code_cannot_be_confirmed_twice(site, bot, clock):
    j = get_code(site)
    nonce = site.cookies.get("rm_login")
    assert send(bot, LUKA, f"/start login_{token_of(j)}", clock)[0]["text"] == MSG_OK
    # второй человек (или тот же повторно) — тот же код уже не подтвердить
    assert send(bot, TONI, j["code"], clock)[0]["text"] == MSG_BAD
    assert send(bot, LUKA, f"/start login_{token_of(j)}", clock)[0]["text"] == MSG_BAD
    body = site.get("/api/auth/code/status").json()
    assert body["user"]["id"] == LUKA["id"]  # сессия — тому, кто подтвердил первым
    # и только один раз: даже повторив прежнюю cookie, вторую сессию не получить
    again = TestClient(app, base_url=SITE).get("/api/auth/code/status", headers={"Cookie": f"rm_login={nonce}"})
    assert again.json() == {"status": "expired"}


def test_other_browser_gets_no_session(site, bot, clock):
    j = get_code(site)
    send(bot, LUKA, f"/start login_{token_of(j)}", clock)
    stranger = TestClient(app, base_url=SITE)
    r = stranger.get("/api/auth/code/status")
    assert r.json() == {"status": "missing"} and "rm_session" not in r.headers.get("set-cookie", "")
    r = stranger.get("/api/auth/code/status", headers={"Cookie": "rm_login=guess-" + "x" * 40})
    assert r.json() == {"status": "expired"} and "rm_session=" not in r.headers.get("set-cookie", "").replace('rm_session=""', "")
    # чужой браузер с кодом из ссылки: токен из deep link — не nonce
    r = stranger.get("/api/auth/code/status", headers={"Cookie": f"rm_login={token_of(j)}"})
    assert r.json() == {"status": "expired"}
    # свой браузер по-прежнему получает сессию
    assert site.get("/api/auth/code/status").json()["status"] == "ok"


def test_confirmed_claim_after_ttl_grace(site, bot, clock):
    j = get_code(site)
    clock.set(clock.t + timedelta(minutes=4, seconds=59))
    assert send(bot, LUKA, j["code"], clock)[0]["text"] == MSG_OK
    clock.set(clock.t + timedelta(seconds=30))  # 5 минут вышли, но подтвердили вовремя
    assert site.get("/api/auth/code/status").json()["status"] == "ok"


def test_status_poll_rate_limited(site, mono):
    get_code(site)
    for _ in range(300):
        site.get("/api/auth/code/status")
    assert site.get("/api/auth/code/status").status_code == 429


# ---------- лимиты в боте ----------

def test_bot_attempt_limit_per_sender(site, bot, tg, clock, mono):
    j = get_code(site)
    wrong = f"{(int(j['code']) + 1) % 10**6:06d}"
    for _ in range(5):
        assert send(bot, LUKA, wrong, clock)[0]["text"] == MSG_BAD
    # шестая попытка — даже верный код не принимается; о лимите говорим один раз
    assert send(bot, LUKA, j["code"], clock) == [{"chat_id": LUKA["id"], "text": MSG_LIMIT}]
    assert send(bot, LUKA, j["code"], clock) == []
    assert site.get("/api/auth/code/status").json()["status"] == "pending"
    # другой человек не заблокирован
    assert send(bot, TONI, j["code"], clock)[0]["text"] == MSG_OK
    mono.t += 601
    k = get_code(site)
    assert send(bot, LUKA, k["code"], clock)[0]["text"] == MSG_OK


def test_bot_global_limit_on_digits(site, bot, clock, monkeypatch):
    monkeypatch.setattr(bot.global_fails, "limit", 3)
    j = get_code(site)
    wrong = f"{(int(j['code']) + 1) % 10**6:06d}"
    for i in range(3):
        send(bot, {**TONI, "id": 9000 + i}, wrong, clock)
    assert send(bot, LUKA, j["code"], clock)[0]["text"] == MSG_LIMIT
    # ссылка (длинный токен) продолжает работать — перебором её не подобрать
    assert send(bot, {**LUKA, "id": 9100}, f"/start login_{token_of(j)}", clock)[0]["text"] == MSG_OK


# ---------- бот пишет только отправителю ----------

def test_bot_replies_only_to_sender(site, bot, tg, clock):
    j = get_code(site)
    updates = [
        msg(LUKA, j["code"], chat={"id": -100123, "type": "supergroup", "title": "Фанаты"}, clock=clock),  # группа
        msg(LUKA, "/start", chat={"id": -100124, "type": "channel"}, clock=clock),
        msg({**TONI, "is_bot": True}, "/start", clock=clock),                     # другой бот
        msg(LUKA, "привет", clock=clock),                                        # посторонний текст
        msg(LUKA, "12345", clock=clock),                                          # не 6 цифр
        {"update_id": next(_uid), "edited_message": {"text": "/start"}},
        {"update_id": next(_uid), "message": {"from": LUKA, "chat": {"id": LUKA["id"], "type": "private"},
                                              "date": int(clock().timestamp()), "sticker": {}}},
        msg(TONI, "/start", clock=clock),                                         # приветствие
        msg(LUKA, j["code"], clock=clock),                                        # вход
        msg(TONI, "000000" if j["code"] != "000000" else "000001", clock=clock),  # неверный код
    ]
    for u in updates:
        run(bot.handle_update(u))
    sent = tg.sent()
    assert [(s["chat_id"], s["text"]) for s in sent] == [
        (TONI["id"], MSG_HELLO), (LUKA["id"], MSG_OK), (TONI["id"], MSG_BAD)]
    assert sent[0]["reply_markup"] == {"inline_keyboard": [[
        {"text": botmod.BTN_APP, "web_app": {"url": "https://realmadridfan.ru/"}}]]}
    # кроме ответов — только чтение (фото профиля вошедшего), никаких других методов отправки
    assert {m for m, _ in tg.calls} <= {"sendMessage", "getUserProfilePhotos"}
    assert all(p["user_id"] == LUKA["id"] for m, p in tg.calls if m == "getUserProfilePhotos")


def test_stale_messages_are_not_answered(site, bot, tg, clock):
    j = get_code(site)
    old = int((clock() - timedelta(minutes=11)).timestamp())
    assert run(bot.handle_update(msg(LUKA, "/start", date=old))) == []
    assert run(bot.handle_update(msg(LUKA, j["code"], date=old))) == []
    assert tg.sent() == []


# ---------- офсет getUpdates ----------

def test_get_updates_offset_persisted(site, svc, bot, tg, clock):
    j = get_code(site)
    u1 = msg(TONI, "/start", clock=clock)
    u2 = msg(LUKA, f"/start login_{token_of(j)}", clock=clock)
    tg.updates = [[u1, u2]]
    assert run(bot.poll_once()) == 2
    first = tg.calls[0]
    assert first[0] == "getUpdates" and "offset" not in first[1]
    assert first[1]["timeout"] == 25 and first[1]["allowed_updates"] == ["message"]
    c = sqlite3.connect(svc.db_path)
    assert c.execute("SELECT value FROM bot_state WHERE key='offset'").fetchone()[0] == str(u2["update_id"] + 1)
    c.close()
    # «рестарт»: новый экземпляр бота продолжает с сохранённого офсета; повтор апдейта не обрабатывается
    tg2 = FakeTelegram()
    tg2.updates = [[u2]]
    bot2 = TelegramBot(BOT_TOKEN, transport=tg2, db_path=svc.db_path, clock=clock)
    assert run(bot2.poll_once()) == 0
    assert tg2.calls[0][1]["offset"] == u2["update_id"] + 1
    assert tg2.sent() == []  # «Вход выполнен» второй раз не отправлен
    assert site.get("/api/auth/code/status").json()["status"] == "ok"


def test_offset_saved_with_confirmation_atomically(site, svc, bot, tg, clock, monkeypatch):
    """Ошибка до фиксации — ни подтверждения, ни офсета: апдейт придёт снова и будет обработан."""
    j = get_code(site)
    u = msg(LUKA, j["code"], clock=clock)

    def boom(*a, **k):
        raise RuntimeError("диск")
    monkeypatch.setattr(TelegramBot, "_save_offset", staticmethod(boom))
    with pytest.raises(RuntimeError):
        run(bot.handle_update(u))
    monkeypatch.undo()
    c = sqlite3.connect(svc.db_path)
    assert c.execute("SELECT user_id FROM login_codes").fetchone()[0] is None
    assert c.execute("SELECT COUNT(*) FROM bot_state").fetchone()[0] == 0
    c.close()
    assert tg.sent() == []
    assert run(bot.handle_update(u))[0]["text"] == MSG_OK


# ---------- сеть: пауза с ростом, breaker, токен не утекает ----------

def test_network_errors_backoff_and_breaker(svc, bot, tg, monkeypatch):
    tg.fail_with = ConnectionError(f"proxy refused https://api.telegram.org/bot{BOT_TOKEN}/getUpdates")
    sleeps = []

    async def fake_sleep(stop, seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 5:
            stop.set()
    monkeypatch.setattr(botmod, "_sleep", fake_sleep)
    run(bot.run(asyncio.Event()))
    snap = bot.snapshot()
    assert snap["errors"] == 3 and snap["breaker"] == "open" and snap["trips"] == 1
    assert sleeps[:3] == [2.0, 4.0, 8.0]          # пауза растёт
    assert snap["requests"] == 3                   # при открытом breaker в сеть не ходим
    assert BOT_TOKEN not in str(snap) and "bot<token>" in snap["last_error_msg"]
    assert snap["by_kind"] == {"getUpdates": 3} and snap["configured"] is True
    assert snap["bot"]["polls"] == 3


def test_api_error_400_does_not_trip_breaker(bot, tg):
    async def deny(method, payload, timeout):
        return {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}
    bot._transport = deny
    for _ in range(5):
        assert run(bot._send({"chat_id": 1, "text": "x"})) is False
    s = bot.snapshot()
    assert s["breaker"] == "closed" and s["bot"]["reply_errors"] == 5 and s["bot"]["api_errors"] == 5


def test_unconfigured_bot_does_nothing(svc):
    b = TelegramBot("", db_path=svc.db_path)
    run(b.run(asyncio.Event()))  # сразу выходит, в сеть не ходит
    assert b.snapshot()["requests"] == 0 and b.snapshot()["configured"] is False


def test_health_sources_has_bot(tmp_db, svc):
    from app import store
    b = TelegramBot(BOT_TOKEN, db_path=svc.db_path)
    conn = store.connect()
    store.put_source_state(conn, b.name, b.snapshot())
    conn.commit()
    conn.close()
    j = TestClient(app).get("/api/health/sources").json()
    assert j["bot"]["name"] == "telegram_bot" and j["bot"]["breaker"] == "closed" and "logins" in j["bot"]["bot"]
    assert BOT_TOKEN not in str(j)


# ---------- аватар из профиля ----------

def test_avatar_from_profile_photo(site, svc, bot, tg, clock, env):
    tg.photos[LUKA["id"]] = {"total_count": 1, "photos": [[
        {"file_id": "AgAD-small", "file_unique_id": "uniqA", "width": 160, "height": 160},
        {"file_id": "AgAD-mid", "file_unique_id": "uniqB", "width": 320, "height": 320},
        {"file_id": "AgAD-big", "file_unique_id": "uniqC", "width": 640, "height": 640}]]}
    j = get_code(site)
    send(bot, LUKA, j["code"], clock)
    c = sqlite3.connect(svc.db_path)
    q = c.execute("SELECT url FROM avatar_queue WHERE user_id=?", (LUKA["id"],)).fetchone()
    assert q == ("tg-file:uniqB/AgAD-mid",)
    fetched = []

    async def fetch(url):
        fetched.append(url)
        return 200, {"content-type": "image/jpeg"}, b"\xff\xd8\xff" + b"0" * 100
    done = run(avatars.process(c, fetch, now=clock(), resolve=bot.resolve_file))
    c.close()
    assert done[0][0] == LUKA["id"] and done[0][1].startswith("ok")
    assert fetched == [f"https://api.telegram.org/file/bot{BOT_TOKEN}/photos/file_1.jpg"]
    assert avatars.file_for(LUKA["id"]) is not None
    # тот же снимок (file_unique_id), новый file_id — повторно не качаем
    c = sqlite3.connect(svc.db_path)
    assert avatars.want(c, LUKA["id"], "tg-file:uniqB/AgAD-other", clock()) is False
    c.close()
    # вход по коду не стирает photo_url, оставленный виджетом
    assert site.get("/api/auth/code/status").json()["status"] == "ok"


def test_avatar_resolve_error_is_scrubbed(svc, clock, env):
    with svc.conn():
        pass  # схема
    c = sqlite3.connect(svc.db_path)
    c.execute("INSERT INTO users(id, first_name, created_at, updated_at) VALUES (5,'A','x','x')")
    assert avatars.want(c, 5, "tg-file:u1/f1", clock())
    c.commit()

    async def resolve(file_id):
        return f"https://api.telegram.org/file/bot{BOT_TOKEN}/photos/x.jpg"

    async def fetch(url):
        raise ConnectionError(f"timeout {url}")
    done = run(avatars.process(c, fetch, now=clock(), resolve=resolve))
    c.close()
    assert done[0][1].startswith("retry") and BOT_TOKEN not in done[0][1]


def test_tg_file_url_validation():
    assert avatars.allowed_url("tg-file:AbC_-1/AgADBAAD-x_y")
    assert not avatars.allowed_url("tg-file:../etc/passwd")
    assert not avatars.allowed_url("tg-file:a/b/c")


def test_long_poll_does_not_block_event_loop(svc):
    """Пока бот висит в long poll, остальные задачи цикла (лайв-такт сборщика) идут своим чередом."""
    async def hang(method, payload, timeout):
        await asyncio.sleep(timeout)
        return {"ok": True, "result": []}

    async def main():
        b = TelegramBot(BOT_TOKEN, transport=hang, db_path=svc.db_path)
        task = asyncio.create_task(b.run(asyncio.Event()))
        ticks = 0
        for _ in range(20):
            await asyncio.sleep(0.01)
            ticks += 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return ticks, b.snapshot()["requests"]
    ticks, requests = run(main())
    assert ticks == 20 and requests == 1
