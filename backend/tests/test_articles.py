"""Чтение новости внутри приложения: разбор статей на сохранённых реальных страницах трёх сайтов,
белый список HTML (санитизация), картинки только через наш /img/news, сборщик (предзагрузка,
заявки, повторы) и API /api/news/{aid}. Без сети: страницы — tests/fixtures/articles/*.html.gz
(скачаны с сервера с заголовками сборщика 17.10.2026)."""
import asyncio
import gzip
import json
import os
import re
import time

import pytest
from fastapi.testclient import TestClient
from lxml import html as LH

from app import config, store
from app.collector import Collector
from app.sources import article as A
from app.sources import media as M
from app.sources.base import NotFound

from .conftest import FIX

ART = os.path.join(FIX, "articles")
with open(os.path.join(ART, "urls.json"), encoding="utf-8") as _f:
    URLS: dict[str, str] = json.load(_f)
SITE = {"championat": "championat", "sportsru": "sportsru", "sportexpress": "sportexpress"}
SOURCE = {"championat": "Чемпионат", "sportsru": "Sports.ru", "sportexpress": "Спорт-Экспресс"}


def page(name: str) -> bytes:
    with gzip.open(os.path.join(ART, name + ".html.gz"), "rb") as f:
        return f.read()


def site_of(name: str) -> str:
    return name.split("_")[0]


def extract(name: str) -> dict:
    return A.extract(site_of(name), URLS[name], page(name))


ALLOWED = {"p", "h2", "h3", "blockquote", "ul", "ol", "li", "strong", "em", "a", "img", "figure", "figcaption", "br"}
ALLOWED_ATTRS = {"a": {"href", "rel", "data-internal"}, "img": {"src", "alt", "loading", "width", "height"}}


def assert_safe(html_text: str):
    """Каждый тег — из белого списка, атрибуты — только разрешённые, ссылки http(s) или /news/,
    картинки — только /img/news/<ключ из NEWS_IMG_HOSTS>/."""
    low = html_text.lower()
    for bad in ("<script", "<iframe", "<style", "<svg", "<object", "<embed", "<form", "javascript:", "onerror",
                "onload", "onclick", "style=", "srcset", "data:"):
        assert bad not in low, bad
    frag = LH.fragment_fromstring(html_text, create_parent="div")
    keys = tuple(f"/img/news/{k}/" for k in M.NEWS_IMG_HOSTS)
    for el in frag.iter():
        if el is frag or not isinstance(el.tag, str):
            continue
        assert el.tag in ALLOWED, el.tag
        assert set(el.attrib) <= ALLOWED_ATTRS.get(el.tag, set()), (el.tag, dict(el.attrib))
        if el.tag == "a":
            href = el.get("href")
            assert href.startswith(("https://", "http://", "/news/")), href
            if not href.startswith("/news/"):
                assert el.get("rel") == "noopener nofollow"
        if el.tag == "img":
            assert el.get("src").startswith(keys), el.get("src")


# ----------------------------------------------------------------------------- разбор по сайтам

def test_championat_article_with_photo():
    a = extract("championat_photo")
    assert a["title"] == "Неймар назвал Ламина Ямаля лучшим футболистом в мире"
    assert a["author"] == "Елизавета Искам"
    assert a["published"] == "2026-10-16T22:46:57Z"
    assert a["image"].startswith("/img/news/championat/news/big/") and a["image_caption"] == "Фото: Getty Images"
    # фото в тексте: подписанный адрес ресайзера → тот же файл без подписи, подпись — в figcaption
    assert '<figure><img src="/img/news/championat/i/e/w/17921904111931825592.jpg"' in a["html"]
    assert "<figcaption>Фото: Соцсети Неймара</figcaption>" in a["html"]
    assert a["html"].count("<p>") == 3 and a["images"] == 1 and a["chars"] > 800
    assert_safe(a["html"])


def test_championat_drops_related_and_player():
    a = extract("championat_endrick")
    assert a["title"].startswith("Моуринью видит Эндрика")
    assert a["html"].count("<p>") == 4
    assert "Материалы по теме" not in a["html"] and "CHAMP(" not in a["html"]   # блок «по теме», плеер
    assert "<strong>" in a["html"] and 'href="https://www.championat.com/tags/723-zhoze-mourinju/"' in a["html"]
    assert a["origin"] == "AS"
    assert_safe(a["html"])


def test_sportsru_news_lead_links_origin():
    a = extract("sportsru_news")
    assert a["title"].startswith("Тебас о возможном наказании")
    assert a["lead"] == "Тебас высказался о возможном наказании за слова про ТВ «Реала»."
    assert a["author"] == "Ilia Shevchenko" and a["origin"] == "аккаунт Хавьера Тебаса в X"
    assert a["published"] == "2026-10-16T21:23:00Z"
    assert a["image"] == "/img/news/sportsru/dynamic_images/news/111/740/353/8/share/e6c98b_no_logo_no_text.jpg"
    assert a["html"].count("<p>") == 12 and "ad-slot" not in a["html"]
    # ссылка на другую новость Sports.ru — пока внешняя (внутренней её сделает API, если новость у нас есть)
    assert ('href="https://www.sports.ru/football/1117403499-sportivnyj-sovet-ispanii-dumaet-nakazat-tebasa-'
            'za-slova-o-reale.html" rel="noopener nofollow"') in a["html"]
    assert_safe(a["html"])


def test_sportsru_blog_subtitles_photos_no_promo():
    a = extract("sportsru_blog")
    assert a["title"].startswith("Вундеркинд из «МЮ»") and a["author"]
    assert a["published"] == "2026-10-15T16:40:00Z"                  # блог: дата из data-test="published-date"
    assert a["hero_in_text"] and a["html"].splitlines()[1].startswith("<figure>")  # фото — в тексте, не дублируем
    assert a["html"].count("<h2>") == 4
    assert a["images"] == 5 and a["html"].count('src="/img/news/sportsru-photo/preset/') == 5
    assert "sprts.cc" not in a["html"] and "dumpster" not in a["html"]  # промо-картинка со ссылкой — убрана
    assert "фрибет" not in a["html"].lower()
    assert a["words"] > 1000
    assert_safe(a["html"])


def test_sportsru_live_blog_has_no_text():
    # онлайн-трансляция в блоге: записи рисует скрипт, в HTML только первая строка
    with pytest.raises(A.NoArticle):
        extract("sportsru_liveblog")


def test_sportexpress_article_no_promo_no_generated_cover():
    a = extract("sportexpress_real")
    assert a["title"] == "«Реал» потребовал отставки президента Ла лиги за сравнение с нацистской Германией"
    assert a["author"] == "Алексей Михайлов" and a["published"] == "2026-10-16T13:49:00Z"
    assert a["image"] is None              # og:image у СЭ — сгенерированная карточка с заголовком, не фото
    assert "Max" not in a["html"] and "max.ru" not in a["html"]
    assert a["html"].count("<p>") == 5
    assert_safe(a["html"])


def test_sportexpress_drops_announcement_block():
    a = extract("sportexpress_rivaldo")
    assert "Акинфеев тоже заслужил" not in a["html"] and "image_preview.svg" not in a["html"]
    assert a["html"].startswith("<p>") and a["chars"] > 300
    assert_safe(a["html"])


def test_stub_pages_are_not_articles():
    # заглушка SSO «Чемпионата» (её отдают без cookie) и пустая страница — не статья
    sso = ('<!DOCTYPE html><html lang="ru"><head><meta name="robots" content="noindex, nofollow"><title>Чемпионат'
           '</title></head><body><div class="auth-container"><h2>Вход через SberID</h2><p>Пожалуйста, подождите, '
           'выполняется перенаправление...</p></div><script src="/static/auth/_script.js"></script></body></html>')
    with pytest.raises(A.NoArticle):
        A.extract("championat", URLS["championat_photo"], sso)
    with pytest.raises(A.NoArticle):
        A.extract("sportexpress", URLS["sportexpress_real"], b"   ")
    with pytest.raises(A.NoArticle):
        A.extract("unknown", "https://example.com/", b"<p>x</p>")


# ----------------------------------------------------------------------------- санитизация

EVIL_BODY = """
<p>Нормальный абзац с <b>жирным</b>, <i>курсивом</i> и <a href="/football/club/real/" onclick="steal()">ссылкой</a>.
Текст достаточно длинный, чтобы статья считалась статьёй, а не заглушкой: ещё немного слов про «Реал».</p>
<p><script>alert(1)</script>Перед скриптом и после<style>p{color:red}</style></p>
<p><img src="x" onerror="alert(1)"><img src="https://evil.example/tracker.jpg" alt="чужая">
<img src="data:image/png;base64,AAAA"><img src="https://img.championat.com/news/big/a/b/ok.jpg" onload="x()" style="width:1px"></p>
<p><a href="javascript:alert(1)">js-ссылка</a> <a href="data:text/html,<script>1</script>">data</a>
<a href="mailto:a@b.c">почта</a> <a href="https://ok.example/page">внешняя</a></p>
<iframe src="https://evil.example/frame"></iframe>
<p><svg onload="alert(1)"><circle/></svg><object data="x.swf"></object><embed src="x.swf">ок</p>
<p>&lt;script&gt;alert("в тексте")&lt;/script&gt; — это просто текст</p>
<p><span style="color:red" class="x" id="y" data-x="1">обёртка</span><form><input value="x"></form></p>
<h2 onmouseover="x()">Подзаголовок</h2>
<ul><li>пункт <u>один</u></li><li onclick="x">два</li></ul>
<blockquote cite="x">цитата</blockquote>
<figure><img src="https://evil.example/pic.jpg"><figcaption>чужое фото</figcaption></figure>
"""


@pytest.mark.parametrize("site,wrap", [
    ("championat", '<article class="article"><div class="article-head__title">Заголовок</div>'
                   '<div class="article-content" id="articleBody">{}</div></article>'),
    ("sportexpress", '<h1 class="se-material-page__title">Заголовок</h1>'
                     '<div class="se-material-page__content">{}</div>'),
    ("sportsru", '<div class="structured-body-wrapper">{}</div>'),
])
def test_sanitizer_whitelist(site, wrap):
    url = {"championat": "https://www.championat.com/football/news-1-x.html",
           "sportexpress": "https://www.sport-express.ru/football/spain/news/x-1/",
           "sportsru": "https://www.sports.ru/football/1-x.html"}[site]
    a = A.extract(site, url, "<html><body>" + wrap.format(EVIL_BODY) + "</body></html>")
    h = a["html"]
    assert_safe(h)
    assert "alert(1)" not in h and "evil.example/tracker" not in h and "evil.example/pic" not in h
    assert "чужое фото" not in h                        # фигура без нашей картинки удалена целиком
    assert '<img src="/img/news/championat/news/big/a/b/ok.jpg" alt="" loading="lazy">' in h
    assert "<strong>жирным</strong>" in h and "<em>курсивом</em>" in h
    # относительная ссылка → абсолютная на сайт источника, с rel; js:/data:/mailto: → только текст
    host = re.match(r"https://[^/]+", url).group(0)
    assert f'<a href="{host}/football/club/real/" rel="noopener nofollow">ссылкой</a>' in h
    assert "js-ссылка" in h and "почта" in h and '<a href="https://ok.example/page" rel="noopener nofollow">' in h
    assert "&lt;script&gt;alert(&quot;в тексте&quot;)&lt;/script&gt;" in h or "&lt;script&gt;alert(\"в тексте\")" in h
    assert "<h2>Подзаголовок</h2>" in h and "<ul><li>пункт один</li><li>два</li></ul>" in h
    assert "<blockquote>цитата</blockquote>" in h and "обёртка" in h


def test_image_paths_only_known_hosts():
    p = M.news_image_path
    assert p("https://img.championat.com/mPk9Y2PBJtRXqX6EL3TceOga2ODm4ytYBSr2e-RBqnY/p()/news/big/u/g/a_1.jpg") \
        == "/img/news/championat/news/big/u/g/a_1.jpg"
    assert p("https://img.championat.com/bgDUpkkhWeR2TesahpB8oGfeDSJ9gRG5DmvkHPh1mZE/p(w:732/h:488)/i/e/w/1.jpg") \
        == "/img/news/championat/i/e/w/1.jpg"
    assert p("https://photobooth.cdn.sports.ru/preset/wysiwyg/8/d4/59ae.jpeg?f=webp&q=90&w=730") \
        == "/img/news/sportsru-photo/preset/wysiwyg/8/d4/59ae.jpeg"
    assert p("https://ss.sport-express.ru/userfiles/materials/223/2234100/don.jpg") \
        == "/img/news/sportexpress/userfiles/materials/223/2234100/don.jpg"
    assert p("https://ss.sport-express.ru/img-gen/%D0%A4+x.jpg") is None          # не фото, а карточка
    assert p("https://photobooth.cdn.sports.ru/other/x.jpg") is None               # не тот префикс
    assert p("https://evil.example/preset/x.jpg") is None
    assert p("https://img.championat.com/a/../../etc/passwd.jpg") is None
    assert p("javascript:alert(1)//img.championat.com/x.jpg") is None


def test_nginx_has_location_for_every_image_key():
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    with open(os.path.join(root, "deploy", "nginx.conf.template"), encoding="utf-8") as f:
        conf = f.read()
    for key, (host, prefix) in M.NEWS_IMG_HOSTS.items():
        assert f'location ~ "^/img/news/{key}/' in conf, key
        assert f"https://{host}/$rmv2p" in conf, host


def test_link_internal_rewrites_known_news_only():
    h = ('<p><a href="https://www.sports.ru/football/1117403499-x.html" rel="noopener nofollow">своя</a> '
         '<a href="https://www.sports.ru/football/person/x/" rel="noopener nofollow">чужая</a></p>')
    out = A.link_internal(h, {"sports.ru/football/1117403499-x.html": "abcdef012345"})
    assert '<a href="/news/abcdef012345" data-internal="1">своя</a>' in out
    assert 'href="https://www.sports.ru/football/person/x/" rel="noopener nofollow"' in out


def test_news_aid():
    aid = M.news_aid("sports.ru/football/1117403538-x.html")
    assert re.fullmatch(r"[0-9a-f]{12}", aid) and M.is_aid(aid) and aid == M.news_aid("sports.ru/football/1117403538-x.html")
    assert not M.is_aid("../../etc") and not M.is_aid("ABCDEF012345")


# ----------------------------------------------------------------------------- сборщик и API

def _item(name: str, **kw) -> dict:
    url = URLS[name]
    site = site_of(name)
    return {"id": M.canonical_url(url), "feed": site, "site": site, "source": SOURCE[site],
            "title": f"Новость {name}", "summary": f"Лид из ленты для {name}.", "url": url,
            "published": "2026-10-16T20:00:00Z", "image": None, "categories": [], "tagged": False, **kw}


OTHER = {"id": "sports.ru/football/1117403499-sportivnyj-sovet-ispanii-dumaet-nakazat-tebasa-za-slova-o-reale.html",
         "feed": "sportsru_top", "site": "sportsru", "source": "Sports.ru", "title": "Спортивный совет Испании",
         "summary": "", "url": "https://www.sports.ru/football/1117403499-sportivnyj-sovet-ispanii-dumaet-nakazat-"
                                "tebasa-za-slova-o-reale.html",
         "published": "2026-10-16T19:00:00Z", "image": None, "categories": [], "tagged": False}

NAMES = ["sportsru_news", "championat_photo", "sportexpress_real", "sportsru_liveblog", "championat_endrick",
         "sportsru_blog", "sportexpress_rivaldo"]


def _snapshot(conn):
    items = [_item(n) for n in NAMES] + [OTHER]
    store.put(conn, "news", "test", {"items": items, "feeds": {}})
    return items


def _fake_pages(calls: list, missing=frozenset(), down=frozenset()):
    by_url = {u: n for n, u in URLS.items()}

    async def fetch(self, url, params=None):
        calls.append((self.name, url))
        if self.name in down:
            raise TimeoutError("timeout")
        if url in missing:
            raise NotFound(f"404 {url}")
        if url in by_url:
            return page(by_url[url])
        raise AssertionError(url)
    return fetch


def test_page_sources_headers():
    srcs = M.make_sources()
    try:
        for name in ("championat_pages", "sportexpress_pages", "sportsru_pages"):
            s = srcs[name]
            assert s.client.headers["User-Agent"] == M.PAGE_UA and "text/html" in s.client.headers["Accept"]
        assert srcs["championat_pages"].client.cookies.get("unity_pause_sso") == "1"
        assert srcs["sportsru_pages"].client.cookies.get("unity_pause_sso") is None
    finally:
        for s in srcs.values():
            asyncio.run(s.close())


def test_prefetch_limits_and_cache_forever(tmp_db, monkeypatch):
    calls: list = []
    monkeypatch.setattr(M.RssSource, "_fetch", _fake_pages(calls))
    conn = store.connect()
    items = _snapshot(conn)
    c = Collector(conn)
    try:
        n = asyncio.run(c._prefetch_articles(items, 3))
        assert n == 3 and len(calls) == 3                              # не больше N страниц за цикл
        assert [u for _, u in calls] == [URLS[x] for x in NAMES[:3]]   # свежие сначала
        assert {s for s, _ in calls} == {"sportsru_pages", "championat_pages", "sportexpress_pages"}
        n = asyncio.run(c._prefetch_articles(items, 10))
        assert n == 5                                                   # готовые не скачиваем снова
        n = asyncio.run(c._prefetch_articles(items, 10))
        assert n == 0                                                   # кэш навсегда; live-блог ждёт повтора
        assert c.cycles["article"] == 8 and c.cycles["article_failed"] == 2   # live-блог и OTHER без страницы
    finally:
        asyncio.run(c.close())
    a = store.get(conn, f"article:{M.news_aid(items[0]['id'])}")
    assert a["source"] == "sportsru_pages" and a["data"]["lead"].startswith("Тебас высказался")
    assert a["data"]["source"] == "Sports.ru" and a["data"]["title"] == "Новость sportsru_news"
    fail = store.get(conn, f"article_fail:{M.news_aid(_item('sportsru_liveblog')['id'])}")
    assert fail["data"]["tries"] == 1 and fail["data"]["status"] == "no_text"
    # у Sports.ru картинка новости берётся со страницы статьи — og:image отдельно не нужен
    assert items[0]["image"].startswith("/img/news/sportsru/dynamic_images/") and items[0]["img_tried"]


def test_article_rate_limit_per_minute(tmp_db, monkeypatch):
    calls: list = []
    monkeypatch.setattr(M.RssSource, "_fetch", _fake_pages(calls))
    monkeypatch.setattr(config, "ARTICLE_RATE_PER_MIN", 2)
    conn = store.connect()
    items = _snapshot(conn)
    c = Collector(conn)
    try:
        assert asyncio.run(c._prefetch_articles(items, 10)) == 2
    finally:
        asyncio.run(c.close())


def test_retry_and_not_found(tmp_db, monkeypatch):
    calls: list = []
    monkeypatch.setattr(M.RssSource, "_fetch", _fake_pages(calls, missing={URLS["championat_photo"]}))
    conn = store.connect()
    _snapshot(conn)
    c = Collector(conn)
    live = M.news_aid(_item("sportsru_liveblog")["id"])
    gone = M.news_aid(_item("championat_photo")["id"])
    try:
        asyncio.run(c.refresh_article(_item("sportsru_liveblog")))
        asyncio.run(c.refresh_article(_item("championat_photo")))
        now = time.time()
        assert c._article_state(live, now) == "wait"
        assert c._article_state(live, now + config.ARTICLE_RETRY + 1) == "due"      # повтор через 30 мин
        assert store.get(conn, f"article_fail:{gone}")["data"]["tries"] == config.ARTICLE_MAX_TRIES
        assert c._article_state(gone, now + 10 * config.ARTICLE_RETRY) == "wait"    # 404 — больше не ходим
    finally:
        asyncio.run(c.close())


def test_breaker_open_does_not_count_as_try(tmp_db, monkeypatch):
    calls: list = []
    monkeypatch.setattr(M.RssSource, "_fetch", _fake_pages(calls, down={"championat_pages"}))
    conn = store.connect()
    items = _snapshot(conn)
    c = Collector(conn)
    try:
        for _ in range(config.BREAKER_THRESHOLD):
            asyncio.run(c.refresh_article(_item("championat_photo")))
        assert c.media["championat_pages"].snapshot()["breaker"] == "open"
        before = len(calls)
        assert asyncio.run(c.refresh_article(_item("championat_endrick"))) is None
        assert len(calls) == before                                     # breaker: в источник не ходим
        assert store.get(conn, f"article_fail:{M.news_aid(_item('championat_endrick')['id'])}") is None
        # прочие сайты breaker «Чемпионата» не задевает
        assert asyncio.run(c.refresh_article(items[0]))["parser"] == "sportsru"
    finally:
        asyncio.run(c.close())


def test_api_article_pending_then_full(tmp_db, monkeypatch):
    calls: list = []
    monkeypatch.setattr(M.RssSource, "_fetch", _fake_pages(calls))
    conn = store.connect()
    items = _snapshot(conn)
    from app.main import app
    api = TestClient(app)
    aid = M.news_aid(items[0]["id"])

    assert api.get("/api/news/zzz").status_code == 404
    assert api.get("/api/news/0123456789ab").status_code == 404

    r = api.get(f"/api/news/{aid}")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    d = r.json()
    assert d["pending"] and not d["full"] and d["html"] is None and d["source"] == "Sports.ru"
    assert d["title"] == "Новость sportsru_news" and d["summary"].startswith("Лид из ленты")
    assert store.peek_article_demand(conn, 5) == [aid]
    assert len(d["more"]) == 3 and d["more"][0]["aid"] == M.news_aid(items[1]["id"])

    c = Collector(conn)
    try:
        done = asyncio.run(c.tick_articles(time.time()))
    finally:
        asyncio.run(c.close())
    assert done == [aid] and store.peek_article_demand(conn, 5) == []

    r = api.get(f"/api/news/{aid}")
    d = r.json()
    assert r.headers["cache-control"] == "public, max-age=300"
    assert d["full"] and not d["pending"] and d["available"] == ["text", "image"]
    assert d["lead"].startswith("Тебас высказался") and d["author"] == "Ilia Shevchenko"
    assert d["url"] == URLS["sportsru_news"] and d["site"] == "sportsru"
    # ссылка на новость, которая есть у нас, — внутренняя; на прочие страницы — внешняя
    assert f'<a href="/news/{M.news_aid(OTHER["id"])}" data-internal="1">информацию</a>' in d["html"]
    assert 'href="https://www.sports.ru/football/person/javier-tebas/" rel="noopener nofollow"' in d["html"]
    assert_safe(d["html"])
    # «ещё новости» с конца ленты — самые свежие, без этой же
    last = M.news_aid(OTHER["id"])
    more = api.get(f"/api/news/{last}").json()["more"]
    assert [m["aid"] for m in more] == [M.news_aid(i["id"]) for i in items[:3]]

    h = api.get("/api/health/sources").json()
    assert h["articles"] == {"texts": 1, "failed": 0, "queued": 1}      # заявка на `last` от запроса выше
    assert not any(k.startswith("article") for k in h["snapshots"])
    assert [s["name"] for s in h["media_sources"]] == []                # состояние ещё не писали


def test_api_article_partial_after_failures(tmp_db, monkeypatch):
    calls: list = []
    monkeypatch.setattr(M.RssSource, "_fetch", _fake_pages(calls))
    conn = store.connect()
    _snapshot(conn)
    from app.main import app
    api = TestClient(app)
    it = _item("sportsru_liveblog")
    aid = M.news_aid(it["id"])
    c = Collector(conn)
    try:
        asyncio.run(c.refresh_article(it))
    finally:
        asyncio.run(c.close())
    d = api.get(f"/api/news/{aid}").json()
    assert not d["pending"] and not d["full"] and d["reason"] == "no_text"
    assert d["summary"] == "Лид из ленты для sportsru_liveblog." and d["available"] == ["summary"]
    assert d["url"] == URLS["sportsru_liveblog"] and store.peek_article_demand(conn, 5) == []


def test_api_article_survives_news_rotation(tmp_db, monkeypatch):
    calls: list = []
    monkeypatch.setattr(M.RssSource, "_fetch", _fake_pages(calls))
    conn = store.connect()
    items = _snapshot(conn)
    c = Collector(conn)
    try:
        asyncio.run(c.refresh_article(items[1]))
    finally:
        asyncio.run(c.close())
    store.put(conn, "news", "test", {"items": [OTHER], "feeds": {}})   # новость ушла из ленты
    from app.main import app
    d = TestClient(app).get(f"/api/news/{M.news_aid(items[1]['id'])}").json()
    assert d["full"] and d["source"] == "Чемпионат" and d["html"].startswith("<p>")
    assert d["image_caption"] == "Фото: Getty Images"


def test_news_cycle_in_match_window_fetches_no_articles(tmp_db, monkeypatch):
    from .test_media import _fake_fetch, _put_team
    pages: dict = {}
    monkeypatch.setattr(M.RssSource, "_fetch", _fake_fetch(pages=pages))
    conn = store.connect()
    _put_team(conn)
    c = Collector(conn)
    try:
        r = asyncio.run(c.refresh_news(og_limit=0, article_limit=0))
    finally:
        asyncio.run(c.close())
    assert r["articles"] == 0 and r["og"] == 0 and pages == {}
