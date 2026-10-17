"""Локальный бэкенд для проверки входа по коду (Playwright): наш app.main с ФЕЙКОВЫМ токеном бота.

  python local_backend.py <DATA_DIR> <PORT>

Только для проверки (в продакшен-коде этих эндпоинтов нет — они добавляются здесь к объекту приложения):
  POST /api/_test/bot_update {user: {...}, text}  — «бот получил сообщение»: настоящий обработчик апдейта
       app.bot.TelegramBot.handle_update с фейковым транспортом Bot API. Ответ — что бот вызвал бы
       (sendMessage и т. п.), в Telegram ничего не уходит.
  POST /api/_test/ttl {seconds}                   — срок жизни новых кодов (проверка истечения).
"""
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

DATA, PORT = sys.argv[1], int(sys.argv[2])
BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.update(DATA_DIR=DATA, BOT_TOKEN="123456:LOCAL-fake-bot-token", ADMIN_IDS="4242",
                  BOT_USERNAME="Real_Madrid_football_bot", SESSION_COOKIE_SECURE="1")
os.environ.pop("SESSION_SECRET", None)

import uvicorn  # noqa: E402
from fastapi import Request  # noqa: E402

from app import login_codes  # noqa: E402
from app.bot import TelegramBot  # noqa: E402
from app.main import app  # noqa: E402
from app.predictions import api as predict_api  # noqa: E402
from app.predictions.provider import FakeProvider  # noqa: E402

CALLS: list = []
_seq = [int(time.time())]


async def fake_api(method: str, payload: dict, timeout: float) -> dict:
    CALLS.append([method, payload])
    if method == "getUserProfilePhotos":
        return {"ok": True, "result": {"total_count": 1, "photos": [[
            {"file_id": "AgADfake320", "file_unique_id": "uniqFake", "width": 320, "height": 320}]]}}
    return {"ok": True, "result": {"message_id": len(CALLS)}}


BOT = TelegramBot(transport=fake_api, db_path=str(Path(DATA) / "predictions.db"))


@app.post("/api/_test/bot_update")
async def _bot_update(request: Request):
    body = await request.json()
    user = body["user"]
    _seq[0] += 1
    upd = {"update_id": _seq[0], "message": {"message_id": _seq[0], "from": {"is_bot": False, **user},
                                             "chat": {"id": user["id"], "type": "private"},
                                             "date": int(time.time()), "text": body["text"]}}
    start = len(CALLS)
    sent = await BOT.handle_update(upd)
    return {"sent": sent, "calls": CALLS[start:]}


@app.post("/api/_test/ttl")
async def _ttl(request: Request):
    login_codes.CODE_TTL = timedelta(seconds=float((await request.json())["seconds"]))
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


if __name__ == "__main__":
    seed()
    print("seeded", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
