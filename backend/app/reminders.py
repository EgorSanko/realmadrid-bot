"""Напоминание «матч через 10 минут» в личку бота — каждому получателю на его языке.

Кому: те же, кто получает ролики голов (bot_chats в predictions.db), кроме заблокировавших бота и
отписавшихся от напоминаний командой /noremind (вернуть — /remind). /stop (ролики голов) их не выключает.

Язык — bot_chats.lang: язык Telegram, когда человек пишет боту, или выбранный в приложении при входе
(app/auth_api.py). Неизвестен — русский.

Когда: матч «Реала» из расписания (снимок fixtures), ещё не начался, до начала от 10 до 2 минут. Сборщик
лежал и проснулся позже — не напоминаем (матч уже идёт). Каждый матч — один раз: строка в match_reminders
пишется до отправки, поэтому перезапуск посреди рассылки дублей не даёт (недоотправленным — без повтора).

Отправляет сборщик — там бот и SOCKS-туннель к Telegram (как app/broadcast.py).
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from . import broadcast
from .model import ts
from .predictions import db as predictions_db

log = logging.getLogger("reminders")

LEAD = 600            # напоминаем за 10 минут
LATEST = 120          # ближе 2 минут к началу — уже не напоминаем
CHECK_EVERY = 20.0
SEND_PAUSE = 0.06     # ~16 сообщений в секунду — ниже лимита Telegram (30/с)
MSK = timezone(timedelta(hours=3))

# турниры по-русски — как в приложении (frontend/src/lib/mapMatches.ts)
TOURNAMENT_RU = {87: "Ла Лига", 42: "Лига чемпионов", 138: "Кубок Испании", 139: "Суперкубок Испании"}
TOURNAMENT_RU_BY_NAME = {"uefa super cup": "Суперкубок УЕФА", "fifa club world cup": "Клубный чемпионат мира",
                         "club friendlies": "Товарищеский матч"}
TEXT = {
    "ru": ("⏰ <b>Через 10 минут — матч!</b>\n\n{home} — {away}\n{tournament}начало в {time} МСК\n\n"
           "Не напоминать: /noremind"),
    "en": ("⏰ <b>Kick-off in 10 minutes!</b>\n\n{home} vs {away}\n{tournament}{time} MSK\n\n"
           "Stop match reminders: /noremind"),
}
BUTTON = {"ru": "Смотреть матч", "en": "Open the match"}


def tournament_name(t: Optional[dict], lang: str) -> str:
    if not t:
        return ""
    name = t.get("name") or ""
    if lang == "ru":
        name = TOURNAMENT_RU.get(t.get("id")) or TOURNAMENT_RU_BY_NAME.get(name.lower()) or name
    return name


def message(f: dict, lang: str, site_url: str) -> dict:
    """Текст и кнопка (мини-апп сразу на странице матча) — без chat_id."""
    lang = lang if lang in TEXT else "ru"
    tour = tournament_name(f.get("tournament"), lang)
    ko = datetime.fromtimestamp(ts(f["kickoff"]), MSK)
    text = TEXT[lang].format(
        home=html.escape(f["home"]["name"] or "?"), away=html.escape(f["away"]["name"] or "?"),
        tournament=f"{html.escape(tour)} · " if tour else "", time=ko.strftime("%H:%M"))
    url = f"{site_url.rstrip('/')}/match/{f['id']}"
    return {"text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [[{"text": BUTTON[lang], "web_app": {"url": url}}]]}}


def due(fixtures: list, now: float) -> Optional[dict]:
    """Матч, о котором пора напомнить: не начался, до начала от LEAD до LATEST секунд."""
    for f in fixtures:
        st = f.get("status") or {}
        ko = ts(f.get("kickoff")) if f.get("kickoff") else None
        if (not isinstance(f.get("id"), int) or ko is None or st.get("live") or st.get("finished")
                or st.get("state") not in (None, "scheduled")):
            continue
        if ko - LEAD <= now <= ko - LATEST:
            return f
    return None


def claim(conn, f: dict) -> bool:
    """Занять матч до отправки: False — о нём уже напоминали (или напоминают)."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO match_reminders(match_id, kickoff, title, created_at) VALUES (?,?,?,?)",
        (f["id"], f["kickoff"], f"{f['home']['name']} — {f['away']['name']}", broadcast._now()))
    return cur.rowcount == 1


def recipients(conn) -> list[tuple[int, str]]:
    return [(r[0], r[1] or "ru") for r in conn.execute(
        "SELECT chat_id, lang FROM bot_chats WHERE remind=1 AND blocked_at IS NULL ORDER BY added_at")]


async def send(f: dict, bot, conn_factory: Callable[[], Any] = predictions_db.connect,
               pause: float = SEND_PAUSE) -> Optional[dict]:
    from .bot import TgApiError
    conn = conn_factory()
    try:
        if not claim(conn, f):
            return None
        to = recipients(conn)
        res = {"total": len(to), "sent": 0, "blocked": 0, "failed": 0}
        conn.execute("UPDATE match_reminders SET total=? WHERE match_id=?", (len(to), f["id"]))
        bodies = {lang: message(f, lang, bot.site_url) for lang in TEXT}
        for chat, lang in to:
            body = {"chat_id": chat, **bodies.get(lang, bodies["ru"])}
            try:
                try:
                    await bot.call("sendMessage", body)
                except TgApiError as e:
                    m = re.search(r"retry after (\d+)", e.description or "")
                    if e.code != 429 or not m:
                        raise
                    await asyncio.sleep(int(m.group(1)) + 1)
                    await bot.call("sendMessage", body)
                res["sent"] += 1
            except TgApiError as e:
                desc = (e.description or "").lower()
                if e.code == 403 or (e.code == 400 and ("chat not found" in desc or "deactivated" in desc)):
                    broadcast.mark_blocked(conn, chat, f"{e.code} {e.description}")
                    res["blocked"] += 1
                else:
                    res["failed"] += 1
                    log.warning("напоминание %s: %s — %s", f["id"], chat, e)
            except Exception as e:  # noqa: BLE001 — один получатель не должен ронять рассылку
                res["failed"] += 1
                log.warning("напоминание %s: %s — %s: %s", f["id"], chat, type(e).__name__, str(e)[:200])
            await asyncio.sleep(pause)
        conn.execute("UPDATE match_reminders SET finished_at=?, sent=?, blocked=?, failed=? WHERE match_id=?",
                     (broadcast._now(), res["sent"], res["blocked"], res["failed"], f["id"]))
        log.info("напоминание %s (%s — %s): отправлено %d из %d, заблокировали %d, ошибок %d", f["id"],
                 f["home"]["name"], f["away"]["name"], res["sent"], res["total"], res["blocked"], res["failed"])
        return res
    finally:
        conn.close()


async def run(bot, fixtures: Callable[[], list], stop: asyncio.Event, clock: Callable[[], float] = time.time) -> None:
    """Задача сборщика: раз в CHECK_EVERY секунд — не пора ли напомнить о матче."""
    while not stop.is_set():
        try:
            f = due(fixtures(), clock())
            if f:
                await send(f, bot)
        except Exception:  # noqa: BLE001
            log.exception("напоминания: ошибка (продолжаю)")
        try:
            await asyncio.wait_for(stop.wait(), timeout=CHECK_EVERY)
        except asyncio.TimeoutError:
            pass
