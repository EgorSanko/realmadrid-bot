"""Итоги игр: сохранение для вошедших, рекорды по игре и уровню, рейтинг недели, отдельность от прогнозов."""
import sqlite3
from datetime import timedelta

from app.auth import issue_session
from app.games.service import QUIZ_ROUND, week_label, week_start
from app.predictions import db

from .conftest import correct_choice, tma


def play_quiz(client, mono, headers, right: int, level="easy"):
    sid = client.post("/api/games/quiz/start", json={"level": level}, headers=headers).json()["session"]
    r = None
    for i in range(QUIZ_ROUND):
        q = client.post(f"/api/games/quiz/{sid}/next", headers=headers).json()
        mono.t += 2
        choice = correct_choice(q) if i < right else (correct_choice(q) + 1) % 4
        r = client.post(f"/api/games/quiz/{sid}/answer", json={"choice": choice}, headers=headers).json()
    assert r["done"]
    return r["result"]


def play_penalty(client, mono, rng, headers, keepers, rival, level="easy"):
    sid = client.post("/api/games/penalty/start", json={"level": level}, headers=headers).json()["session"]
    rng.keepers, rng.rival = list(keepers), list(rival)
    while True:
        mono.t += 1
        r = client.post(f"/api/games/penalty/{sid}/shot", json={"zone": 1}, headers=headers).json()
        if r["done"]:
            return r["result"]


def test_migration_v4(env):
    conn = db.connect(str(env / "x.db"))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(game_results)")}
    assert {"user_id", "game", "level", "score", "detail", "week", "created_at"} <= cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 4
    try:
        conn.execute("INSERT INTO game_results(user_id, game, level, score, week, created_at) "
                     "VALUES (1, 'darts', 'easy', 1, 'w', 't')")
        raise AssertionError("CHECK по game не сработал")
    except sqlite3.IntegrityError:
        pass


def test_anonymous_not_saved(client, mono, svc):
    res = play_quiz(client, mono, {}, right=5)
    assert res["saved"] is False and res["best"] is None
    with svc.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM game_results").fetchone()[0] == 0
    assert client.get("/api/games/me").status_code == 401


def test_logged_in_saved_best_and_record(client, mono, rng):
    h = tma(101, first_name="Иван", last_name="Петров")
    r1 = play_quiz(client, mono, h, right=6)
    assert r1["saved"] and r1["record"] and r1["best"] == r1["score"] > 0
    r2 = play_quiz(client, mono, h, right=2)
    assert r2["saved"] and not r2["record"] and r2["best"] == r1["score"]
    r3 = play_quiz(client, mono, h, right=4, level="hard")
    assert r3["record"]
    p = play_penalty(client, mono, rng, h, [6] * 5, [False] * 5)
    assert p["saved"] and p["won"] and p["score"] == 5 * 100 + 300

    me = client.get("/api/games/me", headers=h).json()
    assert me["best"]["quiz"]["easy"] == {"best": r1["score"], "played": 2}
    assert me["best"]["quiz"]["hard"]["best"] == r3["score"]
    assert me["best"]["penalty"]["easy"]["best"] == p["score"]
    assert me["week"]["quiz"] == {"best": max(r1["score"], r3["score"]), "played": 3}


def test_session_login_works(client, mono, svc):
    svc.upsert_user({"id": 202, "first_name": "Сайт"})
    token, _ = issue_session(202, svc.session_epoch(202))
    h = {"Authorization": f"Session {token}"}
    assert play_quiz(client, mono, h, right=3)["saved"] is True


def test_weekly_leaderboard(client, mono, rng, clock, svc):
    a, b, c = tma(1, first_name="Анна"), tma(2, first_name="Борис"), tma(3, first_name="Вера")
    sa = play_quiz(client, mono, a, right=8)["score"]
    play_quiz(client, mono, a, right=1)
    sb = play_quiz(client, mono, b, right=3)["score"]
    play_penalty(client, mono, rng, c, [6] * 5, [False] * 5)

    lb = client.get("/api/games/leaderboard?game=quiz", headers=b).json()
    start = week_start(clock())
    assert lb["week"] == {"start": start.isoformat(), "label": week_label(start)}
    assert lb["total"] == 2
    assert [(r["rank"], r["name"], r["score"], r["played"]) for r in lb["top"]] == [(1, "Анна", sa, 2), (2, "Борис", sb, 1)]
    assert [r["is_me"] for r in lb["top"]] == [False, True]
    assert all("avatar" in r and "level" in r for r in lb["top"])
    assert lb["me"] == {"rank": 2, "score": sb, "played": 1}

    pen = client.get("/api/games/leaderboard?game=penalty").json()
    assert [r["name"] for r in pen["top"]] == ["Вера"] and pen["me"] is None
    assert client.get("/api/games/leaderboard?game=chess").status_code == 400
    assert client.get("/api/games/leaderboard?game=quiz&limit=0").status_code == 422

    # новая неделя — рейтинг с нуля, рекорды остаются
    clock.set(clock() + timedelta(days=7))
    lb2 = client.get("/api/games/leaderboard?game=quiz", headers=a).json()
    assert lb2["top"] == [] and lb2["me"] == {"rank": None, "score": 0, "played": 0}
    assert client.get("/api/games/me", headers=a).json()["best"]["quiz"]["easy"]["best"] == sa


def test_games_do_not_touch_predictions(client, mono, rng, svc):
    h = tma(7)
    play_quiz(client, mono, h, right=10)
    play_penalty(client, mono, rng, h, [6] * 5, [False] * 5)
    with svc.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM standings").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0
    me = client.get("/api/predict/me", headers=h).json()
    assert me["season"]["points"] == 0
    lb = client.get("/api/predict/leaderboard").json()
    assert lb["total"] == 0 and lb["top"] == []
