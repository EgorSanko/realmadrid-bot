"""Откуда прогнозы берут данные о матчах — протокол, а не реализация.

Матч — словарь:
    {
      "id": str | int,
      "kickoff_utc": "2026-10-18T20:00:00Z" | datetime (aware, UTC),
      "home": {"id": ..., "name": str},
      "away": {"id": ..., "name": str},
      "status": "scheduled" | "live" | "finished" | "cancelled" | "postponed",
      "score": {"home": int, "away": int} | None,   # основное + дополнительное время, без серии пенальти
      "first_rm_scorer_player_id": str | int | None, # автор первого гола Реала (None, если Реал не забил)
      "rm_squad": [{"id": ..., "name": str}, ...],    # из кого можно выбрать первого бомбардира
      # необязательно: "rm_is_home": bool — если нет, сторона Реала ищется по RM_TEAM_ID
    }

Перенос со сменой даты — это тот же матч (тот же id) с новым `kickoff_utc`
и статусом `scheduled` (или `postponed`, пока новой даты нет).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

STATUSES = ("scheduled", "live", "finished", "cancelled", "postponed")

Match = dict[str, Any]


@runtime_checkable
class MatchProvider(Protocol):
    def get_match(self, match_id: str) -> Optional[Match]:
        """Матч по id или None, если такого нет."""

    def upcoming(self, limit: int) -> list[Match]:
        """Ближайшие матчи Реала (не завершённые), по возрастанию времени начала."""

    def recent(self, limit: int) -> list[Match]:
        """Последние сыгранные матчи Реала, от новых к старым."""


def rm_team_id() -> str:
    # канонический id Реала — FotMob (см. app/config.py: TEAM_ID)
    return os.environ.get("RM_TEAM_ID", "8633").strip()


def parse_kickoff(v: Any) -> datetime:
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, (int, float)):
        dt = datetime.fromtimestamp(v, timezone.utc)
    else:
        s = str(v).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rm_is_home(m: Match) -> bool:
    if "rm_is_home" in m and m["rm_is_home"] is not None:
        return bool(m["rm_is_home"])
    rid = rm_team_id()
    if str((m.get("home") or {}).get("id")) == rid:
        return True
    if str((m.get("away") or {}).get("id")) == rid:
        return False
    # не нашли — по имени, иначе считаем, что Реал дома
    return "real madrid" not in str((m.get("away") or {}).get("name", "")).lower()


class FakeProvider:
    """Провайдер в памяти — для тестов и локальной отладки."""

    def __init__(self, matches: Optional[list[Match]] = None):
        self.matches: dict[str, Match] = {}
        for m in matches or []:
            self.put(m)

    def put(self, m: Match) -> Match:
        m = dict(m)
        m["id"] = str(m["id"])
        m.setdefault("status", "scheduled")
        m.setdefault("score", None)
        m.setdefault("first_rm_scorer_player_id", None)
        m.setdefault("rm_squad", [])
        self.matches[m["id"]] = m
        return m

    def update(self, match_id: str, **fields: Any) -> Match:
        m = dict(self.matches[str(match_id)])
        m.update(fields)
        return self.put(m)

    def get_match(self, match_id: str) -> Optional[Match]:
        m = self.matches.get(str(match_id))
        return dict(m) if m else None

    def upcoming(self, limit: int) -> list[Match]:
        ms = [m for m in self.matches.values() if m["status"] in ("scheduled", "live", "postponed")]
        ms.sort(key=lambda m: parse_kickoff(m["kickoff_utc"]))
        return [dict(m) for m in ms[:limit]]

    def recent(self, limit: int) -> list[Match]:
        ms = [m for m in self.matches.values() if m["status"] == "finished"]
        ms.sort(key=lambda m: parse_kickoff(m["kickoff_utc"]), reverse=True)
        return [dict(m) for m in ms[:limit]]
