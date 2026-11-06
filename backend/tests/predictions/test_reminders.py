"""Напоминание «матч через 10 минут» (app/reminders.py): когда, кому, на каком языке, один раз."""
import asyncio

from fastapi.testclient import TestClient

from app import broadcast, reminders
from app.bot import EN, MSG_NOREMIND, MSG_REMIND, TelegramBot
from app.main import app
from app.model import ts
from app.predictions import db as predictions_db

from .conftest import BOT_TOKEN
from .test_broadcast import FakeBotTx  # noqa: F401
from .test_code_login import LUKA, TONI, FakeTelegram, bot, msg, tg  # noqa: F401 — фикстуры

KO = "2026-11-07T20:00:00Z"
FIX = {"id": 5868129, "kickoff": KO, "tournament": {"id": 87, "name": "LaLiga", "round": None},
       "home": {"id": 10267, "name": "Valencia"}, "away": {"id": 8633, "name": "Real Madrid"},
       "status": {"state": "scheduled", "live": False, "finished": False}}


class BlockingTg(FakeTelegram):
    def __init__(self, blocked=()):
        super().__init__()
        self.blocked = set(blocked)

    async def __call__(self, method, payload, timeout):
        if method == "sendMessage" and payload["chat_id"] in self.blocked:
            self.calls.append((method, payload))
            return {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}
        return await super().__call__(method, payload, timeout)


def _conn(svc):
    return predictions_db.connect(svc.db_path)


def test_due_window_10_to_2_minutes():
    k = ts(KO)
    assert reminders.due([FIX], k - 601) is None
    assert reminders.due([FIX], k - 600) is FIX
    assert reminders.due([FIX], k - 121) is FIX
    assert reminders.due([FIX], k - 119) is None          # проснулись поздно — уже не напоминаем
    live = {**FIX, "status": {"state": "live", "live": True, "finished": False}}
    moved = {**FIX, "status": {"state": "postponed", "live": False, "finished": False}}
    assert reminders.due([live, moved], k - 300) is None


def test_message_ru_and_en():
    ru = reminders.message(FIX, "ru", "https://realmadridfan.ru/")
    assert ru["text"] == ("⏰ <b>Через 10 минут — матч!</b>\n\nValencia — Real Madrid\nЛа Лига · начало в 23:00 МСК\n\n"
                          "Не напоминать: /noremind")
    btn = ru["reply_markup"]["inline_keyboard"][0][0]
    assert btn == {"text": "Смотреть матч", "web_app": {"url": "https://realmadridfan.ru/match/5868129"}}
    en = reminders.message(FIX, "en", "https://realmadridfan.ru/")
    assert en["text"].startswith("⏰ <b>Kick-off in 10 minutes!</b>\n\nValencia vs Real Madrid\nLaLiga · 23:00 MSK")
    assert en["reply_markup"]["inline_keyboard"][0][0]["text"] == "Open the match"
    odd = {**FIX, "home": {"name": "A&B <FC>"}, "tournament": {"id": 1, "name": "UEFA Super Cup"}}
    assert "A&amp;B &lt;FC&gt; — Real Madrid\nСуперкубок УЕФА" in reminders.message(odd, "ru", "x")["text"]


def test_send_each_in_own_language_once_skip_blocked_and_noremind(svc, clock, mono):
    c = _conn(svc)
    jude, kyl, nobody = 7005, 7006, 7007
    broadcast.record_chat(c, LUKA, lang="ru")
    broadcast.record_chat(c, {"id": jude, "first_name": "Jude"}, lang="en")
    broadcast.record_chat(c, {"id": kyl, "first_name": "Kylian"})          # язык неизвестен — русский
    broadcast.record_chat(c, TONI)
    broadcast.record_chat(c, {"id": nobody, "first_name": "X"})
    broadcast.set_remind(c, TONI["id"], False)
    c.close()
    tx = BlockingTg(blocked={nobody})
    b = TelegramBot(BOT_TOKEN, transport=tx, db_path=svc.db_path, clock=clock, mono=mono,
                    site_url="https://realmadridfan.ru/")
    res = asyncio.run(reminders.send(FIX, b, conn_factory=lambda: _conn(svc), pause=0))
    assert res == {"total": 4, "sent": 3, "blocked": 1, "failed": 0}
    got = {p["chat_id"]: p["text"].split("\n")[0] for m, p in tx.calls if m == "sendMessage"}
    assert got == {LUKA["id"]: "⏰ <b>Через 10 минут — матч!</b>", jude: "⏰ <b>Kick-off in 10 minutes!</b>",
                   kyl: "⏰ <b>Через 10 минут — матч!</b>", nobody: "⏰ <b>Через 10 минут — матч!</b>"}
    n = len(tx.calls)
    assert asyncio.run(reminders.send(FIX, b, conn_factory=lambda: _conn(svc), pause=0)) is None   # второй раз — нет
    assert len(tx.calls) == n
    c = _conn(svc)
    row = dict(c.execute("SELECT * FROM match_reminders").fetchone())
    assert (row["total"], row["sent"], row["blocked"]) == (4, 3, 1) and row["finished_at"]
    assert c.execute("SELECT blocked_at FROM bot_chats WHERE chat_id=?", (nobody,)).fetchone()[0]
    c.close()


def test_bot_remembers_language_and_noremind_commands(bot, tg, svc, clock):
    jude = {"id": 7005, "is_bot": False, "first_name": "Jude", "language_code": "en"}
    asyncio.run(bot.handle_update(msg(jude, "/noremind", clock=clock)))
    asyncio.run(bot.handle_update(msg({**jude, "language_code": None}, "/remind", clock=clock)))  # язык не пропадает
    assert [s["text"] for s in tg.sent()] == [EN[MSG_NOREMIND], MSG_REMIND]   # ответ — по текущему Telegram
    c = _conn(svc)
    assert tuple(c.execute("SELECT lang, remind FROM bot_chats WHERE chat_id=7005").fetchone()) == ("en", 1)
    asyncio.run(bot.handle_update(msg(LUKA, "/noremind", clock=clock)))
    assert tuple(c.execute("SELECT lang, remind, notify FROM bot_chats WHERE chat_id=?", (LUKA["id"],)).fetchone())[1:] == (0, 1)
    c.close()


def test_app_language_saved_on_login(svc, monkeypatch):
    """Вход из английской версии приложения (?lang=en) — напоминания по-английски."""
    from app import auth_api
    seen = []
    monkeypatch.setattr(broadcast, "set_lang", lambda c, uid, lang: seen.append((uid, lang)))
    auth_api._remember_lang(svc, 42, "en")
    assert seen == [(42, "en")]
