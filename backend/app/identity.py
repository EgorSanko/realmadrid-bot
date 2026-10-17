"""Кто делает запрос: один разбор для прогнозов, админки и /api/auth/*.

Порядок:
  1. `Authorization: tma <initData>` — мини-апп (подпись Telegram, ≤ 24 ч);
  2. `Authorization: Session <token>` — наша сессия, если cookie не работают;
  3. cookie `rm_session` — сайт в браузере (и мини-апп, где WebView держит cookie).
Явный заголовок Authorization главнее cookie: неверный заголовок — 401, без отката на cookie.

Сессия проверяется по подписи, сроку и счётчику `users.session_epoch` («Выйти» его увеличивает).
Изменяющие запросы по cookie с чужого сайта отклоняются (Sec-Fetch-Site / Origin) — защита от CSRF
поверх SameSite=Lax.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import Request

from .auth import (SESSION_COOKIE, InitDataError, is_session_header, is_tma, parse_session,
                   validate_tma)

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


@dataclass(frozen=True)
class Principal:
    id: int
    via: str                     # tma | session
    tg_user: Any = None          # WebAppUser из initData (только для tma)
    start_param: Optional[str] = None


def has_credentials(request: Request, authorization: Optional[str]) -> bool:
    return bool(authorization) or bool(request.cookies.get(SESSION_COOKIE))


def _cross_site(request: Request) -> bool:
    site = (request.headers.get("sec-fetch-site") or "").lower()
    if site == "cross-site":
        return True
    origin = request.headers.get("origin")
    if origin and origin != "null":
        host = (request.headers.get("host") or "").lower()
        try:
            return (urlsplit(origin).netloc or "").lower() != host
        except ValueError:
            return True
    return origin == "null"


def session_principal(token: Optional[str], svc: Any) -> Principal:
    s = parse_session(token)
    epoch = svc.session_epoch(s.user_id)
    if epoch is None or epoch != s.epoch:
        raise InitDataError("invalid", "Сессия недействительна — войдите снова")
    return Principal(s.user_id, "session")


def authenticate(request: Request, authorization: Optional[str], svc: Any,
                 bot_token: Optional[str] = None) -> Principal:
    """Бросает InitDataError (reason: missing | invalid | expired | no_user | not_configured | cross_site)."""
    if is_tma(authorization):
        data = validate_tma(authorization, bot_token)
        return Principal(int(data.user.id), "tma", data.user, getattr(data, "start_param", None))
    if is_session_header(authorization):
        return session_principal(authorization[8:], svc)
    if authorization:
        raise InitDataError("missing", "Нужна авторизация")
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise InitDataError("missing", "Нужна авторизация")
    p = session_principal(token, svc)
    if request.method.upper() not in SAFE_METHODS and _cross_site(request):
        raise InitDataError("cross_site", "Запрос с чужого сайта отклонён")
    return p
