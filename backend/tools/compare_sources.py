"""Сравнение 4 источников на одном матче (сохранённые ответы, Рома 3:4 Реал).

    python -m tools.compare_sources        (из каталога backend)
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.sources import espn, fotmob, livescore, sofascore  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures")


def load(n):
    with open(os.path.join(FIX, n), encoding="utf-8") as f:
        return json.load(f)


def main():
    ms = {
        "FotMob": fotmob.normalize_match(load("fotmob_match_6106274.json")),
        "SofaScore": sofascore.normalize_match({k: load(f"sofa_{v}.json") for k, v in {
            "event": "event", "incidents": "incidents", "lineups": "lineups", "statistics": "statistics",
            "shotmap": "shotmap", "graph": "graph", "best": "best"}.items()}),
        "ESPN": espn.normalize_match(load("espn_summary_401915414.json")),
        "LiveScore": livescore.normalize_match({k: load(f"livescore_{k}_1882774.json")
                                                for k in ("scoreboard", "incidents", "lineups", "statistics")}),
    }

    def stat(m, k):
        x = next((s for s in (m["stats"] or {}).get("all", []) if s["key"] == k), None)
        return f"{x['home']}–{x['away']}" if x else "—"

    def goals(m):
        return [e for e in m["events"] if e["type"] == "goal"]

    rows = [
        ("id матча", lambda m: str(m["ids"].get({"fotmob": "fotmob", "sofascore": "sofascore", "espn": "espn",
                                                 "livescore": "livescore"}[m["source"]]))),
        ("счёт", lambda m: f"{m['home']['score']}:{m['away']['score']} (тайм {m['home']['ht_score']}:{m['away']['ht_score']})"),
        ("число голов", lambda m: str(len(goals(m)))),
        ("авторы голов (мин.)", lambda m: ", ".join(f"{g['player']['name'].split()[-1]} {g['minute']}'" for g in goals(m))),
        ("голов с ассистом", lambda m: str(sum(1 for g in goals(m) if g.get("assist")))),
        ("удары всего", lambda m: stat(m, "shots_total")),
        ("в створ", lambda m: stat(m, "shots_on_target")),
        ("xG", lambda m: stat(m, "xg")),
        ("точек на карте ударов", lambda m: str(len(m["shots"])) + (" (с xG)" if any(s["xg"] for s in m["shots"]) else "")),
        ("оценки игроков", lambda m: "да" if "ratings" in m["available"] else "нет"),
        ("координаты на поле", lambda m: "да" if "lineup_positions" in m["available"] else "нет"),
        ("давление (точек)", lambda m: str(len(m["momentum"])) if m["momentum"] else "нет"),
        ("игрок матча", lambda m: f"{m['potm']['name']} {m['potm']['rating']}" if m["potm"] else "нет"),
        ("карточки / замены", lambda m: f"{sum(e['type'] == 'card' for e in m['events'])} / {sum(e['type'] == 'sub' for e in m['events'])}"),
        ("VAR-события", lambda m: str(sum(e["type"] == "var" for e in m["events"]))),
        ("available", lambda m: str(len(m["available"]))),
    ]
    names = list(ms)
    print("| поле | " + " | ".join(names) + " |")
    print("|---|" + "---|" * len(names))
    for title, fn in rows:
        print(f"| {title} | " + " | ".join(fn(ms[n]) for n in names) + " |")


if __name__ == "__main__":
    main()
