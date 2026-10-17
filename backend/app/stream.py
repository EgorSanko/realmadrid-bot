"""Этап 3: трансляция.

Владелец вставляет HLS-ссылку (m3u8) в админку и нажимает «Старт», в конце — «Стоп».
Состояние эфира — один JSON-файл DATA_DIR/stream.json (атомарная запись через os.replace).

Доступ к админ-эндпоинтам:
  (а) Telegram initData в заголовке `Authorization: tma <initData>` — подпись по BOT_TOKEN,
      возраст не больше 24 ч, id пользователя из ADMIN_IDS;
  (б) заголовок `X-Admin-Token`, равный ADMIN_TOKEN.
Если ни один способ не настроен в env — админка закрыта полностью.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel
from app.auth import (INIT_DATA_MAX_AGE, SESSION_COOKIE, InitDataError, is_session_header, is_tma,  # noqa: F401
                      validate_tma)
from app.identity import authenticate

router = APIRouter()

URL_MAX = 2000
TITLE_MAX = 200

_lock = threading.Lock()


# ---------- хранилище ----------

def data_dir() -> Path:
    raw = os.environ.get("DATA_DIR", "").strip()
    return Path(raw) if raw else Path(__file__).resolve().parent.parent / "data"


def _state_path() -> Path:
    return data_dir() / "stream.json"


def _empty_state() -> dict[str, Any]:
    return {"live": False, "url": None, "title": None, "started_at": None, "stopped_at": None}


def load_state() -> dict[str, Any]:
    try:
        raw = json.loads(_state_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return _empty_state()
    if not isinstance(raw, dict):
        return _empty_state()
    state = _empty_state()
    state.update({k: raw.get(k) for k in state})
    state["live"] = bool(state["live"]) and isinstance(state["url"], str) and bool(state["url"])
    return state


def save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".stream-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------- срок действия ссылки ----------

def token_expiry(url: str) -> Optional[str]:
    """Срок действия ссылки из параметра `token` (Nimble Streamer: base64url(JSON).подпись).

    Возвращает ISO-время UTC из поля `exp` или None, если разобрать не удалось.
    """
    try:
        tokens = parse_qs(urlsplit(url).query).get("token")
        if not tokens:
            return None
        head = tokens[0].split(".", 1)[0]
        head += "=" * (-len(head) % 4)
        payload = json.loads(base64.urlsafe_b64decode(head.encode("ascii")))
        exp = payload.get("exp") if isinstance(payload, dict) else None
        if isinstance(exp, bool) or not isinstance(exp, (int, float)):
            return None
        return datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
    except (ValueError, binascii.Error, UnicodeError, OverflowError, OSError):
        return None


# ---------- публичные данные ----------

def public_view(state: dict[str, Any]) -> dict[str, Any]:
    if not state["live"]:
        return {"live": False, "url": None, "title": None, "started_at": None}
    return {
        "live": True,
        "url": state["url"],
        "title": state["title"],
        "started_at": state["started_at"],
    }


@router.get("/api/stream")
def get_stream(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return public_view(load_state())


# ---------- доступ ----------

def _admin_ids() -> set[int]:
    ids = set()
    for part in os.environ.get("ADMIN_IDS", "").split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def _deny(status: int, msg: str) -> HTTPException:
    return HTTPException(status_code=status, detail=msg)


def require_admin(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> str:
    bot_token = os.environ.get("BOT_TOKEN", "").strip()
    admin_ids = _admin_ids()
    admin_token = os.environ.get("ADMIN_TOKEN", "").strip()
    tg_enabled = bool(bot_token and admin_ids)

    if not tg_enabled and not admin_token:
        raise _deny(403, "Админка отключена")

    if x_admin_token is not None:
        if admin_token and hmac.compare_digest(
            x_admin_token.strip().encode("utf-8"), admin_token.encode("utf-8")
        ):
            return "token"
        raise _deny(401, "Неверный токен")

    # initData мини-аппа или сессия сайта (заголовок `Session …` / cookie rm_session)
    via_cookie = not authorization and bool(request.cookies.get(SESSION_COOKIE))
    if is_tma(authorization) or is_session_header(authorization) or via_cookie:
        if not tg_enabled:
            raise _deny(401, "Вход через Telegram не настроен")
        from app.predictions.api import get_service  # сессии сверяются с users.session_epoch

        try:
            p = authenticate(request, authorization, get_service(), bot_token)
        except InitDataError as e:
            if e.reason == "no_user":
                raise _deny(403, "Нет доступа") from None
            if e.reason == "missing":
                raise _deny(401, "Нужна авторизация") from None
            raise _deny(401, e.message) from None
        if p.id not in admin_ids:
            raise _deny(403, "Нет доступа")
        return f"tg:{p.id}" if p.via == "tma" else f"session:{p.id}"

    raise _deny(401, "Нужна авторизация")


# ---------- админка ----------

class StartIn(BaseModel):
    url: str
    title: Optional[str] = None


def validate_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise _deny(422, "Вставьте ссылку на трансляцию")
    if len(url) > URL_MAX:
        raise _deny(422, f"Ссылка длиннее {URL_MAX} символов")
    if any(c.isspace() or ord(c) < 32 for c in url):
        raise _deny(422, "В ссылке не должно быть пробелов")
    try:
        parts = urlsplit(url)
    except ValueError:
        raise _deny(422, "Ссылка не распознана") from None
    if parts.scheme.lower() not in ("http", "https"):
        raise _deny(422, "Ссылка должна начинаться с https://")
    if not parts.hostname:
        raise _deny(422, "В ссылке нет адреса сервера")
    return url


def admin_view(state: dict[str, Any]) -> dict[str, Any]:
    out = dict(state)
    out["expires_at"] = token_expiry(state["url"]) if state["url"] else None
    return out


@router.get("/api/admin/stream")
def admin_get(response: Response, who: str = Depends(require_admin)) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return admin_view(load_state())


@router.post("/api/admin/stream/start")
def admin_start(body: StartIn, who: str = Depends(require_admin)) -> dict[str, Any]:
    url = validate_url(body.url)
    title = (body.title or "").strip()[:TITLE_MAX] or None
    with _lock:
        state = {
            "live": True,
            "url": url,
            "title": title,
            "started_at": _now_iso(),
            "stopped_at": None,
        }
        save_state(state)
    return admin_view(state)


@router.post("/api/admin/stream/stop")
def admin_stop(who: str = Depends(require_admin)) -> dict[str, Any]:
    with _lock:
        state = load_state()
        state["live"] = False
        state["stopped_at"] = _now_iso()
        save_state(state)
    return admin_view(state)
