"""Проверка Telegram initData — общая для админки трансляции и прогнозов.

Заголовок `Authorization: tma <initData>`; подпись по BOT_TOKEN (алгоритм WebAppData → HMAC-SHA256),
возраст не больше 24 ч. Сама криптография — библиотека `telegram-webapp-auth`.
"""
from __future__ import annotations

import os
from datetime import timedelta
from typing import Optional

from telegram_webapp_auth.auth import TelegramAuthenticator, generate_secret_key
from telegram_webapp_auth.data import WebAppInitData
from telegram_webapp_auth.errors import BaseTWAError

INIT_DATA_MAX_AGE = timedelta(hours=24)


class InitDataError(Exception):
    """initData не прошёл проверку. `reason`: not_configured | missing | invalid | no_user."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def bot_token() -> str:
    return os.environ.get("BOT_TOKEN", "").strip()


def is_tma(authorization: Optional[str]) -> bool:
    return bool(authorization) and authorization[:4].lower() == "tma "


def validate_tma(authorization: Optional[str], token: Optional[str] = None) -> WebAppInitData:
    """Разбирает и проверяет `tma <initData>`. Бросает InitDataError."""
    if not is_tma(authorization):
        raise InitDataError("missing", "Нужна авторизация")
    token = bot_token() if token is None else token
    if not token:
        raise InitDataError("not_configured", "Вход через Telegram не настроен")
    auth = TelegramAuthenticator(generate_secret_key(token))
    try:
        data = auth.validate(authorization[4:].strip(), expr_in=INIT_DATA_MAX_AGE)
    except BaseTWAError:
        raise InitDataError("invalid", "Подпись Telegram не прошла проверку") from None
    if data.user is None:
        raise InitDataError("no_user", "В данных Telegram нет пользователя")
    return data
