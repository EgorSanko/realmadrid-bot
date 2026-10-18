"""Прогрев кэша эмблем: nginx берёт /img/team/<id>.png с FotMob при первом запросе и держит 30 дней.

Команда, которую ещё никто не открывал (низ таблицы ЛЧ, новый соперник), иначе грузится
у первого человека с задержкой FotMob. Сборщик после обновления таблиц и календаря сам
запрашивает эмблемы всех команд из снимков — через наш же сайт, чтобы картинка легла в кэш nginx.
"""
import asyncio
import json
import logging
import re

import httpx

from . import config, store

log = logging.getLogger("crests")

_LOGO = re.compile(r'"/img/team/(\d{1,10})\.png"')
SNAPSHOT_KEYS = ("tables", "fixtures")


def team_ids(conn) -> list[int]:
    """id команд, чьи эмблемы показывают таблицы и календарь (по путям logo в снимках)."""
    ids: set[int] = set()
    for key in SNAPSHOT_KEYS:
        snap = store.get(conn, key)
        if snap:
            ids.update(int(x) for x in _LOGO.findall(json.dumps(snap["data"], ensure_ascii=False)))
    return sorted(ids)


class CrestWarmer:
    """Помнит, что уже прогрето: повтор — раз в REWARM (кэш nginx живёт 30 дн.), неудача — через RETRY."""

    def __init__(self, base: str | None = None, fetch=None, concurrency: int = 4):
        self.base = (base or config.CREST_WARM_BASE).rstrip("/")
        self._fetch = fetch
        self._client: httpx.AsyncClient | None = None
        self.sem = asyncio.Semaphore(concurrency)
        self.done: dict[int, float] = {}    # id → когда прогрели
        self.failed: dict[int, float] = {}  # id → когда не вышло

    def due(self, ids, now: float) -> list[int]:
        return [i for i in ids
                if now - self.done.get(i, -1e18) >= config.CREST_REWARM
                and now - self.failed.get(i, -1e18) >= config.CREST_RETRY]

    async def _get(self, url: str) -> tuple[int, dict]:
        if self._fetch is not None:
            return await self._fetch(url)
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=config.HTTP_TIMEOUT, headers={"User-Agent": "rm-v2-collector"})
        r = await self._client.get(url)
        return r.status_code, r.headers

    async def _one(self, tid: int, now: float) -> bool:
        async with self.sem:
            try:
                status, headers = await self._get(f"{self.base}/img/team/{tid}.png")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("crest %s: %r", tid, e)
                status, headers = 0, {}
        # прозрачная заглушка (FotMob не отдал) — не «прогрето», попробуем позже
        ok = status == 200 and not headers.get("x-img-fallback")
        (self.done if ok else self.failed)[tid] = now
        if ok:
            self.failed.pop(tid, None)
        return ok

    async def warm(self, ids, now: float) -> dict:
        todo = self.due(ids, now)
        if not todo:
            return {"warmed": 0, "failed": 0}
        res = await asyncio.gather(*(self._one(t, now) for t in todo))
        return {"warmed": sum(res), "failed": len(res) - sum(res)}

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None
