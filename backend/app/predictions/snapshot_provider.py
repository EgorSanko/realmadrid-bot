"""Адаптер «снимки сборщика → MatchProvider» (контракт — provider.py).

Источник — DATA_DIR/rm.sqlite3 (app/store.py), который пишет только сборщик:
  `fixtures`     — календарь Реала: [{id, kickoff, tournament, home{id,name,score}, away{...}, status, is_home}]
  `match:<id>`   — снимок матча (app/model.py: status, home/away.score, events, lineups)
  `team`         — состав команды (squad: goalkeepers/defenders/midfielders/attackers)

Правила сборки матча:
  * статус и счёт — из более свежего из двух снимков (строка календаря / снимок матча);
    «завершён» назад не откатывается, даже если второй снимок старше и ещё «идёт»;
  * счёт — основное + дополнительное время, серия пенальти не считается: если в событиях есть удары
    серии (`shootout`) или статус говорит о пенальти, берём счёт последнего гола не из серии;
  * `first_rm_scorer_player_id` — автор первого по хронологии гола Реала, забитого игроком Реала.
    РЕШЕНИЕ ВЛАДЕЛЬЦА: автогол соперника бонусом не считается — такие голы пропускаем, первым
    становится следующий гол Реала. Если Реал забил только автоголами — None (бонус никому);
  * `rm_squad` — объявленный состав на матч (основа + запас), если он подтверждён; ожидаемый
    состав — первым, затем остальные из снимка команды; нет состава на матч — снимок команды.
    Травмированные и выбывшие на матч не предлагаются. Порядок: нападающие → полузащитники →
    защитники → вратари (сначала стартовый состав).

Нет календаря и снимка матча — ProviderUnavailable (API отвечает 503 «данные не подключены»).
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Optional

from .. import config, store
from ..model import ROLE_BY_POS, ts
from .provider import Match, ProviderUnavailable, rm_team_id

STATUS_MAP = {
    "scheduled": "scheduled", "live": "live", "halftime": "live", "finished": "finished",
    "postponed": "postponed", "cancelled": "cancelled",
    "abandoned": "cancelled",  # прерванный матч: очки аннулируются; переигровку источник даст заново
}
# незавершённый матч, чьё время начала прошло больше 4 ч назад, а статус не обновился, — не «ближайший»
STALE_UPCOMING_S = 4 * 3600
_PEN_LABELS = {"PEN", "PENS", "AP", "FT_PEN", "AET+P", "P"}
_ROLE_ORDER = {"FW": 0, "MF": 1, "DF": 2, "GK": 3}
_LINE_ROLE = {"attackers": "FW", "midfielders": "MF", "defenders": "DF", "goalkeepers": "GK"}
_CACHE_MAX = 64


def _pos_id(v: Any) -> Optional[int]:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _role(pos: Any) -> Optional[str]:
    if not pos:
        return None
    first = str(pos).split(",")[0].strip().upper()
    return first if first in _ROLE_ORDER else ROLE_BY_POS.get(first)


def map_status(state: Optional[str]) -> str:
    return STATUS_MAP.get(state or "scheduled", "scheduled")


def regular_score(home: Any, away: Any, events: list, label: Optional[str]) -> Optional[dict]:
    """Счёт без серии пенальти. None — счёта нет."""
    if home is None or away is None:
        return None
    goals = [e for e in events or [] if e.get("type") == "goal"]
    shootout = any(e.get("shootout") for e in goals)
    pens = str(label or "").strip().upper() in _PEN_LABELS
    if shootout or pens:
        regular = [e for e in goals if not e.get("shootout")]
        sc = regular[-1].get("score") if regular else [0, 0]
        if isinstance(sc, list) and len(sc) == 2 and all(isinstance(x, int) for x in sc):
            return {"home": sc[0], "away": sc[1]}
    return {"home": int(home), "away": int(away)}


def first_rm_scorer(events: list, rm_side: str) -> Optional[int]:
    """Первый по времени гол Реала, забитый игроком Реала (автоголы соперника пропускаем — решение владельца)."""
    goals = [e for e in events or [] if e.get("type") == "goal" and not e.get("shootout")]
    goals.sort(key=lambda e: (e.get("minute") or 0, e.get("added") or 0))  # sort стабильный: порядок источника
    for e in goals:
        if e.get("side") != rm_side or e.get("own_goal"):
            continue
        return _pos_id((e.get("player") or {}).get("id"))  # нет id игрока — автор неизвестен, бонуса нет
    return None


class SnapshotProvider:
    def __init__(self, db_path: Optional[str] = None, clock: Callable[[], float] = time.time):
        self.db_path = db_path          # None — config.DB_PATH на момент вызова (тесты подменяют config)
        self.clock = clock
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    # ---------- чтение снимков (кэш по fetched_at: JSON календаря не разбираем на каждый запрос) ----------

    def _conn(self):
        return store.connect(self.db_path or config.DB_PATH)

    def _get(self, conn, key: str) -> Optional[tuple[float, Any]]:
        row = conn.execute("SELECT fetched_at FROM snapshots WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] == row[0]:
                return hit
        row = conn.execute("SELECT fetched_at, data FROM snapshots WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        val = (row[0], json.loads(row[1]))
        with self._lock:
            if len(self._cache) >= _CACHE_MAX:
                self._cache.clear()
            self._cache[key] = val
        return val

    def _fixtures(self, conn) -> Optional[tuple[float, list]]:
        return self._get(conn, "fixtures")

    # ---------- сборка матча ----------

    def _build(self, conn, f: Optional[dict], f_at: float, mid: str) -> Optional[Match]:
        ms = self._get(conn, f"match:{mid}")
        m, m_at = (ms[1], ms[0]) if ms else (None, 0.0)
        base = f or m
        if base is None:
            return None
        rid = rm_team_id()
        home, away = base.get("home") or {}, base.get("away") or {}
        if f is not None and f.get("is_home") is not None:
            rm_home = bool(f["is_home"])
        else:
            rm_home = str(home.get("id")) == rid or (str(away.get("id")) != rid and
                                                     "real madrid" not in str(away.get("name", "")).lower())
        rm_side = "home" if rm_home else "away"

        # статус/счёт — из более свежего снимка; «завершён» не откатываем
        src = base
        if m is not None and f is not None:
            m_fin, f_fin = (m.get("status") or {}).get("finished"), (f.get("status") or {}).get("finished")
            if m_fin != f_fin:
                src = m if m_fin else f
            else:
                src = m if m_at >= f_at else f
        st = src.get("status") or {}
        status = map_status(st.get("state"))
        kickoff = (src.get("kickoff") or (f or {}).get("kickoff") or (m or {}).get("kickoff"))
        if not kickoff:
            return None
        events = (m or {}).get("events") or []
        score = None
        if status in ("live", "finished"):
            score = regular_score((src.get("home") or {}).get("score"), (src.get("away") or {}).get("score"),
                                  events, st.get("label"))
        scorer = first_rm_scorer(events, rm_side) if status in ("live", "finished") else None
        tour = base.get("tournament") or {}
        return {
            "id": str(mid),
            "kickoff_utc": kickoff,
            "home": {"id": home.get("id"), "name": home.get("name") or ""},
            "away": {"id": away.get("id"), "name": away.get("name") or ""},
            "rm_is_home": rm_home,
            "status": status,
            "score": score,
            "first_rm_scorer_player_id": scorer,
            "rm_squad": self._squad(conn, m, rm_side),
            "tournament": {"id": tour.get("id"), "name": tour.get("name")} if tour else None,
        }

    def _squad(self, conn, m: Optional[dict], rm_side: str) -> list[dict]:
        out: list[dict] = []
        seen: set[int] = set()

        def add(p: dict, role: Optional[str], starter: bool) -> None:
            pid = _pos_id(p.get("id"))
            if pid is None or pid in seen:
                return
            seen.add(pid)
            out.append({"id": pid, "name": p.get("name") or "", "position": role,
                        "number": p.get("number"), "starter": starter})

        def by_role(ps: list, role_of: Callable[[dict], Optional[str]]) -> list:
            return sorted(ps, key=lambda p: _ROLE_ORDER.get(role_of(p) or "", 4))  # стабильно: порядок источника

        out_ids: set[int] = set()
        lu = (m or {}).get("lineups") or {}
        t = lu.get(rm_side) or {}
        if t and str(t.get("team_id") or rm_team_id()) == rm_team_id():
            out_ids = {i for i in (_pos_id(p.get("id")) for p in t.get("unavailable") or []) if i}
            for p in by_role(t.get("starters") or [], lambda p: _role(p.get("position"))):
                add(p, _role(p.get("position")), True)
            for p in by_role(t.get("subs") or [], lambda p: _role(p.get("position"))):
                add(p, _role(p.get("position")), False)
            if lu.get("confirmed") and t.get("starters") and t.get("subs"):
                return out  # объявлен полный состав на матч — выбираем только из него
        team = self._get(conn, "team")
        squad = ((team[1] if team else {}) or {}).get("squad") or {}
        rest = [(p, _LINE_ROLE.get(line)) for line, ps in squad.items() for p in ps or []]
        rest.sort(key=lambda x: _ROLE_ORDER.get(x[1] or "", 4))
        for p, role in rest:
            if p.get("injured") or _pos_id(p.get("id")) in out_ids:
                continue
            add(p, role, False)
        return out

    # ---------- MatchProvider ----------

    def get_match(self, match_id: str) -> Optional[Match]:
        mid = str(match_id)
        conn = self._conn()
        try:
            fx = self._fixtures(conn)
            f = next((x for x in (fx[1] if fx else []) if str(x.get("id")) == mid), None)
            if f is None and fx is None and self._get(conn, f"match:{mid}") is None:
                raise ProviderUnavailable("нет календаря")
            return self._build(conn, f, fx[0] if fx else 0.0, mid)
        finally:
            conn.close()

    def _pick(self, limit: int, newest_first: bool, row_ok: Callable[[dict], bool],
              keep: Callable[[Match], bool]) -> list[Match]:
        """Матчи календаря по времени начала; собираем (с чтением снимка матча) только пока не набрали limit."""
        conn = self._conn()
        try:
            fx = self._fixtures(conn)
            if fx is None:
                raise ProviderUnavailable("нет календаря")
            rows = [f for f in fx[1] if f.get("id") not in (None, "") and ts(f.get("kickoff")) and row_ok(f)]
            rows.sort(key=lambda f: ts(f["kickoff"]) or 0, reverse=newest_first)
            out: list[Match] = []
            for f in rows:
                if len(out) >= limit:
                    break
                mt = self._build(conn, f, fx[0], str(f["id"]))
                if mt is not None and keep(mt):
                    out.append(mt)
            return out
        finally:
            conn.close()

    def upcoming(self, limit: int) -> list[Match]:
        edge = self.clock() - STALE_UPCOMING_S
        # строка календаря «завершён» уже не станет ближайшим матчем — снимок матча не читаем
        return self._pick(limit, False, lambda f: not (f.get("status") or {}).get("finished"),
                          lambda m: m["status"] == "live" or (
            m["status"] in ("scheduled", "postponed") and (ts(m["kickoff_utc"]) or 0) > edge))

    def recent(self, limit: int) -> list[Match]:
        now = self.clock()
        return self._pick(limit, True, lambda f: (ts(f["kickoff"]) or 0) <= now,
                          lambda m: m["status"] == "finished")
