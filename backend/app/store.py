"""Хранилище снимков: SQLite в DATA_DIR (том /opt/rm-v2/data).

Пишет только сборщик, API только читает. Каждая запись — одна транзакция
(INSERT OR REPLACE), поэтому читатель видит либо старый, либо новый снимок целиком.
Режим WAL: чтение не блокирует запись и наоборот, в т.ч. из разных контейнеров
на одном томе.
"""
import json
import os
import sqlite3
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    key        TEXT PRIMARY KEY,   -- fixtures | tables | team | match:<fotmobId> | match:sofascore:<id>
    source     TEXT NOT NULL,      -- откуда взят снимок
    fetched_at REAL NOT NULL,      -- unix-время успешного получения
    data       TEXT NOT NULL       -- нормализованный JSON
);
CREATE TABLE IF NOT EXISTS idmap (
    kind      TEXT NOT NULL,       -- match | team | player
    source    TEXT NOT NULL,       -- sofascore | espn | livescore
    source_id TEXT NOT NULL,
    fotmob_id TEXT NOT NULL,       -- канонический id
    note      TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (kind, source, source_id)
);
CREATE INDEX IF NOT EXISTS idmap_by_fotmob ON idmap(kind, fotmob_id, source);
CREATE TABLE IF NOT EXISTS source_state (
    name       TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS demand (       -- API просит сборщика подтянуть матч, которого нет в снимках
    match_id   TEXT PRIMARY KEY,
    asked_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS player_demand (  -- то же для карточки игрока (чужие игроки, устаревший кэш)
    player_id  TEXT PRIMARY KEY,
    asked_at   REAL NOT NULL
);
"""

PLAYER_DEMAND_CAP = 200  # больше заявок в очереди не копим — защита от перебора id


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)  # autocommit; транзакции явно
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    return conn


# ---------- снимки ----------

def put(conn: sqlite3.Connection, key: str, source: str, data, fetched_at: float | None = None) -> None:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    conn.execute(
        "INSERT OR REPLACE INTO snapshots(key, source, fetched_at, data) VALUES (?,?,?,?)",
        (key, source, fetched_at or time.time(), body),
    )


def get(conn: sqlite3.Connection, key: str) -> dict | None:
    row = conn.execute("SELECT source, fetched_at, data FROM snapshots WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    return {"source": row[0], "fetched_at": row[1], "data": json.loads(row[2])}


def ages(conn: sqlite3.Connection) -> dict:
    now = time.time()
    return {k: {"source": s, "age_s": round(now - t, 1)}
            for k, s, t in conn.execute("SELECT key, source, fetched_at FROM snapshots ORDER BY key")}


# ---------- соответствие id ----------

def map_set(conn, kind: str, source: str, source_id, fotmob_id, note: str | None = None) -> None:
    if source_id in (None, "") or fotmob_id in (None, ""):
        return
    conn.execute(
        "INSERT OR REPLACE INTO idmap(kind, source, source_id, fotmob_id, note, updated_at) VALUES (?,?,?,?,?,?)",
        (kind, source, str(source_id), str(fotmob_id), note, time.time()),
    )


def to_fotmob(conn, kind: str, source: str, source_id) -> str | None:
    row = conn.execute("SELECT fotmob_id FROM idmap WHERE kind=? AND source=? AND source_id=?",
                       (kind, source, str(source_id))).fetchone()
    return row[0] if row else None


def from_fotmob(conn, kind: str, source: str, fotmob_id) -> str | None:
    row = conn.execute(
        "SELECT source_id FROM idmap WHERE kind=? AND source=? AND fotmob_id=? ORDER BY updated_at DESC LIMIT 1",
        (kind, source, str(fotmob_id))).fetchone()
    return row[0] if row else None


def map_all(conn, kind: str, source: str) -> dict[str, str]:
    return {s: f for s, f in conn.execute(
        "SELECT source_id, fotmob_id FROM idmap WHERE kind=? AND source=?", (kind, source))}


def map_count(conn) -> dict:
    return {f"{k}/{s}": n for k, s, n in conn.execute(
        "SELECT kind, source, COUNT(*) FROM idmap GROUP BY kind, source")}


# ---------- состояние источников ----------

def put_source_state(conn, name: str, data: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO source_state(name, data, updated_at) VALUES (?,?,?)",
                 (name, json.dumps(data), time.time()))


def source_states(conn) -> dict:
    return {n: {**json.loads(d), "state_written_age_s": round(time.time() - u, 1)}
            for n, d, u in conn.execute("SELECT name, data, updated_at FROM source_state")}


# ---------- заявки API → сборщик ----------

def ask(conn, match_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO demand(match_id, asked_at) VALUES (?,?)", (str(match_id), time.time()))


def take_demand(conn, limit: int = 1) -> list[str]:
    rows = [r[0] for r in conn.execute("SELECT match_id FROM demand ORDER BY asked_at LIMIT ?", (limit,))]
    for r in rows:
        conn.execute("DELETE FROM demand WHERE match_id=?", (r,))
    return rows


def ask_player(conn, player_id) -> bool:
    """Заявка на игрока. False — очередь переполнена (заявку не приняли)."""
    n = conn.execute("SELECT COUNT(*) FROM player_demand").fetchone()[0]
    if n >= PLAYER_DEMAND_CAP:
        return bool(conn.execute("SELECT 1 FROM player_demand WHERE player_id=?", (str(player_id),)).fetchone())
    conn.execute("INSERT OR IGNORE INTO player_demand(player_id, asked_at) VALUES (?,?)",
                 (str(player_id), time.time()))
    return True


def peek_player_demand(conn, limit: int = 1) -> list[str]:
    return [r[0] for r in conn.execute("SELECT player_id FROM player_demand ORDER BY asked_at LIMIT ?", (limit,))]


def drop_player_demand(conn, player_id) -> None:
    conn.execute("DELETE FROM player_demand WHERE player_id=?", (str(player_id),))
