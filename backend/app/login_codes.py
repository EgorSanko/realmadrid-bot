"""Вход на сайте по коду через бота: заявки в predictions.db (таблица login_codes).

Поток:
  1. Сайт: POST /api/auth/code → `issue()`: 6 цифр (`code`), длинный URL-safe `token` для deep link
     `https://t.me/<бот>?start=login_<token>` и секретный `nonce` — он уходит только в HttpOnly-cookie
     этого браузера (в базе — его SHA-256). В ссылку nonce не попадает, 6 цифр — тоже.
  2. Бот (сборщик, app/bot.py) получает `/start login_<token>` или 6 цифр → `confirm()`: вписывает
     в заявку from.id и имя. Только если заявка не истекла и ещё не подтверждена.
  3. Сайт опрашивает GET /api/auth/code/status → `take()` по nonce из cookie: подтверждена —
     заявка удаляется (одноразово) и браузер получает сессию.

Код живёт CODE_TTL (5 мин). Подтверждённую заявку браузер может забрать ещё CLAIM_GRACE после
подтверждения, даже если 5 минут уже вышли (подтвердили на последней секунде).
"""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

CODE_TTL = timedelta(minutes=5)
CLAIM_GRACE = timedelta(minutes=2)
TOKEN_BYTES = 16                 # token_urlsafe(16) — 22 символа [A-Za-z0-9_-], 128 бит
NONCE_BYTES = 32
MAX_ACTIVE = 5000                # предохранитель: больше живых заявок не держим
START_PREFIX = "login_"

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
CODE_RE = re.compile(r"^\d{6}$")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _from_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def iso_short(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nonce_hash(nonce: str) -> str:
    return hashlib.sha256(("rm-v2 login|" + nonce).encode()).hexdigest()


def normalize_code(text: Any) -> Optional[str]:
    """«123 456», «123-456», «123456» → «123456»; остальное — None."""
    if not isinstance(text, str) or len(text) > 20:
        return None
    s = re.sub(r"[\s\-–—]", "", text)
    return s if CODE_RE.match(s) else None


@dataclass(frozen=True)
class Issued:
    code: str
    token: str
    nonce: str
    expires_at: datetime


class TooMany(Exception):
    pass


def purge(conn: sqlite3.Connection, now: datetime) -> int:
    """Удалить истёкшие неподтверждённые и забытые подтверждённые заявки."""
    cur = conn.execute(
        "DELETE FROM login_codes WHERE (confirmed_at IS NULL AND expires_at <= ?) OR "
        "(confirmed_at IS NOT NULL AND confirmed_at <= ?)",
        (_iso(now), _iso(now - CLAIM_GRACE)))
    return cur.rowcount


def issue(conn: sqlite3.Connection, now: datetime, ip: Optional[str] = None,
          replace_nonce: Optional[str] = None) -> Issued:
    """Новая заявка. `replace_nonce` — nonce прежней заявки этого браузера: её удаляем (один браузер —
    один живой код). Бросает TooMany, если живых заявок слишком много."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        purge(conn, now)
        if replace_nonce:
            conn.execute("DELETE FROM login_codes WHERE nonce_hash=?", (nonce_hash(replace_nonce),))
        if conn.execute("SELECT COUNT(*) FROM login_codes").fetchone()[0] >= MAX_ACTIVE:
            raise TooMany()
        exp = now + CODE_TTL
        for _ in range(20):
            code = f"{secrets.randbelow(10 ** 6):06d}"
            token = secrets.token_urlsafe(TOKEN_BYTES)
            nonce = secrets.token_urlsafe(NONCE_BYTES)
            try:
                conn.execute(
                    "INSERT INTO login_codes(token, code, nonce_hash, ip, created_at, expires_at) VALUES (?,?,?,?,?,?)",
                    (token, code, nonce_hash(nonce), (ip or "")[:64] or None, _iso(now), _iso(exp)))
            except sqlite3.IntegrityError:  # совпал живой код — берём другой
                continue
            conn.execute("COMMIT")
            return Issued(code, token, nonce, exp)
        raise TooMany()
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def confirm(conn: sqlite3.Connection, now: datetime, user: dict[str, Any], *, token: Optional[str] = None,
            code: Optional[str] = None) -> bool:
    """Бот: вписать пользователя в живую неподтверждённую заявку. True — подтверждена сейчас.
    Повторное подтверждение (тем же или другим человеком) не проходит. Вызывается внутри транзакции бота."""
    if token is not None:
        if not TOKEN_RE.match(token):
            return False
        where, arg = "token=?", token
    elif code is not None:
        if not CODE_RE.match(code):
            return False
        where, arg = "code=?", code
    else:
        return False
    cur = conn.execute(
        f"UPDATE login_codes SET user_id=?, first_name=?, last_name=?, username=?, confirmed_at=? "
        f"WHERE {where} AND user_id IS NULL AND expires_at > ?",
        (int(user["id"]), (user.get("first_name") or "")[:128], user.get("last_name"), user.get("username"),
         _iso(now), arg, _iso(now)))
    return cur.rowcount == 1


@dataclass(frozen=True)
class Status:
    state: str                      # missing | expired | pending | ok
    expires_at: Optional[datetime] = None
    user: Optional[dict[str, Any]] = None


def take(conn: sqlite3.Connection, now: datetime, nonce: Optional[str]) -> Status:
    """Сайт: состояние заявки этого браузера. Подтверждена — удаляется и возвращается пользователь
    (забрать можно ровно один раз)."""
    if not nonce or len(nonce) > 128:
        return Status("missing")
    h = nonce_hash(nonce)
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT * FROM login_codes WHERE nonce_hash=?", (h,)).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return Status("expired")
        if row["user_id"] is None:
            exp = _from_iso(row["expires_at"])
            if exp <= now:
                conn.execute("DELETE FROM login_codes WHERE nonce_hash=?", (h,))
                conn.execute("COMMIT")
                return Status("expired")
            conn.execute("COMMIT")
            return Status("pending", exp)
        if _from_iso(row["confirmed_at"]) <= now - CLAIM_GRACE:
            conn.execute("DELETE FROM login_codes WHERE nonce_hash=?", (h,))
            conn.execute("COMMIT")
            return Status("expired")
        conn.execute("DELETE FROM login_codes WHERE nonce_hash=?", (h,))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return Status("ok", user={"id": int(row["user_id"]), "first_name": row["first_name"] or "",
                              "last_name": row["last_name"], "username": row["username"]})
