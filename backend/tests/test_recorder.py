import json
import sqlite3

from app import recorder


def _db(tmp_path, events, live=True):
    conn = sqlite3.connect(tmp_path / "rm.sqlite3")
    conn.execute("CREATE TABLE IF NOT EXISTS snapshots(key TEXT PRIMARY KEY, source TEXT, fetched_at REAL, data TEXT)")
    fx = [{"id": 1, "status": {"live": live}}]
    m = {"id": 1, "home": {"name": "Real Madrid", "score": 1}, "away": {"name": "Sevilla", "score": 0},
         "events": events}
    for k, v in (("fixtures", fx), ("match:1", m)):
        conn.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)", (k, "t", 0, json.dumps(v)))
    conn.commit()
    conn.close()


def _goal(minute, name, side="home", **kw):
    return {"type": "goal", "minute": minute, "side": side, "player": {"id": minute, "name": name} if name else None, **kw}


def test_only_new_goals_make_clips(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder, "DATA", tmp_path)
    _db(tmp_path, [_goal(10, "Mbappe", score=[1, 0])])
    g = recorder.Goals()
    assert g.poll() == []                                    # гол до запуска — без ролика
    _db(tmp_path, [_goal(10, "Mbappe", score=[1, 0]), {"type": "yellow", "minute": 20},
                   _goal(23, "Vinicius", added=2, score=[2, 0])])
    new = g.poll()
    assert [x["label"] for x in new] == ["23+2' Vinicius"]
    assert new[0]["home"] == "Real Madrid"
    assert new[0]["goal_key"] == "1:home:23:2:23"
    assert g.poll() == []                                    # повторно тот же гол не ловим


def test_finished_match_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder, "DATA", tmp_path)
    _db(tmp_path, [], live=False)
    g = recorder.Goals()
    g.poll()
    _db(tmp_path, [_goal(5, "X")], live=False)
    assert g.poll() == []


def test_scorer_arrives_later_same_goal(tmp_path, monkeypatch):
    """Сначала гол без автора, через ~30 с тот же гол с автором (и сдвинутой минутой) — ролик один, имя свежее."""
    monkeypatch.setattr(recorder, "DATA", tmp_path)
    _db(tmp_path, [])
    g = recorder.Goals()
    g.poll()
    _db(tmp_path, [_goal(44, None, score=[1, 0])])
    first = g.poll()
    assert len(first) == 1 and first[0]["player"] == ""
    _db(tmp_path, [_goal(45, "Mbappe", score=[1, 0])])
    assert g.poll() == []
    job = recorder._refresh({**first[0], "at": 0})
    assert job["player"] == "Mbappe" and job["label"] == "45' Mbappe"
