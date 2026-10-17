"""Суточная очистка (вызывает сборщик раз в CLEANUP_INTERVAL).

  * тексты статей старше ARTICLE_TEXT_TTL_DAYS (≈10 КБ на статью, копятся навсегда): из снимка
    `article:<aid>` убираем html и лид, сама новость остаётся — заголовок, источник, ссылка, дата,
    анонс и картинка. API отдаёт её как «текста нет» (full: false, reason: expired) со ссылкой на
    источник; заново текст не качаем. Старые `article_fail:*` — удаляем;
  * аватары пользователей, которых не было AVATAR_TTL_DAYS: файл удаляем, avatar_src/avatar_at
    сбрасываем — вернётся человек, при входе аватар скачается заново;
  * снимки карточек чужих игроков (не из состава Реала) старше FOREIGN_PLAYER_TTL_DAYS и старые
    `player_fail:*`. Свои игроки обновляются раз в 6 ч и сюда не попадают.
"""
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from . import avatars, config

log = logging.getLogger("cleanup")

# что остаётся от статьи после удаления текста
ARTICLE_KEEP = ("aid", "id", "url", "site", "source", "title", "published", "summary", "image", "author", "origin")


def _squad_ids(conn: sqlite3.Connection) -> set[str]:
    row = conn.execute("SELECT data FROM snapshots WHERE key='team'").fetchone()
    if not row:
        return set()
    d = json.loads(row[0])
    ids = {str(p["id"]) for line in (d.get("squad") or {}).values() for p in line if p.get("id")}
    if (d.get("coach") or {}).get("id"):
        ids.add(str(d["coach"]["id"]))
    return ids


def articles(conn: sqlite3.Connection, now: float | None = None) -> dict:
    now = now or time.time()
    cutoff = now - config.ARTICLE_TEXT_TTL_DAYS * 86400
    stripped = 0
    rows = conn.execute(
        "SELECT key, source, fetched_at, data FROM snapshots WHERE key LIKE 'article:%' AND fetched_at < ? "
        "AND json_extract(data, '$.text_removed') IS NULL", (cutoff,)).fetchall()
    with conn:
        for key, source, fetched_at, body in rows:
            d = json.loads(body)
            stub = {k: d.get(k) for k in ARTICLE_KEEP}
            stub.update(text_removed=True, words=d.get("words"), hero_in_text=False)
            conn.execute("UPDATE snapshots SET data=? WHERE key=?",
                         (json.dumps(stub, ensure_ascii=False, separators=(",", ":")), key))
            stripped += 1
        fails = conn.execute("DELETE FROM snapshots WHERE key LIKE 'article_fail:%' AND fetched_at < ?",
                             (cutoff,)).rowcount
    return {"article_texts": stripped, "article_fails": fails}


def foreign_players(conn: sqlite3.Connection, now: float | None = None) -> dict:
    now = now or time.time()
    cutoff = now - config.FOREIGN_PLAYER_TTL_DAYS * 86400
    own = _squad_ids(conn)
    drop = []
    for key, body in conn.execute(
            "SELECT key, data FROM snapshots WHERE key LIKE 'player:%' AND fetched_at < ?", (cutoff,)):
        pid = key.split(":", 1)[1]
        team = (json.loads(body).get("team") or {}).get("id")
        if pid in own or team == config.TEAM_ID:
            continue
        drop.append(key)
    with conn:
        for key in drop:
            conn.execute("DELETE FROM snapshots WHERE key=?", (key,))
        fails = conn.execute("DELETE FROM snapshots WHERE key LIKE 'player_fail:%' AND fetched_at < ?",
                             (cutoff,)).rowcount
    return {"foreign_players": len(drop), "player_fails": fails}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def stale_avatars(pconn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Пользователи, которых не было AVATAR_TTL_DAYS: «был» — seen_at (вход, /me), а у тех, кто заходил до
    появления seen_at, — самое позднее из avatar_at, updated_at, created_at."""
    now = now or datetime.now(timezone.utc)
    cutoff = _iso(now - timedelta(days=config.AVATAR_TTL_DAYS))
    stale = {uid for (uid,) in pconn.execute(
        "SELECT id FROM users WHERE COALESCE(seen_at, MAX(COALESCE(avatar_at, ''), updated_at, created_at)) < ?",
        (cutoff,))}
    n = 0
    for uid in stale:
        had = avatars.file_for(uid) is not None
        if had:
            avatars.remove(uid)
        pconn.execute("UPDATE users SET avatar_src=NULL, avatar_at=NULL WHERE id=? AND avatar_src IS NOT NULL", (uid,))
        n += had
    # файлы пользователей, которых в базе уже нет
    orphans = 0
    d = avatars.avatars_dir()
    if d.is_dir():
        known = {uid for (uid,) in pconn.execute("SELECT id FROM users")}
        for p in d.iterdir():
            if p.suffix in (".jpg", ".png") and p.stem.isdigit() and int(p.stem) not in known:
                p.unlink(missing_ok=True)
                orphans += 1
    return {"avatars": n, "avatar_orphans": orphans}


def run(conn: sqlite3.Connection, pconn: sqlite3.Connection | None, now: float | None = None) -> dict:
    now = now or time.time()
    res = {**articles(conn, now), **foreign_players(conn, now)}
    if pconn is not None:
        res.update(stale_avatars(pconn, datetime.fromtimestamp(now, timezone.utc)))
    return res
