"""Медиа: разбор лент на сохранённых реальных ответах, фильтр «про Реал», дедупликация,
видео YouTube, картинки, сборщик и API. Без сети: всё — из tests/fixtures."""
import asyncio
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import store
from app.collector import Collector
from app.sources import fotmob, media as M
from app.sources.base import SourceError

from .conftest import FIX, load

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
TEAM_FIXTURE = os.path.join(ROOT, "frontend", "src", "__fixtures__", "team.json")


def raw(name: str) -> bytes:
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


def labels(name: str) -> dict:
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return {r["id"]: r for r in json.load(f)["items"]}


def squad_ids() -> set[int]:
    with open(TEAM_FIXTURE, encoding="utf-8") as f:
        t = json.load(f)
    return {p["id"] for line in t["squad"].values() for p in line} | {t["coach"]["id"]}


FEEDS = {f.key: f for f in M.NEWS_FEEDS}


def parsed(key: str) -> list[dict]:
    return M.parse_rss(FEEDS[key], raw(f"rss_{key}.xml"))


# ---------------------------------------------------------------- разбор RSS

@pytest.mark.parametrize("key,count,with_images", [
    ("championat", 31, 31), ("sportexpress", 220, 0), ("sportsru_top", 20, 0), ("sportsru_real", 93, 0)])
def test_parse_each_feed(key, count, with_images):
    items = parsed(key)
    assert len(items) == count
    assert sum(1 for i in items if i["image"]) == with_images
    for i in items:
        assert i["title"] and "\n" not in i["title"] and "<" not in i["title"]
        assert i["url"].startswith("https://") and i["url"] == i["url"].strip()
        assert i["published"] and i["published"].endswith("Z") and len(i["published"]) == 20
        assert i["source"] == FEEDS[key].title and i["site"] == FEEDS[key].site
        assert len(i["summary"]) <= 281
        assert i["image"] is None or i["image"].startswith("/img/news/")


def test_parse_details():
    ch = parsed("championat")[1]
    assert ch["published"] == "2026-10-16T22:34:29Z"            # 01:34:29 +0300 → UTC
    assert ch["image"].startswith("/img/news/championat/news/big/")
    assert "ЧМ-2026" in ch["categories"]
    se = parsed("sportexpress")[1]
    assert se["categories"] == ["Футбол - Франция"] and se["summary"].startswith("«Труа»")
    real = parsed("sportsru_real")
    assert all(i["tagged"] for i in real)
    assert real[0]["url"].startswith("https://www.sports.ru/football/")   # CDATA с пробелами
    # реклама sirena.sports.ru в ленте тега — не новость
    assert not any("sirena" in i["url"] for i in real)


def test_parse_broken_xml():
    with pytest.raises(ValueError):
        M.parse_rss(FEEDS["championat"], b"<rss><channel><item><title>x</title>")


# ---------------------------------------------------------------- фильтр

def _score(path: str, feeds: list[tuple[M.Feed, bytes]], tagged=None):
    lab = labels(path)
    sq = squad_ids()
    tp = fp = fn = tn = 0
    seen = set()
    errors = []
    for feed, body in feeds:
        for it in M.parse_rss(feed, body):
            if it["id"] not in lab or it["id"] in seen:
                continue
            seen.add(it["id"])
            if tagged is not None:
                it["tagged"] = tagged
            y = bool(lab[it["id"]]["rm"])
            p = M.is_about_rm(it, sq)
            tp += p and y
            fp += p and not y
            fn += (not p) and y
            tn += (not p) and not y
            if p != y:
                errors.append(("FP" if p else "FN", it["title"]))
    return {"n": len(seen), "tp": tp, "fp": fp, "fn": fn, "tn": tn}, errors


def _main_set():
    return _score("news_labeled.json", [(FEEDS[k], raw(f"rss_{k}.xml")) for k in FEEDS])


def _holdout_set():
    feeds = [(M.Feed(f"hold_{c}", "sportsru", "Sports.ru", ""), raw(f"hold_sportsru_{c}.xml"))
             for c in ("real-sociedad", "betis", "atletico", "barcelona")]
    return _score("news_labeled_holdout.json", feeds, tagged=False)


def _final_set():
    feeds = [(M.Feed(f"final_{c}", "sportsru", "Sports.ru", ""), raw(f"final_sportsru_{c}.xml"))
             for c in ("laliga", "ucl")]
    return _score("news_labeled_final.json", feeds, tagged=False)


def _pr(c):
    return c["tp"] / max(1, c["tp"] + c["fp"]), c["tp"] / max(1, c["tp"] + c["fn"])


def test_labeled_sample_is_big_enough():
    main, _ = _main_set()
    hold, _ = _holdout_set()
    final, _ = _final_set()
    assert main["n"] == 361 and hold["n"] == 309 and final["n"] == 56   # без рекламы и видео-ссылок
    assert main["n"] + hold["n"] + final["n"] >= 150


def test_filter_precision_recall_main():
    """Основная выборка: 4 боевые ленты (Чемпионат, СЭ, Sports.ru топ и тег «Реал»), 365 заголовков."""
    c, errors = _main_set()
    p, r = _pr(c)
    print(f"\nmain: {c} precision={p:.3f} recall={r:.3f}", *errors, sep="\n  ")
    assert p >= 0.95 and r >= 0.85, (c, errors)


def test_filter_precision_recall_pooled():
    """Основная + отложенная (теги «Реал Сосьедад», «Бетис», «Атлетико», «Барселона» — там много
    чужих «Реалов» и упоминаний Реала вскользь) + контрольная (теги «Ла Лига», «ЛЧ»)."""
    total = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for fn_ in (_main_set, _holdout_set, _final_set):
        c, errors = fn_()
        p, r = _pr(c)
        print(f"\n{fn_.__name__}: {c} precision={p:.3f} recall={r:.3f}", *errors, sep="\n  ")
        for k in total:
            total[k] += c[k]
    p, r = _pr(total)
    print(f"pooled: {total} precision={p:.3f} recall={r:.3f}")
    assert p >= 0.95 and r >= 0.85
    final, _ = _final_set()
    assert final["fp"] == 0


@pytest.mark.parametrize("title,summary,expected", [
    ("«Реал Сосьедад» упустил победу над «Юнионом» в Лиге Европы", "", False),
    ("«Юнион» — «Реал Сосьеад»: Захарян остался в запасе", "", False),        # опечатка в ленте
    ("Дом вингера «Бетиса» Антони ограбили во время матча с «Порту»", "", False),
    ("Пресс-атташе «Сосьедада» о Захаряне: «У него нет намерения покидать «Реал»", "", False),
    ("Брат Мбаппе получил красную в матче с «Бетисом»", "", False),
    ("Вальверде отказал Браулио. Теперь «Валенсия» считает деньги на нового тренера", "", False),
    ("Эррера раскрыл причину конфликта между Моуринью и Погба в «Манчестер Юнайтед»", "", False),
    ("«Барселона» лидирует в Ла Лиге, «Реал» отстает на 3 балла, «Атлетико» – на 5", "", False),
    ("«Реал» обыграл «Барселону» в Евролиге", "Баскетбольный «Реал» победил.", False),
    ("Апелляция «Реала» на дисквалификацию Винисиуса отклонена", "", True),
    ("Мбаппе стал восьмым игроком, забившим в своем 100-м матче Лиги чемпионов", "", True),
    ("Моуринью назвал неуважением объявление дисквалификации Винисиуса", "", True),
    ("Тебас о возможном наказании за слова о ТВ «Мадрида»", "", True),
    ("«Реал» – «Реал Сосьедад»: Мбаппе оформил дубль", "", True),
    ("Флорентино Перес: клуб не продаст Вальверде", "", True),
])
def test_filter_cases(title, summary, expected):
    assert M.is_about_rm({"title": title, "summary": summary}, squad_ids()) is expected


def test_filter_uses_current_squad_only():
    t = {"title": "Карвахаль ответил, почему решил перейти в «Хетафе»", "summary": ""}
    assert not M.is_about_rm(t, squad_ids())                   # ушёл из Реала — фамилии в словаре нет
    t = {"title": "Беллингем — о своём положении в команде", "summary": ""}
    assert M.is_about_rm(t, squad_ids())
    assert not M.is_about_rm(t, squad_ids() - {1077894})       # продали — новости о нём не про Реал


# ---------------------------------------------------------------- дедупликация

def test_dedupe_same_url_between_sportsru_feeds():
    top, tag = parsed("sportsru_top"), parsed("sportsru_real")
    common = {i["id"] for i in top} & {i["id"] for i in tag}
    assert common
    out = M.dedupe(top + tag)
    assert len(out) == len(top) + len(tag) - len(common)
    assert all(i["tagged"] for i in out if i["id"] in common)


def test_dedupe_between_sites():
    sq = squad_ids()
    items = [i for k in FEEDS for i in parsed(k) if M.is_about_rm(i, sq)]
    out = M.dedupe(items)
    by_title = {i["title"]: i for i in out}
    bell = next(i for t, i in by_title.items() if t.startswith("Источник: «Реал» близок к продлению"))
    assert bell["source"] == "Спорт-Экспресс" and bell["also"] == ["Sports.ru"]
    assert not any(t.startswith("«Реал» и Беллингем продлят контракт") for t in by_title)
    # разные новости про одного игрока не склеиваются
    assert sum(1 for t in by_title if t.startswith("Винисиус")) >= 4
    assert len(out) < len({i["id"] for i in items})


def test_same_story():
    assert M.same_story("Источник: «Реал» близок к продлению контракта с Беллингемом до 2031 года",
                        "«Реал» и Беллингем продлят контракт до 2031 года. Хавбеку повысят зарплату")
    assert not M.same_story("Винисиус: «Сейчас у меня непростой период, но я вернусь»",
                            "Винисиус о свисте болельщиков: «Люди платят деньги»")


def test_dedupe_same_site_kept():
    a = {"id": "a", "site": "sportexpress", "source": "СЭ", "published": "2026-10-16T10:00:00Z",
         "title": "Апелляция «Реала» на дисквалификацию Винисиуса отклонена клубом"}
    b = {**a, "id": "b", "published": "2026-10-16T11:00:00Z"}
    assert len(M.dedupe([a, b])) == 2
    c = {**a, "id": "c", "site": "sportsru", "source": "Sports.ru"}
    assert len(M.dedupe([a, c])) == 1


def test_merge_news_keeps_week_and_filters_old():
    now = time.time()
    old = [{"id": "x", "site": "sportsru", "source": "Sports.ru", "title": "Мбаппе забил «Севилье»",
            "summary": "", "published": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 8 * 86400))},
           {"id": "y", "site": "sportsru", "source": "Sports.ru", "title": "«Реал Сосьедад» победил",
            "summary": "", "published": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))}]
    fresh = [{"id": "z", "site": "sportsru", "source": "Sports.ru", "title": "Моуринью о матче с «Севильей»",
              "summary": "", "published": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 60))}]
    out = M.merge_news(old, fresh, squad_ids(), now=now)
    assert [i["id"] for i in out] == ["z"]


# ---------------------------------------------------------------- картинки

@pytest.mark.parametrize("url,expected", [
    ("https://img.championat.com/news/big/x/j/neymar_1792.jpg", "/img/news/championat/news/big/x/j/neymar_1792.jpg"),
    ("https://www.sports.ru/dynamic_images/news/111/740/353/8/share/e6c98b_no_logo_no_text.jpg",
     "/img/news/sportsru/dynamic_images/news/111/740/353/8/share/e6c98b_no_logo_no_text.jpg"),
    ("https://img.championat.com/news/a.jpg?x=1", "/img/news/championat/news/a.jpg"),
    ("https://www.sports.ru/i/logo.png", None),                          # не тот префикс
    ("https://evil.example/news/a.jpg", None),                          # хост не из списка
    ("https://img.championat.com.evil.example/a.jpg", None),
    ("https://img.championat.com/news/%D0%A4.jpg", None),               # не ASCII — nginx не пропустит
    ("https://img.championat.com/news/../../etc/passwd.jpg", None),
    ("https://img.championat.com/news/a.svg", None),
    ("https://ss.sport-express.ru/img-gen/%D0%A4.jpg?full", None),      # картинка-заголовок СЭ
    ("javascript:alert(1)", None),
    (None, None),
])
def test_news_image_path(url, expected):
    assert M.news_image_path(url) == expected


def test_og_image():
    page = b'<html><head><meta property="og:image" content="https://www.sports.ru/dynamic_images/a.jpg">'
    assert M.og_image(page) == "https://www.sports.ru/dynamic_images/a.jpg"
    assert M.og_image(b'<meta content="https://x/y.png" property="og:image"/>') == "https://x/y.png"
    assert M.og_image(b"<html></html>") is None


# ---------------------------------------------------------------- видео

def test_parse_youtube():
    v = M.parse_youtube(raw("rss_youtube.xml"))
    assert len(v) == 15
    assert sum(x["short"] for x in v) == 11
    titles = [x["title"] for x in v]
    for t in titles:
        assert t == t.strip() and t
        assert not M._EMOJI.search(t), t
        assert "#" not in t
    first = v[0]
    assert first["id"] == "yaadxZp8v84" and first["short"] and first["kind"] == "short"
    assert first["title"] == "Vini Jr."                                  # «🎯 Vini Jr. 🎯 #RMCity #RealMadrid»
    assert first["url"] == "https://www.youtube.com/shorts/yaadxZp8v84"
    assert first["thumb"] == "/img/yt/yaadxZp8v84.jpg" and first["published"] == "2026-10-16T17:24:50Z"
    assert "Getting READY for SEVILLA with some BRILLIANT goals!" in titles   # без «🔛» и «| Real Madrid»
    hl = next(x for x in v if x["id"] == "zkgpyvjJl84")
    assert hl["kind"] == "highlights" and not hl["short"] and hl["url"].endswith("watch?v=zkgpyvjJl84")
    assert hl["title"] == "HIGHLIGHTS | Roma 3-4 Real Madrid | Champions League"
    assert M.video_kind("GOALS | Roma 3-4 Real Madrid", False) == "goals"
    assert M.video_kind("GOALS | Roma 3-4 Real Madrid", True) == "short"


@pytest.mark.parametrize("raw_title,clean", [
    ("🇮🇹 5, 4, 3, 2, 1...", "5, 4, 3, 2, 1..."),
    ("⌚ C.Espí time!", "C.Espí time!"),
    ("Simply, Antonioooo! 🤍", "Simply, Antonioooo!"),
    ("ACCESS DENIED 🚫", "ACCESS DENIED"),
    ("⏱️ MINUTO A MINUTO | AS Roma vs Real Madrid | Champions League",
     "MINUTO A MINUTO | AS Roma vs Real Madrid | Champions League"),
    ("👨‍👩‍👧 Family day ❤️‍🔥", "Family day"),
    ("🔥🔥🔥", "Real Madrid"),
])
def test_clean_video_title(raw_title, clean):
    assert M.clean_video_title(raw_title) == clean


@pytest.mark.parametrize("url,vid", [
    ("https://www.youtube.com/watch?v=zkgpyvjJl84", "zkgpyvjJl84"),
    ("https://youtu.be/zkgpyvjJl84", "zkgpyvjJl84"),
    ("https://www.youtube.com/shorts/yaadxZp8v84", "yaadxZp8v84"),
    ("https://i.ytimg.com/vi/zkgpyvjJl84/maxresdefault.jpg", "zkgpyvjJl84"),
    ("https://www.youtube.com/watch?v=bad", None),
    ("https://vimeo.com/123", None),
    (None, None),
])
def test_youtube_id(url, vid):
    assert M.youtube_id(url) == vid


def test_merge_videos():
    a = [{"id": "a" * 11, "published": "2026-10-01T00:00:00Z", "title": "old"}]
    b = [{"id": "a" * 11, "published": "2026-10-01T00:00:00Z", "title": "new"},
         {"id": "b" * 11, "published": "2026-10-02T00:00:00Z", "title": "b"}]
    out = M.merge_videos(a, b)
    assert [v["id"] for v in out] == ["b" * 11, "a" * 11] and out[1]["title"] == "new"


def test_match_highlights_from_match_snapshot_and_fallback():
    m = fotmob.normalize_match(load("fotmob_match_6106274.json"))
    fx = {"id": m["id"], "kickoff": m["kickoff"], "home": m["home"], "away": m["away"],
          "tournament": m["tournament"], "status": m["status"]}
    vids = M.parse_youtube(raw("rss_youtube.xml"))
    h = M.match_highlights([fx], {str(m["id"]): m}, vids)
    assert len(h) == 1 and h[0]["video_id"] == "zkgpyvjJl84" and h[0]["origin"] == "match"
    assert h[0]["thumb"] == "/img/yt/zkgpyvjJl84.jpg" and h[0]["title"] == "Roma 3:4 Real Madrid"
    # в снимке матча обзора нет — ищем ролик канала «HIGHLIGHTS | Roma 3-4 Real Madrid»
    h2 = M.match_highlights([fx], {str(m["id"]): {**m, "highlights": None}}, vids)
    assert h2[0]["video_id"] == "zkgpyvjJl84" and h2[0]["origin"] == "youtube"
    other = {**fx, "home": {**fx["home"], "name": "Sevilla"}}
    assert M.match_highlights([other], {}, vids) == []


# ---------------------------------------------------------------- сборщик и API

URL_FIXTURE = {f.url: f"rss_{f.key}.xml" for f in M.NEWS_FEEDS}
URL_FIXTURE[M.YT_FEED] = "rss_youtube.xml"


def _fake_fetch(fail: set[str] = frozenset(), pages: dict | None = None):
    async def fetch(self, url, params=None):
        if self.name in fail:
            raise TimeoutError("timeout")
        if url in URL_FIXTURE:
            return raw(URL_FIXTURE[url])
        if pages is not None:
            pages[url] = pages.get(url, 0) + 1
            return b'<meta property="og:image" content="https://www.sports.ru/dynamic_images/x/1.jpg">'
        raise AssertionError(url)
    return fetch


def _put_team(conn):
    with open(TEAM_FIXTURE, encoding="utf-8") as f:
        t = json.load(f)
    store.put(conn, "team", "fotmob", {k: t[k] for k in ("team", "coach", "squad")})


def test_collector_news_videos_and_api(tmp_db, monkeypatch):
    pages: dict = {}
    monkeypatch.setattr(M.RssSource, "_fetch", _fake_fetch(pages=pages))
    conn = store.connect()
    _put_team(conn)
    c = Collector(conn)
    try:
        r = asyncio.run(c.refresh_news(article_limit=0))
        v = asyncio.run(c.refresh_videos())
        c.write_state()
    finally:
        asyncio.run(c.close())
    assert r["feeds"]["sportsru_real"]["ok"] and r["feeds"]["championat"]["matched"] >= 5
    assert r["og"] == 6 and len(pages) == 6                     # не больше 6 страниц за цикл
    assert v["videos"] == 15 and v["shorts"] == 11
    snap = store.get(conn, "news")
    assert snap["source"] == "championat+sportexpress+sportsru"

    from app.main import app
    api = TestClient(app)
    n = api.get("/api/news?limit=5").json()
    assert n["count"] == 5 and n["available"][0] == "news" and not n["stale"]
    it = n["items"][0]
    assert set(it) == {"id", "title", "summary", "source", "url", "published", "image", "aid", "also"}
    assert all(i["published"] >= j["published"] for i, j in zip(n["items"], n["items"][1:]))
    assert api.get("/api/news?limit=999").json()["count"] <= 100
    assert api.get("/api/news").headers["cache-control"] == "public, max-age=60"
    imgs = [i["image"] for i in api.get("/api/news?limit=100").json()["items"] if i["image"]]
    assert imgs and all(i.startswith(("/img/news/championat/", "/img/news/sportsru/dynamic_images/")) for i in imgs)

    vd = api.get("/api/videos?limit=3").json()
    assert vd["count"] == 3 and vd["items"][0]["thumb"].startswith("/img/yt/") and "videos" in vd["available"]
    assert vd["highlights"] == []                                # снимков матчей в базе нет

    h = api.get("/api/health/sources").json()
    names = [s["name"] for s in h["media_sources"]]
    assert names == list(M.MEDIA_SOURCES)
    by = {s["name"]: s for s in h["media_sources"]}
    assert by["sportsru"]["requests"] == 2 and by["youtube"]["requests"] == 1
    assert by["sportsru_pages"]["by_kind"] == {"og": 6}
    assert "news" in h["snapshots"] and "videos" in h["snapshots"]
    assert h["collector"]["cycles"]["news"] == 1


def test_collector_news_all_feeds_down_keeps_snapshot(tmp_db, monkeypatch):
    monkeypatch.setattr(M.RssSource, "_fetch", _fake_fetch(pages={}))
    conn = store.connect()
    c = Collector(conn)
    try:
        asyncio.run(c.refresh_news(og_limit=0, article_limit=0))
        before = store.get(conn, "news")
        monkeypatch.setattr(M.RssSource, "_fetch", _fake_fetch(fail={"championat", "sportexpress", "sportsru"}))
        r = asyncio.run(c.refresh_news())
        assert r["news"] == "stale"
        assert store.get(conn, "news") == before
        # упала одна лента — снимок обновляется по остальным, старые новости остаются
        monkeypatch.setattr(M.RssSource, "_fetch", _fake_fetch(fail={"sportsru"}))
        r = asyncio.run(c.refresh_news(og_limit=0, article_limit=0))
        assert not r["feeds"]["sportsru_real"]["ok"] and r["feeds"]["championat"]["ok"]
        after = store.get(conn, "news")
        assert after["source"] == "championat+sportexpress"
        assert len(after["data"]["items"]) == len(before["data"]["items"])
        monkeypatch.setattr(M.RssSource, "_fetch", _fake_fetch(fail={"youtube"}))
        assert asyncio.run(c.refresh_videos())["videos"] == "stale"
        with pytest.raises(SourceError):
            asyncio.run(c.media["youtube"].text(M.YT_FEED, kind="channel"))
    finally:
        asyncio.run(c.close())


def test_api_media_cold_start(tmp_db):
    from app.main import app
    api = TestClient(app)
    assert api.get("/api/news").status_code == 503
    assert api.get("/api/videos").status_code == 503
