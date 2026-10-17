"""Локальный «сборщик» только для карточек: раз в секунду — такт tick_players (заявки API + состав).
Запуск: DATA_DIR=... python player_worker.py [seconds]"""
import asyncio
import logging
import sys
import time

sys.path.insert(0, r"C:\Users\egor3\Projects\rm-v2\.claude\worktrees\agent-ac6fdf250a955bc40\backend")
from app import store  # noqa: E402
from app.collector import Collector  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)


async def main(seconds: float):
    conn = store.connect()
    c = Collector(conn)
    if not store.get(conn, "team"):
        print("team:", await c.refresh_team(), flush=True)
    end = time.time() + seconds
    try:
        while time.time() < end:
            done = await c.tick_players(time.time(), squad=False)
            if done:
                print("done", done, flush=True)
            await asyncio.sleep(1)
    finally:
        await c.close()


asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 600))
