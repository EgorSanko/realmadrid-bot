"""Аватары пользователей: копия у нас, клиент на t.me не ходит.

photo_url у Telegram лежит на t.me (и CDN Telegram) — внешний хост, к тому же с нашего сервера
напрямую недоступный. Поэтому:

  1. API при входе ставит заявку в avatar_queue (predictions.db) — `want()`;
  2. сборщик (network_mode: host, видит SOCKS-туннель 127.0.0.1:1080) скачивает её — `process()`:
     только https и хосты Telegram, только image/jpeg или image/png, не больше 1 МБ,
     сигнатура файла должна совпасть с типом; пишет атомарно DATA_DIR/avatars/{id}.jpg|png (0644);
  3. nginx отдаёт /img/avatar/{id}.jpg прямо из /opt/rm-v2/data/avatars (нет файла — силуэт);
     API в ответах даёт ссылку с ?v=<mtime>, чтобы новый аватар не застревал в кэше.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urljoin, urlsplit

log = logging.getLogger("avatars")

MAX_BYTES = 1024 * 1024
TYPES = {"image/jpeg": ".jpg", "image/png": ".png"}
MAGIC = {".jpg": (b"\xff\xd8\xff",), ".png": (b"\x89PNG\r\n\x1a\n",)}
ALLOWED_HOSTS = ("t.me", "telegram.org", "telesco.pe", "cdn-telegram.org", "telegram-cdn.org")
REFRESH_AFTER = timedelta(days=7)     # свежий аватар раз в неделю (если пользователь заходит)
REQUEUE_AFTER = timedelta(minutes=10)  # повторная заявка на тот же url — не чаще
RETRY_AFTER = (timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=3))
MAX_REDIRECTS = 3
QUEUE_CAP = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _from_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def avatars_dir() -> Path:
    raw = os.environ.get("DATA_DIR", "").strip()
    base = Path(raw) if raw else Path(__file__).resolve().parents[1] / "data"
    return base / "avatars"


def file_for(user_id: int) -> Optional[Path]:
    d = avatars_dir()
    for ext in (".jpg", ".png"):
        p = d / f"{int(user_id)}{ext}"
        if p.is_file():
            return p
    return None


def url_for(user_id: int) -> Optional[str]:
    """Ссылка на наш файл аватара или None (тогда клиент рисует силуэт)."""
    p = file_for(user_id)
    if p is None:
        return None
    try:
        v = int(p.stat().st_mtime)
    except OSError:
        return None
    return f"/img/avatar/{int(user_id)}.jpg?v={v}"


def allowed_url(url: Any) -> bool:
    if not isinstance(url, str) or len(url) > 1000:
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        return False
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


# ---------- заявки (API) ----------

def want(conn: sqlite3.Connection, user_id: int, photo_url: Optional[str], now: Optional[datetime] = None) -> bool:
    """Поставить заявку, если файла нет, url сменился или файл старше недели. True — заявка поставлена."""
    now = now or _now()
    url = photo_url if allowed_url(photo_url) else None
    row = conn.execute("SELECT avatar_src, avatar_at FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        return False
    src, at = row[0], row[1]
    have = file_for(user_id) is not None
    if url is None:
        if not have and src is None:
            return False  # нечего ни качать, ни удалять
    elif have and src == url and at and now - _from_iso(at) < REFRESH_AFTER:
        return False
    q = conn.execute("SELECT url, asked_at FROM avatar_queue WHERE user_id=?", (user_id,)).fetchone()
    if q is not None and q[0] == url and now - _from_iso(q[1]) < REQUEUE_AFTER:
        return False
    if q is None and conn.execute("SELECT COUNT(*) FROM avatar_queue").fetchone()[0] >= QUEUE_CAP:
        return False
    conn.execute(
        """INSERT INTO avatar_queue(user_id, url, asked_at, tries, next_at) VALUES (?,?,?,0,?)
           ON CONFLICT(user_id) DO UPDATE SET url=excluded.url, asked_at=excluded.asked_at, tries=0,
               next_at=excluded.next_at""",
        (user_id, url, _iso(now), _iso(now)))
    return True


# ---------- скачивание (сборщик) ----------

class AvatarError(Exception):
    pass


# fetch(url) → (status, headers{lower: value}, location|None, body: bytes|None)
# body читается с ограничением MAX_BYTES + 1: больше — значит, файл слишком большой.
Fetch = Callable[[str], Awaitable[tuple[int, dict[str, str], Optional[bytes]]]]


async def download(url: str, fetch: Fetch) -> tuple[bytes, str]:
    """Скачать аватар: (байты, расширение). Редиректы — только на хосты Telegram."""
    for _ in range(MAX_REDIRECTS + 1):
        if not allowed_url(url):
            raise AvatarError(f"хост не разрешён: {urlsplit(url).hostname}")
        status, headers, body = await fetch(url)
        if status in (301, 302, 303, 307, 308):
            loc = headers.get("location")
            if not loc:
                raise AvatarError(f"HTTP {status} без Location")
            url = urljoin(url, loc)
            continue
        if status != 200:
            raise AvatarError(f"HTTP {status}")
        ctype = (headers.get("content-type") or "").split(";")[0].strip().lower()
        ext = TYPES.get(ctype)
        if ext is None:
            raise AvatarError(f"тип не разрешён: {ctype or '—'}")
        try:
            declared = int(headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        if declared > MAX_BYTES or body is None or len(body) > MAX_BYTES:
            raise AvatarError("больше 1 МБ")
        if not body or not body.startswith(MAGIC[ext]):
            raise AvatarError("содержимое не похоже на картинку")
        return body, ext
    raise AvatarError("слишком много перенаправлений")


def save(user_id: int, body: bytes, ext: str) -> Path:
    d = avatars_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o755)  # nginx (www-data) на хосте читает папку напрямую
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=".av-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        os.chmod(tmp, 0o644)
        target = d / f"{int(user_id)}{ext}"
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    remove(user_id, keep=ext)
    return target


def remove(user_id: int, keep: Optional[str] = None) -> None:
    for ext in (".jpg", ".png"):
        if ext != keep:
            try:
                (avatars_dir() / f"{int(user_id)}{ext}").unlink()
            except FileNotFoundError:
                pass


async def process(conn: sqlite3.Connection, fetch: Fetch, limit: int = 2,
                  now: Optional[datetime] = None) -> list[tuple[int, str]]:
    """Обработать до `limit` заявок, чей срок подошёл. Возвращает [(user_id, итог)]."""
    now = now or _now()
    rows = conn.execute("SELECT user_id, url, tries, asked_at FROM avatar_queue WHERE next_at <= ? "
                        "ORDER BY next_at LIMIT ?", (_iso(now), limit)).fetchall()
    out = []
    for uid, url, tries, asked_at in rows:
        if url is None:
            remove(uid)
            _done(conn, uid, asked_at, None, now)
            out.append((uid, "removed"))
            continue
        try:
            body, ext = await download(url, fetch)
        except Exception as e:  # сеть, туннель, неверный ответ — повтор с паузой, потом бросаем
            msg = f"{type(e).__name__}: {e}"[:200]
            if tries >= len(RETRY_AFTER):  # 1 попытка + len(RETRY_AFTER) повторов
                conn.execute("DELETE FROM avatar_queue WHERE user_id=? AND asked_at=?", (uid, asked_at))
                out.append((uid, f"failed: {msg}"))
            else:
                conn.execute("UPDATE avatar_queue SET tries=?, next_at=? WHERE user_id=? AND asked_at=?",
                             (tries + 1, _iso(now + RETRY_AFTER[tries]), uid, asked_at))
                out.append((uid, f"retry: {msg}"))
            log.warning("avatar %s: %s", uid, msg)
            continue
        save(uid, body, ext)
        _done(conn, uid, asked_at, url, now)
        out.append((uid, f"ok {len(body)} B {ext}"))
    return out


def _done(conn: sqlite3.Connection, uid: int, asked_at: str, url: Optional[str], now: datetime) -> None:
    conn.execute("UPDATE users SET avatar_src=?, avatar_at=? WHERE id=?",
                 (url, _iso(now) if url else None, uid))
    # заявку могли перезаписать, пока качали, — тогда её не трогаем
    conn.execute("DELETE FROM avatar_queue WHERE user_id=? AND asked_at=?", (uid, asked_at))


def curl_fetch(proxy: str, timeout: float = 15.0) -> tuple[Fetch, Callable[[], Awaitable[None]]]:
    """fetch через curl_cffi и SOCKS-туннель хоста; читает тело не больше MAX_BYTES + 1."""
    from curl_cffi.requests import AsyncSession

    session: dict[str, Any] = {}

    async def fetch(url: str) -> tuple[int, dict[str, str], Optional[bytes]]:
        if "s" not in session:
            session["s"] = AsyncSession(proxies={"http": proxy, "https": proxy} if proxy else None)
        r = await session["s"].get(url, stream=True, allow_redirects=False, timeout=timeout,
                                   headers={"Accept": "image/jpeg,image/png;q=0.9"})
        try:
            headers = {k.lower(): v for k, v in r.headers.items()}
            body = None
            if r.status_code == 200:
                buf = bytearray()
                async for chunk in r.aiter_content():
                    buf.extend(chunk)
                    if len(buf) > MAX_BYTES:
                        break
                body = bytes(buf)
            return r.status_code, headers, body
        finally:
            await r.aclose()

    async def close() -> None:
        if "s" in session:
            await session["s"].close()

    return fetch, close
