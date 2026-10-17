"""Локальный бэкенд для проверок прогнозов (Playwright): наш app.main с ФЕЙКОВЫМ токеном бота.

  python local_backend.py <DATA_DIR> <PORT> <rm.sqlite3 — копия снимков с сервера> <avatar.jpg>

* DATA_DIR — пустая папка. Туда копируется rm.sqlite3 (снимки сборщика с сервера, только чтение там),
  predictions.db создаётся заново: пользователи и их прогнозы на уже сыгранные матчи Реала (по настоящим
  итогам из снимков), очки начислены настоящим settle.
* /api/predict/* — настоящий PredictionService с SnapshotProvider на этой копии (как будет на сервере).
* Управление для сценариев (только здесь, не в приложении):
    POST /__ctl/kickoff?min=N    ближайший матч начинается через N минут (N<0 — уже начался, статус live)
    POST /__ctl/finish?home=H&away=A&scorer=ID   ближайший матч завершён с таким счётом и первым голом
    POST /__ctl/settle           то, что делает сборщик: settle_pending()
"""
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA, PORT, SNAP, AVATAR = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))


def fresh_files() -> None:
    Path(DATA).mkdir(parents=True, exist_ok=True)
    for name in ("rm.sqlite3", "rm.sqlite3-wal", "rm.sqlite3-shm", "predictions.db", "predictions.db-wal",
                 "predictions.db-shm"):
        try:
            os.remove(Path(DATA) / name)
        except FileNotFoundError:
            pass
    shutil.copyfile(SNAP, Path(DATA) / "rm.sqlite3")


fresh_files()
os.environ.update(DATA_DIR=DATA, BOT_TOKEN="123456:LOCAL-fake-bot-token", ADMIN_IDS="4242",
                  BOT_USERNAME="Real_Madrid_football_bot", SESSION_COOKIE_SECURE="1")
os.environ.pop("SESSION_SECRET", None)

import uvicorn  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app import config, store  # noqa: E402
from app.main import app  # noqa: E402
from app.predictions import api  # noqa: E402
from app.predictions.provider import FakeProvider  # noqa: E402
from app.predictions.service import PredictionService  # noqa: E402
from app.predictions.snapshot_provider import SnapshotProvider  # noqa: E402

assert config.DB_PATH == os.path.join(DATA, "rm.sqlite3"), config.DB_PATH
SNAPS = SnapshotProvider()
PDB = str(Path(DATA) / "predictions.db")
SVC = api.configure(provider=SNAPS, db_path=PDB, bot_username="Real_Madrid_football_bot")

PEOPLE = {4242: ("Алексей", "Морозов", "madridista_alex"), 1001: ("Мария", None, "maria_rm"),
          1002: ("Дмитрий", "К", None), 1003: ("Сергей", None, "serg_bernabeu"),
          1004: ("Ольга", "Л", None), 1005: ("Пётр", None, "petr9"), 5005: ("Иван", "Друг", "ivan_friend")}
# ещё болельщики, чтобы рейтинг был длиннее показанного топа-10
FANS = {2001 + i: (n, None, None) for i, n in enumerate(
    ["Хорхе", "Анна", "Карим", "Лука", "Тони", "Серхио", "Икер", "Рауль", "Гути", "Марсело"])}


def seed() -> dict:
    """Прогнозы других болельщиков на три последних сыгранных матча — по настоящим итогам снимков."""
    recent = SNAPS.recent(3)
    fake = FakeProvider()
    clock = {"t": datetime.now(timezone.utc)}
    svc = PredictionService(fake, db_path=PDB, clock=lambda: clock["t"], bot_username="Real_Madrid_football_bot")
    for uid, (f, l, u) in {**PEOPLE, **FANS}.items():
        svc.upsert_user({"id": uid, "first_name": f, "last_name": l, "username": u})
    picks = {1001: [(2, 1), (3, 4), (1, 0)], 1002: [(1, 1), (2, 3), (2, 0)], 1003: [(0, 2), (3, 3), (1, 1)],
             1004: [(3, 1), (1, 2), (0, 0)], 1005: [(2, 2), (4, 3), (2, 1)],
             4242: [(0, 0), (0, 0), (0, 2)]}  # у «меня» мало очков — я ниже топа-10, пока не сыграна Севилья
    variants = [(3, 4), (1, 0), (2, 1), (1, 2), (2, 0), (0, 1), (1, 1), (3, 1)]
    for k, uid in enumerate(FANS):
        picks[uid] = [variants[(k + j) % len(variants)] for j in range(3)]
    out = []
    for i, real in enumerate(recent):
        ko = datetime.fromisoformat(real["kickoff_utc"].replace("Z", "+00:00"))
        fake.put({**real, "status": "scheduled", "score": None, "first_rm_scorer_player_id": None})
        clock["t"] = ko - timedelta(hours=2)
        for uid, ps in picks.items():
            sc = real["first_rm_scorer_player_id"] if uid in (1001, 1004) else None
            if sc is not None and (ps[i][1] if not real["rm_is_home"] else ps[i][0]) == 0:
                sc = None
            if sc is not None and str(sc) not in {str(x["id"]) for x in real["rm_squad"]}:
                sc = None
            svc.put_prediction(uid, real["id"], *ps[i], sc)
        fake.put(real)
        clock["t"] = ko + timedelta(hours=3)
        out.append({"id": real["id"], "settle": svc.settle(real["id"])["result"], "score": real["score"]})
    # аватары двоим (файл как у сборщика), остальным — силуэт
    (Path(DATA) / "avatars").mkdir(exist_ok=True)
    for uid in (4242, 1001):
        shutil.copyfile(AVATAR, Path(DATA) / "avatars" / f"{uid}.jpg")
    return {"recent": out, "next": (SNAPS.upcoming(1) or [{}])[0].get("id")}


def _next_id() -> str:
    return SNAPS.upcoming(1)[0]["id"]


def _edit_match(mid: str, fn) -> None:
    conn = store.connect()
    try:
        fx = store.get(conn, "fixtures")
        rows = fx["data"]
        row = next(f for f in rows if str(f["id"]) == mid)
        snap = store.get(conn, f"match:{mid}")
        m = snap["data"] if snap else None
        fn(row, m)
        store.put(conn, "fixtures", fx["source"], rows)
        if m is not None:
            store.put(conn, f"match:{mid}", snap["source"], m)
    finally:
        conn.close()


@app.post("/__ctl/kickoff")
def ctl_kickoff(min: float):  # noqa: A002
    mid = _next_id()
    ko = (datetime.now(timezone.utc) + timedelta(minutes=min)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def fn(row, m):
        for x in (row, m):
            if x is None:
                continue
            x["kickoff"] = ko
            if min < 0:
                x["status"] = {"state": "live", "live": True, "finished": False, "minute": int(-min) + 1,
                               "added": None, "label": f"{int(-min) + 1}'"}
                x["home"]["score"], x["away"]["score"] = 0, 0
    _edit_match(mid, fn)
    return {"id": mid, "kickoff": ko}


@app.post("/__ctl/score")
def ctl_score(home: int, away: int, scorer: int | None = None, minute: int = 30):
    """Идёт матч: текущий счёт и (по желанию) гол Реала игроком scorer."""
    mid = _next_id()

    def fn(row, m):
        for x in (row, m):
            if x is not None:
                x["home"]["score"], x["away"]["score"] = home, away
        if m is not None:
            m["events"] = [e for e in m.get("events") or [] if e.get("type") != "goal"]
            if scorer:
                side = "home" if row.get("is_home") else "away"
                m["events"].append({"type": "goal", "minute": minute, "added": None, "side": side,
                                    "player": {"id": scorer, "name": "", "photo": None}, "assist": None,
                                    "own_goal": False, "penalty": False, "shootout": False, "score": [home, away]})
    _edit_match(mid, fn)
    return {"id": mid}


@app.post("/__ctl/finish")
def ctl_finish(home: int, away: int, scorer: int | None = None):
    mid = SNAPS.upcoming(1)[0]["id"]
    ctl_score(home, away, scorer)

    def fn(row, m):
        for x in (row, m):
            if x is not None:
                x["status"] = {"state": "finished", "live": False, "finished": True, "minute": None, "added": None,
                               "label": "FT"}
    _edit_match(mid, fn)
    return {"id": mid}


@app.post("/__ctl/settle")
def ctl_settle():
    return [r for r in SVC.settle_pending() if r["result"] != "unchanged"]


@app.post("/__ctl/reset")
def ctl_reset():
    """Начать сценарии заново: свежая копия снимков и predictions.db."""
    with SNAPS._lock:
        SNAPS._cache.clear()
    fresh_files()
    return seed()


@app.get("/__ctl/state")
def ctl_state(request: Request):
    return JSONResponse({"next": SNAPS.upcoming(1), "recent": [m["id"] for m in SNAPS.recent(3)]})


if __name__ == "__main__":
    print("seed:", json.dumps(seed(), ensure_ascii=False), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
