"""SQLite прогнозов: DATA_DIR/predictions.db, WAL, внешние ключи, миграции по PRAGMA user_version.

Новая миграция — новый элемент в конце MIGRATIONS; старые не править.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE users (
        id          INTEGER PRIMARY KEY,              -- Telegram user id
        first_name  TEXT NOT NULL DEFAULT '',
        last_name   TEXT,
        username    TEXT,
        photo_url   TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );

    -- локальная копия матча из MatchProvider: нужна для FK, периодов рейтинга и идемпотентного расчёта
    CREATE TABLE matches (
        id            TEXT PRIMARY KEY,
        kickoff_utc   TEXT NOT NULL,
        home_id       TEXT,
        home_name     TEXT NOT NULL DEFAULT '',
        away_id       TEXT,
        away_name     TEXT NOT NULL DEFAULT '',
        rm_is_home    INTEGER NOT NULL CHECK (rm_is_home IN (0, 1)),
        status        TEXT NOT NULL CHECK (status IN ('scheduled','live','finished','cancelled','postponed')),
        score_home    INTEGER,
        score_away    INTEGER,
        first_scorer  TEXT,
        season        INTEGER NOT NULL,               -- год начала сезона (июль–июнь, МСК)
        month         TEXT NOT NULL,                  -- 'YYYY-MM' по МСК
        settled_sig   TEXT,                           -- результат, по которому начислены очки
        settled_at    TEXT,
        updated_at    TEXT NOT NULL
    );
    CREATE INDEX matches_season ON matches(season);
    CREATE INDEX matches_month ON matches(month);
    CREATE INDEX matches_kickoff ON matches(kickoff_utc);

    CREATE TABLE predictions (
        id            INTEGER PRIMARY KEY,
        user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        match_id      TEXT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
        home          INTEGER NOT NULL CHECK (home BETWEEN 0 AND 20),
        away          INTEGER NOT NULL CHECK (away BETWEEN 0 AND 20),
        first_scorer  TEXT,
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL,                  -- время последнего изменения
        revisions     INTEGER NOT NULL DEFAULT 1,
        points        INTEGER,                        -- NULL — не рассчитан / матч не состоялся
        points_score  INTEGER,
        points_scorer INTEGER,
        exact         INTEGER,
        settled_at    TEXT,
        UNIQUE (user_id, match_id)
    );
    CREATE INDEX predictions_match ON predictions(match_id);

    -- материализованный рейтинг: period = 'S2026' (сезон 2026/27) или 'M2026-10'
    CREATE TABLE standings (
        period        TEXT NOT NULL,
        user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        points        INTEGER NOT NULL,
        exact         INTEGER NOT NULL,
        played        INTEGER NOT NULL,
        last_pred_at  TEXT NOT NULL,
        PRIMARY KEY (period, user_id)
    );
    CREATE INDEX standings_rank ON standings(period, points DESC, exact DESC, last_pred_at ASC, user_id ASC);

    CREATE TABLE leagues (
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 40),
        code        TEXT NOT NULL UNIQUE,
        owner_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE INDEX leagues_owner ON leagues(owner_id);

    CREATE TABLE league_members (
        league_id   INTEGER NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        joined_at   TEXT NOT NULL,
        PRIMARY KEY (league_id, user_id)
    );
    CREATE INDEX league_members_user ON league_members(user_id);

    -- аудит расчётов: первый расчёт, пересчёт после исправления результата, аннулирование
    CREATE TABLE settle_audit (
        id          INTEGER PRIMARY KEY,
        match_id    TEXT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
        at          TEXT NOT NULL,
        kind        TEXT NOT NULL CHECK (kind IN ('settle','resettle','void')),
        old_result  TEXT,
        new_result  TEXT,
        predictions INTEGER NOT NULL,
        changed     INTEGER NOT NULL
    );
    CREATE INDEX settle_audit_match ON settle_audit(match_id);
    """,
    # v2 — вход на сайте и аватары
    """
    -- «Выйти» увеличивает счётчик: все выданные раньше сессии пользователя недействительны
    ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0;
    -- photo_url, по которому скачан файл аватара, и когда (файл — DATA_DIR/avatars/{id}.jpg|png)
    ALTER TABLE users ADD COLUMN avatar_src TEXT;
    ALTER TABLE users ADD COLUMN avatar_at TEXT;

    -- заявки API → сборщик: скачать аватар через туннель (url NULL — удалить файл)
    CREATE TABLE avatar_queue (
        user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        url         TEXT,
        asked_at    TEXT NOT NULL,
        tries       INTEGER NOT NULL DEFAULT 0,
        next_at     TEXT NOT NULL
    );
    CREATE INDEX avatar_queue_next ON avatar_queue(next_at);
    """,
    # v3 — когда пользователь был в последний раз (вход, /me; пишется не чаще раза в сутки).
    # По нему сборщик удаляет аватары тех, кого нет больше AVATAR_TTL_DAYS
    """
    ALTER TABLE users ADD COLUMN seen_at TEXT;
    """,
    # v4 — мини-игры (викторина, пенальти): итоги партий вошедших пользователей.
    # Отдельный рейтинг: в standings и очки прогнозов не попадает никогда (app/games/service.py).
    """
    CREATE TABLE game_results (
        id          INTEGER PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        game        TEXT NOT NULL CHECK (game IN ('quiz', 'penalty')),
        level       TEXT NOT NULL,
        score       INTEGER NOT NULL CHECK (score >= 0),
        detail      TEXT NOT NULL DEFAULT '{}',          -- JSON: верных/голов, серия, счёт серии…
        week        TEXT NOT NULL,                       -- неделя по МСК, понедельник: 'YYYY-MM-DD'
        created_at  TEXT NOT NULL
    );
    CREATE INDEX game_results_week ON game_results(game, week, score DESC);
    CREATE INDEX game_results_user ON game_results(user_id, game, level, score DESC);
    """,
    # v5 — вход на сайте по коду через бота (app/login_codes.py, app/bot.py)
    """
    -- заявка на вход: сайт выдал код, бот вписывает того, кто его прислал; браузер забирает сессию
    CREATE TABLE login_codes (
        token        TEXT PRIMARY KEY,                 -- в deep link: /start login_<token>
        code         TEXT NOT NULL UNIQUE,             -- 6 цифр — ввести боту вручную
        nonce_hash   TEXT NOT NULL UNIQUE,             -- SHA-256 от nonce; сам nonce — только в cookie браузера
        ip           TEXT,
        created_at   TEXT NOT NULL,
        expires_at   TEXT NOT NULL,
        user_id      INTEGER,                          -- NULL — ещё не подтверждён
        first_name   TEXT,
        last_name    TEXT,
        username     TEXT,
        confirmed_at TEXT
    );
    CREATE INDEX login_codes_expires ON login_codes(expires_at);

    -- состояние бота: офсет getUpdates (после рестарта апдейты не теряются и не повторяются)
    CREATE TABLE bot_state (
        key    TEXT PRIMARY KEY,
        value  TEXT NOT NULL
    );
    """,
]

SCHEMA_VERSION = len(MIGRATIONS)

_mig_lock = threading.Lock()


def data_dir() -> Path:
    raw = os.environ.get("DATA_DIR", "").strip()
    return Path(raw) if raw else Path(__file__).resolve().parents[2] / "data"


def default_path() -> str:
    return str(data_dir() / "predictions.db")


def migrate(conn: sqlite3.Connection) -> int:
    """Доводит схему до SCHEMA_VERSION. Возвращает итоговую версию."""
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if ver > SCHEMA_VERSION:
        raise RuntimeError(f"predictions.db: схема v{ver} новее кода (v{SCHEMA_VERSION})")
    for i in range(ver, SCHEMA_VERSION):
        conn.execute("BEGIN IMMEDIATE")  # другой процесс мог мигрировать раньше — перечитываем под блокировкой
        try:
            if conn.execute("PRAGMA user_version").fetchone()[0] == i:
                for stmt in MIGRATIONS[i].split(";\n"):
                    if stmt.strip():
                        conn.execute(stmt)
                conn.execute(f"PRAGMA user_version = {i + 1}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return SCHEMA_VERSION


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or default_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    with _mig_lock:
        conn.execute("PRAGMA journal_mode = WAL")
        migrate(conn)
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn
