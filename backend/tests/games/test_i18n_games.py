"""?lang=en в мини-играх и прогнозах: вопросы из английского банка (проверка ответа — та же, по id и индексу),
названия уровней, подпись недели, сообщения об ошибках (коды те же), «Болельщик» → «Fan»."""
import re

from app import i18n
from app.games import bank

CYR = re.compile("[А-Яа-яЁё]")


def test_quiz_english_questions_same_scoring(games, client, mono):
    from app.games.service import QUIZ_ROUND
    s = client.post("/api/games/quiz/start?lang=en", json={"level": "easy"}).json()
    ru_by_id = {q.id: q for q in bank.load()["easy"]}
    en_by_text = {q.q: q for q in bank.load_en()["easy"]}
    for i in range(QUIZ_ROUND):
        en = client.post(f"/api/games/quiz/{s['session']}/next?lang=en").json()
        ru = client.post(f"/api/games/quiz/{s['session']}/next").json()   # тот же открытый вопрос
        assert not CYR.search(en["q"]) and CYR.search(ru["q"])
        q_en = en_by_text[en["q"]]
        q_ru = ru_by_id[q_en.id]
        # тот же порядок вариантов: i-й показанный вариант — перевод i-го русского
        assert [q_en.a.index(x) for x in en["a"]] == [q_ru.a.index(x) for x in ru["a"]]
        right = en["a"].index(q_en.a[q_en.correct])
        assert right == ru["a"].index(q_ru.a[q_ru.correct])
        mono.t += 2.0
        r = client.post(f"/api/games/quiz/{s['session']}/answer?lang=en", json={"choice": right}).json()
        assert r["correct"] is True and r["correct_choice"] == right
    assert r["done"] and r["result"]["correct"] == QUIZ_ROUND


def test_games_info_leaderboard_and_errors_english(games, client):
    info = client.get("/api/games/info?lang=en").json()
    assert [l["title"] for l in info["quiz"]["levels"]] == ["Easy", "Medium", "Hard", "Expert"]
    assert [l["title"] for l in info["penalty"]["levels"]] == ["Easy", "Medium", "Hard", "Legend"]
    assert client.get("/api/games/info").json()["quiz"]["levels"][0]["title"] == "Лёгкий"
    lb = client.get("/api/games/leaderboard?game=quiz&lang=en").json()
    assert not CYR.search(lb["week"]["label"])
    assert CYR.search(client.get("/api/games/leaderboard?game=quiz").json()["week"]["label"])
    r = client.post("/api/games/quiz/start?lang=en", json={"level": "nope"})
    assert r.status_code == 400 and r.json() == {"error": "bad_level", "message": "Unknown level"}
    r = client.post("/api/games/quiz/start", json={"level": "nope"})
    assert r.json() == {"error": "bad_level", "message": "Неизвестный уровень"}
    r = client.get("/api/games/leaderboard?game=chess&lang=en")
    assert r.json() == {"error": "bad_game", "message": "Game: quiz or penalty"}


def test_week_label_english():
    from datetime import date
    from app.games.service import week_label
    assert week_label(date(2026, 10, 12), "en") == "October 12–18"
    assert week_label(date(2026, 9, 28), "en") == "September 28 – October 4"
    assert week_label(date(2026, 10, 12)) == "12–18 октября"


def test_predictions_errors_and_fan_name_english(svc, client):
    r = client.put("/api/predict/matches/1?lang=en", json={"home": 1, "away": 0})
    assert r.status_code == 401 and r.json()["error"] == "unauthorized" and not CYR.search(r.json()["message"])
    r = client.get("/api/predict/leaderboard?period=year&lang=en")
    assert r.status_code == 422 and r.json() == {"error": "validation", "message": "period: season or month"}
    assert i18n.fan_names({"top": [{"name": "Болельщик"}, {"name": "Иван"}]}, "en") == \
        {"top": [{"name": "Fan"}, {"name": "Иван"}]}
