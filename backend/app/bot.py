"""Бот @Real_Madrid_football_bot: приём апдейтов (long polling) — только для входа на сайт по коду.

Живёт в сборщике отдельной asyncio-задачей (`Collector.run` → `TelegramBot.run`): сборщику и так
виден SOCKS-туннель (api.telegram.org из России напрямую не открывается), а отдельная задача не
задерживает лайв-такт матчей — пока идёт long poll, цикл событий свободен.

Что бот делает (и ничего больше — требование владельца: никаких рассылок, пишем только отправителю
и только в ответ на его личное сообщение):
  * `/start login_<token>` или 6 цифр кода → подтверждает заявку входа (app/login_codes.py) и отвечает
    «Вход на сайт выполнен ✅ …» или «Код не найден или устарел …»;
  * `/start` без кода → короткое приветствие с кнопкой мини-аппа (web_app);
  * всё остальное (группы, каналы, другие тексты, сообщения старше 10 мин) — молча пропускает.
После подтверждения бот берёт фото профиля (getUserProfilePhotos) и ставит заявку `tg-file:…`
в avatar_queue — файл скачивает обычный механизм аватаров (app/avatars.py, `resolve_file`).

Офсет getUpdates хранится в predictions.db (bot_state) и пишется в той же транзакции, что и
подтверждение заявки: после рестарта апдейты не теряются и не обрабатываются дважды. Ответ
отправляется после фиксации (если процесс умер между ними — ответ потеряется, вход — нет).

Сеть: breaker и счётчики — как у источников (sources/base.py), имя `telegram_bot`; при ошибке —
пауза с ростом (2 → 4 → … → 120 с). Выключить: DISABLED_SOURCES=telegram_bot или файл-флаг.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from . import avatars, config, login_codes
from .predictions import db as predictions_db
from .predictions.service import upsert_names
from .sources.base import Source, SourceError

log = logging.getLogger("bot")

POLL_TIMEOUT = 25                 # long polling, с
HTTP_SLACK = 10                   # запас HTTP-таймаута поверх long poll
CALL_TIMEOUT = 15.0               # обычные методы (sendMessage, getFile…)
BACKOFF_MIN, BACKOFF_MAX = 2.0, 120.0
STALE_MESSAGE = timedelta(minutes=10)    # старые сообщения (накопились, пока бот лежал) — без ответа
FAIL_LIMIT = (5, 600.0)           # неверных кодов от одного человека за 10 мин
GLOBAL_FAIL_LIMIT = (300, 600.0)  # неверных кодов от всех за 10 мин — дальше 6 цифр не принимаем

MSG_OK = "Вход на сайт выполнен ✅ Можно вернуться в браузер."
MSG_BAD = "Код не найден или устарел. Нажмите „Войти“ на сайте ещё раз."
MSG_LIMIT = "Слишком много неверных кодов. Подождите 10 минут и нажмите „Войти“ на сайте ещё раз."
MSG_HELLO = ("Привет! Это «Мадридиста» — всё о «Реале»: матчи онлайн, новости, прогнозы и игры.\n"
             "Откройте приложение кнопкой ниже.")
BTN_APP = "Открыть «Мадридисту»"

START_RE = re.compile(r"^/start(?:@[A-Za-z0-9_]+)?(?:\s+(\S+))?\s*$")
TOKEN_SCRUB = re.compile(r"bot\d+:[A-Za-z0-9_-]+")

# transport(method, payload, timeout) → разобранный JSON-ответ Telegram {"ok": …, "result"|"description": …}
Transport = Callable[[str, dict, float], Awaitable[dict]]


def scrub(text: str) -> str:
    """Токен бота не должен попасть ни в логи, ни в /api/health/sources."""
    return TOKEN_SCRUB.sub("bot<token>", text)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TgApiError(SourceError):
    def __init__(self, method: str, code: Any, description: str):
        super().__init__(f"{method}: {code} {description}")
        self.code = code
        self.description = description


class _Window:
    """Счётчик событий за скользящее окно (неверные коды)."""

    def __init__(self, limit: int, window: float, clock: Callable[[], float]):
        self.limit, self.window, self.clock = limit, window, clock
        self._q: dict[Any, deque] = {}

    def _trim(self, key: Any) -> deque:
        q = self._q.setdefault(key, deque())
        now = self.clock()
        while q and q[0] <= now - self.window:
            q.popleft()
        if not q and len(self._q) > 10_000:
            self._q = {k: v for k, v in self._q.items() if v}
        return q

    def blocked(self, key: Any) -> bool:
        return len(self._trim(key)) >= self.limit

    def add(self, key: Any) -> None:
        self._trim(key).append(self.clock())


def curl_transport(base: str, token: str, proxy: Optional[str]) -> tuple[Transport, Callable[[], Awaitable[None]]]:
    """POST JSON к Bot API через curl_cffi и SOCKS-туннель хоста."""
    from curl_cffi.requests import AsyncSession

    holder: dict[str, Any] = {}

    async def call(method: str, payload: dict, timeout: float) -> dict:
        if "s" not in holder:
            holder["s"] = AsyncSession(proxies={"http": proxy, "https": proxy} if proxy else None)
        r = await holder["s"].post(f"{base}/bot{token}/{method}", json=payload, timeout=timeout)
        try:
            data = r.json()
        except (ValueError, json.JSONDecodeError):
            raise SourceError(f"HTTP {r.status_code}: не JSON") from None
        if not isinstance(data, dict):
            raise SourceError(f"HTTP {r.status_code}: неожиданный ответ")
        return data

    async def close() -> None:
        if "s" in holder:
            await holder["s"].close()

    return call, close


class TelegramBot(Source):
    name = "telegram_bot"

    def __init__(self, token: Optional[str] = None, *, transport: Optional[Transport] = None,
                 db_path: Optional[str] = None, clock: Callable[[], datetime] = utcnow,
                 mono: Callable[[], float] = time.monotonic, api_base: Optional[str] = None,
                 site_url: Optional[str] = None):
        super().__init__()
        self.token = (os.environ.get("BOT_TOKEN", "") if token is None else token).strip()
        self.api_base = (api_base or os.environ.get("TG_API_BASE") or "https://api.telegram.org").rstrip("/")
        self.site_url = site_url or os.environ.get("SITE_URL") or "https://realmadridfan.ru/"
        self.db_path = db_path
        self.clock = clock
        self._transport = transport
        self._close: Optional[Callable[[], Awaitable[None]]] = None
        self.fails = _Window(*FAIL_LIMIT, clock=mono)
        self.global_fails = _Window(*GLOBAL_FAIL_LIMIT, clock=mono)
        self._limit_told: dict[int, float] = {}
        self.mono = mono
        self.backoff = 0.0
        self.offset: Optional[int] = None
        self.stats = {"polls": 0, "updates": 0, "logins": 0, "login_failed": 0, "rate_limited": 0,
                      "greetings": 0, "ignored": 0, "stale": 0, "replies": 0, "reply_errors": 0,
                      "avatars": 0, "avatar_errors": 0, "api_errors": 0}

    # ---------- инфраструктура ----------

    def configured(self) -> bool:
        return bool(self.token)

    def _tx(self):
        return predictions_db.connect(self.db_path)

    async def close(self) -> None:
        if self._close is not None:
            await self._close()
            self._close = None

    def _failure(self, err: Exception):
        super()._failure(err)
        if self.last_error_msg:
            self.last_error_msg = scrub(self.last_error_msg)

    async def call(self, method: str, payload: dict, timeout: float = CALL_TIMEOUT) -> Any:
        """Метод Bot API с breaker и счётчиками. Сеть / 5xx / 401 / 409 / 429 — ошибка источника;
        400/403 (нет такого чата, бот заблокирован) — ошибка запроса, breaker не трогает."""
        self._check()
        if self._transport is None:
            self._transport, self._close = curl_transport(self.api_base, self.token, config.TG_PROXY)
        now = time.time()
        self.requests += 1
        self.by_kind[method] = self.by_kind.get(method, 0) + 1
        self._recent.append(now)
        while self._recent and self._recent[0] < now - 3600:
            self._recent.popleft()
        t0 = time.monotonic()
        try:
            data = await self._transport(method, payload, timeout)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._failure(e)
            raise SourceError(scrub(f"{self.name}: {method}: {type(e).__name__}: {e}")) from None
        finally:
            self.last_latency_ms = round((time.monotonic() - t0) * 1000)
        if data.get("ok"):
            self._success()
            return data.get("result")
        code, desc = data.get("error_code"), scrub(str(data.get("description") or ""))[:200]
        err = TgApiError(method, code, desc)
        if code in (400, 403):
            self._success()
            self.stats["api_errors"] += 1
        else:
            self._failure(err)
        raise err

    def snapshot(self) -> dict:
        snap = super().snapshot()
        snap.update({"configured": self.configured(), "offset": self.offset, "backoff_s": self.backoff,
                     "bot": dict(self.stats)})
        return snap

    # ---------- офсет ----------

    @staticmethod
    def load_offset(conn) -> Optional[int]:
        row = conn.execute("SELECT value FROM bot_state WHERE key='offset'").fetchone()
        return int(row[0]) if row else None

    @staticmethod
    def _save_offset(conn, offset: int) -> None:
        conn.execute("INSERT INTO bot_state(key, value) VALUES ('offset', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(offset),))

    # ---------- цикл ----------

    async def run(self, stop: asyncio.Event) -> None:
        if not self.configured():
            log.info("bot: BOT_TOKEN не задан — приём апдейтов выключен")
            return
        log.info("bot: long polling getUpdates (timeout %d с)", POLL_TIMEOUT)
        while not stop.is_set():
            if self.disabled():
                await _sleep(stop, 15)
                continue
            if self.state == "open" and time.time() < self.open_until:
                await _sleep(stop, min(self.open_until - time.time(), 60))
                continue
            try:
                await self.poll_once()
                self.backoff = 0.0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.backoff = min(max(self.backoff * 2, BACKOFF_MIN), BACKOFF_MAX)
                log.warning("bot: getUpdates — %s; пауза %.0f с", scrub(f"{type(e).__name__}: {e}")[:300], self.backoff)
                await _sleep(stop, self.backoff)

    async def poll_once(self) -> int:
        """Один getUpdates и обработка всего, что пришло. Возвращает число апдейтов."""
        conn = self._tx()
        try:
            self.offset = self.load_offset(conn)
        finally:
            conn.close()
        payload: dict[str, Any] = {"timeout": POLL_TIMEOUT, "allowed_updates": ["message"]}
        if self.offset is not None:
            payload["offset"] = self.offset
        self.stats["polls"] += 1
        updates = await self.call("getUpdates", payload, timeout=POLL_TIMEOUT + HTTP_SLACK)
        n = 0
        for upd in updates or []:
            if not isinstance(upd, dict) or not isinstance(upd.get("update_id"), int):
                continue
            if self.offset is not None and upd["update_id"] < self.offset:
                continue  # уже обработан (Telegram прислал повторно)
            await self.handle_update(upd)
            n += 1
        return n

    # ---------- апдейт ----------

    async def handle_update(self, upd: dict) -> list[dict]:
        """Обработать один апдейт: решение и офсет — одной транзакцией, ответ — после неё.
        Возвращает отправленные сообщения (для проверок)."""
        self.stats["updates"] += 1
        conn = self._tx()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                reply, login_user = self._decide(conn, upd.get("message"))
                self._save_offset(conn, int(upd["update_id"]) + 1)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        self.offset = int(upd["update_id"]) + 1
        sent = []
        if reply is not None:
            if await self._send(reply):
                sent.append(reply)
        if login_user is not None:
            await self._want_avatar(login_user)
        return sent

    def _decide(self, conn, msg: Any) -> tuple[Optional[dict], Optional[int]]:
        """(ответ | None, id вошедшего | None). Ответ — только отправителю личного сообщения."""
        if not isinstance(msg, dict):
            self.stats["ignored"] += 1
            return None, None
        chat, sender = msg.get("chat") or {}, msg.get("from") or {}
        text = msg.get("text")
        if (chat.get("type") != "private" or not isinstance(sender.get("id"), int) or sender.get("is_bot")
                or chat.get("id") != sender.get("id") or not isinstance(text, str)):
            self.stats["ignored"] += 1
            return None, None
        now = self.clock()
        date = msg.get("date")
        if isinstance(date, int) and datetime.fromtimestamp(date, timezone.utc) < now - STALE_MESSAGE:
            self.stats["stale"] += 1
            return None, None
        uid = sender["id"]
        text = text.strip()
        token = code = None
        m = START_RE.match(text)
        if m:
            payload = m.group(1) or ""
            if not payload.startswith(login_codes.START_PREFIX):
                self.stats["greetings"] += 1
                return self._message(uid, MSG_HELLO, {"inline_keyboard": [[
                    {"text": BTN_APP, "web_app": {"url": self.site_url}}]]}), None
            token = payload[len(login_codes.START_PREFIX):]
        else:
            code = login_codes.normalize_code(text)
            if code is None:
                self.stats["ignored"] += 1
                return None, None
        # попытка входа: лимит неверных кодов на человека и (для 6 цифр) на всех
        if self.fails.blocked(uid) or (code is not None and self.global_fails.blocked("*")):
            self.stats["rate_limited"] += 1
            told = self._limit_told.get(uid)
            if told is not None and self.mono() - told < FAIL_LIMIT[1]:
                return None, None  # уже сказали — не отвечаем на каждое сообщение
            self._limit_told[uid] = self.mono()
            return self._message(uid, MSG_LIMIT), None
        user = {"id": uid, "first_name": sender.get("first_name") or "", "last_name": sender.get("last_name"),
                "username": sender.get("username")}
        if login_codes.confirm(conn, now, user, token=token, code=code):
            upsert_names(conn, uid, user["first_name"], user["last_name"], user["username"],
                         now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
            self.stats["logins"] += 1
            log.info("bot: вход по %s подтверждён (user %s)", "ссылке" if token else "коду", uid)
            return self._message(uid, MSG_OK), uid
        self.fails.add(uid)
        if code is not None:
            self.global_fails.add("*")
        self.stats["login_failed"] += 1
        return self._message(uid, MSG_BAD), None

    @staticmethod
    def _message(chat_id: int, text: str, markup: Optional[dict] = None) -> dict:
        body: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if markup is not None:
            body["reply_markup"] = markup
        return body

    async def _send(self, body: dict) -> bool:
        try:
            await self.call("sendMessage", body)
        except Exception as e:
            self.stats["reply_errors"] += 1
            log.warning("bot: sendMessage %s — %s", body.get("chat_id"), scrub(str(e))[:200])
            return False
        self.stats["replies"] += 1
        return True

    # ---------- аватар ----------

    @staticmethod
    def _pick(sizes: list) -> Optional[dict]:
        """Из размеров одного фото — ближайший к 320 px (как userpic t.me), не больше 640."""
        ok = [s for s in sizes if isinstance(s, dict) and s.get("file_id") and s.get("file_unique_id")]
        if not ok:
            return None
        small = [s for s in ok if (s.get("width") or 0) <= 640] or ok
        return min(small, key=lambda s: abs((s.get("width") or 0) - 320))

    async def _want_avatar(self, uid: int) -> None:
        try:
            res = await self.call("getUserProfilePhotos", {"user_id": uid, "limit": 1})
            photos = (res or {}).get("photos") or []
            size = self._pick(photos[0]) if photos else None
            if size is None:
                return  # фото нет или скрыто — прежний аватар (если был) не трогаем
            url = f"{avatars.TG_FILE}{size['file_unique_id']}/{size['file_id']}"
            conn = self._tx()
            try:
                if avatars.want(conn, uid, url, self.clock()):
                    self.stats["avatars"] += 1
            finally:
                conn.close()
        except Exception as e:  # аватар — не повод для ошибки входа
            self.stats["avatar_errors"] += 1
            log.warning("bot: аватар %s — %s", uid, scrub(str(e))[:200])

    async def resolve_file(self, file_id: str) -> str:
        """file_id → https-ссылка на файл (getFile). Ссылка содержит токен — не логировать."""
        res = await self.call("getFile", {"file_id": file_id})
        path = (res or {}).get("file_path")
        if not isinstance(path, str) or not path or ".." in path:
            raise SourceError("getFile: нет file_path")
        return f"{self.api_base}/file/bot{self.token}/{path}"


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=max(0.0, seconds))
    except asyncio.TimeoutError:
        pass
