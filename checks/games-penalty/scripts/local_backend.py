"""Локальный бэкенд для проверки пенальти (Playwright): наш app.main с ФЕЙКОВЫМ токеном бота.

  python local_backend.py <DATA_DIR> <PORT>

Только для проверки: POST /api/games/_test/script {keepers: [1..6], rival: [bool], woodwork: [bool], bar: [bool]}
— задать прыжки вратаря, удары соперника и попадания в каркас, чтобы снять нужные кадры (сейв, гол, штанга).
В продакшен-коде такого эндпоинта нет — он добавляется здесь, к объекту приложения.
"""
import os
import random
import sys
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
from app.main import app  # noqa: E402
from app.predictions import api as predict_api  # noqa: E402
from app.predictions.provider import FakeProvider  # noqa: E402


class ScriptedRng(random.Random):
    def __init__(self):
        super().__init__()
        self.keepers: list[int] = []
        self.rival: list[bool] = []
        self.woodwork: list[bool] = []
        self.bar: list[bool] = []

    def randint(self, a, b):
        return self.keepers.pop(0) if self.keepers else super().randint(a, b)

    def random(self):
        if self.rival:
            return 0.0 if self.rival.pop(0) else 0.999999
        return super().random()

    def getrandbits(self, k):
        if k == 10 and self.woodwork:
            return 0 if self.woodwork.pop(0) else 1023
        if k == 1 and self.bar:
            return 0 if self.bar.pop(0) else 1
        return super().getrandbits(k)


RNG = ScriptedRng()


@app.post("/api/games/_test/script")
async def _script(request: Request):
    body = await request.json()
    RNG.keepers = [int(k) for k in body.get("keepers", [])]
    RNG.rival = [bool(r) for r in body.get("rival", [])]
    RNG.woodwork = [bool(r) for r in body.get("woodwork", [])]
    RNG.bar = [bool(r) for r in body.get("bar", [])]
    return {"ok": True}


def seed() -> None:
    Path(DATA).mkdir(parents=True, exist_ok=True)
    path = str(Path(DATA) / "predictions.db")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass
    predict_api.configure(provider=FakeProvider(), db_path=path)
    games_api.configure(rng=RNG)


if __name__ == "__main__":
    seed()
    print("seeded", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
