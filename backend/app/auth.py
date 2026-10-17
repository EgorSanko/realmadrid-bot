"""Вход через Telegram: initData мини-аппа, Telegram Login Widget и наша сессия.

* initData — заголовок `Authorization: tma <initData>`; подпись по BOT_TOKEN (WebAppData → HMAC-SHA256),
  возраст не больше 24 ч. Криптография — библиотека `telegram-webapp-auth`.
* Login Widget — данные `{id, first_name, …, auth_date, hash}`; официальный алгоритм:
  секрет = SHA256(BOT_TOKEN), hash = HMAC-SHA256(секрет, data-check-string), auth_date не старше 24 ч.
* Сессия — `s1.<id>.<exp>.<epoch>.<подпись>`: HMAC-SHA256 по SESSION_SECRET (если не задан —
  ключ выводится из BOT_TOKEN). `epoch` — счётчик пользователя в БД: «Выйти» его увеличивает,
  и все выданные раньше сессии этого пользователя перестают действовать.
  Передаётся cookie `rm_session` или заголовком `Authorization: Session <token>`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Optional

from telegram_webapp_auth.auth import TelegramAuthenticator, generate_secret_key
from telegram_webapp_auth.data import WebAppInitData
from telegram_webapp_auth.errors import BaseTWAError

INIT_DATA_MAX_AGE = timedelta(hours=24)
WIDGET_MAX_AGE = 24 * 3600
WIDGET_FUTURE_SKEW = 300          # часы могут расходиться — до 5 мин «из будущего» допускаем
SESSION_TTL = 30 * 24 * 3600
SESSION_COOKIE = "rm_session"
SESSION_PREFIX = "s1"


class InitDataError(Exception):
    """Вход не прошёл проверку. `reason`: not_configured | missing | invalid | expired | no_user."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def bot_token() -> str:
    return os.environ.get("BOT_TOKEN", "").strip()


def admin_ids() -> set[int]:
    ids = set()
    for part in os.environ.get("ADMIN_IDS", "").split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def is_tma(authorization: Optional[str]) -> bool:
    return bool(authorization) and authorization[:4].lower() == "tma "


def is_session_header(authorization: Optional[str]) -> bool:
    return bool(authorization) and authorization[:8].lower() == "session "


# ---------- initData мини-аппа ----------

def validate_init_data(raw: Any, token: Optional[str] = None) -> WebAppInitData:
    """Проверяет сырой initData. Бросает InitDataError."""
    token = bot_token() if token is None else token
    if not token:
        raise InitDataError("not_configured", "Вход через Telegram не настроен")
    if not isinstance(raw, str) or not raw.strip():
        raise InitDataError("missing", "Нужна авторизация")
    auth = TelegramAuthenticator(generate_secret_key(token))
    try:
        data = auth.validate(raw.strip(), expr_in=INIT_DATA_MAX_AGE)
    except BaseTWAError:
        raise InitDataError("invalid", "Подпись Telegram не прошла проверку") from None
    if data.user is None:
        raise InitDataError("no_user", "В данных Telegram нет пользователя")
    return data


def validate_tma(authorization: Optional[str], token: Optional[str] = None) -> WebAppInitData:
    """Разбирает и проверяет `tma <initData>`. Бросает InitDataError."""
    if not is_tma(authorization):
        raise InitDataError("missing", "Нужна авторизация")
    return validate_init_data(authorization[4:], token)


# ---------- Telegram Login Widget ----------

def validate_widget(data: Any, token: Optional[str] = None, now: Optional[float] = None) -> dict[str, Any]:
    """Проверяет данные Login Widget по официальному алгоритму. Возвращает пользователя
    `{id, first_name, last_name, username, photo_url}`. Бросает InitDataError."""
    token = bot_token() if token is None else token
    if not token:
        raise InitDataError("not_configured", "Вход через Telegram не настроен")
    if not isinstance(data, Mapping):
        raise InitDataError("invalid", "Неверные данные входа")
    received = data.get("hash")
    if not isinstance(received, str) or not received:
        raise InitDataError("invalid", "Подпись Telegram не прошла проверку")
    # data-check-string — все присланные поля, кроме hash, по алфавиту, «ключ=значение» через \n
    fields: dict[str, str] = {}
    for k, v in data.items():
        if k == "hash" or v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (str, int)):
            raise InitDataError("invalid", "Неверные данные входа")
        fields[str(k)] = str(v)
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hashlib.sha256(token.encode()).digest()
    expected = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), received.strip().lower().encode()):
        raise InitDataError("invalid", "Подпись Telegram не прошла проверку")
    try:
        uid = int(fields["id"])
        auth_date = int(fields["auth_date"])
    except (KeyError, ValueError):
        raise InitDataError("invalid", "Неверные данные входа") from None
    if uid <= 0:
        raise InitDataError("no_user", "В данных Telegram нет пользователя")
    now = time.time() if now is None else now
    if now - auth_date > WIDGET_MAX_AGE or auth_date - now > WIDGET_FUTURE_SKEW:
        raise InitDataError("expired", "Данные входа устарели — войдите ещё раз")
    return {"id": uid, "first_name": fields.get("first_name", ""), "last_name": fields.get("last_name"),
            "username": fields.get("username"), "photo_url": fields.get("photo_url")}


# ---------- сессия ----------

def _session_key() -> bytes:
    secret = os.environ.get("SESSION_SECRET", "").strip()
    if secret:
        return hashlib.sha256(b"rm-v2 session|" + secret.encode()).digest()
    token = bot_token()
    if not token:
        raise InitDataError("not_configured", "Вход через Telegram не настроен")
    # свой ключ, не совпадающий с ключами проверки Telegram (WebAppData / SHA256(token))
    return hmac.new(b"rm-v2 session", token.encode(), hashlib.sha256).digest()


def _sign(body: str) -> str:
    mac = hmac.new(_session_key(), body.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


@dataclass(frozen=True)
class Session:
    user_id: int
    expires_at: int
    epoch: int


def issue_session(user_id: int, epoch: int = 0, now: Optional[float] = None,
                  ttl: int = SESSION_TTL) -> tuple[str, int]:
    """Токен сессии и время его окончания (unix)."""
    exp = int((time.time() if now is None else now) + ttl)
    body = f"{SESSION_PREFIX}.{int(user_id)}.{exp}.{int(epoch)}"
    return f"{body}.{_sign(body)}", exp


def parse_session(token: Optional[str], now: Optional[float] = None) -> Session:
    """Проверяет подпись и срок. Счётчик epoch сверяет вызывающий (он в БД). Бросает InitDataError."""
    if not isinstance(token, str) or not token.strip():
        raise InitDataError("missing", "Нужна авторизация")
    parts = token.strip().split(".")
    if len(parts) != 5 or parts[0] != SESSION_PREFIX or not all(p.isdigit() for p in parts[1:4]):
        raise InitDataError("invalid", "Сессия недействительна — войдите снова")
    body = ".".join(parts[:4])
    if not hmac.compare_digest(_sign(body).encode(), parts[4].encode()):
        raise InitDataError("invalid", "Сессия недействительна — войдите снова")
    uid, exp, epoch = int(parts[1]), int(parts[2]), int(parts[3])
    if (time.time() if now is None else now) >= exp:
        raise InitDataError("expired", "Сессия истекла — войдите снова")
    return Session(uid, exp, epoch)
