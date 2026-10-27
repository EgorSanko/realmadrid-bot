"""?lang=en: новости, статья, видео, факты матча, викторина и сообщения об ошибках. Без параметра — всё
по-русски и без новых полей, как раньше. В сеть не ходим: Google подменяет httpx.MockTransport."""
import ast
import pathlib
import re
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import i18n, store, translate as T
from app.games import bank
from app.sources import media

from .test_translate import fake_google, make_client

CYR = re.compile("[А-Яа-яЁё]")


# ================= разбор параметра =================

@pytest.mark.parametrize("value,expected", [("en", "en"), ("EN", "en"), (" en ", "en"), ("ru", "ru"), ("", "ru"),
                                            (None, "ru"), ("de", "ru"), ("en-US", "ru"), (["en"], "ru")])
def test_lang_validation(value, expected):
    assert i18n.lang(value) == expected


def test_query_lang():
    assert i18n.query_lang(b"limit=5&lang=en") == "en"
    assert i18n.query_lang(b"lang=fr") == "ru" and i18n.query_lang(b"") == "ru"


# ================= сообщения об ошибках =================

def _messages() -> set[str]:
    """Все русские сообщения, которые API отдаёт в message/detail (литералы в вызовах ошибок)."""
    out: set[str] = set()
    calls = ("GameError", "PredictError", "_err", "InitDataError", "_no_data")
    for f in pathlib.Path("app").rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and ast.unparse(n.func).split(".")[-1] in calls:
                for a in n.args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str) and CYR.search(a.value):
                        out.add(a.value)
            if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "detail" for k in n.keys):
                for k, v in zip(n.keys, n.values):
                    if isinstance(k, ast.Constant) and k.value == "detail" and isinstance(v, ast.Constant) \
                            and isinstance(v.value, str) and CYR.search(v.value):
                        out.add(v.value)
    from app.predictions.api import _FIELD_MSG
    return out | set(_FIELD_MSG.values())


def test_every_error_message_has_english():
    msgs = _messages()
    assert len(msgs) > 60
    missing = sorted(m for m in msgs if CYR.search(i18n.msg(m, "en")))
    assert not missing, missing
    # с числами и именами полей
    assert i18n.msg("Зона удара — число от 1 до 6") == "The shot zone must be a number from 1 to 6"
    assert i18n.msg("Лишнее поле: foo") == "Unexpected field: foo"
    assert i18n.msg("news: сборщик ещё не получил данные") == "news: the collector has not received data yet"
    assert i18n.msg("Неверный запрос", "ru") == "Неверный запрос"


def test_errors_english_with_lang_codes_unchanged(tmp_db):
    from app.main import app
    c = TestClient(app)
    ru = c.get("/api/news/zzz")
    en = c.get("/api/news/zzz?lang=en")
    assert ru.status_code == en.status_code == 404
    assert ru.json() == {"error": "not_found", "detail": "неверный id новости", "available": []}
    assert en.json() == {"error": "not_found", "detail": "invalid news id", "available": []}
    assert int(en.headers["content-length"]) == len(en.content)
    assert c.get("/api/news?lang=en").json()["detail"] == "news: the collector has not received data yet"
    assert c.get("/api/news?lang=xx").json()["detail"] == "news: сборщик ещё не получил данные"


# ================= новости =================

@pytest.fixture()
def news_api(tmp_db, monkeypatch):
    from app import main
    conn = store.connect()
    items = [{"id": f"sports.ru/n{i}", "site": "sportsru", "source": "Sports.ru", "title": f"Новость {i}",
              "summary": f"Анонс {i}", "url": f"https://www.sports.ru/n{i}.html", "published": "2026-10-16T20:00:00Z",
              "image": None} for i in range(3)]
    items[1].update(source="Чемпионат", site="championat", also=["Спорт-Экспресс"])
    store.put(conn, "news", "test", {"items": items, "feeds": {}})
    calls: list = []
    monkeypatch.setattr(main, "_ARTICLES", T.ArticleTranslator(make_client(calls)))
    yield TestClient(main.app), conn, items, calls
    conn.close()


def test_news_russian_unchanged(news_api):
    c, conn, items, _ = news_api
    T.save(conn, {"Новость 0": "News 0"}, "en")
    for url in ("/api/news", "/api/news?lang=ru", "/api/news?lang=de"):
        d = c.get(url).json()
        assert [i["title"] for i in d["items"]] == ["Новость 0", "Новость 1", "Новость 2"]
        assert d["items"][1]["source"] == "Чемпионат" and d["items"][1]["also"] == ["Спорт-Экспресс"]
        assert "translated" not in d and "lang" not in d and "translated" not in d["items"][0]


def test_news_english_from_cache_with_fallback(news_api):
    c, conn, items, calls = news_api
    T.save(conn, {"Новость 0": "News 0", "Анонс 0": "Teaser 0", "Новость 1": "News 1"}, "en")
    r = c.get("/api/news?lang=en")
    d = r.json()
    assert r.headers["cache-control"] == "public, max-age=60"
    assert d["lang"] == "en" and d["translated"] is False
    i0, i1, i2 = d["items"]
    assert (i0["title"], i0["summary"], i0["translated"]) == ("News 0", "Teaser 0", True)
    assert (i1["title"], i1["summary"], i1["translated"]) == ("News 1", "Анонс 1", False)   # анонса нет — оригинал
    assert (i2["title"], i2["translated"]) == ("Новость 2", False)
    assert i1["source"] == "Championat" and i1["also"] == ["Sport-Express"] and i0["source"] == "Sports.ru"
    assert calls == []                                  # лента в Google не ходит никогда — только кэш


def _article(conn, aid, html):
    store.put(conn, f"article:{aid}", "sportsru_pages", {
        "aid": aid, "id": "sports.ru/n0", "url": "https://www.sports.ru/n0.html", "site": "sportsru",
        "source": "Sports.ru", "title": "Новость 0", "summary": "Анонс 0", "lead": "Лид статьи",
        "html": html, "image": None, "image_caption": "Фото: Getty", "author": "Иван Петров", "origin": None,
        "words": 10, "hero_in_text": False})


def test_article_translated_on_first_request_then_cached(news_api):
    c, conn, items, calls = news_api
    aid = media.news_aid("sports.ru/n0")
    html = "<p>Первый абзац.</p>\n<p>Второй абзац.</p>"
    _article(conn, aid, html)
    ru = c.get(f"/api/news/{aid}").json()
    assert ru["html"] == html and "translated" not in ru and calls == []

    r = c.get(f"/api/news/{aid}?lang=en")
    d = r.json()
    assert len(calls) == 1 and r.headers["cache-control"] == "public, max-age=300"
    assert d["translated"] is True and d["lang"] == "en"
    assert d["html"] == "<p>EN&lt;Первый абзац.&gt;</p>\n<p>EN&lt;Второй абзац.&gt;</p>"
    assert d["lead"] == "EN<Лид статьи>" and d["image_caption"] == "EN<Фото: Getty>"
    assert d["title"] == "EN<Новость 0>" and d["author"] == "EN<Иван Петров>"
    assert [m["title"] for m in d["more"]] == ["Новость 1", "Новость 2"] and d["more"][0]["source"] == "Championat"
    # второй раз — из кэша, в Google не идём
    assert c.get(f"/api/news/{aid}?lang=en").json()["html"] == d["html"] and len(calls) == 1
    # русская версия не изменилась
    assert c.get(f"/api/news/{aid}").json() == ru


def test_article_falls_back_to_russian_when_google_fails(news_api, monkeypatch):
    from app import main
    c, conn, items, _ = news_api
    bad: list = []
    monkeypatch.setattr(main, "_ARTICLES", T.ArticleTranslator(make_client(bad, fail=429)))
    aid = media.news_aid("sports.ru/n0")
    html = "<p>Первый абзац.</p>"
    _article(conn, aid, html)
    r = c.get(f"/api/news/{aid}?lang=en")
    d = r.json()
    assert r.status_code == 200 and d["full"] is True and d["html"] == html and d["translated"] is False
    assert r.headers["cache-control"] == "public, max-age=30"      # ненадолго — следующий запрос повторит
    assert d["lead"] == "Лид статьи" and len(bad) == 1
    c.get(f"/api/news/{aid}?lang=en")
    assert len(bad) == 1                                            # повтор не раньше TRANSLATE_ARTICLE_RETRY


def test_article_pending_english_titles(news_api):
    c, conn, items, calls = news_api
    T.save(conn, {"Новость 2": "News 2", "Анонс 2": "Teaser 2"}, "en")
    d = c.get(f"/api/news/{media.news_aid('sports.ru/n2')}?lang=en").json()
    assert d["pending"] is True and d["title"] == "News 2" and d["summary"] == "Teaser 2" and d["translated"] is True
    assert calls == []


# ================= видео и факты матча =================

def test_videos_english(tmp_db):
    from app.main import app
    conn = store.connect()
    store.put(conn, "videos", "youtube", {"items": [
        {"id": "v1", "title": "WHAT a header!", "published": "2026-10-16T20:00:00Z", "thumb": None, "url": "u",
         "short": False, "kind": "video", "channel": "Real Madrid"},
        {"id": "v2", "title": "Гол Винисиуса", "published": "2026-10-15T20:00:00Z", "thumb": None, "url": "u",
         "short": True, "kind": "short", "channel": "Real Madrid"}]})
    c = TestClient(app)
    ru = c.get("/api/videos").json()
    assert "translated" not in ru and ru["items"][1]["title"] == "Гол Винисиуса"
    d = c.get("/api/videos?lang=en").json()
    assert d["items"][0] == {**ru["items"][0], "translated": True}       # английский заголовок — как есть
    assert d["items"][1]["title"] == "Гол Винисиуса" and d["items"][1]["translated"] is False
    T.save(conn, {"Гол Винисиуса": "Vinícius goal"}, "en")
    d = c.get("/api/videos?lang=en").json()
    assert d["items"][1]["title"] == "Vinícius goal" and d["translated"] is True


def test_match_insights_english(tmp_db):
    from app import main
    conn = store.connect()
    ins = {"lang": "ru", "main": "Real Madrid выиграл 19 из 20",
           "teams": [{"team_id": 8633, "items": ["Vinícius Jr забил", "Real Madrid scored"]}]}
    T.save(conn, {"Real Madrid выиграл 19 из 20": "Real Madrid won 19 of 20"}, "en")
    out = main._insights_en(conn, ins)
    assert out["main"] == "Real Madrid won 19 of 20" and out["translated"] is False and out["lang"] == "ru"
    assert out["teams"][0]["items"] == ["Vinícius Jr забил", "Real Madrid scored"]
    T.save(conn, {"Vinícius Jr забил": "Vinícius Jr scored"}, "en")
    out = main._insights_en(conn, ins)
    assert out["translated"] is True and out["lang"] == "en" and out["teams"][0]["items"][0] == "Vinícius Jr scored"
    extras_ru = main._match_extras(conn, "1", {"tournament": {}})
    assert extras_ru["insights"] is None


# ================= викторина =================

def test_english_bank_matches_russian():
    ru, en = bank.load(), bank.load_en()
    raw_en = bank.json.loads(bank.PATH_EN.read_text(encoding="utf-8"))
    raw_ru = bank.json.loads(bank.PATH.read_text(encoding="utf-8"))
    for level in bank.LEVELS:
        assert [q["id"] for q in raw_en[level]] == [q["id"] for q in raw_ru[level]]
        for a, b in zip(raw_ru[level], raw_en[level]):
            assert {k: v for k, v in a.items() if k not in ("q", "a", "note")} == \
                   {k: v for k, v in b.items() if k not in ("q", "a", "note")}
        assert [q.id for q in en[level]] == [q.id for q in ru[level]]
        for q in en[level]:
            assert not CYR.search(q.q) and not any(CYR.search(x) for x in q.a), q.id
            assert len(set(q.a)) == 4
