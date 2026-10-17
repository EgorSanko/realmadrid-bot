"""Новые поля API из локального бэкенда (на сервере их ещё нет).

Берёт свежий ответ FotMob через наш источник app.sources.fotmob, прогоняет локальную
нормализацию и сохраняет для каждого матча только новые поля: venue, referee_country, form.
Плюс /api/team: venue (с флагом). Обвязка Playwright подмешивает их в ответы сервера.

Запуск: python local_api.py OUT_DIR MATCH_ID [MATCH_ID ...]
"""
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "backend")))

from app.sources import fotmob  # noqa: E402


async def main(out: str, ids: list[str]):
    os.makedirs(out, exist_ok=True)
    src = fotmob.FotMob()
    try:
        for mid in ids:
            raw = await src.match(mid)
            m = fotmob.normalize_match(raw)
            part = {k: m.get(k) for k in ("venue", "referee", "referee_country", "form")}
            with open(os.path.join(out, f"match_{mid}.json"), "w", encoding="utf-8") as f:
                json.dump(part, f, ensure_ascii=False, indent=1)
            print(mid, "venue:", part["venue"], "| ref:", part["referee_country"],
                  "| form opp:", [x.get("opponent") for x in (part["form"] or {}).get("home", [])][:2])
        raw = await src.team()
        t = fotmob.normalize_team(raw)
        with open(os.path.join(out, "team.json"), "w", encoding="utf-8") as f:
            json.dump({"venue": t.get("venue")}, f, ensure_ascii=False, indent=1)
        print("team venue:", t.get("venue"))
    finally:
        await src.close()


asyncio.run(main(sys.argv[1], sys.argv[2:]))
