"""Логика мини-игр без HTTP: партии в памяти, проверка ответов и ударов, итоги в predictions.db.

Викторина. Партия — QUIZ_ROUND разных вопросов уровня (без повторов внутри партии; по возможности
и без вопросов из последних партий того же игрока). Варианты ответа перемешиваются на партию.
Правильный ответ клиенту заранее не уходит: только в ответе на /answer. Время ответа меряет
сервер: от выдачи вопроса (/next) до /answer; дольше QUIZ_TIMER + QUIZ_GRACE — «время вышло».

Пенальти. Серия из PENALTY_REGULAR ударов против соперника; ничья после пяти — удары до первого
расхождения («до промаха»). Вратарь прыгает как в старой игре (penalty.html): в случайную зону,
выбранную равновероятно, сейв — только если угадал зону удара. Решение принимает сервер после удара.
Удар в угол мимо вратаря изредка (PENALTY_WOODWORK) попадает в каркас: верхний угол — в перекладину
или штангу, нижний — в штангу. Это промах; исход (outcome: goal | save | post | bar) решает сервер.
Уровень задаёт точность соперника (его удары сервер тоже разыгрывает) и множитель очков.

Итог сохраняется только для вошедших. Таблица game_results — отдельная от прогнозов:
очков прогнозов игры не дают и в standings не пишут.

Язык (`lang`: 'ru' | 'en', ?lang=en в API) влияет только на тексты: вопрос и варианты берутся из
английского банка (те же id и порядок вариантов), названия уровней и подпись недели рейтинга —
по-английски. Партия от языка не зависит: перестановки и проверка ответа — по индексам.
"""
from __future__ import annotations

import json
import random
import secrets
import threading
import time
from collections import OrderedDict, defaultdict, deque
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from .. import avatars
from ..predictions.service import MSK, RateLimiter, display_name, iso, utcnow
from .. import i18n
from . import bank

# ---------- правила ----------

QUIZ_LEVELS: dict[str, dict[str, Any]] = {
    "easy": {"title": "Лёгкий", "base": 100},
    "medium": {"title": "Средний", "base": 150},
    "hard": {"title": "Сложный", "base": 200},
    "expert": {"title": "Эксперт", "base": 300},
}
LEVEL_TITLES_EN = {"easy": "Easy", "medium": "Medium", "hard": "Hard", "expert": "Expert", "legend": "Legend"}
QUIZ_ROUND = 10          # вопросов в партии
QUIZ_TIMER = 15.0        # секунд на вопрос (как в старой игре)
QUIZ_GRACE = 2.0         # запас на сеть и отрисовку
QUIZ_MIN_ANSWER = 0.35   # быстрее не прочитать вопрос — запрос отклоняется, вопрос остаётся открытым
QUIZ_RECENT = 60         # сколько последних вопросов уровня помним за игроком, чтобы не повторять

PENALTY_LEVELS: dict[str, dict[str, Any]] = {
    "easy": {"title": "Лёгкий", "rival": 0.55, "mult": 1},
    "medium": {"title": "Средний", "rival": 0.68, "mult": 2},
    "hard": {"title": "Сложный", "rival": 0.80, "mult": 3},
    "legend": {"title": "Легенда", "rival": 0.90, "mult": 4},
}
PENALTY_ZONES = 6        # 1–3 верх (лево, центр, право), 4–6 низ
PENALTY_REGULAR = 5
PENALTY_MAX_SUDDEN = 30  # страховка от бесконечной серии
PENALTY_MIN_INTERVAL = 0.5  # между ударами (анимация дольше) — чаще только скрипт
PENALTY_GOAL, PENALTY_WIN = 100, 300
PENALTY_CORNERS = (1, 3, 4, 6)
PENALTY_WOODWORK = 0.06  # доля ударов в угол мимо вратаря, что попадают в штангу/перекладину

GAMES = ("quiz", "penalty")
SESSION_TTL = 30 * 60
SESSION_MAX = 20_000
START_RATE = (30, 60.0)    # новых партий в минуту на игрока / IP
ACTION_RATE = (150, 60.0)  # ответов и ударов в минуту


class GameError(Exception):
    def __init__(self, status: int, error: str, message: str):
        super().__init__(message)
        self.status, self.error, self.message = status, error, message


def multiplier(streak: int) -> int:
    """Серия верных подряд → множитель: 1–2 ×1, 3–5 ×2, 6+ ×3."""
    return 1 if streak < 3 else 2 if streak < 6 else 3


def quiz_points(level: str, elapsed: float, streak: int) -> int:
    """Очки за верный ответ: база уровня + до 50 % за скорость, × множитель серии."""
    base = QUIZ_LEVELS[level]["base"]
    left = max(0.0, QUIZ_TIMER - max(0.0, elapsed))
    return int(round(base * (1 + 0.5 * left / QUIZ_TIMER))) * multiplier(streak)


def penalty_score(level: str, goals: int, won: bool) -> int:
    return (goals * PENALTY_GOAL + (PENALTY_WIN if won else 0)) * PENALTY_LEVELS[level]["mult"]


def week_start(now: datetime) -> date:
    """Понедельник недели по Москве."""
    d = now.astimezone(MSK).date()
    return d - timedelta(days=d.weekday())


MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
          "октября", "ноября", "декабря")


def week_label(start: date, lang: str = "ru") -> str:
    end = start + timedelta(days=6)
    if lang == i18n.EN:
        m = i18n.MONTHS_EN
        if start.month == end.month:
            return f"{m[end.month - 1]} {start.day}–{end.day}"
        return f"{m[start.month - 1]} {start.day} – {m[end.month - 1]} {end.day}"
    if start.month == end.month:
        return f"{start.day}–{end.day} {MONTHS[end.month - 1]}"
    return f"{start.day} {MONTHS[start.month - 1]} – {end.day} {MONTHS[end.month - 1]}"


def level_title(table: dict[str, dict[str, Any]], level: str, lang: str = "ru") -> str:
    return LEVEL_TITLES_EN.get(level, table[level]["title"]) if lang == i18n.EN else table[level]["title"]


# ---------- партии ----------

@dataclass
class QuizSession:
    id: str
    user_id: Optional[int]
    level: str
    qids: list[str]
    perms: list[list[int]]          # perms[i][shown] = исходный индекс варианта
    touched: float
    idx: int = 0                    # сколько вопросов уже отвечено
    open_at: Optional[float] = None  # когда выдан текущий вопрос (монотонные часы сервера)
    score: int = 0
    streak: int = 0
    best_streak: int = 0
    correct: int = 0
    timeouts: int = 0
    done: bool = False
    result: Optional[dict[str, Any]] = None
    kind: str = "quiz"


@dataclass
class PenaltySession:
    id: str
    user_id: Optional[int]
    level: str
    touched: float
    shots: list[dict[str, Any]] = field(default_factory=list)
    goals: int = 0
    rival: int = 0
    last_shot: Optional[float] = None
    done: bool = False
    result: Optional[dict[str, Any]] = None
    kind: str = "penalty"


class GameService:
    def __init__(self, conn: Callable[[], AbstractContextManager], clock: Callable[[], datetime] = utcnow,
                 mono: Callable[[], float] = time.monotonic, rng: Optional[random.Random] = None,
                 questions: Optional[dict[str, tuple[bank.Question, ...]]] = None,
                 questions_en: Optional[dict[str, tuple[bank.Question, ...]]] = None):
        self._conn = conn
        self.clock = clock
        self.mono = mono
        self.rng = rng or random.SystemRandom()
        self.questions = questions if questions is not None else bank.load()
        self.by_id = {q.id: q for qs in self.questions.values() for q in qs}
        # английский банк; подставили свой набор вопросов (тесты) без английского — тексты по-русски
        if questions_en is None:
            questions_en = bank.load_en() if questions is None else {}
        self.by_id_en = {q.id: q for qs in questions_en.values() for q in qs}
        self._sessions: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()
        self._recent: dict[tuple[int, str], deque] = defaultdict(lambda: deque(maxlen=QUIZ_RECENT))
        self.start_limiter = RateLimiter(*START_RATE, clock=mono)
        self.action_limiter = RateLimiter(*ACTION_RATE, clock=mono)

    # --- хранилище партий ---

    def _put(self, s: Any) -> None:
        now = self.mono()
        with self._lock:
            while self._sessions:
                k, old = next(iter(self._sessions.items()))
                if now - old.touched > SESSION_TTL or len(self._sessions) >= SESSION_MAX:
                    self._sessions.popitem(last=False)
                else:
                    break
            self._sessions[s.id] = s

    def _get(self, sid: str, kind: str, user_id: Optional[int]) -> Any:
        now = self.mono()
        with self._lock:
            s = self._sessions.get(sid)
            if s is None or s.kind != kind or now - s.touched > SESSION_TTL:
                s = None
            elif s.user_id is not None and s.user_id != user_id:
                s = None  # чужая партия — как будто её нет
            else:
                s.touched = now
                self._sessions.move_to_end(sid)
        if s is None:
            raise GameError(404, "session_not_found", "Игра не найдена или устарела — начните заново")
        return s

    def _limit(self, limiter: RateLimiter, key: Any) -> None:
        if not limiter.hit(key):
            raise GameError(429, "rate_limited", "Слишком часто — подождите немного")

    # --- справка ---

    def info(self, lang: str = "ru") -> dict[str, Any]:
        return {
            "quiz": {"round": QUIZ_ROUND, "timer_s": QUIZ_TIMER,
                     "levels": [{"id": k, "title": level_title(QUIZ_LEVELS, k, lang), "base": v["base"],
                                 "questions": len(self.questions.get(k, ()))} for k, v in QUIZ_LEVELS.items()]},
            "penalty": {"shots": PENALTY_REGULAR, "zones": PENALTY_ZONES,
                        "levels": [{"id": k, "title": level_title(PENALTY_LEVELS, k, lang), "mult": v["mult"]}
                                   for k, v in PENALTY_LEVELS.items()]},
        }

    # --- викторина ---

    def quiz_start(self, level: Any, user_id: Optional[int], rate_key: Any) -> dict[str, Any]:
        if level not in QUIZ_LEVELS:
            raise GameError(400, "bad_level", "Неизвестный уровень")
        pool = self.questions.get(level, ())
        if len(pool) < QUIZ_ROUND:
            raise GameError(503, "no_questions", "Вопросы для этого уровня пока не готовы")
        self._limit(self.start_limiter, rate_key)
        recent = list(self._recent[(user_id, level)]) if user_id is not None else []
        seen = set(recent)
        fresh = [q.id for q in pool if q.id not in seen]
        if len(fresh) >= QUIZ_ROUND:
            qids = self.rng.sample(fresh, QUIZ_ROUND)
        else:  # почти всё было недавно — добираем самыми давними (без повторов внутри партии)
            old = list(dict.fromkeys(qid for qid in recent if qid in self.by_id))
            qids = self.rng.sample(fresh, len(fresh)) + old[:QUIZ_ROUND - len(fresh)]
        if user_id is not None:
            self._recent[(user_id, level)].extend(qids)
        perms = []
        for _ in qids:
            p = list(range(4))
            self.rng.shuffle(p)
            perms.append(p)
        s = QuizSession(secrets.token_urlsafe(18), user_id, level, qids, perms, self.mono())
        self._put(s)
        return {"session": s.id, "level": level, "total": QUIZ_ROUND, "timer_s": QUIZ_TIMER,
                "saved": user_id is not None}

    def _question_view(self, s: QuizSession, now: float, lang: str = "ru") -> dict[str, Any]:
        q = self.by_id[s.qids[s.idx]]
        if lang == i18n.EN:
            q = self.by_id_en.get(q.id, q)   # тот же вопрос: id, порядок вариантов и correct совпадают
        assert s.open_at is not None
        left = max(0.0, QUIZ_TIMER - (now - s.open_at))
        return {"index": s.idx, "total": len(s.qids), "q": q.q, "a": [q.a[i] for i in s.perms[s.idx]],
                "media": q.media, "timer_s": QUIZ_TIMER, "left_s": round(left, 2),
                "score": s.score, "streak": s.streak, "multiplier": multiplier(s.streak + 1)}

    def quiz_next(self, sid: str, user_id: Optional[int], rate_key: Any, lang: str = "ru") -> dict[str, Any]:
        s: QuizSession = self._get(sid, "quiz", user_id)
        self._limit(self.action_limiter, rate_key)
        now = self.mono()
        with self._lock:
            if s.done:
                raise GameError(409, "finished", "Игра уже закончилась")
            if s.open_at is None:  # повторный запрос открытого вопроса таймер не сбрасывает
                s.open_at = now
            return self._question_view(s, now, lang)

    def quiz_answer(self, sid: str, choice: Any, user_id: Optional[int], rate_key: Any) -> dict[str, Any]:
        if choice is not None and (isinstance(choice, bool) or not isinstance(choice, int) or not 0 <= choice < 4):
            raise GameError(400, "bad_choice", "Вариант ответа — число от 0 до 3")
        s: QuizSession = self._get(sid, "quiz", user_id)
        self._limit(self.action_limiter, rate_key)
        now = self.mono()
        with self._lock:
            if s.done:
                raise GameError(409, "finished", "Игра уже закончилась")
            if s.open_at is None:
                raise GameError(409, "no_question", "Сначала нужно получить вопрос")
            elapsed = now - s.open_at
            if choice is not None and elapsed < QUIZ_MIN_ANSWER:
                raise GameError(429, "too_fast", "Слишком быстро — прочитайте вопрос")
            q = self.by_id[s.qids[s.idx]]
            perm = s.perms[s.idx]
            timeout = choice is None or elapsed > QUIZ_TIMER + QUIZ_GRACE
            correct = not timeout and perm[choice] == q.correct
            points = 0
            if correct:
                s.streak += 1
                s.best_streak = max(s.best_streak, s.streak)
                s.correct += 1
                points = quiz_points(s.level, elapsed, s.streak)
                s.score += points
            else:
                s.streak = 0
                if timeout:
                    s.timeouts += 1
            s.idx += 1
            s.open_at = None
            s.done = s.idx >= len(s.qids)
            out = {"correct": correct, "timeout": timeout, "correct_choice": perm.index(q.correct),
                   "points": points, "score": s.score, "streak": s.streak,
                   "multiplier": multiplier(s.streak), "elapsed_s": round(elapsed, 2),
                   "index": s.idx - 1, "total": len(s.qids), "done": s.done}
            finish = s.done and s.result is None
        if finish:
            detail = {"correct": s.correct, "total": len(s.qids), "best_streak": s.best_streak, "timeouts": s.timeouts}
            s.result = self._finish("quiz", s.level, s.score, detail, s.user_id)
        if s.done:
            out["result"] = s.result
        return out

    # --- пенальти ---

    def penalty_start(self, level: Any, user_id: Optional[int], rate_key: Any) -> dict[str, Any]:
        if level not in PENALTY_LEVELS:
            raise GameError(400, "bad_level", "Неизвестный уровень")
        self._limit(self.start_limiter, rate_key)
        s = PenaltySession(secrets.token_urlsafe(18), user_id, level, self.mono())
        self._put(s)
        return {"session": s.id, "level": level, "shots": PENALTY_REGULAR, "zones": PENALTY_ZONES,
                "saved": user_id is not None}

    def _woodwork(self) -> bool:
        # getrandbits, а не random()/randrange(): в тестах random() задаёт удар соперника
        return self.rng.getrandbits(10) < PENALTY_WOODWORK * 1024

    def penalty_shot(self, sid: str, zone: Any, user_id: Optional[int], rate_key: Any) -> dict[str, Any]:
        if isinstance(zone, bool) or not isinstance(zone, int) or not 1 <= zone <= PENALTY_ZONES:
            raise GameError(400, "bad_zone", f"Зона удара — число от 1 до {PENALTY_ZONES}")
        s: PenaltySession = self._get(sid, "penalty", user_id)
        self._limit(self.action_limiter, rate_key)
        now = self.mono()
        with self._lock:
            if s.done:
                raise GameError(409, "finished", "Серия уже закончилась")
            if s.last_shot is not None and now - s.last_shot < PENALTY_MIN_INTERVAL:
                raise GameError(429, "too_fast", "Слишком быстро — дождитесь удара")
            s.last_shot = now
            keeper = self.rng.randint(1, PENALTY_ZONES)       # логика старой игры: случайная зона
            outcome = "save" if keeper == zone else "goal"
            if outcome == "goal" and zone in PENALTY_CORNERS and self._woodwork():
                outcome = "bar" if zone <= 3 and self.rng.getrandbits(1) == 0 else "post"
            goal = outcome == "goal"
            rival_goal = self.rng.random() < PENALTY_LEVELS[s.level]["rival"]
            s.goals += goal
            s.rival += rival_goal
            rnd = len(s.shots) + 1
            s.shots.append({"zone": zone, "keeper": keeper, "goal": goal, "outcome": outcome,
                            "rival_goal": rival_goal})
            if rnd >= PENALTY_REGULAR + PENALTY_MAX_SUDDEN:
                s.done = True
            elif rnd >= PENALTY_REGULAR and s.goals != s.rival:
                s.done = True
            out = {"round": rnd, "phase": "regular" if rnd <= PENALTY_REGULAR else "sudden",
                   "zone": zone, "keeper": keeper, "goal": goal, "outcome": outcome,
                   "rival_goal": rival_goal, "goals": s.goals, "rival": s.rival, "done": s.done,
                   "sudden_next": not s.done and rnd >= PENALTY_REGULAR}
            finish = s.done and s.result is None
        if finish:
            won = s.goals > s.rival
            detail = {"goals": s.goals, "rival": s.rival, "shots": len(s.shots), "won": won,
                      "sudden": len(s.shots) > PENALTY_REGULAR}
            s.result = self._finish("penalty", s.level, penalty_score(s.level, s.goals, won), detail, s.user_id)
        if s.done:
            out["result"] = s.result
        return out

    # --- итоги и рейтинг ---

    def _finish(self, game: str, level: str, score: int, detail: dict[str, Any],
                user_id: Optional[int]) -> dict[str, Any]:
        res: dict[str, Any] = {"game": game, "level": level, "score": score, **detail, "saved": False,
                               "best": None, "record": None}
        if user_id is None:
            return res  # без входа — результат только на устройстве
        now = self.clock()
        with self._conn() as c:
            prev = c.execute("SELECT MAX(score) FROM game_results WHERE user_id=? AND game=? AND level=?",
                             (user_id, game, level)).fetchone()[0]
            c.execute("INSERT INTO game_results(user_id, game, level, score, detail, week, created_at) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (user_id, game, level, int(score), json.dumps(detail, ensure_ascii=False),
                       week_start(now).isoformat(), iso(now)))
        res.update(saved=True, best=max(score, prev or 0), record=score > 0 and (prev is None or score > prev))
        return res

    def me(self, user_id: int) -> dict[str, Any]:
        wk = week_start(self.clock()).isoformat()
        out: dict[str, Any] = {g: {} for g in GAMES}
        week: dict[str, Any] = {g: None for g in GAMES}
        with self._conn() as c:
            for r in c.execute("SELECT game, level, MAX(score) AS best, COUNT(*) AS played FROM game_results "
                               "WHERE user_id=? GROUP BY game, level", (user_id,)):
                out[r["game"]][r["level"]] = {"best": r["best"], "played": r["played"]}
            for r in c.execute("SELECT game, MAX(score) AS best, COUNT(*) AS played FROM game_results "
                               "WHERE user_id=? AND week=? GROUP BY game", (user_id, wk)):
                week[r["game"]] = {"best": r["best"], "played": r["played"]}
        return {"best": out, "week": week}

    def leaderboard(self, game: Any, limit: int = 20, user_id: Optional[int] = None,
                    lang: str = "ru") -> dict[str, Any]:
        if game not in GAMES:
            raise GameError(400, "bad_game", "Игра: quiz или penalty")
        limit = max(1, min(int(limit), 100))
        start = week_start(self.clock())
        with self._conn() as c:
            rows = c.execute(
                """WITH b AS (
                       SELECT user_id, score, level, created_at,
                              ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY score DESC, created_at ASC) AS rn,
                              COUNT(*) OVER (PARTITION BY user_id) AS played
                       FROM game_results WHERE game=? AND week=?),
                   r AS (
                       SELECT b.*, ROW_NUMBER() OVER (ORDER BY score DESC, created_at ASC, user_id ASC) AS rnk
                       FROM b WHERE rn = 1)
                   SELECT r.*, u.first_name, u.last_name, u.username FROM r JOIN users u ON u.id = r.user_id
                   WHERE r.rnk <= ? OR r.user_id = ? ORDER BY r.rnk""",
                (game, start.isoformat(), limit, user_id if user_id is not None else -1)).fetchall()
            total = c.execute("SELECT COUNT(DISTINCT user_id) FROM game_results WHERE game=? AND week=?",
                              (game, start.isoformat())).fetchone()[0]
        top = [{"rank": r["rnk"], "name": display_name(r["first_name"], r["last_name"], r["username"]),
                "avatar": avatars.url_for(r["user_id"]), "score": r["score"], "level": r["level"],
                "played": r["played"], "is_me": user_id is not None and r["user_id"] == user_id}
               for r in rows if r["rnk"] <= limit]
        me = None
        if user_id is not None:
            mine = next((r for r in rows if r["user_id"] == user_id), None)
            me = ({"rank": mine["rnk"], "score": mine["score"], "played": mine["played"]} if mine
                  else {"rank": None, "score": 0, "played": 0})
        return i18n.fan_names({"game": game, "week": {"start": start.isoformat(), "label": week_label(start, lang)},
                               "total": total, "top": top, "me": me}, lang)
