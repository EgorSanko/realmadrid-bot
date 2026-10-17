"""Пенальти: серия из пяти, серия до промаха при ничьей, вратарь решает на сервере, частота ударов."""
import pytest

from app.games.service import PENALTY_CORNERS, PENALTY_MIN_INTERVAL, PENALTY_WOODWORK, penalty_score


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
    rng.woodwork = [False] * 5
    zones = [3, 4, 6, 5, 1]
    out = [shoot(client, mono, sid, z) for z in zones]
    assert [o["goal"] for o in out] == [False, True, True, False, True]
    assert [o["keeper"] for o in out] == [3, 1, 1, 5, 2]
    assert [o["outcome"] for o in out] == ["save", "goal", "goal", "save", "goal"]
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
    rng.woodwork = [False] * 8                   # удары в угол 1 — без штанги
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
    rng.woodwork = [False] * 6
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
    """Вратарь прыгает равновероятно по 6 зонам: доля голов ≈ 5/6 (как 4/5 в старой игре с 5 зонами),
    минус редкие попадания в каркас при ударах в углы (4 зоны из 6)."""
    import random
    games.rng = random.Random(level)
    games.mono = lambda: games._t
    games._t = 0.0
    games.start_limiter.hit = games.action_limiter.hit = lambda key: True
    goals = shots = wood = 0
    for _ in range(400):
        sid = games.penalty_start(level, None, ("ip", "x"))["session"]
        while True:
            games._t += 1
            r = games.penalty_shot(sid, 1 + shots % 6, None, ("ip", "x"))
            shots += 1
            goals += r["goal"]
            wood += r["outcome"] in ("post", "bar")
            if r["done"]:
                break
    expect = 5 / 6 * (1 - PENALTY_WOODWORK * 4 / 6)
    assert abs(goals / shots - expect) < 0.045
    assert 0.5 * PENALTY_WOODWORK < wood / shots / (5 / 6 * 4 / 6) < 1.8 * PENALTY_WOODWORK


def test_woodwork_only_in_corners_and_is_a_miss(client, mono, rng):
    sid = start(client)
    rng.keepers = [2, 2, 5, 1, 6]
    rng.woodwork = [True, True, True, False]
    rng.bar = [True, False]
    rng.rival = [False] * 5
    out = [shoot(client, mono, sid, z) for z in (1, 3, 6, 5, 4)]
    # 1, 3 — верхние углы: перекладина, затем штанга; 6 — нижний угол: штанга
    assert [o["outcome"] for o in out[:3]] == ["bar", "post", "post"]
    assert not any(o["goal"] for o in out[:3])
    # центр (5) мимо вратаря — каркас не разыгрывается, очередь woodwork дождалась угла 4
    assert out[3]["outcome"] == "goal" and out[3]["goal"]
    assert out[4]["outcome"] == "goal" and out[4]["goal"] and rng.woodwork == []
    assert out[-1]["goals"] == 2 and out[-1]["done"]


def test_save_never_woodwork(client, mono, rng):
    sid = start(client)
    rng.keepers = [1]
    rng.woodwork = [True]
    o = shoot(client, mono, sid, 1)
    assert o["outcome"] == "save" and not o["goal"] and rng.woodwork == [True]


def test_corners_constant():
    assert PENALTY_CORNERS == (1, 3, 4, 6)
