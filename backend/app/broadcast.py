"""Рассылка ролика гола в личку бота — по кнопке владельца из «Мадридиста · Клипы».

Кому: всем, кто писал боту (таблица bot_chats в predictions.db: /start, вход по коду, плюс разовый импорт
базы старого бота), кроме заблокировавших бота и отписавшихся командой /stop (вернуть — /goals).

Как: программа клипов шлёт mp4 на POST /api/admin/broadcast (X-Admin-Token) → задание в
DATA_DIR/broadcasts/<id>/ (video.mp4 + job.json). API в bridge-сети Telegram не видит, поэтому отправляет
сборщик (`run` — задача рядом с ботом, через тот же SOCKS-туннель): первому получателю (админу) видео
загружается файлом, остальным уходит его file_id — без повторной заливки. 403/400 «бот заблокирован /
чата нет» → получатель помечается и больше не получает.

Повторно один гол всем не уходит: ключ задания (key) уникален среди «всем»-рассылок; «проверка» (test)
уходит только админам и ключ не занимает.

  python -m app.broadcast import <betting.db>   # разово: получатели из базы старого бота
  python -m app.broadcast count                 # сколько получит «всем»
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from . import config
from .predictions import db as predictions_db
from .stream import _admin_ids, require_admin

log = logging.getLogger("broadcast")
router = APIRouter()

VIDEO_MAX = 50 * 1024 * 1024        # sendVideo загрузкой файла — до 50 МБ
CAPTION_MAX = 1024
FOOTER = "\n\n▶️ Матчи онлайн, счёт и прогнозы — @Real_Madrid_football_bot\nНе присылать голы: /stop"
SEND_PAUSE = 0.06                   # ~16 сообщений в секунду — ниже лимита Telegram (30/с)
KEY_RE = re.compile(r"^[\w:.\-]{1,120}$")
JOB_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- получатели ----------

def record_chat(conn, user: dict, source: str = "bot") -> None:
    """Человек написал боту — он получатель. Вернулся после блокировки — снова получатель."""
    conn.execute(
        "INSERT INTO bot_chats(chat_id, first_name, username, source, added_at, seen_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET first_name=excluded.first_name, username=excluded.username, "
        "seen_at=excluded.seen_at, blocked_at=NULL",
        (int(user["id"]), user.get("first_name") or "", user.get("username"), source, _now(), _now()))


def set_notify(conn, chat_id: int, on: bool) -> None:
    conn.execute("UPDATE bot_chats SET notify=? WHERE chat_id=?", (1 if on else 0, int(chat_id)))


def mark_blocked(conn, chat_id: int, reason: str) -> None:
    conn.execute("UPDATE bot_chats SET blocked_at=?, blocked_reason=? WHERE chat_id=?",
                 (_now(), reason[:200], int(chat_id)))


def recipients(conn, test: bool) -> list[int]:
    admins = sorted(_admin_ids())
    if test:
        return admins
    rows = [r[0] for r in conn.execute(
        "SELECT chat_id FROM bot_chats WHERE notify=1 AND blocked_at IS NULL ORDER BY added_at")]
    # админы первыми: на них видео заливается файлом, остальным — его file_id
    return admins + [c for c in rows if c not in set(admins)]


def import_legacy(conn, path: str) -> dict:
    """Получатели из базы старого бота (betting.db). Заблокировавшие его — сразу помечены."""
    old = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = old.execute("SELECT user_id, first_name, username, is_blocked FROM users").fetchall()
    finally:
        old.close()
    added = blocked = 0
    for uid, first, username, is_blocked in rows:
        cur = conn.execute(
            "INSERT OR IGNORE INTO bot_chats(chat_id, first_name, username, source, added_at, blocked_at, blocked_reason) "
            "VALUES (?,?,?,?,?,?,?)",
            (int(uid), first or "", username, "legacy", _now(), _now() if is_blocked else None,
             "старый бот: заблокирован" if is_blocked else None))
        added += cur.rowcount
        blocked += cur.rowcount and bool(is_blocked)
    return {"rows": len(rows), "added": added, "blocked": blocked}


def import_site_users(conn) -> int:
    """Вошедшие на сайт через Telegram — тоже писали боту (или мини-апп) — получатели."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO bot_chats(chat_id, first_name, username, source, added_at) "
        "SELECT id, first_name, username, 'site', ? FROM users", (_now(),))
    return cur.rowcount


# ---------- задания ----------

def jobs_dir() -> Path:
    return predictions_db.data_dir() / "broadcasts"


def load_job(jid: str) -> Optional[dict]:
    try:
        return json.loads((jobs_dir() / jid / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_job(job: dict) -> None:
    d = jobs_dir() / job["id"]
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".job-", dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    os.replace(tmp, d / "job.json")


def all_jobs() -> list[dict]:
    out = []
    if jobs_dir().exists():
        for d in jobs_dir().iterdir():
            j = load_job(d.name) if d.is_dir() else None
            if j:
                out.append(j)
    return sorted(out, key=lambda j: j["created_at"])


def _public(job: dict) -> dict:
    return {k: v for k, v in job.items() if k not in ("file_id",)}


@router.get("/api/admin/broadcast")
def broadcast_info(who: str = Depends(require_admin)) -> dict:
    conn = predictions_db.connect()
    try:
        n = len(recipients(conn, test=False))
    finally:
        conn.close()
    return {"recipients": n, "jobs": [_public(j) for j in all_jobs()[-10:]]}


@router.post("/api/admin/broadcast")
async def broadcast_create(request: Request, key: str, test: int = 0, caption: str = "",
                           width: int = 0, height: int = 0, duration: float = 0,
                           who: str = Depends(require_admin)) -> dict:
    if not KEY_RE.match(key):
        raise HTTPException(400, "Неверный ключ")
    text = caption.strip()[: CAPTION_MAX - len(FOOTER)] + FOOTER
    if not test:
        for j in all_jobs():
            if j["key"] == key and not j["test"] and j["status"] != "failed":
                raise HTTPException(409, "Этот гол уже отправлен всем")
    jid = uuid.uuid4().hex[:12]
    d = jobs_dir() / jid
    d.mkdir(parents=True, exist_ok=True)
    size = 0
    with open(d / "video.mp4", "wb") as f:
        async for chunk in request.stream():
            size += len(chunk)
            if size > VIDEO_MAX:
                f.close()
                (d / "video.mp4").unlink(missing_ok=True)
                d.rmdir()
                raise HTTPException(413, "Видео больше 50 МБ — Telegram такое не примет")
            f.write(chunk)
    if size < 1000:
        (d / "video.mp4").unlink(missing_ok=True)
        d.rmdir()
        raise HTTPException(400, "Пустое видео")
    job = {"id": jid, "key": key, "test": bool(test), "caption": text, "status": "queued", "who": who,
           "width": width or None, "height": height or None, "duration": round(duration) or None,
           "size": size, "created_at": _now(), "total": 0, "sent": 0, "blocked": 0, "failed": 0}
    save_job(job)
    log.info("рассылка %s: в очереди (%s, %d байт, %s)", jid, key, size, "проверка" if test else "всем")
    return _public(job)


@router.get("/api/admin/broadcast/{jid}")
def broadcast_status(jid: str, who: str = Depends(require_admin)) -> dict:
    job = load_job(jid) if JOB_ID_RE.match(jid) else None
    if not job:
        raise HTTPException(404, "Нет такой рассылки")
    return _public(job)


# ---------- отправка (в сборщике) ----------

Uploader = Callable[[int, Path, dict], Awaitable[dict]]


def curl_uploader(bot) -> Uploader:
    """sendVideo с файлом (multipart) через SOCKS-туннель — Bot API JSON-транспорт файлы не возит."""
    async def upload(chat_id: int, path: Path, fields: dict) -> dict:
        from curl_cffi import CurlMime
        from curl_cffi.requests import AsyncSession
        mp = CurlMime()
        mp.addpart(name="video", content_type="video/mp4", filename="goal.mp4", local_path=str(path))
        proxy = config.TG_PROXY
        async with AsyncSession(proxies={"http": proxy, "https": proxy} if proxy else None) as s:
            r = await s.post(f"{bot.api_base}/bot{bot.token}/sendVideo",
                             data={"chat_id": str(chat_id), **{k: str(v) for k, v in fields.items()}},
                             multipart=mp, timeout=300)
        mp.close()
        return r.json()
    return upload


def _fields(job: dict) -> dict:
    f = {"caption": job["caption"], "supports_streaming": "true"}
    for k in ("width", "height", "duration"):
        if job.get(k):
            f[k] = job[k]
    return f


async def send_job(job: dict, bot, upload: Uploader, conn_factory=predictions_db.connect,
                   pause: float = SEND_PAUSE) -> dict:
    from .bot import TgApiError
    conn = conn_factory()
    try:
        to = recipients(conn, job["test"])
        job.update(status="sending", total=len(to), started_at=_now())
        save_job(job)
        video = jobs_dir() / job["id"] / "video.mp4"
        file_id = None
        for i, chat in enumerate(to):
            try:
                if file_id is None:
                    res = await upload(chat, video, _fields(job))
                    if not res.get("ok"):
                        raise TgApiError("sendVideo", res.get("error_code"), str(res.get("description") or ""))
                    file_id = ((res.get("result") or {}).get("video") or {}).get("file_id")
                else:
                    try:
                        await bot.call("sendVideo", {"chat_id": chat, "video": file_id, **_fields(job)})
                    except TgApiError as e:
                        m = re.search(r"retry after (\d+)", e.description or "")
                        if e.code != 429 or not m:
                            raise
                        await asyncio.sleep(int(m.group(1)) + 1)
                        await bot.call("sendVideo", {"chat_id": chat, "video": file_id, **_fields(job)})
                job["sent"] += 1
            except TgApiError as e:
                desc = (e.description or "").lower()
                if e.code == 403 or (e.code == 400 and ("chat not found" in desc or "deactivated" in desc)):
                    mark_blocked(conn, chat, f"{e.code} {e.description}")
                    job["blocked"] += 1
                else:
                    job["failed"] += 1
                    log.warning("рассылка %s: %s — %s", job["id"], chat, e)
            except Exception as e:  # noqa: BLE001 — один получатель не должен ронять рассылку
                job["failed"] += 1
                log.warning("рассылка %s: %s — %s: %s", job["id"], chat, type(e).__name__, str(e)[:200])
            if i % 5 == 4:
                save_job(job)
            await asyncio.sleep(pause)
        job.update(status="done" if job["sent"] or not to else "failed", finished_at=_now())
        save_job(job)
        log.info("рассылка %s: готово — отправлено %d из %d, заблокировали %d, ошибок %d",
                 job["id"], job["sent"], job["total"], job["blocked"], job["failed"])
        return job
    finally:
        conn.close()


async def run(bot, stop: asyncio.Event, upload: Optional[Uploader] = None) -> None:
    """Задача сборщика: берёт задания из очереди по одному."""
    upload = upload or curl_uploader(bot)
    for j in all_jobs():   # упали посреди рассылки — не повторяем (иначе дубли), помечаем
        if j["status"] == "sending":
            j.update(status="failed", error="сборщик перезапустился посреди рассылки")
            save_job(j)
    while not stop.is_set():
        job = next((j for j in all_jobs() if j["status"] == "queued"), None)
        if job:
            try:
                await send_job(job, bot, upload)
            except Exception as e:  # noqa: BLE001
                job.update(status="failed", error=f"{type(e).__name__}: {e}"[:300])
                save_job(job)
                log.exception("рассылка %s упала", job["id"])
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=3)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    c = predictions_db.connect()
    try:
        if len(sys.argv) > 2 and sys.argv[1] == "import":
            print(import_legacy(c, sys.argv[2]), "сайт:", import_site_users(c))
        print("получат «всем»:", len(recipients(c, test=False)), "админы:", sorted(_admin_ids()))
    finally:
        c.close()
