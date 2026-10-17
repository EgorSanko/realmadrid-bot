"""Пенальти: серия из пяти, серия до промаха при ничьей, вратарь решает на сервере, частота ударов."""
import pytest

from app.games.service import PENALTY_MIN_INTERVAL, penalty_score


def start(client, level="medium", headers=None):
    r = client.post("/api/games/penalty/start", json={"level": level}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()["session"]


def shoot(client, mono, sid, zone, headers=None):
    mono.t += PENALTY_MIN_INTERVAL + 0.5
    r = client.post(f"/api/games/penalty/{sid}/shot", json={"zone": zone}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def test_five_shots_win(client, mono, rng):
    sid = start(client)
    # вратарь: 1-й и 4-й удар угадал зону; соперник: забил 2 из 5
    rng.keepers = [3, 1, 1, 5, 2]
    rng.rival = [True, False, True, False, False]
    zones = [3, 4, 6, 5, 1]
    out = [shoot(client, mono, sid, z) for z in zones]
    assert [o["goal"] for o in out] == [False, True, True, False, True]
    assert [o["keeper"] for o in out] == [3, 1, 1, 5, 2]
    assert all(o["phase"] == "regular" for o in out)
    assert [o["done"] for o in out] == [False] * 4 + [True]
    last = out[-1]
    assert (last["goals"], last["rival"]) == (3, 2)
    res = last["result"]
    assert res["won"] and not res["sudden"] and res["shots"] == 5
    assert res["score"] == penalty_score("medium", 3, True) == (300 + 300) * 2
    assert res["saved"] is False
    r = client.post(f"/api/games/penalty/{sid}/shot", json={"zone": 1})
    assert r.status_code == 409


def test_tie_goes_to_sudden_death_until_miss(client, mono, rng):
    sid = start(client, "legend")
    rng.keepers = [6, 6, 6, 6, 6, 6, 6, 2]       # пять голов, затем гол, затем сейв на 8-м
    rng.rival = [True] * 5 + [True, True, True]
    out = [shoot(client, mono, sid, 1) for _ in range(7)]
    assert (out[4]["goals"], out[4]["rival"]) == (5, 5) and not out[4]["done"] and out[4]["sudden_next"]
    assert out[5]["phase"] == "sudden" and not out[5]["done"]
    last = shoot(client, mono, sid, 2)
    assert last["round"] == 8 and not last["goal"] and last["rival_goal"] and last["done"]
    res = last["result"]
    assert not res["won"] and res["sudden"] and (res["goals"], res["rival"]) == (7, 8)
    assert res["score"] == penalty_score("legend", 7, False) == 700 * 4


def test_sudden_death_player_wins(client, mono, rng):
    sid = start(client, "easy")
    rng.keepers = [1, 1, 6, 6, 6, 6]   # 3 из 5, в серии — гол
    rng.rival = [True, True, True, False, False, False]
    out = [shoot(client, mono, sid, 1) for _ in range(6)]
    assert not out[4]["done"] and out[5]["done"] and out[5]["result"]["won"]


def test_shot_validation_and_rate(client, mono):
    sid = start(client)
    for bad in (0, 7, "1", None, True, 2.0):
        r = client.post(f"/api/games/penalty/{sid}/shot", json={"zone": bad})
        assert r.status_code == 400, bad
    shoot(client, mono, sid, 2)
    r = client.post(f"/api/games/penalty/{sid}/shot", json={"zone": 2})   # сразу второй — быстрее анимации
    assert r.status_code == 429 and r.json()["error"] == "too_fast"
    assert client.post("/api/games/penalty/start", json={"level": "hard!"}).status_code == 400
    # сессия викторины не годится для пенальти и наоборот
    qsid = client.post("/api/games/quiz/start", json={"level": "easy"}).json()["session"]
    assert client.post(f"/api/games/penalty/{qsid}/shot", json={"zone": 1}).status_code == 404
    assert client.post(f"/api/games/quiz/{sid}/next").status_code == 404


@pytest.mark.parametrize("level", ["easy", "medium", "hard", "legend"])
def test_keeper_uniform_like_old_game(games, level):
    """Вратарь прыгает равновероятно по 6 зонам: доля голов ≈ 5/6 (как 4/5 в старой игре с 5 зонами)."""
    import random
    games.rng = random.Random(level)
    games.mono = lambda: games._t
    games._t = 0.0
    games.start_limiter.hit = games.action_limiter.hit = lambda key: True
    goals = shots = 0
    for _ in range(400):
        sid = games.penalty_start(level, None, ("ip", "x"))["session"]
        while True:
            games._t += 1
            r = games.penalty_shot(sid, 1 + shots % 6, None, ("ip", "x"))
            shots += 1
            goals += r["goal"]
            if r["done"]:
                break
    assert 0.79 < goals / shots < 0.88
