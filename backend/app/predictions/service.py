"""Логика прогнозов: приём, расчёт очков, рейтинги, лиги. Без HTTP — его делает api.py.

Время — только через self.now() (серверные часы, подменяются в тестах).
Бот никому ничего не пишет: здесь нет и не должно быть никаких уведомлений.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterator, Optional

from .. import avatars
from . import db, rules
from .provider import Match, MatchProvider, ProviderUnavailable, parse_kickoff, rm_is_home

log = logging.getLogger("predictions")

MSK = timezone(timedelta(hours=3))  # Москва без перехода на летнее время с 2014 г.
OPEN_STATUSES = ("scheduled", "postponed")
VOID_STATUSES = ("cancelled", "postponed")
RESETTLE_WINDOW = timedelta(days=14)   # сколько после матча ещё ловим исправления результата

LEAGUE_NAME_MAX = 40
LEAGUE_CODE_LEN = 10
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 32 символа без 0/O/1/I: 10 знаков = 50 бит
MAX_OWNED_LEAGUES = 10
MAX_MEMBERSHIPS = 50

PREDICT_RATE = (30, 60.0)   # не больше 30 изменений прогноза в минуту
JOIN_RATE = (20, 60.0)      # попытки вступления по коду — против перебора
LOGIN_RATE = (30, 60.0)     # входов с одного IP в минуту (/api/auth/telegram)
CODE_RATE = (10, 600.0)     # кодов входа с одного IP за 10 мин (POST /api/auth/code)
CODE_POLL_RATE = (300, 60.0)  # опросов статуса кода с одного IP в минуту (браузер — 40/мин)


class PredictError(Exception):
    def __init__(self, status: int, error: str, message: str):
        super().__init__(message)
        self.status = status
        self.error = error
        self.message = message


# ---------- время и периоды ----------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """Фиксированная ширина с микросекундами — строки сортируются как время."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def iso_short(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(s: str) -> datetime:
    return parse_kickoff(s)


def season_of(dt: datetime) -> int:
    m = dt.astimezone(MSK)
    return m.year if m.month >= 7 else m.year - 1


def month_of(dt: datetime) -> str:
    return dt.astimezone(MSK).strftime("%Y-%m")


def period_info(period: str, now: datetime) -> dict[str, Any]:
    if period == "season":
        y = season_of(now)
        start = datetime(y, 7, 1, tzinfo=MSK)
        end = datetime(y + 1, 7, 1, tzinfo=MSK)
        return {"key": f"S{y}", "period": "season", "label": f"{y}/{(y + 1) % 100:02d}",
                "from": iso_short(start), "to": iso_short(end)}
    if period == "month":
        m = now.astimezone(MSK)
        start = datetime(m.year, m.month, 1, tzinfo=MSK)
        end = datetime(m.year + (m.month == 12), m.month % 12 + 1, 1, tzinfo=MSK)
        return {"key": f"M{m.year:04d}-{m.month:02d}", "period": "month", "label": f"{m.year:04d}-{m.month:02d}",
                "from": iso_short(start), "to": iso_short(end)}
    raise PredictError(422, "validation", "period: season или month")


# ---------- ограничение частоты ----------

class RateLimiter:
    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._hits: dict[Any, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: Any) -> bool:
        """True — можно; False — лимит исчерпан (попытка не засчитывается)."""
        now = self.clock()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._hits) > 100_000:  # не копим память на разовых пользователях
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
                    del self._hits[k]
            return True


# ---------- сервис ----------

def display_name(first: Optional[str], last: Optional[str], username: Optional[str]) -> str:
    first = (first or "").strip()
    last = (last or "").strip()
    if first and last:
        return f"{first} {last[0]}."
    return first or (f"@{username}" if username else "Болельщик")


def upsert_names(c: sqlite3.Connection, uid: int, first: Optional[str], last: Optional[str],
                 username: Optional[str], now: str) -> None:
    """Пользователь по имени и username, photo_url не трогаем (вход по коду, бот)."""
    c.execute(
        """INSERT INTO users(id, first_name, last_name, username, created_at, updated_at) VALUES (?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET first_name=excluded.first_name, last_name=excluded.last_name,
               username=excluded.username, updated_at=excluded.updated_at
           WHERE users.first_name IS NOT excluded.first_name OR users.last_name IS NOT excluded.last_name
              OR users.username IS NOT excluded.username""",
        (uid, (first or "")[:128], last, username, now, now))


class PredictionService:
    def __init__(self, provider: MatchProvider, db_path: Optional[str] = None,
                 clock: Callable[[], datetime] = utcnow, bot_username: Optional[str] = None,
                 rate_clock: Callable[[], float] = time.monotonic):
        self.provider = provider
        self.db_path = db_path
        self.clock = clock
        self._bot_username = bot_username
        self.predict_limiter = RateLimiter(*PREDICT_RATE, clock=rate_clock)
        self.join_limiter = RateLimiter(*JOIN_RATE, clock=rate_clock)
        self.login_limiter = RateLimiter(*LOGIN_RATE, clock=rate_clock)
        self.code_limiter = RateLimiter(*CODE_RATE, clock=rate_clock)
        self.code_poll_limiter = RateLimiter(*CODE_POLL_RATE, clock=rate_clock)

    # --- инфраструктура ---

    def now(self) -> datetime:
        return self.clock().astimezone(timezone.utc)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = db.connect(self.db_path)
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            c.execute("COMMIT")

    def bot_username(self) -> Optional[str]:
        name = self._bot_username if self._bot_username is not None else os.environ.get("BOT_USERNAME", "")
        name = name.strip().lstrip("@")
        return name or None

    def invite_link(self, code: str) -> Optional[str]:
        bot = self.bot_username()
        return f"https://t.me/{bot}?startapp=league_{code}" if bot else None

    def _provider(self, fn: str, *args: Any) -> Any:
        try:
            return getattr(self.provider, fn)(*args)
        except (NotImplementedError, ProviderUnavailable):
            raise PredictError(503, "matches_unavailable", "Данные о матчах пока не подключены") from None

    # --- пользователи ---

    def upsert_user(self, user: Any, keep_photo: bool = False) -> int:
        """Создаёт/обновляет пользователя по данным initData (WebAppUser или dict).
        keep_photo — не трогать photo_url (вход по коду: ссылки на фото в данных нет)."""
        g = (lambda k: user.get(k)) if isinstance(user, dict) else (lambda k: getattr(user, k, None))
        uid = int(g("id"))
        now = iso(self.now())
        if keep_photo:
            with self.conn() as c:
                upsert_names(c, uid, g("first_name"), g("last_name"), g("username"), now)
            return uid
        with self.conn() as c:
            c.execute(
                """INSERT INTO users(id, first_name, last_name, username, photo_url, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET first_name=excluded.first_name, last_name=excluded.last_name,
                       username=excluded.username, photo_url=excluded.photo_url, updated_at=excluded.updated_at
                   WHERE users.first_name IS NOT excluded.first_name OR users.last_name IS NOT excluded.last_name
                      OR users.username IS NOT excluded.username OR users.photo_url IS NOT excluded.photo_url""",
                (uid, (g("first_name") or "")[:128], g("last_name"), g("username"), g("photo_url"), now, now))
        return uid

    def session_epoch(self, user_id: int) -> Optional[int]:
        """Счётчик сессий пользователя; None — пользователя нет."""
        with self.conn() as c:
            row = c.execute("SELECT session_epoch FROM users WHERE id=?", (user_id,)).fetchone()
        return None if row is None else int(row[0])

    def bump_session_epoch(self, user_id: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE users SET session_epoch = session_epoch + 1, updated_at=? WHERE id=?",
                      (iso(self.now()), user_id))

    def touch_seen(self, user_id: int) -> bool:
        """Отметить визит: seen_at — не чаще раза в сутки (иначе каждый /me был бы записью в базу)."""
        now = self.now()
        with self.conn() as c:
            cur = c.execute("UPDATE users SET seen_at=? WHERE id=? AND (seen_at IS NULL OR seen_at < ?)",
                            (iso(now), user_id, iso(now - timedelta(days=1))))
        return cur.rowcount > 0

    def want_avatar(self, user_id: int, photo_url: Optional[str]) -> bool:
        """Заявка сборщику скачать аватар (если файла нет / url сменился / файл старше недели)."""
        with self.conn() as c:
            return avatars.want(c, user_id, photo_url, self.now())

    def user_view(self, user_id: int) -> Optional[dict[str, Any]]:
        with self.conn() as c:
            u = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if u is None:
            return None
        return {"id": u["id"], "name": display_name(u["first_name"], u["last_name"], u["username"]),
                "first_name": u["first_name"], "last_name": u["last_name"], "username": u["username"],
                "avatar": avatars.url_for(u["id"])}

    # --- матчи ---

    @staticmethod
    def _norm(m: Match) -> dict[str, Any]:
        ko = parse_kickoff(m["kickoff_utc"])
        score = m.get("score")
        status = m.get("status") or "scheduled"
        if status not in ("scheduled", "live", "finished", "cancelled", "postponed"):
            raise ValueError(f"неизвестный статус матча: {status!r}")
        fs = m.get("first_rm_scorer_player_id")
        return {
            "id": str(m["id"]), "kickoff": ko,
            "home_id": None if (m.get("home") or {}).get("id") is None else str(m["home"]["id"]),
            "home_name": (m.get("home") or {}).get("name") or "",
            "away_id": None if (m.get("away") or {}).get("id") is None else str(m["away"]["id"]),
            "away_name": (m.get("away") or {}).get("name") or "",
            "rm_is_home": rm_is_home(m), "status": status,
            "score_home": None if not score else int(score["home"]),
            "score_away": None if not score else int(score["away"]),
            "first_scorer": None if fs is None else str(fs),
        }

    def _sync_match(self, c: sqlite3.Connection, m: Match) -> tuple[Optional[sqlite3.Row], dict[str, Any]]:
        n = self._norm(m)
        old = c.execute("SELECT * FROM matches WHERE id=?", (n["id"],)).fetchone()
        c.execute(
            """INSERT INTO matches(id, kickoff_utc, home_id, home_name, away_id, away_name, rm_is_home, status,
                                   score_home, score_away, first_scorer, season, month, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET kickoff_utc=excluded.kickoff_utc, home_id=excluded.home_id,
                   home_name=excluded.home_name, away_id=excluded.away_id, away_name=excluded.away_name,
                   rm_is_home=excluded.rm_is_home, status=excluded.status, score_home=excluded.score_home,
                   score_away=excluded.score_away, first_scorer=excluded.first_scorer, season=excluded.season,
                   month=excluded.month, updated_at=excluded.updated_at""",
            (n["id"], iso(n["kickoff"]), n["home_id"], n["home_name"], n["away_id"], n["away_name"],
             int(n["rm_is_home"]), n["status"], n["score_home"], n["score_away"], n["first_scorer"],
             season_of(n["kickoff"]), month_of(n["kickoff"]), iso(self.now())))
        return old, n

    def accepting(self, status: str, kickoff: datetime) -> bool:
        return status in OPEN_STATUSES and self.now() < kickoff

    def _match_view(self, m: Match) -> dict[str, Any]:
        n = self._norm(m)
        acc = self.accepting(n["status"], n["kickoff"])
        tour = m.get("tournament") or None
        return {
            "id": n["id"], "kickoff_utc": iso_short(n["kickoff"]),
            "home": {"id": n["home_id"], "name": n["home_name"]},
            "away": {"id": n["away_id"], "name": n["away_name"]},
            "rm_side": "home" if n["rm_is_home"] else "away",
            "status": n["status"],
            "score": None if n["score_home"] is None else {"home": n["score_home"], "away": n["score_away"]},
            "accepting": acc, "closes_at": iso_short(n["kickoff"]),
            # автор первого гола Реала — пока матч идёт или после него (для «пока +N» на клиенте)
            "first_rm_scorer_player_id": n["first_scorer"] if n["status"] in ("live", "finished") else None,
            "tournament": {"id": tour.get("id"), "name": tour.get("name")} if isinstance(tour, dict) else None,
        }

    @staticmethod
    def _squad_view(squad: Any) -> list[dict[str, Any]]:
        out = []
        for x in squad or []:
            v = {"id": str(x["id"]), "name": x.get("name", "")}
            for k in ("position", "number", "starter"):
                if x.get(k) is not None:
                    v[k] = x[k]
            out.append(v)
        return out

    @staticmethod
    def _pred_view(p: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
        if p is None:
            return None
        return {"home": p["home"], "away": p["away"], "first_scorer_id": p["first_scorer"],
                "created_at": p["created_at"], "updated_at": p["updated_at"], "revisions": p["revisions"]}

    @staticmethod
    def _points_view(p: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
        if p is None or p["points"] is None:
            return None
        pts = rules.Points(score=p["points_score"], scorer=p["points_scorer"], exact=bool(p["exact"]))
        return {"total": pts.total, "score": pts.score, "scorer": pts.scorer, "kind": pts.kind}

    def matches(self, user_id: Optional[int], recent_limit: int = 5) -> dict[str, Any]:
        upcoming = [m for m in self._provider("upcoming", 5) if m.get("status") != "cancelled"]
        recent = self._provider("recent", recent_limit)
        nxt = upcoming[0] if upcoming else None
        ids = [str(m["id"]) for m in ([nxt] if nxt else []) + recent]
        preds: dict[str, sqlite3.Row] = {}
        if user_id is not None and ids:
            with self.conn() as c:
                q = f"SELECT * FROM predictions WHERE user_id=? AND match_id IN ({','.join('?' * len(ids))})"
                preds = {r["match_id"]: r for r in c.execute(q, (user_id, *ids))}
        out_next = None
        if nxt:
            v = self._match_view(nxt)
            p = preds.get(v["id"])
            v.update(rm_squad=self._squad_view(nxt.get("rm_squad")),
                     my_prediction=self._pred_view(p), my_points=self._points_view(p))
            out_next = v
        out_recent = []
        for m in recent:
            v = self._match_view(m)
            p = preds.get(v["id"])
            v.update(my_prediction=self._pred_view(p), my_points=self._points_view(p),
                     settled=p is not None and p["points"] is not None)
            out_recent.append(v)
        return {"server_time": iso_short(self.now()), "next": out_next, "recent": out_recent}

    # --- приём прогноза ---

    def put_prediction(self, user_id: int, match_id: str, home: Any, away: Any,
                       first_scorer_id: Any = None) -> dict[str, Any]:
        if not self.predict_limiter.hit(user_id):
            raise PredictError(429, "rate_limited", "Слишком часто: не больше 30 изменений прогноза в минуту")
        for g in (home, away):
            if isinstance(g, bool) or not isinstance(g, int) or not rules.GOALS_MIN <= g <= rules.GOALS_MAX:
                raise PredictError(422, "validation", "Голы — целые числа от 0 до 20")
        m = self._provider("get_match", str(match_id))
        if m is None:
            raise PredictError(404, "match_not_found", "Матч не найден")
        n = self._norm(m)
        if n["status"] == "cancelled":
            raise PredictError(409, "match_cancelled", "Матч отменён — прогнозы не принимаются")
        if not self.accepting(n["status"], n["kickoff"]):
            raise PredictError(409, "closed", "Приём закрыт: матч уже начался")
        scorer = None if first_scorer_id is None else str(first_scorer_id)
        if scorer is not None:
            if rules.rm_goals(home, away, n["rm_is_home"]) == 0:
                raise PredictError(422, "scorer_without_goal",
                                   "По вашему прогнозу Реал не забивает — автора первого гола выбрать нельзя")
            squad = {str(x["id"]) for x in m.get("rm_squad") or []}
            if scorer not in squad:
                raise PredictError(422, "scorer_not_in_squad", "Этого игрока нет в составе Реала на матч")
        now = iso(self.now())
        with self.tx() as c:
            self._sync_match(c, m)
            # повторная проверка времени внутри транзакции — на случай гонки с началом матча
            if not self.accepting(n["status"], n["kickoff"]):
                raise PredictError(409, "closed", "Приём закрыт: матч уже начался")
            c.execute(
                """INSERT INTO predictions(user_id, match_id, home, away, first_scorer, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(user_id, match_id) DO UPDATE SET home=excluded.home, away=excluded.away,
                       first_scorer=excluded.first_scorer, updated_at=excluded.updated_at,
                       revisions=predictions.revisions + 1""",
                (user_id, n["id"], home, away, scorer, now, now))
            p = c.execute("SELECT * FROM predictions WHERE user_id=? AND match_id=?", (user_id, n["id"])).fetchone()
        return {"match_id": n["id"], **self._pred_view(p), "closes_at": iso_short(n["kickoff"])}

    # --- расчёт очков ---

    @staticmethod
    def _periods(season: int, month: str) -> set[str]:
        return {f"S{season}", f"M{month}"}

    def _recompute(self, c: sqlite3.Connection, periods: set[str]) -> None:
        for p in sorted(periods):
            col, val = ("season", int(p[1:])) if p[0] == "S" else ("month", p[1:])
            c.execute("DELETE FROM standings WHERE period=?", (p,))
            c.execute(
                f"""INSERT INTO standings(period, user_id, points, exact, played, last_pred_at)
                    SELECT ?, p.user_id, SUM(p.points), SUM(p.exact), COUNT(*), MAX(p.updated_at)
                    FROM matches m JOIN predictions p ON p.match_id = m.id
                    WHERE m.{col} = ? AND p.points IS NOT NULL
                    GROUP BY p.user_id""", (p, val))

    def settle(self, match_id: str, recompute: bool = True) -> dict[str, Any]:
        """Начисляет очки за матч. Идемпотентно: повторный вызов без изменений результата — 'unchanged'.

        Исправленный результат → пересчёт с записью в settle_audit (kind='resettle').
        Отмена/перенос → очки аннулируются (kind='void'), прогнозы остаются.
        """
        m = self._provider("get_match", str(match_id))
        res: dict[str, Any] = {"match_id": str(match_id), "result": "unknown", "predictions": 0, "changed": 0,
                               "periods": []}
        if m is None:
            return res
        now = iso(self.now())
        with self.tx() as c:
            if c.execute("SELECT 1 FROM matches WHERE id=?", (str(match_id),)).fetchone() is None:
                res["result"] = "no_predictions"
                return res
            old, n = self._sync_match(c, m)
            mid = n["id"]
            periods = self._periods(old["season"], old["month"]) | self._periods(season_of(n["kickoff"]),
                                                                                 month_of(n["kickoff"]))
            total = c.execute("SELECT COUNT(*) FROM predictions WHERE match_id=?", (mid,)).fetchone()[0]
            res["predictions"] = total
            touched: set[str] = set()
            if n["status"] in VOID_STATUSES:
                changed = c.execute("""UPDATE predictions SET points=NULL, points_score=NULL, points_scorer=NULL,
                                       exact=NULL, settled_at=NULL WHERE match_id=? AND points IS NOT NULL""",
                                    (mid,)).rowcount
                if old["settled_sig"] is not None or changed:
                    c.execute("UPDATE matches SET settled_sig=NULL, settled_at=NULL WHERE id=?", (mid,))
                    c.execute("""INSERT INTO settle_audit(match_id, at, kind, old_result, new_result, predictions, changed)
                                 VALUES (?,?,?,?,?,?,?)""",
                              (mid, now, "void", old["settled_sig"], n["status"], total, changed))
                    touched = periods
                    res["result"] = "voided"
                else:
                    res["result"] = n["status"]
                res["changed"] = changed
            elif n["status"] == "finished" and n["score_home"] is not None:
                sig = json.dumps({"home": n["score_home"], "away": n["score_away"],
                                  "first_scorer": n["first_scorer"]}, sort_keys=True)
                same_period = (old["season"], old["month"]) == (season_of(n["kickoff"]), month_of(n["kickoff"]))
                if old["settled_sig"] == sig and same_period:
                    res["result"] = "unchanged"
                else:
                    upd = []
                    for p in c.execute("SELECT * FROM predictions WHERE match_id=?", (mid,)).fetchall():
                        pts = rules.compute(p["home"], p["away"], p["first_scorer"], n["score_home"],
                                            n["score_away"], n["first_scorer"], n["rm_is_home"])
                        if (p["points"], p["points_score"], p["points_scorer"]) != (pts.total, pts.score, pts.scorer):
                            upd.append((pts.total, pts.score, pts.scorer, int(pts.exact), now, p["id"]))
                    c.executemany("""UPDATE predictions SET points=?, points_score=?, points_scorer=?, exact=?,
                                     settled_at=? WHERE id=?""", upd)
                    c.execute("UPDATE matches SET settled_sig=?, settled_at=? WHERE id=?", (sig, now, mid))
                    kind = "settle" if old["settled_sig"] is None else "resettle"
                    if old["settled_sig"] != sig:
                        c.execute("""INSERT INTO settle_audit(match_id, at, kind, old_result, new_result, predictions,
                                     changed) VALUES (?,?,?,?,?,?,?)""",
                                  (mid, now, kind, old["settled_sig"], sig, total, len(upd)))
                    touched = periods
                    res["result"] = "settled" if kind == "settle" else "resettled"
                    res["changed"] = len(upd)
            else:
                res["result"] = "pending"
            if touched and recompute:
                self._recompute(c, touched)
            res["periods"] = sorted(touched)
        return res

    def settle_pending(self) -> list[dict[str, Any]]:
        """Для фонового вызова: рассчитать начавшиеся матчи и поймать исправления недавних результатов."""
        now = self.now()
        with self.conn() as c:
            ids = [r[0] for r in c.execute(
                """SELECT id FROM matches WHERE kickoff_utc <= ?
                       AND ((settled_sig IS NULL AND status != 'cancelled') OR kickoff_utc >= ?)""",
                (iso(now), iso(now - RESETTLE_WINDOW)))]
            try:
                for m in self.provider.recent(10):
                    mid = str(m["id"])
                    if mid not in ids and c.execute("SELECT 1 FROM matches WHERE id=?", (mid,)).fetchone():
                        ids.append(mid)
            except (NotImplementedError, ProviderUnavailable):
                pass
        out, periods = [], set()
        for mid in ids:
            try:
                r = self.settle(mid, recompute=False)
            except PredictError:
                raise
            except Exception:  # один битый матч не должен останавливать остальные
                log.exception("settle %s", mid)
                continue
            periods |= set(r["periods"])
            out.append(r)
        if periods:
            with self.tx() as c:
                self._recompute(c, periods)
        return out

    # --- рейтинги ---

    @staticmethod
    def _row_view(r: sqlite3.Row, rank: int, me: Optional[int]) -> dict[str, Any]:
        return {"rank": rank, "name": display_name(r["first_name"], r["last_name"], r["username"]),
                "username": r["username"], "photo_url": r["photo_url"], "avatar": avatars.url_for(r["user_id"]),
                "points": r["points"],
                "exact": r["exact"], "played": r["played"], "is_me": me is not None and r["user_id"] == me}

    def _global_rank(self, c: sqlite3.Connection, key: str, user_id: int) -> Optional[dict[str, Any]]:
        s = c.execute("SELECT * FROM standings WHERE period=? AND user_id=?", (key, user_id)).fetchone()
        if s is None:
            return {"rank": None, "points": 0, "exact": 0, "played": 0}
        better = c.execute(
            """SELECT COUNT(*) FROM standings WHERE period=:p AND (points > :pts OR (points = :pts AND (
                   exact > :ex OR (exact = :ex AND (last_pred_at < :l OR (last_pred_at = :l AND user_id < :u))))))""",
            {"p": key, "pts": s["points"], "ex": s["exact"], "l": s["last_pred_at"], "u": user_id}).fetchone()[0]
        return {"rank": better + 1, "points": s["points"], "exact": s["exact"], "played": s["played"]}

    def leaderboard(self, period: str = "season", league_id: Optional[int] = None, limit: int = 50,
                    user_id: Optional[int] = None) -> dict[str, Any]:
        info = period_info(period, self.now())
        key = info["key"]
        limit = max(1, min(int(limit), 100))
        with self.conn() as c:
            if league_id is None:
                rows = c.execute(
                    """SELECT s.*, u.first_name, u.last_name, u.username, u.photo_url
                       FROM standings s JOIN users u ON u.id = s.user_id WHERE s.period = ?
                       ORDER BY s.points DESC, s.exact DESC, s.last_pred_at ASC, s.user_id ASC LIMIT ?""",
                    (key, limit)).fetchall()
                top = [self._row_view(r, i + 1, user_id) for i, r in enumerate(rows)]
                total = c.execute("SELECT COUNT(*) FROM standings WHERE period=?", (key,)).fetchone()[0]
                me = self._global_rank(c, key, user_id) if user_id is not None else None
                return {**info, "league": None, "total": total, "top": top, "me": me}
            if user_id is None:
                raise PredictError(401, "unauthorized", "Рейтинг лиги виден только её участникам — войдите через Telegram")
            lg = c.execute("SELECT * FROM leagues WHERE id=?", (league_id,)).fetchone()
            if lg is None:
                raise PredictError(404, "league_not_found", "Лига не найдена")
            if not c.execute("SELECT 1 FROM league_members WHERE league_id=? AND user_id=?",
                             (league_id, user_id)).fetchone():
                raise PredictError(403, "not_member", "Вы не состоите в этой лиге")
            rows = c.execute(
                """WITH ranked AS (
                       SELECT lm.user_id, COALESCE(s.points, 0) AS points, COALESCE(s.exact, 0) AS exact,
                              COALESCE(s.played, 0) AS played,
                              ROW_NUMBER() OVER (ORDER BY COALESCE(s.points, 0) DESC, COALESCE(s.exact, 0) DESC,
                                                 s.last_pred_at IS NULL, s.last_pred_at ASC, lm.user_id ASC) AS rnk
                       FROM league_members lm
                       LEFT JOIN standings s ON s.user_id = lm.user_id AND s.period = ?
                       WHERE lm.league_id = ?)
                   SELECT r.*, u.first_name, u.last_name, u.username, u.photo_url
                   FROM ranked r JOIN users u ON u.id = r.user_id
                   WHERE r.rnk <= ? OR r.user_id = ? ORDER BY r.rnk""",
                (key, league_id, limit, user_id)).fetchall()
            top = [self._row_view(r, r["rnk"], user_id) for r in rows if r["rnk"] <= limit]
            mine = next(r for r in rows if r["user_id"] == user_id)
            total = c.execute("SELECT COUNT(*) FROM league_members WHERE league_id=?", (league_id,)).fetchone()[0]
            me = {"rank": mine["rnk"], "points": mine["points"], "exact": mine["exact"], "played": mine["played"]}
            return {**info, "league": {"id": lg["id"], "name": lg["name"]}, "total": total, "top": top, "me": me}

    def me(self, user_id: int) -> dict[str, Any]:
        now = self.now()
        season, month = period_info("season", now), period_info("month", now)
        with self.conn() as c:
            u = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            s = self._global_rank(c, season["key"], user_id)
            mo = self._global_rank(c, month["key"], user_id)
            count = c.execute("SELECT COUNT(*) FROM predictions WHERE user_id=?", (user_id,)).fetchone()[0]
            hist = c.execute(
                """SELECT p.*, m.kickoff_utc, m.home_id, m.home_name, m.away_id, m.away_name, m.rm_is_home,
                          m.status, m.score_home, m.score_away, m.first_scorer AS actual_scorer
                   FROM predictions p JOIN matches m ON m.id = p.match_id
                   WHERE p.user_id = ? ORDER BY m.kickoff_utc DESC LIMIT 20""", (user_id,)).fetchall()
        history = []
        for h in hist:
            ko = from_iso(h["kickoff_utc"])
            if h["points"] is not None:
                state = "settled"
            elif h["status"] in VOID_STATUSES and not self.accepting(h["status"], ko):
                state = "void"
            elif self.accepting(h["status"], ko):
                state = "open"
            else:
                state = "waiting"
            history.append({
                "match": {"id": h["match_id"], "kickoff_utc": iso_short(ko),
                          "home": {"id": h["home_id"], "name": h["home_name"]},
                          "away": {"id": h["away_id"], "name": h["away_name"]},
                          "rm_side": "home" if h["rm_is_home"] else "away", "status": h["status"],
                          "score": None if h["score_home"] is None else {"home": h["score_home"],
                                                                         "away": h["score_away"]},
                          "first_rm_scorer_player_id": h["actual_scorer"]},
                "prediction": self._pred_view(h), "points": self._points_view(h), "state": state})
        return {
            "user": {"id": user_id, "name": display_name(u["first_name"], u["last_name"], u["username"]) if u else "",
                     "username": u["username"] if u else None, "photo_url": u["photo_url"] if u else None},
            "season": {**{k: season[k] for k in ("key", "label")}, **s},
            "month": {**{k: month[k] for k in ("key", "label")}, **mo},
            "points": s["points"], "rank": s["rank"], "exact": s["exact"], "predictions": count,
            "history": history,
        }

    # --- лиги ---

    @staticmethod
    def _clean_name(name: Any) -> str:
        if not isinstance(name, str):
            raise PredictError(422, "validation", "Название лиги — строка до 40 символов")
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            raise PredictError(422, "validation", "Введите название лиги")
        if len(name) > LEAGUE_NAME_MAX:
            raise PredictError(422, "validation", f"Название лиги — не длиннее {LEAGUE_NAME_MAX} символов")
        if any(ord(ch) < 32 or 0x7F <= ord(ch) < 0xA0 for ch in name):
            raise PredictError(422, "validation", "В названии недопустимые символы")
        return name

    @staticmethod
    def _new_code() -> str:
        return "".join(secrets.choice(CODE_ALPHABET) for _ in range(LEAGUE_CODE_LEN))

    @staticmethod
    def _norm_code(code: Any) -> str:
        if not isinstance(code, str):
            return ""
        code = code.strip()
        if code.lower().startswith("league_"):
            code = code[7:]
        return re.sub(r"[\s-]", "", code).upper()

    def _league_view(self, c: sqlite3.Connection, lg: sqlite3.Row, user_id: int) -> dict[str, Any]:
        members = c.execute("SELECT COUNT(*) FROM league_members WHERE league_id=?", (lg["id"],)).fetchone()[0]
        return {"id": lg["id"], "name": lg["name"], "code": lg["code"], "invite_link": self.invite_link(lg["code"]),
                "is_owner": lg["owner_id"] == user_id, "members": members, "created_at": lg["created_at"]}

    def _memberships(self, c: sqlite3.Connection, user_id: int) -> int:
        return c.execute("SELECT COUNT(*) FROM league_members WHERE user_id=?", (user_id,)).fetchone()[0]

    def create_league(self, user_id: int, name: Any) -> dict[str, Any]:
        name = self._clean_name(name)
        now = iso(self.now())
        with self.tx() as c:
            if c.execute("SELECT COUNT(*) FROM leagues WHERE owner_id=?", (user_id,)).fetchone()[0] >= MAX_OWNED_LEAGUES:
                raise PredictError(409, "too_many_leagues", f"Можно создать не больше {MAX_OWNED_LEAGUES} лиг")
            if self._memberships(c, user_id) >= MAX_MEMBERSHIPS:
                raise PredictError(409, "too_many_leagues", f"Можно состоять не больше чем в {MAX_MEMBERSHIPS} лигах")
            for _ in range(10):
                try:
                    cur = c.execute("INSERT INTO leagues(name, code, owner_id, created_at, updated_at) VALUES (?,?,?,?,?)",
                                    (name, self._new_code(), user_id, now, now))
                    break
                except sqlite3.IntegrityError:
                    continue
            else:  # pragma: no cover — 10 коллизий подряд при 2^50 вариантах
                raise PredictError(500, "internal", "Не удалось создать код приглашения")
            lid = cur.lastrowid
            c.execute("INSERT INTO league_members(league_id, user_id, joined_at) VALUES (?,?,?)", (lid, user_id, now))
            lg = c.execute("SELECT * FROM leagues WHERE id=?", (lid,)).fetchone()
            return self._league_view(c, lg, user_id)

    def join_league(self, user_id: int, code: Any) -> dict[str, Any]:
        if not self.join_limiter.hit(user_id):
            raise PredictError(429, "rate_limited", "Слишком много попыток — подождите минуту")
        code = self._norm_code(code)
        if not code:
            raise PredictError(422, "validation", "Введите код приглашения")
        now = iso(self.now())
        with self.tx() as c:
            lg = c.execute("SELECT * FROM leagues WHERE code=?", (code,)).fetchone()
            if lg is None:
                raise PredictError(404, "invalid_code", "Неверный код приглашения")
            if c.execute("SELECT 1 FROM league_members WHERE league_id=? AND user_id=?", (lg["id"], user_id)).fetchone():
                return {**self._league_view(c, lg, user_id), "joined": False}
            if self._memberships(c, user_id) >= MAX_MEMBERSHIPS:
                raise PredictError(409, "too_many_leagues", f"Можно состоять не больше чем в {MAX_MEMBERSHIPS} лигах")
            c.execute("INSERT INTO league_members(league_id, user_id, joined_at) VALUES (?,?,?)", (lg["id"], user_id, now))
            return {**self._league_view(c, lg, user_id), "joined": True}

    def _league_for(self, c: sqlite3.Connection, league_id: int) -> sqlite3.Row:
        lg = c.execute("SELECT * FROM leagues WHERE id=?", (league_id,)).fetchone()
        if lg is None:
            raise PredictError(404, "league_not_found", "Лига не найдена")
        return lg

    def leave_league(self, user_id: int, league_id: int) -> dict[str, Any]:
        with self.tx() as c:
            lg = self._league_for(c, league_id)
            if lg["owner_id"] == user_id:
                raise PredictError(409, "owner_cannot_leave", "Создатель не может выйти из лиги — её можно удалить")
            n = c.execute("DELETE FROM league_members WHERE league_id=? AND user_id=?", (league_id, user_id)).rowcount
            if not n:
                raise PredictError(404, "not_member", "Вы не состоите в этой лиге")
        return {"ok": True}

    def rename_league(self, user_id: int, league_id: int, name: Any) -> dict[str, Any]:
        name = self._clean_name(name)
        with self.tx() as c:
            lg = self._league_for(c, league_id)
            if lg["owner_id"] != user_id:
                raise PredictError(403, "not_owner", "Переименовать лигу может только её создатель")
            c.execute("UPDATE leagues SET name=?, updated_at=? WHERE id=?", (name, iso(self.now()), league_id))
            return self._league_view(c, self._league_for(c, league_id), user_id)

    def delete_league(self, user_id: int, league_id: int) -> dict[str, Any]:
        with self.tx() as c:
            lg = self._league_for(c, league_id)
            if lg["owner_id"] != user_id:
                raise PredictError(403, "not_owner", "Удалить лигу может только её создатель")
            c.execute("DELETE FROM leagues WHERE id=?", (league_id,))
        return {"ok": True}

    def my_leagues(self, user_id: int) -> dict[str, Any]:
        with self.conn() as c:
            rows = c.execute("""SELECT l.* FROM leagues l JOIN league_members lm ON lm.league_id = l.id
                                WHERE lm.user_id = ? ORDER BY lm.joined_at, l.id""", (user_id,)).fetchall()
            return {"leagues": [self._league_view(c, r, user_id) for r in rows]}
