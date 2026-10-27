"""Вход: /api/auth/*. Ответы — JSON, ошибки `{error, message}` по-русски.

POST /api/auth/telegram  {initData} из мини-аппа или данные Login Widget {id, first_name, …, auth_date, hash}
                         → пользователь в users (та же таблица, что у прогнозов), заявка на аватар,
                           сессия: cookie rm_session (HttpOnly, Secure, SameSite=Lax, Path=/, 30 дней)
                           и то же значение в ответе (`token`) — для `Authorization: Session <token>`.
POST /api/auth/code      → вход по коду через бота: {code, expires_at, ttl, deep_link, bot}; секретный nonce —
                           в HttpOnly-cookie rm_login (Path=/api/auth/code, 5 мин), в ответ и в ссылку не попадает.
GET  /api/auth/code/status → {status: pending|expired|missing} или, когда бот подтвердил, — сессия как у
                           /api/auth/telegram (cookie + token, via="code"). Заявка при этом удаляется.
GET  /api/auth/me        → {user|null, is_admin}
POST /api/auth/logout    → выход: cookie стирается, сессии пользователя отзываются (session_epoch + 1).
POST /api/auth/review    {code} → вход для проверки магазином приложений (модератор RuStore не может войти
                           через Telegram): код из REVIEW_LOGIN_CODE (.env сервера; не задан — выключено, 404),
                           сравнение за постоянное время, 10 попыток с IP за 10 мин. Входит в тестового
                           пользователя «RuStore Проверка» (REVIEW_USER_ID), никогда не админа.
DELETE /api/auth/me      {confirm: true} → удалить аккаунт: пользователь, прогнозы, места в рейтинге, свои лиги,
                           итоги игр, заявки на вход, аватар; cookie стирается.
"""
from __future__ import annotations

import hmac
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from . import i18n, login_codes
from .auth import (SESSION_COOKIE, SESSION_TTL, InitDataError, _session_key, admin_ids, issue_session,
                   validate_init_data, validate_widget)
from .identity import Principal, _cross_site, authenticate, has_credentials
from .predictions.api import get_service
from .predictions.service import PredictionService

log = logging.getLogger("auth")

router = APIRouter(prefix="/api/auth")

BODY_MAX = 8192
LOGIN_COOKIE = "rm_login"
LOGIN_COOKIE_PATH = "/api/auth/code"
DEFAULT_BOT = "Real_Madrid_football_bot"
REVIEW_USER_ID_DEFAULT = 9_000_000_000_001   # вне диапазона id Telegram — с живым человеком не совпадёт
REVIEW_NAME = "RuStore Проверка"
REVIEW_CODE_MIN = 10                          # короче — считаем, что вход проверки не настроен


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


def _seen(svc: PredictionService, uid: int) -> None:
    """Отметка «был» (раз в сутки) — по ней удаляются аватары тех, кого давно нет. Не повод не пустить."""
    try:
        svc.touch_seen(uid)
    except Exception:
        log.exception("seen_at: %s", uid)


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
    _seen(svc, uid)
    photo = user.get("photo_url") if isinstance(user, dict) else getattr(user, "photo_url", None)
    try:
        svc.want_avatar(uid, photo)
    except Exception:  # аватар — не повод не пустить
        log.exception("avatar queue: %s", uid)
    return _session_response(svc, uid, via, start_param)


def _session_response(svc: PredictionService, uid: int, via: str, start_param: Optional[str] = None,
                      extra: Optional[dict[str, Any]] = None) -> JSONResponse:
    token, exp = issue_session(uid, svc.session_epoch(uid) or 0)
    resp = _json({**(extra or {}), **_me_body(svc, uid), "via": via, "token": token, "start_param": start_param,
                  "expires_at": datetime.fromtimestamp(exp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    _set_cookie(resp, token)
    return resp


# ---------- вход по коду через бота ----------

def _set_login_cookie(resp: JSONResponse, nonce: str) -> None:
    resp.set_cookie(LOGIN_COOKIE, nonce, max_age=int(login_codes.CODE_TTL.total_seconds()),
                    path=LOGIN_COOKIE_PATH, secure=_secure(), httponly=True, samesite="lax")


def _clear_login_cookie(resp: JSONResponse) -> None:
    resp.delete_cookie(LOGIN_COOKIE, path=LOGIN_COOKIE_PATH, secure=_secure(), httponly=True, samesite="lax")


@router.post("/code")
def code_issue(request: Request, svc: PredictionService = Depends(get_service)):
    if _cross_site(request):
        return _err(403, "cross_site", "Запрос с чужого сайта отклонён")
    try:
        _session_key()  # без ключа сессий вход всё равно не завершить
    except InitDataError as e:
        return _err(503, "not_configured", e.message)
    if not svc.code_limiter.hit(_client_ip(request)):
        return _err(429, "rate_limited", "Слишком много кодов входа — подождите несколько минут")
    now = svc.now()
    try:
        with svc.conn() as c:
            it = login_codes.issue(c, now, _client_ip(request), request.cookies.get(LOGIN_COOKIE))
    except login_codes.TooMany:
        return _err(503, "busy", "Сейчас слишком много входов — попробуйте через минуту")
    bot = svc.bot_username() or DEFAULT_BOT
    resp = _json({"code": it.code, "expires_at": login_codes.iso_short(it.expires_at),
                  "ttl": int((it.expires_at - now).total_seconds()), "bot": bot,
                  "deep_link": f"https://t.me/{bot}?start={login_codes.START_PREFIX}{it.token}"})
    _set_login_cookie(resp, it.nonce)
    return resp


@router.get("/code/status")
def code_status(request: Request, svc: PredictionService = Depends(get_service)):
    if not svc.code_poll_limiter.hit(_client_ip(request)):
        return _err(429, "rate_limited", "Слишком частые запросы — подождите минуту")
    now = svc.now()
    with svc.conn() as c:
        st = login_codes.take(c, now, request.cookies.get(LOGIN_COOKIE))
    if st.state == "pending":
        return _json({"status": "pending", "expires_at": login_codes.iso_short(st.expires_at),
                      "ttl": max(0, int((st.expires_at - now).total_seconds()))})
    if st.state != "ok":
        resp = _json({"status": st.state})
        if request.cookies.get(LOGIN_COOKIE):
            _clear_login_cookie(resp)
        return resp
    uid = svc.upsert_user(st.user, keep_photo=True)
    _seen(svc, uid)
    resp = _session_response(svc, uid, "code", extra={"status": "ok"})
    _clear_login_cookie(resp)
    return resp


# ---------- вход для проверки магазином приложений ----------

def _norm_review(text: Any) -> str:
    """«rs-7k4p q9tx» → «RS7K4PQ9TX»: регистр, пробелы и дефисы не важны (модератор вводит руками)."""
    if not isinstance(text, str) or len(text) > 64:
        return ""
    return re.sub(r"[\s\-–—_]", "", text).upper()


def review_user_id() -> int:
    raw = os.environ.get("REVIEW_USER_ID", "").strip()
    try:
        return int(raw) if raw else REVIEW_USER_ID_DEFAULT
    except ValueError:
        return REVIEW_USER_ID_DEFAULT


@router.post("/review")
async def review_login(request: Request, svc: PredictionService = Depends(get_service)):
    secret = _norm_review(os.environ.get("REVIEW_LOGIN_CODE", ""))
    if len(secret) < REVIEW_CODE_MIN:
        return _err(404, "not_enabled", "Вход по коду проверки выключен")
    if _cross_site(request):
        return _err(403, "cross_site", "Запрос с чужого сайта отклонён")
    if not svc.review_limiter.hit(_client_ip(request)):
        return _err(429, "rate_limited", "Слишком много попыток — подождите несколько минут")
    raw = await request.body()
    if len(raw) > 1024:
        return _err(413, "too_large", "Слишком большой запрос")
    try:
        body = await request.json()
    except ValueError:
        return _err(422, "validation", "Неверный запрос")
    given = _norm_review(body.get("code") if isinstance(body, dict) else None)
    if not given or not hmac.compare_digest(given.encode(), secret.encode()):
        return _err(401, "bad_code", "Неверный код")
    try:
        _session_key()
    except InitDataError as e:
        return _err(503, "not_configured", e.message)
    uid = review_user_id()
    if uid in admin_ids():  # тестовый вход никогда не даёт прав админа
        return _err(503, "not_configured", "Вход по коду проверки настроен неверно")
    svc.upsert_user({"id": uid, "first_name": REVIEW_NAME, "last_name": None, "username": None}, keep_photo=True)
    _seen(svc, uid)
    log.info("review login from %s", _client_ip(request))
    return _session_response(svc, uid, "review")


@router.delete("/me")
async def delete_account(request: Request, authorization: Optional[str] = Header(default=None),
                         svc: PredictionService = Depends(get_service)):
    if not has_credentials(request, authorization):
        return _err(401, "unauthorized", "Нужна авторизация")
    try:
        p = authenticate(request, authorization, svc)
    except InitDataError as e:
        return _err(401, "unauthorized", e.message)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("confirm") is not True:
        return _err(422, "validation", "Подтвердите удаление аккаунта")
    deleted = svc.delete_user(p.id)
    log.info("account deleted: %s (%s)", p.id, "ok" if deleted else "already gone")
    resp = _json({"ok": True, "deleted": deleted})
    _clear_cookie(resp)
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
    else:
        _seen(svc, uid)
    return _json(i18n.fan_names(body, i18n.request_lang(request)))


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
