"""Новости на русском (RSS) и видео с официального YouTube-канала."""
import asyncio
import email.utils
import html
import re
import xml.etree.ElementTree as ET

from ..cache import cached
from ..http import get_text

YT_CHANNEL = "UCWV3obpZVGgJ3j9FVhEjF2Q"  # Real Madrid CF

NEWS_FEEDS = {
    "Чемпионат": "https://www.championat.com/rss/news/football/",
    "Спорт-Экспресс": "https://www.sport-express.ru/services/materials/news/football/se/",
    "Sports.ru": "https://www.sports.ru/rss/topnews.xml",
}

# «Реал» без уточнения — это Мадрид; остальные «Реалы» отсекаем
_RM = re.compile(r"\bРеал\w*\b(?!\s+(Сосьедад|Бетис|Овьедо|Вальядолид|Сарагоса|Мурсия|Сальт))", re.I)
_RM_EXTRA = re.compile(r"Мбапп|Винисиус|Беллингем|Вальверде|Куртуа|Моуринью|Бернабеу|Мадридск|"
                       r"Чуамени|Камавинга|Гюлер|Родриго|Рюдигер|Арда", re.I)

NEWS_TTL = 600
VIDEO_TTL = 900


def _clean(s: str | None) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return html.unescape(s).strip()


def _parse_rss(source: str, text: str) -> list[dict]:
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    items = []
    for it in root.iter("item"):
        title = _clean(it.findtext("title"))
        desc = _clean(it.findtext("description"))
        img = None
        enc = it.find("enclosure")
        if enc is not None and (enc.get("type") or "").startswith("image"):
            img = enc.get("url")
        pub = it.findtext("pubDate")
        try:
            ts = email.utils.parsedate_to_datetime(pub).isoformat() if pub else None
        except Exception:
            ts = None
        items.append({"source": source, "title": title, "summary": desc[:300],
                      "url": (it.findtext("link") or "").strip(), "image": img, "published": ts})
    return items


async def _feed(source: str, url: str) -> list[dict]:
    return await cached(f"rss:{source}", NEWS_TTL, lambda: _fetch_feed(source, url))


async def _fetch_feed(source: str, url: str) -> list[dict]:
    return _parse_rss(source, await get_text(url))


def is_about_rm(item: dict) -> bool:
    text = f"{item['title']} {item['summary']}"
    return bool(_RM.search(text) or _RM_EXTRA.search(text))


async def news(limit: int = 30) -> list[dict]:
    results = await asyncio.gather(*(_feed(s, u) for s, u in NEWS_FEEDS.items()),
                                   return_exceptions=True)
    seen, out = set(), []
    for res in results:
        if isinstance(res, Exception):
            continue
        for it in res:
            key = it["title"].lower()[:60]
            if key in seen or not is_about_rm(it):
                continue
            seen.add(key)
            out.append(it)
    out.sort(key=lambda x: x["published"] or "", reverse=True)
    return out[:limit]


async def _fetch_videos() -> list[dict]:
    text = await get_text(f"https://www.youtube.com/feeds/videos.xml?channel_id={YT_CHANNEL}")
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
          "media": "http://search.yahoo.com/mrss/"}
    root = ET.fromstring(text.encode("utf-8"))
    out = []
    for e in root.findall("a:entry", ns):
        vid = e.findtext("yt:videoId", namespaces=ns)
        out.append({
            "id": vid,
            "title": e.findtext("a:title", namespaces=ns),
            "published": e.findtext("a:published", namespaces=ns),
            "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "url": f"https://www.youtube.com/watch?v={vid}",
            # шорты в RSS не помечены явно — отличаем по ссылке
            "short": "/shorts/" in (e.find("a:link", ns).get("href") if e.find("a:link", ns) is not None else ""),
        })
    return out


async def videos() -> list[dict]:
    return await cached("yt:rm", VIDEO_TTL, _fetch_videos)
