"""Настройки слоя данных. Всё, что зависит от окружения, — только здесь."""
import os

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
DB_PATH = os.path.join(DATA_DIR, "rm.sqlite3")
# файл-флаг блокировки источников (по одному имени в строке или через запятую);
# читается сборщиком на каждом такте, перезапуск не нужен
DISABLED_FILE = os.path.join(DATA_DIR, "disabled_sources")
HEARTBEAT_FILE = os.path.join(DATA_DIR, "collector.heartbeat")

# --- Реал в разных источниках (канонические id — FotMob) ---
TEAM_ID = 8633
SOFA_TEAM_ID = 2829
ESPN_TEAM_ID = "86"

# 4 турнира сезона: FotMob id → id/слаги в других источниках
LEAGUES = {
    87: {"name": "LaLiga", "sofa": 8, "espn": "esp.1"},
    42: {"name": "Champions League", "sofa": 7, "espn": "uefa.champions"},
    138: {"name": "Copa del Rey", "sofa": 329, "espn": "esp.copa_del_rey"},
    139: {"name": "Super Cup", "sofa": 213, "espn": "esp.super_cup"},
}
SOFA_TO_FM_LEAGUE = {v["sofa"]: k for k, v in LEAGUES.items()}
ESPN_TO_FM_LEAGUE = {v["espn"]: k for k, v in LEAGUES.items()}
TABLE_LEAGUES = (87, 42)  # таблицы: Ла Лига и ЛЧ

SOURCE_ORDER = ("fotmob", "sofascore", "espn", "livescore")

SOFA_PROXY = os.environ.get("SOFA_PROXY", "socks5h://127.0.0.1:1080")
# t.me / CDN Telegram (аватары) с сервера в России напрямую не открываются — тот же туннель
TG_PROXY = os.environ.get("TG_PROXY", SOFA_PROXY)
UA = os.environ.get(
    "HTTP_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# --- расписание (секунды) ---
TEAM_INTERVAL = _int("TEAM_INTERVAL", 720)          # команда/календарь/таблицы: 12 мин
LIVE_INTERVAL = _int("LIVE_INTERVAL", 12)           # детали матча в окне: 12 с
IDLE_MATCH_INTERVAL = _int("IDLE_MATCH_INTERVAL", 1800)  # последний/следующий вне окна: 30 мин
MAPPING_INTERVAL = _int("MAPPING_INTERVAL", 6 * 3600)    # сопоставление id с другими источниками
NEWS_INTERVAL = _int("NEWS_INTERVAL", 600)          # новости (RSS): 10 мин
VIDEO_INTERVAL = _int("VIDEO_INTERVAL", 900)        # видео YouTube (RSS канала): 15 мин
NEWS_OG_PER_CYCLE = _int("NEWS_OG_PER_CYCLE", 6)    # сколько страниц Sports.ru открыть за цикл ради картинки
# карточки игроков: свои — заранее раз в 6 ч, чужие — по заявке API, кэш 24 ч
PLAYER_INTERVAL = _int("PLAYER_INTERVAL", 6 * 3600)
PLAYER_FOREIGN_TTL = _int("PLAYER_FOREIGN_TTL", 24 * 3600)
PLAYER_RATE_PER_MIN = _int("PLAYER_RATE_PER_MIN", 10)   # не больше N игроков в минуту (все источники вместе)
AVATAR_INTERVAL = _int("AVATAR_INTERVAL", 5)            # как часто смотреть очередь аватаров
PLAYER_FAIL_RETRY = _int("PLAYER_FAIL_RETRY", 600)      # не нашли / все упали — повтор не раньше чем через 10 мин
WINDOW_BEFORE = 75 * 60        # окно матча открывается за 75 мин до начала
WINDOW_AFTER_START = 150 * 60  # ~2,5 ч после старта, если «завершён» ещё не видели
WINDOW_AFTER_FINISH = 30 * 60  # после «завершён» — ещё 30 мин на добор оценок и статистики
WINDOW_HARD_CAP = 4 * 3600     # предохранитель: дольше 4 ч от старта не держим лайв-режим

# --- надёжность источников ---
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "10"))
SOFA_TIMEOUT = float(os.environ.get("SOFA_TIMEOUT", "15"))
BREAKER_THRESHOLD = _int("BREAKER_THRESHOLD", 3)   # подряд ошибок до размыкания
BREAKER_COOLDOWN = _int("BREAKER_COOLDOWN", 60)    # первая пауза, дальше удваивается
BREAKER_MAX_COOLDOWN = _int("BREAKER_MAX_COOLDOWN", 900)

# отладка лайва на любом матче: id FotMob через запятую — сборщик считает их «в окне»
DEBUG_LIVE_MATCHES = [int(x) for x in os.environ.get("DEBUG_LIVE_MATCH", "").replace(" ", "").split(",") if x.isdigit()]


def disabled_sources() -> set[str]:
    """Источники, выключенные переменной DISABLED_SOURCES или файлом-флагом."""
    names = set(filter(None, os.environ.get("DISABLED_SOURCES", "").replace(" ", "").lower().split(",")))
    try:
        with open(DISABLED_FILE, encoding="utf-8") as f:
            names |= set(filter(None, f.read().replace(",", "\n").lower().split()))
    except OSError:
        pass
    return names
