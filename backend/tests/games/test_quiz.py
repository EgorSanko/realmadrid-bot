"""Викторина: банк вопросов, партия без повторов, проверка ответа на сервере, таймер, очки."""
import json

import pytest

from app.games import bank, service
from app.games.service import QUIZ_ROUND, QUIZ_TIMER, multiplier, quiz_points

from .conftest import correct_choice, tma


def start(client, level="easy", headers=None):
    r = client.post("/api/games/quiz/start", json={"level": level}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def nxt(client, sid, headers=None):
    r = client.post(f"/api/games/quiz/{sid}/next", headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def answer(client, sid, choice, headers=None):
    return client.post(f"/api/games/quiz/{sid}/answer", json={"choice": choice}, headers=headers or {})


# ---------- банк ----------

def test_bank_levels_and_format():
    qs = bank.load()
    assert set(qs) == {"easy", "medium", "hard", "expert"}
    for level, items in qs.items():
        assert len(items) >= QUIZ_ROUND * 5, level
        assert len({q.q for q in items}) == len(items), f"повтор текста вопроса в {level}"
        for q in items:
            assert len(q.a) == 4 and 0 <= q.correct < 4
            if q.media:
                assert q.media["type"] in ("player", "team", "league") and isinstance(q.media["id"], int)


def test_bank_stale_hidden_and_actual():
    raw = json.loads(bank.PATH.read_text(encoding="utf-8"))
    stale = {q["id"] for items in raw.values() for q in items if q.get("stale")}
    active = {q.id for items in bank.load().values() for q in items}
    assert stale and not (stale & active)
    by_id = {q["id"]: q for items in raw.values() for q in items}
    coach = by_id["e9"]
    assert coach["a"][coach["correct"]] == "Жозе Моуринью" and "2026/27" in coach["q"]
    # «кто сейчас тренер / капитан» в настоящем времени не осталось
    for q in active:
        text = by_id[q]["q"].lower()
        assert "является капитаном" not in text and "на 2024 год" not in text


# ---------- партия ----------

def test_question_hides_answer_and_no_repeats(client, mono):
    s = start(client)
    assert s["total"] == QUIZ_ROUND and s["timer_s"] == QUIZ_TIMER and s["saved"] is False
    seen = set()
    for i in range(QUIZ_ROUND):
        q = nxt(client, s["session"])
        assert q["index"] == i and len(q["a"]) == 4
        assert "correct" not in q and "correct_choice" not in q
        seen.add(q["q"])
        mono.t += 1
        r = answer(client, s["session"], 0).json()
        assert "correct_choice" in r
    assert len(seen) == QUIZ_ROUND


def test_correct_wrong_timeout_and_result(client, mono):
    s = start(client, "medium")
    sid = s["session"]
    q = nxt(client, sid)
    mono.t += 3
    r = answer(client, sid, correct_choice(q)).json()
    assert r["correct"] and not r["timeout"] and r["points"] == quiz_points("medium", 3, 1) and r["streak"] == 1

    q = nxt(client, sid)
    mono.t += 2
    wrong = (correct_choice(q) + 1) % 4
    r = answer(client, sid, wrong).json()
    assert not r["correct"] and r["points"] == 0 and r["streak"] == 0 and r["correct_choice"] == correct_choice(q)

    # время вышло по серверным часам — даже верный ответ не засчитан
    q = nxt(client, sid)
    mono.t += QUIZ_TIMER + 2.5
    r = answer(client, sid, correct_choice(q)).json()
    assert r["timeout"] and not r["correct"] and r["points"] == 0

    # клиентский таймер истёк — choice: null
    q = nxt(client, sid)
    mono.t += QUIZ_TIMER
    r = answer(client, sid, None).json()
    assert r["timeout"] and not r["correct"]

    score = r["score"]
    for _ in range(QUIZ_ROUND - 4):
        q = nxt(client, sid)
        mono.t += 1
        r = answer(client, sid, correct_choice(q)).json()
        score += r["points"]
    assert r["done"] and r["score"] == score
    res = r["result"]
    assert res["correct"] == QUIZ_ROUND - 3 and res["timeouts"] == 2 and res["best_streak"] == QUIZ_ROUND - 4
    assert res["saved"] is False and res["score"] == score
    assert client.post(f"/api/games/quiz/{sid}/next").status_code == 409
    assert answer(client, sid, 0).status_code == 409


def test_streak_multiplier():
    assert [multiplier(n) for n in (0, 1, 2, 3, 5, 6, 10)] == [1, 1, 1, 2, 2, 3, 3]
    assert quiz_points("easy", 0, 1) == 150 and quiz_points("easy", QUIZ_TIMER, 1) == 100
    assert quiz_points("expert", 0, 6) == 450 * 3


def test_repeat_next_keeps_timer(client, mono):
    sid = start(client)["session"]
    q1 = nxt(client, sid)
    mono.t += 10
    q2 = nxt(client, sid)
    assert q2["q"] == q1["q"] and q2["a"] == q1["a"] and q2["left_s"] == pytest.approx(QUIZ_TIMER - 10)


def test_answer_rules(client, mono):
    sid = start(client)["session"]
    assert answer(client, sid, 0).status_code == 409          # вопрос ещё не выдан
    nxt(client, sid)
    r = answer(client, sid, 0)                                 # мгновенный ответ — не человек
    assert r.status_code == 429 and r.json()["error"] == "too_fast"
    for bad in (4, -1, "1", True, 1.5):
        assert answer(client, sid, bad).status_code == 400, bad
    assert client.post(f"/api/games/quiz/{sid}/answer", json={}).status_code == 400
    mono.t += 1
    assert answer(client, sid, 0).status_code == 200            # вопрос оставался открытым


def test_bad_level_and_unknown_session(client):
    assert client.post("/api/games/quiz/start", json={"level": "god"}).status_code == 400
    assert client.post("/api/games/quiz/start", content=b"nope").status_code == 400
    r = client.post("/api/games/quiz/xxx/next")
    assert r.status_code == 404 and r.json()["error"] == "session_not_found"


def test_session_expires(client, mono):
    sid = start(client)["session"]
    mono.t += service.SESSION_TTL + 1
    assert client.post(f"/api/games/quiz/{sid}/next").status_code == 404


def test_foreign_session_not_found(client):
    sid = start(client, headers=tma(11))["session"]
    assert client.post(f"/api/games/quiz/{sid}/next", headers=tma(12)).status_code == 404
    assert client.post(f"/api/games/quiz/{sid}/next").status_code == 404
    assert client.post(f"/api/games/quiz/{sid}/next", headers=tma(11)).status_code == 200


def test_no_repeat_across_rounds_for_user(client, mono):
    seen = []
    for _ in range(3):
        sid = start(client, "hard", headers=tma(21))["session"]
        for _ in range(QUIZ_ROUND):
            seen.append(nxt(client, sid, tma(21))["q"])
            mono.t += 1
            answer(client, sid, 0, tma(21))
    assert len(set(seen)) == len(seen)


def test_start_rate_limit(client):
    for _ in range(service.START_RATE[0]):
        start(client)
    r = client.post("/api/games/quiz/start", json={"level": "easy"})
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"


def test_info(client):
    r = client.get("/api/games/info").json()
    assert [lv["id"] for lv in r["quiz"]["levels"]] == ["easy", "medium", "hard", "expert"]
    assert all(lv["questions"] >= QUIZ_ROUND for lv in r["quiz"]["levels"])
    assert r["penalty"]["shots"] == 5 and r["penalty"]["zones"] == 6
