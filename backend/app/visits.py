"""Счётчик посещений без входа: сколько новых людей приходит каждый день (сайт, мини-апп, Android).

POST /api/visit        {device, platform} → {ok, counted}. device — случайный id устройства из localStorage
                       (crypto.randomUUID), platform — tg | android | web. Клиент шлёт не чаще раза в день.
                       В базе — только SHA-256 от id с солью сервера (VISIT_SALT), день по МСК и платформа.
                       IP и User-Agent не храним: IP — лишь ключ ограничителя частоты в памяти, UA — только
                       чтобы не считать ботов. Если запрос с сессией/initData — к устройству пишется user_id.
                       Повтор в тот же день ничего не пишет (строка (day, device) уже есть).
GET  /api/admin/stats  → только админ (ADMIN_IDS): по дням за 30 дней новые/активные люди и новые
                       пользователи с разбивкой по платформам, плюс итоги. 401 без входа, 403 — не админ.

Бот здесь ни при чём и никому ничего не пишет.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from .auth import InitDataError, admin_ids
from .auth_api import review_user_id
from .identity import _cross_site, authenticate, has_credentials
from .predictions.api import get_service
from .predictions.service import MSK, PredictionService, RateLimiter

log = logging.getLogger("visits")

router = APIRouter()

PLATFORMS = ("tg", "android", "web")
DEVICE_RE = re.compile(r"^[A-Za-z0-9-]{16,64}$")   # UUID — 36 символов; запасной id клиента — короче
BODY_MAX = 512
STATS_DAYS = 30
VISIT_RATE = (30, 600.0)   # новых отметок с одного IP за 10 мин: один человек — одна в день
# браузерные боты и проверялки страниц JS почти не исполняют, но те, что исполняют, — мимо счёта
BOT_UA = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview|phantom|puppeteer|playwright",
                    re.IGNORECASE)
SALT_DEFAULT = "rm-v2 visits"

_limiter: Optional[RateLimiter] = None


def limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(*VISIT_RATE)
    return _limiter


def _json(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def _err(status: int, error: str, message: str) -> JSONResponse:
    return _json({"error": error, "message": message}, status)


def device_hash(device: str) -> str:
    """Соль — VISIT_SALT из .env сервера (не задана — постоянная строка): по хешу id устройства не узнать."""
    salt = os.environ.get("VISIT_SALT", "").strip() or SALT_DEFAULT
    return hashlib.sha256(f"{salt}|{device}".encode()).hexdigest()


def msk_day(now: datetime) -> str:
    return now.astimezone(MSK).strftime("%Y-%m-%d")


def is_bot(ua: Optional[str]) -> bool:
    return not ua or bool(BOT_UA.search(ua))


def record(c: sqlite3.Connection, device_h: str, platform: str, day: str, user_id: Optional[int]) -> bool:
    """Отметить посещение. True — новая отметка за день, False — уже было (только дописываем user_id)."""
    c.execute("BEGIN IMMEDIATE")
    try:
        fresh = c.execute("INSERT OR IGNORE INTO visit_days(day, device, platform) VALUES (?,?,?)",
                          (day, device_h, platform)).rowcount > 0
        if fresh:
            c.execute(
                """INSERT INTO visitors(device, first_day, last_day, platform, user_id) VALUES (?,?,?,?,?)
                   ON CONFLICT(device) DO UPDATE SET last_day=excluded.last_day,
                       user_id=COALESCE(excluded.user_id, visitors.user_id)""",
                (device_h, day, day, platform, user_id))
        elif user_id is not None:
            c.execute("UPDATE visitors SET user_id=? WHERE device=? AND user_id IS NOT ?", (user_id, device_h, user_id))
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    return fresh


def _user_id(request: Request, authorization: Optional[str], svc: PredictionService) -> Optional[int]:
    """Кто вошёл (initData или сессия) — без создания пользователя; невалидный вход — просто аноним."""
    if not has_credentials(request, authorization):
        return None
    try:
        return authenticate(request, authorization, svc).id
    except InitDataError:
        return None


def _client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


@router.post("/api/visit")
async def visit(request: Request, authorization: Optional[str] = Header(default=None),
                user_agent: Optional[str] = Header(default=None),
                svc: PredictionService = Depends(get_service)):
    if _cross_site(request):
        return _err(403, "cross_site", "Запрос с чужого сайта отклонён")
    raw = await request.body()
    if len(raw) > BODY_MAX:
        return _err(413, "too_large", "Слишком большой запрос")
    try:
        body = await request.json()
    except ValueError:
        return _err(422, "validation", "Неверный запрос")
    if not isinstance(body, dict):
        return _err(422, "validation", "Неверный запрос")
    device, platform = body.get("device"), body.get("platform")
    if not isinstance(device, str) or not DEVICE_RE.match(device):
        return _err(422, "validation", "device: случайный id устройства")
    if platform not in PLATFORMS:
        return _err(422, "validation", "platform: tg, android или web")
    if is_bot(user_agent):
        return _json({"ok": True, "counted": False})
    h = device_hash(device)
    day = msk_day(svc.now())
    with svc.conn() as c:
        seen = c.execute("SELECT 1 FROM visit_days WHERE day=? AND device=?", (day, h)).fetchone() is not None
    uid = _user_id(request, authorization, svc)
    if seen and uid is None:  # повтор за день — без записи и без расхода лимита
        return _json({"ok": True, "counted": False})
    if not seen and not limiter().hit(_client_ip(request)):
        return _err(429, "rate_limited", "Слишком много запросов — подождите")
    with svc.conn() as c:
        fresh = record(c, h, platform, day, uid)
    return _json({"ok": True, "counted": fresh})


# ---------- статистика для админа ----------

def _days(today: date, n: int) -> list[str]:
    return [(today - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _by_platform(rows: Any) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for day, platform, n in rows:
        out.setdefault(day, {})[platform] = int(n)
    return out


# users.created_at — UTC 'YYYY-MM-DDTHH:MM:SS.ffffffZ' → день по МСК
_USER_DAY = "date(substr(created_at, 1, 10) || ' ' || substr(created_at, 12, 8), '+3 hours')"


def stats(c: sqlite3.Connection, now: datetime, exclude_users: tuple[int, ...] = ()) -> dict[str, Any]:
    today = now.astimezone(MSK).date()
    days = _days(today, STATS_DAYS)
    since = days[0]
    new = _by_platform(c.execute(
        "SELECT first_day, platform, COUNT(*) FROM visitors WHERE first_day >= ? GROUP BY 1, 2", (since,)))
    active = _by_platform(c.execute(
        "SELECT day, platform, COUNT(*) FROM visit_days WHERE day >= ? GROUP BY 1, 2", (since,)))
    skip = ",".join("?" * len(exclude_users)) or "NULL"
    users_new = {d: int(n) for d, n in c.execute(
        f"SELECT {_USER_DAY} AS d, COUNT(*) FROM users WHERE id NOT IN ({skip}) GROUP BY d HAVING d >= ?",
        (*exclude_users, since))}

    rows = []
    for d in days:
        nb = {p: new.get(d, {}).get(p, 0) for p in PLATFORMS}
        ab = {p: active.get(d, {}).get(p, 0) for p in PLATFORMS}
        rows.append({"day": d, "new_visitors": sum(nb.values()), "active_visitors": sum(ab.values()),
                     "new_users": users_new.get(d, 0), "new_by_platform": nb, "active_by_platform": ab})

    def distinct_since(d: str) -> int:
        return int(c.execute("SELECT COUNT(DISTINCT device) FROM visit_days WHERE day >= ?", (d,)).fetchone()[0])

    by_platform = {p: 0 for p in PLATFORMS}
    for p, n in c.execute("SELECT platform, COUNT(*) FROM visitors GROUP BY platform"):
        by_platform[p] = int(n)
    totals = {
        "visitors": sum(by_platform.values()),
        "visitors_by_platform": by_platform,
        "users": int(c.execute(f"SELECT COUNT(*) FROM users WHERE id NOT IN ({skip})", exclude_users).fetchone()[0]),
        "linked_visitors": int(c.execute("SELECT COUNT(*) FROM visitors WHERE user_id IS NOT NULL").fetchone()[0]),
        "new_1d": rows[-1]["new_visitors"],
        "new_7d": sum(r["new_visitors"] for r in rows[-7:]),
        "new_30d": sum(r["new_visitors"] for r in rows),
        "new_users_1d": rows[-1]["new_users"],
        "new_users_7d": sum(r["new_users"] for r in rows[-7:]),
        "new_users_30d": sum(r["new_users"] for r in rows),
        "active_1d": distinct_since(days[-1]),
        "active_7d": distinct_since(days[-7]),
        "active_30d": distinct_since(since),
    }
    return {"today": days[-1], "tz": "Europe/Moscow", "platforms": list(PLATFORMS), "days": rows, "totals": totals}


@router.get("/api/admin/stats")
def admin_stats(request: Request, authorization: Optional[str] = Header(default=None),
                svc: PredictionService = Depends(get_service)):
    if not has_credentials(request, authorization):
        return _err(401, "unauthorized", "Нужна авторизация")
    try:
        p = authenticate(request, authorization, svc)
    except InitDataError as e:
        return _err(401, "unauthorized", e.message)
    if p.id not in admin_ids():
        return _err(403, "forbidden", "Нет доступа")
    with svc.conn() as c:  # тестовый вход магазина (REVIEW_USER_ID) — не живой человек
        return _json(stats(c, svc.now(), (review_user_id(),)))


def install(app) -> None:
    app.include_router(router)
