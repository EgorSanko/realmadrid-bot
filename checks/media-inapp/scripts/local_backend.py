"""Локальный бэкенд для проверки «новости внутри приложения» (на сервер не выкладываем).

  python local_backend.py seed <data_dir> <prod_news.json> <pages_dir> <pending_url>
      снимок `news` из ответа боевого /api/news + тексты статей из страниц, скачанных с сервера
      с заголовками сборщика (pages_dir/all.json: url → файл). Статья <pending_url> не качается —
      на ней проверяем состояние pending.
  python local_backend.py worker <data_dir> <pages_dir> <seconds> [delay]
      «сборщик» только для заявок на статьи: такт tick_articles раз в секунду; первую заявку
      обрабатывает не раньше чем через <delay> с (чтобы снять экран ожидания).

Страницы отдаёт подменённый RssSource._fetch — те же байты, что сервер получил от источника.
"""
import asyncio
import json
import os
import sys
import time

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend"))
sys.path.insert(0, BACKEND)


def setup(data_dir: str):
    os.environ["DATA_DIR"] = data_dir
    from app import config
    config.DATA_DIR = data_dir
    config.DB_PATH = os.path.join(data_dir, "rm.sqlite3")
    config.HEARTBEAT_FILE = os.path.join(data_dir, "hb")
    config.DISABLED_FILE = os.path.join(data_dir, "disabled")


def fake_fetch(pages_dir: str, skip: set[str] = frozenset()):
    with open(os.path.join(pages_dir, "all.json"), encoding="utf-8") as f:
        by_url = {x["url"]: x["file"] for x in json.load(f) if x["status"] == "200"}
    from app.sources.base import NotFound

    async def fetch(self, url, params=None):
        if url in skip or url not in by_url:
            raise NotFound(f"нет сохранённой страницы: {url}")
        with open(by_url[url], "rb") as f:
            return f.read()
    return fetch


SITE = {"www.championat.com": "championat", "www.sport-express.ru": "sportexpress", "www.sports.ru": "sportsru"}


def seed(data_dir, news_json, pages_dir, pending_url):
    setup(data_dir)
    from urllib.parse import urlsplit
    from app import store
    from app.collector import Collector
    from app.sources import media
    with open(news_json, encoding="utf-8") as f:
        prod = json.load(f)
    items = []
    for it in prod["items"]:
        site = SITE[urlsplit(it["url"]).netloc]
        items.append({**{k: it[k] for k in ("id", "title", "summary", "source", "url", "published", "image")},
                      "feed": site, "site": site, "categories": [], "tagged": False, "also": it.get("also") or []})
    conn = store.connect()
    store.put(conn, "news", "+".join(sorted({i["site"] for i in items})), {"items": items, "feeds": {}})
    media.RssSource._fetch = fake_fetch(pages_dir, {pending_url})
    from app import config
    config.ARTICLE_RATE_PER_MIN = 10_000
    c = Collector(conn)

    async def run():
        try:
            for it in items:
                if it["url"] != pending_url:
                    await c.refresh_article(it)
        finally:
            await c.close()
    asyncio.run(run())
    n_ok = conn.execute("SELECT COUNT(*) FROM snapshots WHERE key LIKE 'article:%'").fetchone()[0]
    n_fail = conn.execute("SELECT COUNT(*) FROM snapshots WHERE key LIKE 'article_fail:%'").fetchone()[0]
    conn.execute("DELETE FROM article_demand")
    print(json.dumps({"news": len(items), "articles": n_ok, "failed": n_fail,
                      "pending_aid": media.news_aid(media.canonical_url(pending_url))}))


def worker(data_dir, pages_dir, seconds, delay):
    setup(data_dir)
    from app import store
    from app.collector import Collector
    from app.sources import media
    media.RssSource._fetch = fake_fetch(pages_dir)
    conn = store.connect()
    c = Collector(conn)

    async def run():
        end = time.time() + seconds
        first_seen = None
        try:
            while time.time() < end:
                if store.peek_article_demand(conn, 1):
                    first_seen = first_seen or time.time()
                    if time.time() - first_seen >= delay:
                        done = await c.tick_articles(time.time())
                        if done:
                            print("done", done, flush=True)
                            first_seen = None
                await asyncio.sleep(0.5)
        finally:
            await c.close()
    asyncio.run(run())


if __name__ == "__main__":
    if sys.argv[1] == "seed":
        seed(*sys.argv[2:6])
    elif sys.argv[1] == "reset":         # reset <data_dir> <aid> — снова «текста ещё нет»
        setup(sys.argv[2])
        from app import store
        conn = store.connect()
        aid = sys.argv[3]
        n = conn.execute("DELETE FROM snapshots WHERE key IN (?, ?)", (f"article:{aid}", f"article_fail:{aid}")).rowcount
        conn.execute("DELETE FROM article_demand")
        print("reset", aid, n)
    else:
        worker(sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5]) if len(sys.argv) > 5 else 0)
