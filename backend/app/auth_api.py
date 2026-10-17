"""Вход: /api/auth/*. Ответы — JSON, ошибки `{error, message}` по-русски.

POST /api/auth/telegram  {initData} из мини-аппа или данные Login Widget {id, first_name, …, auth_date, hash}
                         → пользователь в users (та же таблица, что у прогнозов), заявка на аватар,
                           сессия: cookie rm_session (HttpOnly, Secure, SameSite=Lax, Path=/, 30 дней)
                           и то же значение в ответе (`token`) — для `Authorization: Session <token>`.
GET  /api/auth/me        → {user|null, is_admin}
POST /api/auth/logout    → выход: cookie стирается, сессии пользователя отзываются (session_epoch + 1).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from .auth import (SESSION_COOKIE, SESSION_TTL, InitDataError, admin_ids, issue_session, validate_init_data,
                   validate_widget)
from .identity import Principal, authenticate, has_credentials
from .predictions.api import get_service
from .predictions.service import PredictionService

log = logging.getLogger("auth")

router = APIRouter(prefix="/api/auth")

BODY_MAX = 8192


def _json(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def _err(status: int, error: str, message: str) -> JSONResponse:
    return _json({"error": error, "message": message}, status)


def _secure() -> bool:
    return os.environ.get("SESSION_COOKIE_SECURE", "1").strip().lower() not in ("0", "false", "no")


def _set_cookie(resp: JSONResponse, token: str) -> None:
    resp.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL, path="/", secure=_secure(), httponly=True,
                    samesite="lax")


def _clear_cookie(resp: JSONResponse) -> None:
    resp.delete_cookie(SESSION_COOKIE, path="/", secure=_secure(), httponly=True, samesite="lax")


def _client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


def _me_body(svc: PredictionService, uid: int) -> dict[str, Any]:
    return {"user": svc.user_view(uid), "is_admin": uid in admin_ids()}


@router.post("/telegram")
async def login(request: Request, svc: PredictionService = Depends(get_service)):
    if not svc.login_limiter.hit(_client_ip(request)):
        return _err(429, "rate_limited", "Слишком много попыток входа — подождите минуту")
    raw = await request.body()
    if len(raw) > BODY_MAX:
        return _err(413, "too_large", "Слишком большой запрос")
    try:
        body = await request.json()
    except ValueError:
        return _err(422, "validation", "Неверный запрос")
    if not isinstance(body, dict):
        return _err(422, "validation", "Неверный запрос")
    start_param: Optional[str] = None
    try:
        if "initData" in body:
            data = validate_init_data(body["initData"])
            user: Any = data.user
            start_param = getattr(data, "start_param", None)
            via = "tma"
        else:
            user = validate_widget(body)
            via = "widget"
    except InitDataError as e:
        status = 503 if e.reason == "not_configured" else 401
        return _err(status, "unauthorized" if status == 401 else "not_configured", e.message)
    uid = svc.upsert_user(user)
    photo = user.get("photo_url") if isinstance(user, dict) else getattr(user, "photo_url", None)
    try:
        svc.want_avatar(uid, photo)
    except Exception:  # аватар — не повод не пустить
        log.exception("avatar queue: %s", uid)
    token, exp = issue_session(uid, svc.session_epoch(uid) or 0)
    resp = _json({**_me_body(svc, uid), "via": via, "token": token, "start_param": start_param,
                  "expires_at": datetime.fromtimestamp(exp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    _set_cookie(resp, token)
    return resp


@router.get("/me")
def me(request: Request, authorization: Optional[str] = Header(default=None),
       svc: PredictionService = Depends(get_service)):
    if not has_credentials(request, authorization):
        return _json({"user": None, "is_admin": False})
    try:
        p: Principal = authenticate(request, authorization, svc)
    except InitDataError:
        resp = _json({"user": None, "is_admin": False})
        if not authorization and request.cookies.get(SESSION_COOKIE):
            _clear_cookie(resp)  # протухшая или отозванная cookie — убираем
        return resp
    uid = svc.upsert_user(p.tg_user) if p.tg_user is not None else p.id
    body = _me_body(svc, uid)
    if body["user"] is None:  # сессия есть, а пользователя уже нет
        body["is_admin"] = False
    return _json(body)


@router.post("/logout")
def logout(request: Request, authorization: Optional[str] = Header(default=None),
           svc: PredictionService = Depends(get_service)):
    revoked = False
    if has_credentials(request, authorization):
        try:
            p = authenticate(request, authorization, svc)
        except InitDataError:
            p = None
        if p is not None and p.via == "session":
            svc.bump_session_epoch(p.id)
            revoked = True
    resp = _json({"ok": True, "revoked": revoked})
    _clear_cookie(resp)
    return resp


def install(app) -> None:
    app.include_router(router)
