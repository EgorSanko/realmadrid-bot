import json
import os

import pytest

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name: str):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def sofa_bundle() -> dict:
    return {"event": load("sofa_event.json"), "incidents": load("sofa_incidents.json"),
            "lineups": load("sofa_lineups.json"), "statistics": load("sofa_statistics.json"),
            "shotmap": load("sofa_shotmap.json"), "graph": load("sofa_graph.json"), "best": load("sofa_best.json")}


def ls_bundle() -> dict:
    return {k: load(f"livescore_{k}_1882774.json") for k in ("scoreboard", "incidents", "lineups", "statistics")}


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "rm.sqlite3"))
    monkeypatch.setattr(config, "DISABLED_FILE", str(tmp_path / "disabled_sources"))
    monkeypatch.setattr(config, "HEARTBEAT_FILE", str(tmp_path / "hb"))
    monkeypatch.delenv("DISABLED_SOURCES", raising=False)
    return tmp_path
