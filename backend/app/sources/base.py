"""Источник данных: HTTP-клиент + circuit breaker + счётчики запросов.

Состояния breaker:
  closed    — работаем;
  open      — после BREAKER_THRESHOLD ошибок подряд пауза (60 с, дальше ×2, до 15 мин);
  half_open — пауза истекла, пропускаем один пробный запрос: успех → closed, ошибка → open.
404 источника — это «нет такого ресурса», а не поломка: breaker не трогает.
"""
import logging
import time
from collections import deque

import httpx

from .. import config

log = logging.getLogger("source")


class SourceError(Exception):
    pass


class SourceDisabled(SourceError):
    pass


class CircuitOpen(SourceError):
    pass


class NotFound(SourceError):
    pass


class Source:
    name = "base"
    timeout = config.HTTP_TIMEOUT

    def __init__(self):
        self.requests = 0          # всего HTTP-запросов (вкл. неудачные)
        self.ok = 0
        self.errors = 0
        self.not_found = 0
        self.skipped_open = 0      # сколько раз не пошли в источник из-за breaker
        self.skipped_disabled = 0
        self.consecutive_failures = 0
        self.trips = 0             # сколько раз размыкался
        self.state = "closed"
        self.open_until = 0.0
        self.last_ok = None
        self.last_error = None
        self.last_error_msg = None
        self.last_latency_ms = None
        self.by_kind: dict[str, int] = {}
        self._recent = deque()     # время запросов за последний час

    # --- breaker ---
    def disabled(self) -> bool:
        return self.name in config.disabled_sources()

    def available(self) -> bool:
        if self.disabled():
            return False
        if self.state == "open" and time.time() < self.open_until:
            return False
        return True

    def _check(self):
        if self.disabled():
            self.skipped_disabled += 1
            raise SourceDisabled(f"{self.name}: выключен флагом")
        if self.state == "open":
            if time.time() < self.open_until:
                self.skipped_open += 1
                raise CircuitOpen(f"{self.name}: breaker open ещё {self.open_until - time.time():.0f} с")
            self.state = "half_open"

    def _success(self):
        self.ok += 1
        self.consecutive_failures = 0
        self.last_ok = time.time()
        if self.state != "closed":
            log.info("%s: breaker closed", self.name)
        self.state = "closed"

    def _failure(self, err: Exception):
        self.errors += 1
        self.consecutive_failures += 1
        self.last_error = time.time()
        self.last_error_msg = f"{type(err).__name__}: {err}"[:300]
        if self.state == "half_open" or self.consecutive_failures >= config.BREAKER_THRESHOLD:
            cooldown = min(config.BREAKER_COOLDOWN * (2 ** self.trips), config.BREAKER_MAX_COOLDOWN)
            self.trips += 1
            self.state = "open"
            self.open_until = time.time() + cooldown
            log.warning("%s: breaker OPEN на %d с (%s)", self.name, cooldown, self.last_error_msg)

    # --- запрос ---
    async def get(self, url: str, params: dict | None = None, kind: str = "other"):
        self._check()
        now = time.time()
        self.requests += 1
        self.by_kind[kind] = self.by_kind.get(kind, 0) + 1
        self._recent.append(now)
        while self._recent and self._recent[0] < now - 3600:
            self._recent.popleft()
        t0 = time.monotonic()
        try:
            data = await self._fetch(url, params)
        except NotFound:
            self.not_found += 1
            self._success()
            raise
        except Exception as e:  # сеть, таймаут, 4xx/5xx, не-JSON
            self._failure(e)
            raise SourceError(f"{self.name}: {type(e).__name__}: {e}") from e
        finally:
            self.last_latency_ms = round((time.monotonic() - t0) * 1000)
        self._success()
        return data

    async def _fetch(self, url: str, params: dict | None):
        raise NotImplementedError

    async def close(self):
        pass

    def snapshot(self) -> dict:
        now = time.time()
        last_min = sum(1 for t in self._recent if t > now - 60)
        return {
            "name": self.name,
            "disabled": self.disabled(),
            "breaker": "open" if self.state == "open" and now < self.open_until else self.state,
            "open_for_s": round(self.open_until - now) if self.state == "open" and now < self.open_until else 0,
            "trips": self.trips,
            "requests": self.requests, "ok": self.ok, "errors": self.errors, "not_found": self.not_found,
            "skipped_breaker": self.skipped_open, "skipped_disabled": self.skipped_disabled,
            "consecutive_failures": self.consecutive_failures,
            "requests_last_min": last_min, "requests_last_hour": len(self._recent),
            "by_kind": dict(self.by_kind),
            "last_ok": self.last_ok, "last_ok_age_s": round(now - self.last_ok, 1) if self.last_ok else None,
            "last_error": self.last_error, "last_error_msg": self.last_error_msg,
            "last_latency_ms": self.last_latency_ms,
        }


class HttpxSource(Source):
    """Обычный HTTPS с User-Agent (FotMob, ESPN, LiveScore)."""

    def __init__(self):
        super().__init__()
        self.client = httpx.AsyncClient(
            headers={"User-Agent": config.UA, "Accept": "application/json", "Accept-Language": "en"},
            timeout=httpx.Timeout(self.timeout, connect=5.0),
            follow_redirects=True,
        )

    async def _fetch(self, url, params):
        r = await self.client.get(url, params=params)
        if r.status_code == 404:
            raise NotFound(f"404 {url}")
        r.raise_for_status()
        return r.json()

    async def close(self):
        await self.client.aclose()
