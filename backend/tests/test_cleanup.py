"""Суточная очистка: тексты статей > 90 дн., аватары тех, кого нет > 180 дн., чужие игроки > 30 дн."""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import avatars, cleanup, config, store
from app.collector import Collector
from app.main import app
from app.predictions import db as pdb
from app.sources import media

DAY = 86400
NOW = time.time()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _article(aid: str, **kw) -> dict:
    return {"aid": aid, "id": f"sports.ru/{aid}", "url": f"https://www.sports.ru/{aid}.html", "site": "sportsru",
            "source": "Sports.ru", "title": "Заголовок", "published": "2026-06-01T10:00:00Z", "summary": "Анонс",
            "image": "/img/news/x.jpg", "lead": "Лид " * 50, "html": "<p>" + "текст " * 2000 + "</p>",
            "author": "Автор", "origin": None, "image_caption": None, "words": 2000, "hero_in_text": False, **kw}


# ---------- статьи ----------

def test_old_article_text_removed_news_kept(tmp_db):
    conn = store.connect()
    old, fresh = media.news_aid("old-news"), media.news_aid("fresh-news")
    store.put(conn, f"article:{old}", "sportsru_pages", _article(old), fetched_at=NOW - 91 * DAY)
    store.put(conn, f"article:{fresh}", "sportsru_pages", _article(fresh), fetched_at=NOW - 89 * DAY)
    store.put(conn, "article_fail:aaaaaaaaaaaa", "x", {"tries": 3}, fetched_at=NOW - 91 * DAY)
    store.put(conn, "article_fail:bbbbbbbbbbbb", "x", {"tries": 1}, fetched_at=NOW - DAY)
    before = len(store.get(conn, f"article:{old}")["data"]["html"])

    res = cleanup.articles(conn, NOW)
    assert res == {"article_texts": 1, "article_fails": 1}
    stub = store.get(conn, f"article:{old}")
    assert stub["data"]["text_removed"] and "html" not in stub["data"] and "lead" not in stub["data"]
    assert stub["data"]["title"] == "Заголовок" and stub["data"]["url"].endswith(f"{old}.html")
    assert stub["fetched_at"] == NOW - 91 * DAY  # время не трогаем — повторно не обрабатывается
    assert len(str(stub["data"])) < before / 10
    assert store.get(conn, f"article:{fresh}")["data"]["html"]
    assert store.get(conn, "article_fail:bbbbbbbbbbbb") and not store.get(conn, "article_fail:aaaaaaaaaaaa")
    assert cleanup.articles(conn, NOW) == {"article_texts": 0, "article_fails": 0}  # идемпотентно

    # API: новость открывается (заголовок, ссылка на источник), текста нет, заявку сборщику не ставит
    r = TestClient(app).get(f"/api/news/{old}")
    assert r.status_code == 200
    b = r.json()
    assert b["full"] is False and b["reason"] == "expired" and b["pending"] is False
    assert b["title"] == "Заголовок" and b["url"].endswith(f"{old}.html") and b["html"] is None
    assert conn.execute("SELECT COUNT(*) FROM article_demand").fetchone()[0] == 0
    # сборщик считает статью готовой — заново не качает
    c = Collector(conn)
    assert c._article_state(old, NOW) == "done"
    asyncio.run(c.close())


# ---------- игроки ----------

def test_foreign_player_snapshots_older_30_days_removed(tmp_db):
    conn = store.connect()
    store.put(conn, "team", "fotmob", {"squad": {"fw": [{"id": 111, "name": "Свой"}]}, "coach": {"id": 999}})
    old = NOW - 31 * DAY
    store.put(conn, "player:111", "fotmob", {"team": {"id": config.TEAM_ID}}, fetched_at=old)    # свой, в составе
    store.put(conn, "player:112", "fotmob", {"team": {"id": config.TEAM_ID}}, fetched_at=old)    # свой, не в составе
    store.put(conn, "player:500", "fotmob", {"team": {"id": 8634}}, fetched_at=old)               # чужой, старый
    store.put(conn, "player:501", "fotmob", {"team": {"id": 8634}}, fetched_at=NOW - 29 * DAY)    # чужой, свежий
    store.put(conn, "player:502", "fotmob", {"team": None}, fetched_at=old)                       # без клуба
    store.put(conn, "player_fail:600", "collector", {"errors": {}}, fetched_at=old)
    res = cleanup.foreign_players(conn, NOW)
    assert res == {"foreign_players": 2, "player_fails": 1}
    left = {k for k in store.ages(conn) if k.startswith(("player:", "player_fail:"))}
    assert left == {"player:111", "player:112", "player:501"}


# ---------- аватары ----------

def test_stale_avatars_removed(tmp_db, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_db))
    now = datetime.now(timezone.utc)
    pconn = pdb.connect()
    d = avatars.avatars_dir()
    d.mkdir(parents=True, exist_ok=True)

    def user(uid, seen=None, updated=now, avatar=True):
        pconn.execute("INSERT INTO users(id, first_name, created_at, updated_at, seen_at, avatar_src, avatar_at) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (uid, "u", _iso(updated), _iso(updated), seen and _iso(seen),
                       "https://t.me/i/userpic/1.jpg" if avatar else None, _iso(updated) if avatar else None))
        if avatar:
            (d / f"{uid}.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 10)

    user(1, seen=now - timedelta(days=181))                                   # давно не был
    user(2, seen=now - timedelta(days=10), updated=now - timedelta(days=300))  # был недавно, профиль старый
    user(3, seen=None, updated=now - timedelta(days=200))                     # до появления seen_at, давно
    user(4, seen=None, updated=now - timedelta(days=5))                       # до появления seen_at, недавно
    (d / "777.png").write_bytes(b"\x89PNG")                                   # пользователя нет в базе
    (d / "notes.txt").write_text("не аватар")

    res = cleanup.stale_avatars(pconn, now)
    assert res == {"avatars": 2, "avatar_orphans": 1}
    assert {p.name for p in d.iterdir()} == {"2.jpg", "4.jpg", "notes.txt"}
    row = pconn.execute("SELECT avatar_src, avatar_at FROM users WHERE id=1").fetchone()
    assert tuple(row) == (None, None)  # вернётся — при входе аватар скачается заново
    assert avatars.want(pconn, 1, "https://t.me/i/userpic/1.jpg", now)
    pconn.close()


def test_touch_seen_once_a_day(tmp_db, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_db))
    from app.predictions.provider import FakeProvider
    from app.predictions.service import PredictionService

    t = [datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)]
    svc = PredictionService(FakeProvider(), db_path=str(tmp_db / "predictions.db"), clock=lambda: t[0])
    svc.upsert_user({"id": 42, "first_name": "A"})
    assert svc.touch_seen(42) is True
    t[0] += timedelta(hours=5)
    assert svc.touch_seen(42) is False      # в тот же день — без записи
    t[0] += timedelta(hours=20)
    assert svc.touch_seen(42) is True


def test_collector_cleanup_daily(tmp_db, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_db))
    conn = store.connect()
    c = Collector(conn)
    assert c.tick_cleanup(NOW) is not None
    assert c.tick_cleanup(NOW + 3600) is None                  # раз в сутки
    assert c.tick_cleanup(NOW + config.CLEANUP_INTERVAL) is not None
    asyncio.run(c.close())
