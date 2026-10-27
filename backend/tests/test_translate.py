"""Машинный перевод (app/translate.py): куски и строки, разбор ответа, кэш в SQLite, клиент с breaker'ом
(HTTP подменяется httpx.MockTransport — в сеть тесты не ходят), HTML статьи, предперевод в сборщике,
очистка по сроку."""
import asyncio
import gzip
import json
import os
import re
import time
from urllib.parse import parse_qs

import httpx
import pytest

from app import cleanup, config, store, translate as T
from app.collector import Collector
from app.sources import article
from app.sources.base import SourceError

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "articles")


def run(coro):
    return asyncio.run(coro)


def fake_google(calls: list, fail: int | None = None, mangle=None):
    """Обработчик MockTransport: «переводит» каждую строку в EN<строка>; fail — код ошибки."""
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode("utf-8"))
        q = form["q"][0]
        calls.append({"method": request.method, "params": dict(request.url.params), "q": q})
        if fail:
            return httpx.Response(fail, text="<html>Sorry...</html>")
        out = "\n".join(f"EN<{line}>" for line in q.split("\n"))
        if mangle:
            out = mangle(out)
        return httpx.Response(200, json=[[[out, q, None, None, 3]], None, "ru"])
    return handler


def make_client(calls, **kw) -> T.GoogleTranslate:
    g = T.GoogleTranslate()
    tr = httpx.MockTransport(fake_google(calls, **kw))
    g._aclient = httpx.AsyncClient(transport=tr)
    g._client = httpx.Client(transport=tr)
    return g


# ================= чистые функции =================

def test_needs_and_key():
    assert T.needs("Реал выиграл") and T.needs("Real Madrid забил") and not T.needs("Vini Jr. 🎯")
    assert not T.needs(None) and not T.needs("")
    k = T.cache_key("Привет", "en")
    assert len(k) == 64 and k == T.cache_key("Привет", "en") and k != T.cache_key("Привет", "de")


def test_parse_response():
    assert T.parse([[["Real beat ", "Реал обыграл ", None], ["Barcelona.", "Барселону.", None]], None, "ru"]) \
        == "Real beat Barcelona."
    with pytest.raises(ValueError):
        T.parse({"error": 1})


def test_long_text_chunked_on_paragraph_boundaries():
    para = "Абзац номер {}. " + "Слово " * 120          # ~730 символов
    units = [para.format(i).strip() for i in range(20)]  # ~14,6 тыс. символов
    groups = T.groups(units, T.CHUNK)
    assert len(groups) >= 4
    for g in groups:
        assert len("\n".join(units[i] for i in g)) <= T.CHUNK
    assert [i for g in groups for i in g] == list(range(20))   # порядок и все абзацы на месте


def test_long_paragraph_split_by_sentences():
    text = " ".join(f"Предложение {i} про Реал и Мбаппе." for i in range(400))   # ~13 тыс. символов
    parts = T.pieces(text, T.CHUNK)
    assert len(parts) >= 3 and all(len(p) <= T.CHUNK for p in parts)
    assert " ".join(parts) == text
    assert all(p.endswith(".") for p in parts)                 # режем по границе предложения


def test_plan_splits_group_when_google_changes_line_count():
    calls: list = []
    gen = T.plan(["Раз", "Два", "Три", "Четыре"])
    q = next(gen)
    calls.append(q)
    try:
        q = gen.send("One Two\nThree Four")                    # 2 строки вместо 4 — делим пополам
        while True:
            calls.append(q)
            n = len(q.split("\n"))
            q = gen.send("\n".join(f"T{len(calls)}-{i}" for i in range(n)))
    except StopIteration as e:
        out = e.value
    assert calls[0] == "Раз\nДва\nТри\nЧетыре" and calls[1:] == ["Раз\nДва", "Три\nЧетыре"]
    assert out == ["T2-0", "T2-1", "T3-0", "T3-1"]


def test_plan_request_budget():
    gen = T.plan(["Раз"] * 3, batch=1, max_requests=2)
    next(gen)
    gen.send("a")
    with pytest.raises(T.TranslateError):
        gen.send("b")


# ================= клиент =================

def test_async_translate_posts_form_in_batches():
    calls: list = []
    g = make_client(calls)
    texts = [f"Заголовок {i}" for i in range(25)]
    out = run(g.translate(texts, "en", batch=10))
    run(g.close())
    assert out == [f"EN<Заголовок {i}>" for i in range(25)]
    assert len(calls) == 3 and all(c["method"] == "POST" for c in calls)
    assert calls[0]["params"] == {"client": "gtx", "sl": "ru", "tl": "en", "dt": "t"}
    assert calls[0]["q"].split("\n") == texts[:10]
    assert g.snapshot()["requests"] == 3 and g.snapshot()["breaker"] == "closed"


def test_google_failure_opens_breaker_and_disabled_flag(tmp_db, monkeypatch):
    calls: list = []
    g = make_client(calls, fail=429)
    for _ in range(config.BREAKER_THRESHOLD):
        with pytest.raises(SourceError):
            run(g.translate(["Привет"]))
    assert g.state == "open" and not g.available()
    with pytest.raises(SourceError):                            # breaker: в Google больше не ходим
        run(g.translate(["Привет"]))
    assert len(calls) == config.BREAKER_THRESHOLD
    # DISABLED_SOURCES=gtranslate выключает перевод
    g2 = make_client(calls)
    monkeypatch.setenv("DISABLED_SOURCES", "gtranslate")
    assert not g2.available()
    with pytest.raises(SourceError):
        g2.translate_sync(["Привет"])
    run(g.close())
    run(g2.close())


def test_sync_translate_respects_deadline():
    calls: list = []
    g = make_client(calls)
    assert g.translate_sync(["Привет", "Мир"], "en", deadline=time.monotonic() + 5) == ["EN<Привет>", "EN<Мир>"]
    with pytest.raises(T.TranslateError):
        g.translate_sync(["Привет"], "en", deadline=time.monotonic() - 1)
    assert len(calls) == 1
    run(g.close())


# ================= кэш =================

def test_cache_lookup_save_missing(tmp_db):
    conn = store.connect()
    texts = ["Реал выиграл", "Vini Jr.", "Мбаппе забил", None, "Реал выиграл"]
    assert T.missing(conn, texts, "en") == ["Реал выиграл", "Мбаппе забил"]
    assert T.save(conn, {"Реал выиграл": "Real won", "Vini Jr.": "x"}, "en") == 1   # без кириллицы — не пишем
    assert T.lookup(conn, texts, "en") == {"Реал выиграл": "Real won", "Vini Jr.": "Vini Jr."}
    assert T.missing(conn, texts, "en") == ["Мбаппе забил"]
    row = conn.execute("SELECT key, lang, kind FROM translations").fetchone()
    assert row == (T.cache_key("Реал выиграл", "en"), "en", "text")


def test_cleanup_translations_ttl(tmp_db):
    conn = store.connect()
    now = time.time()
    T.save(conn, {"Старое": "Old"}, "en", now=now - (config.TRANSLATION_TTL_DAYS + 1) * 86400)
    T.save(conn, {"Свежее": "Fresh"}, "en", now=now)
    T.save_article(conn, "<p>Старая статья</p>", "en", "<p>Old</p>", now=now - (config.TRANSLATION_TTL_DAYS + 1) * 86400)
    res = cleanup.run(conn, None, now)
    assert res["translations"] == 2
    assert T.lookup(conn, ["Старое", "Свежее"], "en") == {"Свежее": "Fresh"}


# ================= HTML статьи =================

def _fixture_article(name: str) -> dict:
    urls = json.load(open(os.path.join(FIX, "urls.json"), encoding="utf-8"))
    page = gzip.open(os.path.join(FIX, f"{name}.html.gz")).read()
    return article.extract(name.split("_")[0], urls[name], page)


@pytest.mark.parametrize("name", ["sportsru_news", "sportsru_blog", "championat_photo", "sportexpress_real"])
def test_html_roundtrip_and_tags_kept(name):
    html = _fixture_article(name)["html"]
    root, slots = T.segment_html(html)
    assert T.render_html(root) == html                        # без перевода — байт в байт
    assert slots and all(T.needs(t) for t, _ in slots)
    T.apply(slots, [f"EN{i} <b>&" for i in range(len(slots))])
    out = T.render_html(root)
    assert not T.needs(re.sub(r'<[^>]+>', "", out))         # весь видимый текст переведён (alt не трогаем)
    assert "EN0 &lt;b&gt;&amp;" in out                        # перевод — текст, не разметка
    assert out.count("<img") == html.count("<img") and out.count("<figure") == html.count("<figure")
    assert out.count("<p>") == html.count("<p>")


def test_html_segment_modes():
    html = ("<p>Простой абзац.</p>\n<p>Строка один<br>строка два</p>\n<p><strong>Весь абзац жирный</strong></p>\n"
            "<p>Сказал <a href=\"https://x.ru/\" rel=\"noopener nofollow\">Мбаппе</a> после матча.</p>\n"
            "<figure><img src=\"/img/news/sportsru/dynamic_images/a.jpg\" alt=\"\" loading=\"lazy\">"
            "<figcaption>Фото: Реал</figcaption></figure>\n<ul><li>Пункт</li><li>Real Madrid</li></ul>")
    root, slots = T.segment_html(html)
    assert [t for t, _ in slots] == ["Простой абзац.", "Строка один", "строка два", "Весь абзац жирный",
                                     "Сказал Мбаппе после матча.", "Фото: Реал", "Пункт"]
    T.apply(slots, ["Plain paragraph.", "Line one", "line two", "Whole paragraph bold",
                    "Mbappé said after the match.", "Photo: Real", "Item"])
    assert T.render_html(root) == (
        "<p>Plain paragraph.</p>\n<p>Line one<br>line two</p>\n<p><strong>Whole paragraph bold</strong></p>\n"
        "<p>Mbappé said after the match.</p>\n"     # смешанная разметка — фраза целиком, без внутренних тегов
        "<figure><img src=\"/img/news/sportsru/dynamic_images/a.jpg\" alt=\"\" loading=\"lazy\">"
        "<figcaption>Photo: Real</figcaption></figure>\n<ul><li>Item</li><li>Real Madrid</li></ul>")
    assert T.segment_html("") == (None, [])


def test_article_translator_caches_and_backs_off(tmp_db):
    conn = store.connect()
    calls: list = []
    clock = [1000.0]
    tr = T.ArticleTranslator(make_client(calls), clock=lambda: clock[0])
    html = "<p>Первый абзац.</p>\n<p>Второй абзац.</p>"
    assert tr.translate(conn, html, ["Лид статьи", None, "Vini Jr."], "en")
    assert T.cached_article(conn, html, "en") == "<p>EN&lt;Первый абзац.&gt;</p>\n<p>EN&lt;Второй абзац.&gt;</p>"
    assert T.lookup(conn, ["Лид статьи"], "en") == {"Лид статьи": "EN<Лид статьи>"}
    assert len(calls) == 1                                     # всё одной пачкой

    # Google не отвечает: False, повтор этой статьи — не раньше TRANSLATE_ARTICLE_RETRY
    bad: list = []
    tr2 = T.ArticleTranslator(make_client(bad, fail=503), clock=lambda: clock[0])
    html2 = "<p>Другая статья.</p>"
    assert tr2.translate(conn, html2, [], "en") is False
    assert tr2.translate(conn, html2, [], "en") is False and len(bad) == 1
    clock[0] += config.TRANSLATE_ARTICLE_RETRY + 1
    assert tr2.translate(conn, html2, [], "en") is False and len(bad) == 2
    assert T.cached_article(conn, html2, "en") is None


def test_article_translator_rate_limit(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "TRANSLATE_ARTICLE_RATE_PER_MIN", 2)
    conn = store.connect()
    calls: list = []
    tr = T.ArticleTranslator(make_client(calls))
    assert [tr.translate(conn, f"<p>Статья {i}</p>", [], "en") for i in range(3)] == [True, True, False]


# ================= сборщик =================

def _seed_media(conn, n=5):
    items = [{"id": f"sports.ru/n{i}", "site": "sportsru", "source": "Sports.ru", "title": f"Новость {i}",
              "summary": f"Анонс {i}" if i % 2 == 0 else "", "url": f"https://www.sports.ru/n{i}.html",
              "published": "2026-10-16T20:00:00Z", "image": None} for i in range(n)]
    store.put(conn, "news", "test", {"items": items, "feeds": {}})
    store.put(conn, "videos", "youtube", {"items": [{"id": "v1", "title": "WHAT a header!"}]})
    return items


def test_collector_pretranslates_titles_summaries(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "TRANSLATE_BATCH", 4)
    conn = store.connect()
    _seed_media(conn)
    c = Collector(conn)
    calls: list = []
    tr = httpx.MockTransport(fake_google(calls))
    c.tr._aclient = httpx.AsyncClient(transport=tr)
    try:
        assert set(c.translate_texts()) == {"Новость 0", "Анонс 0", "Новость 1", "Новость 2", "Анонс 2",
                                            "Новость 3", "Новость 4", "Анонс 4"}
        r = run(c.tick_translate(time.time()))
        assert r == {"translated": 8, "left": 0} and len(calls) == 2   # 8 текстов по 4 в запросе
        assert run(c.tick_translate(time.time())) is None               # раньше TRANSLATE_INTERVAL — не идём
        assert run(c.tick_translate(time.time(), force=True)) == {"translated": 0, "left": 0}
        assert len(calls) == 2                                           # всё уже в кэше
        assert T.lookup(conn, ["Новость 3"], "en") == {"Новость 3": "EN<Новость 3>"}
        c.write_state()
        assert store.source_states(conn)["gtranslate"]["requests"] == 2
    finally:
        run(c.close())


def test_collector_translate_google_down_and_rate_limit(tmp_db, monkeypatch):
    monkeypatch.setattr(config, "TRANSLATE_BATCH", 2)
    monkeypatch.setattr(config, "TRANSLATE_RATE_PER_MIN", 2)
    conn = store.connect()
    _seed_media(conn)
    c = Collector(conn)
    calls: list = []
    c.tr._aclient = httpx.AsyncClient(transport=httpx.MockTransport(fake_google(calls, fail=429)))
    try:
        r = run(c.tick_translate(time.time(), force=True))
        assert r == {"translated": 0, "left": 8} and len(calls) == 1    # ошибка — до следующего прохода
        assert conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0] == 0
        ok: list = []
        c.tr = T.GoogleTranslate()
        c.tr._aclient = httpx.AsyncClient(transport=httpx.MockTransport(fake_google(ok)))
        r = run(c.tick_translate(time.time(), force=True))
        assert r == {"translated": 4, "left": 4} and len(ok) == 2       # лимит 2 запроса в минуту
    finally:
        run(c.close())


def test_collector_translates_insights_of_next_match(tmp_db, monkeypatch):
    conn = store.connect()
    c = Collector(conn)
    monkeypatch.setattr(c, "last_next", lambda now: ["777"])
    monkeypatch.setattr(c, "window", lambda now: [])
    store.put(conn, "insights:777", "fotmob", {"lang": "ru", "main": "Real Madrid выиграл 19 из 20",
                                               "teams": [{"team_id": 8633, "items": ["Vinícius Jr забил"]}]})
    try:
        assert c.translate_texts() == ["Real Madrid выиграл 19 из 20", "Vinícius Jr забил"]
    finally:
        run(c.close())
