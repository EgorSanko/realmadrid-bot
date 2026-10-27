"""Рассылка ролика гола в личку бота (app/broadcast.py): получатели, /stop и /goals, задания, отправка."""
import asyncio
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import broadcast
from app.bot import MSG_GOALS, MSG_STOP
from app.main import app
from app.predictions import db as predictions_db

from .test_code_login import LUKA, TONI, FakeTelegram, bot, msg, site, tg  # noqa: F401 — фикстуры

ADMIN = 1697882482
H = {"X-Admin-Token": "s3cret-token"}
VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"x" * 4000


@pytest.fixture()
def admin_env(env, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret-token")
    monkeypatch.setenv("ADMIN_IDS", str(ADMIN))
    return env


def _chats(svc):
    c = predictions_db.connect(svc.db_path)
    try:
        return {r["chat_id"]: dict(r) for r in c.execute("SELECT * FROM bot_chats")}
    finally:
        c.close()


def test_writer_becomes_recipient_and_stop_goals(bot, tg, svc, clock):
    asyncio.run(bot.handle_update(msg(LUKA, "/start", clock=clock)))
    assert _chats(svc)[LUKA["id"]]["notify"] == 1
    asyncio.run(bot.handle_update(msg(LUKA, "/stop", clock=clock)))
    assert _chats(svc)[LUKA["id"]]["notify"] == 0
    assert tg.sent()[-1]["text"] == MSG_STOP and tg.sent()[-1]["chat_id"] == LUKA["id"]
    asyncio.run(bot.handle_update(msg(LUKA, "/goals", clock=clock)))
    assert _chats(svc)[LUKA["id"]]["notify"] == 1 and tg.sent()[-1]["text"] == MSG_GOALS


def test_recipients_admins_first_skip_blocked_and_stopped(admin_env, svc):
    c = predictions_db.connect(svc.db_path)
    try:
        for u in (LUKA, TONI, {"id": ADMIN, "first_name": "Егор"}, {"id": 9, "first_name": "X"}):
            broadcast.record_chat(c, u)
        broadcast.set_notify(c, TONI["id"], False)
        broadcast.mark_blocked(c, 9, "403 Forbidden: bot was blocked by the user")
        assert broadcast.recipients(c, test=False) == [ADMIN, LUKA["id"]]
        assert broadcast.recipients(c, test=True) == [ADMIN]
        broadcast.record_chat(c, {"id": 9, "first_name": "X"})   # вернулся и написал — снова получатель
        assert 9 in broadcast.recipients(c, test=False)
    finally:
        c.close()


def test_import_legacy(admin_env, svc, tmp_path):
    old = tmp_path / "betting.db"
    o = sqlite3.connect(old)
    o.execute("CREATE TABLE users (user_id INTEGER, first_name TEXT, username TEXT, is_blocked INTEGER)")
    o.executemany("INSERT INTO users VALUES (?,?,?,?)", [(1, "A", None, 0), (2, "B", "b", 1), (LUKA["id"], "Л", None, 0)])
    o.commit()
    o.close()
    c = predictions_db.connect(svc.db_path)
    try:
        broadcast.record_chat(c, LUKA)
        assert broadcast.import_legacy(c, str(old)) == {"rows": 3, "added": 2, "blocked": 1}
        to = broadcast.recipients(c, test=False)
        assert to[0] == ADMIN and sorted(to[1:]) == [1, LUKA["id"]]
    finally:
        c.close()


def test_api_create_and_no_double_send(admin_env, svc):
    client = TestClient(app)
    assert client.post("/api/admin/broadcast?key=g1", content=VIDEO).status_code == 401
    r = client.post("/api/admin/broadcast?key=6106244:2-0&caption=ГОЛ! Гюлер&width=1080&height=1920",
                    content=VIDEO, headers=H)
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "queued" and job["caption"].startswith("ГОЛ! Гюлер") and "/stop" in job["caption"]
    assert client.get(f"/api/admin/broadcast/{job['id']}", headers=H).json()["id"] == job["id"]
    assert client.post("/api/admin/broadcast?key=6106244:2-0", content=VIDEO, headers=H).status_code == 409
    # проверка «только мне» ключ не занимает и не блокируется
    assert client.post("/api/admin/broadcast?key=6106244:2-0&test=1", content=VIDEO, headers=H).status_code == 200


class FakeBotTx(FakeTelegram):
    def __init__(self, blocked=()):
        super().__init__()
        self.blocked = set(blocked)

    async def __call__(self, method, payload, timeout):
        if method == "sendVideo":
            self.calls.append((method, payload))
            if payload["chat_id"] in self.blocked:
                return {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}
            return {"ok": True, "result": {"message_id": 1}}
        return await super().__call__(method, payload, timeout)


def test_send_job_uploads_once_then_file_id(admin_env, svc, clock, mono):
    from app.bot import TelegramBot
    from .conftest import BOT_TOKEN
    c = predictions_db.connect(svc.db_path)
    for u in ({"id": ADMIN, "first_name": "Е"}, LUKA, TONI):
        broadcast.record_chat(c, u)
    c.close()
    client = TestClient(app)
    job = client.post("/api/admin/broadcast?key=k1&caption=ГОЛ!", content=VIDEO, headers=H).json()
    tx = FakeBotTx(blocked={TONI["id"]})
    b = TelegramBot(BOT_TOKEN, transport=tx, db_path=svc.db_path, clock=clock, mono=mono)
    uploads = []

    async def upload(chat, path, fields):
        uploads.append((chat, path.stat().st_size, fields["caption"]))
        return {"ok": True, "result": {"video": {"file_id": "FILE1"}}}

    done = asyncio.run(broadcast.send_job(broadcast.load_job(job["id"]), b, upload,
                                          conn_factory=lambda: predictions_db.connect(svc.db_path), pause=0))
    assert uploads == [(ADMIN, len(VIDEO), job["caption"])]
    assert [p["chat_id"] for m, p in tx.calls if m == "sendVideo"] == [LUKA["id"], TONI["id"]]
    assert all(p["video"] == "FILE1" for m, p in tx.calls if m == "sendVideo")
    assert (done["status"], done["sent"], done["blocked"], done["failed"]) == ("done", 2, 1, 0)
    assert _chats(svc)[TONI["id"]]["blocked_at"] is not None


def test_plain_caption_only_to_self(admin_env, svc):
    client = TestClient(app)
    assert client.post("/api/admin/broadcast?key=k&plain=1&caption=x", content=VIDEO, headers=H).status_code == 400
    j = client.post("/api/admin/broadcast?key=k&plain=1&test=1&caption=ГОЛ!%0A%0A%23реал", content=VIDEO, headers=H).json()
    assert j["caption"] == "ГОЛ!\n\n#реал" and j["test"] is True


# ---------- входящие: что люди пишут боту — владельцу ----------

def test_inbox_forwarded_to_admin_with_thanks_once(admin_env, bot, tg, svc, clock):
    from app.bot import MSG_ABOUT
    asyncio.run(bot.handle_update(msg(LUKA, "Когда следующий матч?", clock=clock)))
    asyncio.run(bot.handle_update(msg(LUKA, "И ещё вопрос", clock=clock)))
    sent = tg.sent()
    to_admin = [s["text"] for s in sent if s["chat_id"] == ADMIN]
    assert to_admin == ["✉️ Лука Модрич (@lm10) · id 7001:\n\nКогда следующий матч?",
                        "✉️ Лука Модрич (@lm10) · id 7001:\n\nИ ещё вопрос"]
    to_luka = [s for s in sent if s["chat_id"] == LUKA["id"]]
    assert [s["text"] for s in to_luka] == [MSG_ABOUT]   # «что это за бот + поддержка» — один раз
    assert "@papito007" in MSG_ABOUT and to_luka[0]["reply_markup"]["inline_keyboard"][0][0]["web_app"]
    c = predictions_db.connect(svc.db_path)
    try:
        assert [r[0] for r in c.execute("SELECT text FROM bot_messages ORDER BY id")] == [
            "Когда следующий матч?", "И ещё вопрос"]
    finally:
        c.close()


def test_inbox_media_is_forwarded_and_admin_not_echoed(admin_env, bot, tg, clock):
    upd = {"update_id": 9_000_001, "message": {"message_id": 55, "from": TONI, "chat": {"id": TONI["id"], "type": "private"},
                                               "date": int(clock().timestamp()), "voice": {"file_id": "v"}}}
    asyncio.run(bot.handle_update(upd))
    fw = [p for m, p in tg.calls if m == "forwardMessage"]
    assert fw == [{"chat_id": ADMIN, "from_chat_id": TONI["id"], "message_id": 55}]
    n = len(tg.calls)
    asyncio.run(bot.handle_update(msg({"id": ADMIN, "is_bot": False, "first_name": "Егор"}, "тест", clock=clock)))
    assert all(m != "forwardMessage" and p.get("chat_id") != ADMIN for m, p in tg.calls[n:])


def test_bot_answers_in_english_for_english_telegram(admin_env, bot, tg, clock):
    """language_code не русский (и не близкий) — ответы бота на английском; ru/uk/без языка — по-русски."""
    from app.bot import EN, MSG_ABOUT, MSG_STOP, lang_of
    jude = {"id": 7005, "is_bot": False, "first_name": "Jude", "username": "jb5", "language_code": "en"}
    asyncio.run(bot.handle_update(msg(jude, "Hello, is this the Real Madrid app?", clock=clock)))
    asyncio.run(bot.handle_update(msg(jude, "/stop", clock=clock)))
    mine = [s for s in tg.sent() if s["chat_id"] == jude["id"]]
    assert [s["text"] for s in mine] == [EN[MSG_ABOUT], EN[MSG_STOP]]
    assert mine[0]["reply_markup"]["inline_keyboard"][0][0]["text"] == "Open Madridista"
    assert [lang_of({"language_code": c}) for c in ("ru", "uk", "pt-br", None, "")] == ["ru", "ru", "en", "ru", "ru"]
