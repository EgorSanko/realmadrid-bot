"""Локальный бэкенд для проверок входа (Playwright): наш app.main с ФЕЙКОВЫМ токеном бота.

  python local_backend.py <DATA_DIR> <PORT> <avatar.jpg>

* DATA_DIR — пустая папка: predictions.db создаётся заново и заполняется тестовыми данными
  (реальные матчи Реала октября 2026, прогнозы, рейтинг, лиги). Коды лиг — в DATA_DIR/seed.json.
* Матчи для API прогнозов — как на сервере сейчас: SnapshotProvider (503 на /api/predict/matches).
* «Сборщик» аватаров: фоновый поток обрабатывает avatar_queue настоящим avatars.process, но вместо
  туннеля к t.me — подставной fetch: t.me/i/userpic/… → 302 на cdn4.telesco.pe → байты <avatar.jpg>.
"""
import asyncio
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA, PORT, AVATAR_SRC = sys.argv[1], int(sys.argv[2]), sys.argv[3]
BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.update(DATA_DIR=DATA, BOT_TOKEN="123456:LOCAL-fake-bot-token", ADMIN_IDS="4242",
                  BOT_USERNAME="Real_Madrid_football_bot", SESSION_COOKIE_SECURE="1")
os.environ.pop("SESSION_SECRET", None)

import uvicorn  # noqa: E402

from app import avatars  # noqa: E402
from app.main import app  # noqa: E402
from app.predictions import db  # noqa: E402
from app.predictions.provider import FakeProvider  # noqa: E402
from app.predictions.service import PredictionService  # noqa: E402

RM = {"id": 8633, "name": "Реал Мадрид"}


class Clock:
    def __init__(self):
        self.t = datetime.now(timezone.utc)

    def __call__(self):
        return self.t


def seed() -> dict:
    Path(DATA).mkdir(parents=True, exist_ok=True)
    path = str(Path(DATA) / "predictions.db")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass
    clock = Clock()
    prov = FakeProvider()
    svc = PredictionService(prov, db_path=path, clock=clock, bot_username="Real_Madrid_football_bot")
    people = {4242: ("Алексей", "Морозов", "madridista_alex"), 1001: ("Мария", None, "maria_rm"),
              1002: ("Дмитрий", "К", None), 1003: ("Сергей", None, "serg_bernabeu"),
              1004: ("Ольга", "Л", None), 1005: ("Пётр", None, "petr9")}
    for uid, (f, l, u) in people.items():
        svc.upsert_user({"id": uid, "first_name": f, "last_name": l, "username": u})
    # реальные матчи (id FotMob, эмблемы /img/team/{id}.png); прогнозы делаются «до начала»
    games = [
        ("5868072", datetime(2026, 9, 20, 14, 15, tzinfo=timezone.utc), {"id": 9906, "name": "Атлетико"}, False, (2, 1)),
        ("5868089", datetime(2026, 10, 10, 19, 0, tzinfo=timezone.utc), {"id": 10205, "name": "Вильярреал"}, True, (1, 0)),
        ("6106274", datetime(2026, 10, 14, 19, 0, tzinfo=timezone.utc), {"id": 8686, "name": "Рома"}, False, (3, 4)),
    ]
    picks = {  # uid → [(home, away) по играм]
        4242: [(1, 2), (1, 0), (2, 3)], 1001: [(2, 1), (2, 0), (3, 4)], 1002: [(0, 2), (1, 1), (1, 2)],
        1003: [(1, 1), (2, 0), (2, 2)], 1004: [(3, 0), (0, 0), (1, 3)], 1005: [(2, 2), (3, 1), (0, 1)],
    }
    for i, (mid, ko, opp, rm_home, score) in enumerate(games):
        m = {"id": mid, "kickoff_utc": ko.strftime("%Y-%m-%dT%H:%M:%SZ"), "home": RM if rm_home else opp,
             "away": opp if rm_home else RM, "status": "scheduled", "score": None,
             "first_rm_scorer_player_id": None, "rm_squad": []}
        prov.put(m)
        clock.t = ko - timedelta(hours=3)
        for uid, ps in picks.items():
            svc.put_prediction(uid, mid, *ps[i])
        prov.update(mid, status="finished", score={"home": score[0], "away": score[1]})
        clock.t = ko + timedelta(hours=3)
        svc.settle(mid)
    # ближайший матч: прогноз ещё можно менять
    nxt = datetime(2026, 10, 18, 19, 0, tzinfo=timezone.utc)
    prov.put({"id": "5868098", "kickoff_utc": nxt.strftime("%Y-%m-%dT%H:%M:%SZ"), "home": RM,
              "away": {"id": 8302, "name": "Севилья"}, "status": "scheduled", "score": None, "rm_squad": []})
    clock.t = datetime.now(timezone.utc)
    svc.put_prediction(4242, "5868098", 3, 1)
    own = svc.create_league(4242, "Пенья Бернабеу")
    for uid in (1001, 1002):
        svc.join_league(uid, own["code"])
    office = svc.create_league(1003, "Офис · Мадрид")
    svc.join_league(1004, office["code"])
    info = {"own_code": own["code"], "office_code": office["code"], "office_name": office["name"]}
    (Path(DATA) / "seed.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


async def fake_fetch(url: str):
    """Подмена туннеля: userpic t.me → редирект на CDN Telegram → файл-картинка."""
    if url.startswith("https://t.me/i/userpic/"):
        return 302, {"location": "https://cdn4.telesco.pe/file/" + url.rsplit("/", 1)[-1]}, None
    if url.startswith("https://cdn4.telesco.pe/file/"):
        body = Path(AVATAR_SRC).read_bytes()
        return 200, {"content-type": "image/jpeg", "content-length": str(len(body))}, body
    return 404, {}, None


def avatar_worker():
    while True:
        try:
            conn = db.connect(str(Path(DATA) / "predictions.db"))
            try:
                for uid, res in asyncio.run(avatars.process(conn, fake_fetch, limit=5)):
                    print(f"[avatar] {uid}: {res}", flush=True)
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            print("[avatar] ошибка", e, flush=True)
        time.sleep(1)


if __name__ == "__main__":
    print("seed:", seed(), flush=True)
    threading.Thread(target=avatar_worker, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
