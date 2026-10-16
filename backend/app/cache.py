"""TTL-кэш со stale-фолбэком и сохранением на диск.

Источник упал → отдаём последнее известное значение (а не 500).
Метка времени записи НЕ обновляется при отдаче stale — иначе после
восстановления источника мы бы продолжали считать старые данные свежими.
"""
import asyncio
import json
import logging
import os
import time
from typing import Any, Awaitable, Callable

log = logging.getLogger("cache")

_DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
_PERSIST_PATH = os.path.join(_DATA_DIR, "cache.json")

_store: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}
_dirty = False


def load() -> None:
    try:
        with open(_PERSIST_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        for k, (ts, val) in raw.items():
            _store[k] = (ts, val)
        log.info("cache: восстановлено %d записей с диска", len(raw))
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("cache: не удалось прочитать %s: %s", _PERSIST_PATH, e)


def save() -> None:
    global _dirty
    if not _dirty:
        return
    os.makedirs(_DATA_DIR, exist_ok=True)
    tmp = _PERSIST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_store, f, ensure_ascii=False)
    os.replace(tmp, _PERSIST_PATH)
    _dirty = False


def age(key: str) -> float | None:
    entry = _store.get(key)
    return None if entry is None else time.time() - entry[0]


async def cached(key: str, ttl: float, fetch: Callable[[], Awaitable[Any]]) -> Any:
    """Свежее значение из кэша, иначе fetch(); при ошибке fetch — stale, если есть."""
    global _dirty
    entry = _store.get(key)
    if entry and time.time() - entry[0] < ttl:
        return entry[1]

    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        # пока ждали лок, значение мог обновить параллельный запрос
        entry = _store.get(key)
        if entry and time.time() - entry[0] < ttl:
            return entry[1]
        try:
            val = await fetch()
        except Exception as e:
            if entry is not None:
                log.warning("cache: %s — источник упал (%s), отдаю stale возрастом %.0fс",
                            key, e, time.time() - entry[0])
                return entry[1]
            raise
        _store[key] = (time.time(), val)
        _dirty = True
        return val
