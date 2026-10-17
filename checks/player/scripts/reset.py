"""Перед прогоном сценариев: убрать снимок чужого игрока (Dybala), чтобы снова увидеть pending."""
import os
import sys

sys.path.insert(0, r"C:\Users\egor3\Projects\rm-v2\.claude\worktrees\agent-ac6fdf250a955bc40\backend")
from app import config, store  # noqa: E402

config.DATA_DIR = r"C:\Users\egor3\AppData\Local\Temp\claude\C--Users-egor3-Projects\55f22295-6a88-466e-bf97-572f0c3bc385\scratchpad\data"
config.DB_PATH = os.path.join(config.DATA_DIR, "rm.sqlite3")
c = store.connect()
n = c.execute("DELETE FROM snapshots WHERE key='player:325916' OR key LIKE 'player_fail:%'").rowcount
print("reset", n)
