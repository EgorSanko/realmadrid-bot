"""Локальный бэкенд для проверок игр (Playwright): наш app.main с ФЕЙКОВЫМ токеном бота.

  python local_backend.py <DATA_DIR> <PORT>

* DATA_DIR — пустая папка: predictions.db создаётся заново; в ней болельщики и их результаты игр
  за текущую неделю (для «Лучших за неделю»). Аватары кладёт run.js в DATA_DIR/avatars.
* Только для проверки: POST /api/games/_test/script {keepers: [1..6], rival: [bool]} — задать
  прыжки вратаря и удары соперника, чтобы серия до промаха случилась наверняка. В продакшен-коде
  такого эндпоинта нет — он добавляется здесь, к объекту приложения.
"""
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA, PORT = sys.argv[1], int(sys.argv[2])
BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.update(DATA_DIR=DATA, BOT_TOKEN="123456:LOCAL-fake-bot-token", ADMIN_IDS="4242",
                  BOT_USERNAME="Real_Madrid_football_bot", SESSION_COOKIE_SECURE="1")
os.environ.pop("SESSION_SECRET", None)

import uvicorn  # noqa: E402
from fastapi import Request  # noqa: E402

from app.games import api as games_api  # noqa: E402
from app.games.service import iso, week_start  # noqa: E402
from app.main import app  # noqa: E402
from app.predictions import api as predict_api  # noqa: E402
from app.predictions.provider import FakeProvider  # noqa: E402


class ScriptedRng(random.Random):
    def __init__(self):
        super().__init__()
        self.keepers: list[int] = []
        self.rival: list[bool] = []

    def randint(self, a, b):
        return self.keepers.pop(0) if self.keepers else super().randint(a, b)

    def random(self):
        if self.rival:
            return 0.0 if self.rival.pop(0) else 0.999999
        return super().random()


RNG = ScriptedRng()


@app.post("/api/games/_test/script")
async def _script(request: Request):
    body = await request.json()
    RNG.keepers = [int(k) for k in body.get("keepers", [])]
    RNG.rival = [bool(r) for r in body.get("rival", [])]
    return {"ok": True}


def seed() -> None:
    Path(DATA).mkdir(parents=True, exist_ok=True)
    path = str(Path(DATA) / "predictions.db")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass
    svc = predict_api.configure(provider=FakeProvider(), db_path=path)
    games_api.configure(rng=RNG)
    people = {4242: ("Алексей", "Морозов", "madridista_alex"), 1001: ("Мария", None, "maria_rm"),
              1002: ("Дмитрий", "К", None), 1003: ("Сергей", None, "serg_bernabeu"),
              1004: ("Ольга", "Л", None), 1005: ("Пётр", None, "petr9"), 1006: ("Хави", None, "hala")}
    for uid, (f, l, u) in people.items():
        svc.upsert_user({"id": uid, "first_name": f, "last_name": l, "username": u})
    now = datetime.now(timezone.utc)
    wk = week_start(now).isoformat()
    rows = [  # (uid, game, level, score, detail)
        (1001, "quiz", "hard", 3920, {"correct": 9, "total": 10}), (1001, "quiz", "easy", 1650, {"correct": 8, "total": 10}),
        (1002, "quiz", "expert", 3480, {"correct": 6, "total": 10}), (1003, "quiz", "medium", 2215, {"correct": 8, "total": 10}),
        (1004, "quiz", "easy", 1290, {"correct": 7, "total": 10}), (1006, "quiz", "medium", 980, {"correct": 4, "total": 10}),
        (1001, "penalty", "hard", 2400, {"goals": 5, "rival": 3, "won": True}),
        (1005, "penalty", "legend", 2800, {"goals": 4, "rival": 3, "won": True}),
        (1003, "penalty", "medium", 1400, {"goals": 4, "rival": 2, "won": True}),
        (1004, "penalty", "easy", 300, {"goals": 3, "rival": 4, "won": False}),
    ]
    with svc.conn() as c:
        for uid, game, level, score, detail in rows:
            c.execute("INSERT INTO game_results(user_id, game, level, score, detail, week, created_at) VALUES (?,?,?,?,?,?,?)",
                      (uid, game, level, score, json.dumps(detail), wk, iso(now)))


if __name__ == "__main__":
    seed()
    print("seeded", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
