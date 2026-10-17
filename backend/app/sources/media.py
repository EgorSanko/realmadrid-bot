"""Медиа: новости на русском (RSS) и видео официального YouTube-канала Real Madrid.

Ходит в сеть только сборщик (через Source: breaker + счётчики), API читает снимки
`news` и `videos`. Здесь — HTTP-источники, разбор лент, фильтр «про Реал Мадрид»,
дедупликация и чистка заголовков видео. Всё, кроме `RssSource`, — чистые функции,
их гоняют тесты на сохранённых реальных ответах.
"""
import email.utils
import hashlib
import html
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .base import HttpxSource, NotFound

YT_CHANNEL = "UCWV3obpZVGgJ3j9FVhEjF2Q"  # Real Madrid CF
YT_FEED = f"https://www.youtube.com/feeds/videos.xml?channel_id={YT_CHANNEL}"


@dataclass(frozen=True)
class Feed:
    key: str        # ключ ленты (в снимке и счётчиках)
    site: str       # источник = HTTP-клиент со своим breaker'ом
    title: str      # подпись в интерфейсе
    url: str
    tagged: bool = False   # тематическая лента «Реал Мадрид»: редакция уже отобрала


NEWS_FEEDS = (
    Feed("championat", "championat", "Чемпионат", "https://www.championat.com/rss/news/football/"),
    Feed("sportexpress", "sportexpress", "Спорт-Экспресс",
         "https://www.sport-express.ru/services/materials/news/football/se/"),
    Feed("sportsru_top", "sportsru", "Sports.ru", "https://www.sports.ru/rss/topnews.xml"),
    # тег «Реал Мадрид» на Sports.ru (id из страницы клуба /football/club/real/)
    Feed("sportsru_real", "sportsru", "Sports.ru", "https://www.sports.ru/stat/export/rss/taglenta.xml?id=1363868",
         tagged=True),
)
NEWS_HOSTS = {"www.championat.com", "championat.com", "www.sport-express.ru", "sport-express.ru",
              "www.sports.ru", "sports.ru"}
# страницы статей — свои клиенты (breaker и счётчики отдельно от лент): блокировка страниц не
# должна выключать ленту. sportsru_pages — и og:image, и текст статей Sports.ru.
PAGE_SOURCES = {"championat": "championat_pages", "sportexpress": "sportexpress_pages", "sportsru": "sportsru_pages"}
MEDIA_SOURCES = ("championat", "sportexpress", "sportsru", "sportsru_pages", "championat_pages",
                 "sportexpress_pages", "youtube")
# вежливый User-Agent для страниц статей: кто мы и где нас найти
PAGE_UA = "Mozilla/5.0 (compatible; MadridistaBot/1.0; +https://realmadridfan.ru)"
# «Чемпионат» без cookie отдаёт заглушку «Вход через SberID» (JS-редирект на SSO). Этот cookie
# ставит их же скрипт, когда вход откладывают («unity_pause_sso=1»), — с ним приходит сама статья.
PAGE_COOKIES = {"championat_pages": {"unity_pause_sso": "1"}}


class RssSource(HttpxSource):
    """Тот же HttpxSource (breaker, счётчики), но ответ — байты XML/HTML, а не JSON."""

    timeout = 15.0

    def __init__(self, name: str):
        self.name = name
        super().__init__()
        self.client.headers["Accept"] = "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"
        self.client.headers["Accept-Language"] = "ru,en;q=0.8"
        if name.endswith("_pages"):
            self.client.headers["Accept"] = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"
            self.client.headers["User-Agent"] = PAGE_UA
            for k, v in PAGE_COOKIES.get(name, {}).items():
                self.client.cookies.set(k, v)

    async def _fetch(self, url, params):
        r = await self.client.get(url, params=params)
        if r.status_code == 404:
            raise NotFound(f"404 {url}")
        r.raise_for_status()
        body = r.content
        if len(body) > 3_000_000:
            raise ValueError(f"слишком большой ответ: {len(body)} байт")
        return body

    async def text(self, url: str, kind: str) -> bytes:
        return await self.get(url, kind=kind)


# ===================================================================== разбор RSS

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean_text(s: str | None) -> str:
    s = _TAG.sub(" ", s or "")
    s = html.unescape(s).replace("\xa0", " ")
    return _WS.sub(" ", s).strip()


def iso_from_rfc822(s: str | None) -> str | None:
    if not s or not s.strip():
        return None
    try:
        d = email.utils.parsedate_to_datetime(s.strip())
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _summary(text: str, limit: int = 280) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:—-– ")
    return cut + "…"


def parse_rss(feed: Feed, body: bytes | str) -> list[dict]:
    """RSS 2.0 → список новостей. Битый XML — ValueError (ловит сборщик)."""
    raw = body.encode("utf-8") if isinstance(body, str) else body
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValueError(f"{feed.key}: XML не разобран: {e}") from e
    out = []
    for it in root.iter("item"):
        title = clean_text(it.findtext("title"))
        link = (it.findtext("link") or it.findtext("guid") or "").strip()
        if not title or not link.startswith("http"):
            continue
        # реклама и спецпроекты в лентах (sirena.sports.ru/…?utm_source=native) — не новости
        if urlsplit(link).netloc.lower() not in NEWS_HOSTS or "utm_source=native" in link:
            continue
        desc = clean_text(it.findtext("description"))
        if desc == title:
            desc = ""
        cats = [clean_text(c.text) for c in it.findall("category")
                if c.text and (c.get("domain") in (None, "tags", "sections"))]
        img = None
        for el in it:
            name = _local(el.tag)
            if name == "enclosure" and (el.get("type") or "image").startswith("image"):
                img = el.get("url")
            elif name in ("content", "thumbnail") and el.get("url") and (el.get("medium") in (None, "image")):
                img = img or el.get("url")
            if img:
                break
        out.append({
            "id": canonical_url(link), "feed": feed.key, "site": feed.site, "source": feed.title,
            "title": title, "summary": _summary(desc), "url": link,
            "published": iso_from_rfc822(it.findtext("pubDate")),
            "image": news_image_path(img) if img else None,
            "categories": cats[:12], "tagged": feed.tagged,
        })
    return out


def canonical_url(url: str) -> str:
    p = urlsplit(url.strip())
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"


def news_aid(news_id: str) -> str:
    """Короткий id новости для адреса /news/<aid>: 12 hex от канонического id (хост+путь)."""
    return hashlib.sha1(news_id.encode("utf-8")).hexdigest()[:12]


_AID = re.compile(r"^[0-9a-f]{12}$")


def is_aid(s: str) -> bool:
    return bool(_AID.match(s or ""))


# ===================================================================== картинки новостей
# Клиент не ходит на чужие хосты: картинка — путь /img/news/<ключ>/<путь>, nginx знает только
# эти ключи (deploy/nginx.conf.template) и проксирует на соответствующий хост. Открытого
# прокси нет: путь только из безопасных символов, хост задан ключом, не URL.

NEWS_IMG_HOSTS = {
    # ключ: (хост, допустимый префикс пути); у каждого ключа — свой location в nginx
    "championat": ("img.championat.com", "/"),
    "sportsru": ("www.sports.ru", "/dynamic_images/"),
    "sportsru-photo": ("photobooth.cdn.sports.ru", "/preset/"),      # фото в тексте статей и блогов
    "sportsru-dump": ("dumpster.cdn.sports.ru", "/"),                # картинки в блогах
    "sportexpress": ("ss.sport-express.ru", "/userfiles/"),          # фото в материалах «Спорт-Экспресса»
}
_HOST_KEY = {h: (k, pfx) for k, (h, pfx) in NEWS_IMG_HOSTS.items()}
# те же символы, что пропускает nginx (location /img/news/…): только ASCII, без %-кодов
_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._~/-]{1,400}\.(?:jpe?g|png|webp)$")
_CH_SIGNED = re.compile(r"^/[A-Za-z0-9_-]{20,80}/p\([A-Za-z0-9:%/]*\)/(.+)$")


def news_image_path(url: str | None) -> str | None:
    if not url:
        return None
    p = urlsplit(url.strip())
    if p.scheme not in ("http", "https", ""):
        return None
    host = p.netloc.lower()
    if host not in _HOST_KEY:
        return None
    key, prefix = _HOST_KEY[host]
    path = quote(unquote(p.path), safe="/._~-()")
    if key == "championat":
        # подписанный адрес ресайзера: /<подпись>/p(w:732/h:488)/news/big/… → тот же файл без подписи
        m = _CH_SIGNED.match(path)
        if m:
            path = "/" + m.group(1)
    if not path.startswith(prefix) or ".." in path or "//" in path or not _SAFE_PATH.match(path):
        return None
    return f"/img/news/{key}{path}"


_OG_IMAGE = re.compile(
    rb"""<meta[^>]+(?:property|name)=["']og:image["'][^>]*content=["']([^"']+)["']"""
    rb"""|<meta[^>]+content=["']([^"']+)["'][^>]*(?:property|name)=["']og:image["']""", re.I)


def og_image(page: bytes) -> str | None:
    m = _OG_IMAGE.search(page[:400_000])
    if not m:
        return None
    return html.unescape((m.group(1) or m.group(2)).decode("utf-8", "replace"))


# ===================================================================== фильтр «про Реал Мадрид»
#
# Очки по заголовку (вес 1) и по анонсу с рубриками (вес 0,5); проходит при score ≥ THRESHOLD.
# Плюсы:
#   «Реал» без уточнения — первым из клубов в тексте +3, не первым +2 («…опередил «Реал»»)
#   «Реал Мадрид», «мадридский Реал», «Мадрид» в кавычках, «Бернабеу», «сливочные»,
#   «королевский клуб», «Лос Бланкос», «Флорентино»                                  +3
#   «Перес» рядом с «президент» +2; «Кастилья», «класико» +1
#   игрок текущего состава: в начале заголовка +3, дальше +2; неоднозначная фамилия +1
#   тренер (Моуринью) +3 (как игрок — по позиции); про его прошлые клубы без «Реала» — 0
#   (имена в сумме не больше 3)
#   тематическая лента «Реал Мадрид» (Sports.ru) +1
# Минусы:
#   «Реал» с уточнением другого клуба (Сосьедад, Бетис, Овьедо…) не считается; если в тексте
#   есть такой «Реал» или «Сосьедад», голое «Реал» весит 2 первым и 1 не первым;
#   «Реал» в перечислении «…, «Реал» – 8-й, …» / «Реал», «Барса», «Сосьедад» и … — 1;
#   список из 6+ фамилий через запятую — имена весят не больше 1;
#   дайджест («Главное в ЛЧ», «большой обзор», «хроника», «превью», «команда недели»…) −2;
#   «кроме «Реала»» −3; баскетбол, футзал и т. п. −4 (приложение про футбольную команду).

THRESHOLD = 3.0

_OTHER_REAL = (r"Сосье\w*|Бетис\w*|Овьедо|Вальядолид\w*|Сарагос\w*|Мурси\w*|Сальт[- ]Лейк\w*|Кашмир\w*|"
               r"Монаркс|Эспань\w*|Потоси|Сантакрус\w*|Эстели|Бамако|Банжул\w*|Кариока|Брасилиа|Хаэн\w*|"
               r"Унион\w*|Сан-Андрес|Сан-Хосе|Таллин\w*|Ирун\w*|Касталия|Тампере|Авилес\w*")
_REAL = re.compile(r"(?<![\w-])Реал(?:а|у|ом|е)?(?![\w-])(?:»?\s*«?(?P<next>[А-ЯЁA-Z][\w-]*))?")
_OTHER_AFTER = re.compile(rf"^(?:{_OTHER_REAL})$", re.I)
# «Сосьедад» без «Реал»: в тексте о нём «Реал» часто означает именно его
_OTHER_ANY = re.compile(rf"Реал\w*»?\s+«?(?:{_OTHER_REAL})|«Сосье\w*»", re.I)
_MADRID_AFTER = re.compile(r"^(?:Мадрид\w*|Madrid)$", re.I)
# клуб в кавычках: короткое название с заглавной буквы («Барса», «Ман Сити»), а не цитата
_CLUB = re.compile(r"«([А-ЯЁA-Z][\w.-]*(?:[ -][А-ЯЁA-Z\d][\w.-]*){0,2})»")
_ENUM_AFTER = re.compile(r"^»?\s*[–—-]\s*\d|^»?\s*(?:,\s*«[^»]+»){1,}\s*(?:и|,)\s*«")
_EXCEPT_REAL = re.compile(r"кроме\s+«?Реал", re.I)
_DIGEST = re.compile(r"Главное\s+в\s|большой\s+обзор|обзор\s+\d|хроника|превью|интриги|команд[аеуы]\s+недели|"
                     r"сборн\w+\s+\d-го\s+тура|номинант|претендуют\s+на|все\s+\d+\s+клуб", re.I)

_STRONG = [
    re.compile(r"мадридск\w+\s+«?Реал", re.I),
    re.compile(r"«Мадрид\w*»"),                       # «ТВ «Мадрида»» — так пишут о клубе
    re.compile(r"Бернабеу", re.I),
    re.compile(r"сливочн\w+", re.I),
    re.compile(r"королевск\w+\s+клуб\w*", re.I),
    re.compile(r"Лос\s+Бланкос|«бланкос»", re.I),
    re.compile(r"Real\s+Madrid", re.I),
    re.compile(r"Флорентино", re.I),
]
_WEAK = [
    (re.compile(r"(?:президент\w*|глав\w+)\s+(?:\w+\s+){0,3}Перес\w*|Перес\w*\s*[,—–-]\s*президент", re.I), 2.0),
    (re.compile(r"Кастиль\w+", re.I), 1.0),
    (re.compile(r"(?<![\w-])класико(?![\w-])", re.I), 1.0),
]

# фамилии по-русски: FotMob id → (шаблон, вес, «чужой» контекст). Учитываются только игроки
# из текущего снимка команды — ушедшие не тянут чужие новости. Новичков нужно дописывать сюда.
# Если в тексте есть «чужой» контекст и нет «Реала», фамилия весит 0.
PLAYER_NAMES: dict[int, tuple[str, int, str | None]] = {
    170323: (r"Куртуа", 3, None),
    800882: (r"Лунин\w*", 3, None),
    1580528: (r"Рауль\w*\s+Асенсио|Асенсио", 1, r"Марко"),       # и Марко Асенсио
    844415: (r"Милитао", 3, None),
    1367619: (r"Х[её]йсен\w*|Хюйсен\w*", 3, None),
    760712: (r"Александер-Арнольд\w*", 3, None),
    820140: (r"Конате", 3, None),
    873289: (r"Кукурель\w+", 3, None),
    1190025: (r"Каррерас\w*", 3, None),
    276738: (r"Рюдигер\w*", 3, None),
    623537: (r"Ферлан\w*\s+Менди", 3, None),
    593118: (r"Д[юу]мфрис\w*", 3, None),
    1077894: (r"Беллингем\w*", 3, r"Джоб\w*|«Боруссии»|«Боруссия»"),     # брат Джоб
    1015185: (r"Камавинг\w+", 3, None),
    743533: (r"Вальверде", 3, r"Эрнесто|тренер\w*|Браулио"),             # тренер Эрнесто Вальверде
    914458: (r"Чуамени", 3, None),
    1253890: (r"Гюлер\w*|Арда", 3, None),
    488139: (r"Бернарду\w*\s+Силв\w+|Бернардо\s+Силв\w+", 3, None),
    1796908: (r"Питарч\w*", 3, None),
    846033: (r"Винисиус\w*|Вини\s+Жуниор\w*|Вини-младш\w*", 3, None),
    1406729: (r"Эндрик\w*", 3, None),
    701154: (r"Мбапп[еэ]", 3, r"Этан\w*|брат\w*\s+(?:Килиана\s+)?Мбапп\w*"),  # брат Этан из «Лилля»
    895362: (r"Родриго", 1, r"де\s+Пауль|Мендос\w*|Рикельме|Сапата|Эрнандес"),
    1610744: (r"Карлос\w*\s+Эспи|Эспи", 3, None),
    750027: (r"Брахим\w*|Браим\w*", 3, None),
    1735453: (r"Ян\w*\s+Диоманде|Диоманде", 1, r"Усман\w*|«Спортинг\w*»"),
}
COACH_NAMES: dict[int, str] = {78719: r"Моуринью"}


def _rx(p: str) -> re.Pattern:
    return re.compile(rf"(?<![\w-])(?:{p})(?![\w-])", re.I)


_PLAYER_RE = {pid: (_rx(p), w, _rx(neg) if neg else None) for pid, (p, w, neg) in PLAYER_NAMES.items()}
_COACH_RE = {pid: _rx(p) for pid, p in COACH_NAMES.items()}
_HEAD = 30   # «начало заголовка»: имя в первых 30 символах — скорее всего, герой новости

# прошлые клубы тренера: «Моуринью и Погба в «МЮ»» без «Реала» в тексте — не про Реал.
# «Рому» сюда не включаем: это и соперник Реала по ЛЧ этого сезона.
_COACH_PAST = re.compile(
    r"Фенербахче|Бенфик\w*|Тоттенхэм\w*|Челси|«Интер\w*»|«Порту»|Манчестер\s+Юнайтед\w*|«МЮ»|(?<![\w-])МЮ(?![\w-])|"
    r"«(?:Ман\s+|Манчестер\s+)?Сити»|Манчестер\s+Сити", re.I)
_LIST_OF_NAMES = re.compile(r"^(?:[А-ЯЁ][\w-]+,\s+){5,}")
_NOT_FOOTBALL = re.compile(r"баскетбол|Евролиг|Единой\s+лиг|ВТБ|футзал|мини-футбол|гандбол|волейбол", re.I)


def _real_points(text: str, other_present: bool) -> float:
    """Очки за «Реал»: 3 — явно Мадрид и герой, 2/1 — упомянут вскользь, 0 — нет или другой «Реал»."""
    if any(rx.search(text) for rx in _STRONG):
        return 3.0
    best = 0.0
    first_club = _CLUB.search(text)
    for m in _REAL.finditer(text):
        nxt = m.group("next") or ""
        if nxt and _OTHER_AFTER.match(nxt):
            continue                                   # «Реал Сосьедад», «Реала Бетис»
        if nxt and _MADRID_AFTER.match(nxt):
            return 3.0
        first = first_club is None or first_club.start() >= m.start() - 1
        if other_present:
            pts = 2.0 if first else 1.0
        else:
            pts = 3.0 if first else 2.0
        if _ENUM_AFTER.match(text[m.end():]):
            pts = 1.0                                  # «…, «Реал» – 8-й», «Реал», «Барса» и …
        best = max(best, pts)
    return best


def relevance(title: str, summary: str = "", categories=(), squad_ids=None,
              tagged: bool = False) -> tuple[float, list[str]]:
    """Очки «про Реал Мадрид» и причины (для отладки и тестов)."""
    reasons: list[str] = []
    rest = f"{summary} {' '.join(categories or ())}".strip()
    full = f"{title} {rest}"
    other_present = bool(_OTHER_ANY.search(full))
    ids = set(squad_ids) if squad_ids else None
    parts = [(title, 1.0, True), (rest, 0.5, False)]
    real = []
    for part, _, _ in parts:
        s = _real_points(part, other_present) if part else 0.0
        for rx, pts in _WEAK:
            if rx.search(part):
                s = max(s, pts)
        real.append(s)
    real_anywhere = max(real) >= 2
    score = 0.0
    for (part, w, is_title), s in zip(parts, real):
        if not part:
            continue
        names = 0.0

        def pos_w(m, base):
            # имя в начале заголовка — герой новости; дальше — может быть упомянут вскользь
            if base < 3 or not is_title or m.start() < _HEAD:
                return base
            return 2.0

        for pid, (rx, pts, neg) in _PLAYER_RE.items():
            if ids is not None and pid not in ids:
                continue
            m = rx.search(part)
            if not m:
                continue
            if neg is not None and neg.search(full) and not real_anywhere:
                reasons.append(f"player:{pid}:other")
                continue
            names += pos_w(m, pts)
            reasons.append(f"player:{pid}")
        for pid, rx in _COACH_RE.items():
            m = rx.search(part)
            if not m or (ids is not None and pid not in ids):
                continue
            if _COACH_PAST.search(full) and not real_anywhere:
                reasons.append("coach:past-club")
                continue
            names += pos_w(m, 3)
            reasons.append("coach")
        if names and _LIST_OF_NAMES.match(part):
            names = min(names, 1.0)
            reasons.append("names-list")
        if s:
            reasons.append(f"real:{s:g}")
        score += w * (s + min(names, 3.0))
    if tagged:
        score += 1.0
        reasons.append("tagged")
    if _DIGEST.search(title):
        score -= 2
        reasons.append("digest")
    if _EXCEPT_REAL.search(title):
        score -= 3
        reasons.append("except-real")
    if _NOT_FOOTBALL.search(full):
        score -= 4
        reasons.append("not-football")
    return score, reasons


def is_about_rm(item: dict, squad_ids=None) -> bool:
    score, _ = relevance(item.get("title", ""), item.get("summary", ""), item.get("categories") or (),
                         squad_ids, item.get("tagged", False))
    return score >= THRESHOLD


# ===================================================================== дедупликация

_WORD = re.compile(r"[a-zа-я0-9]+")
# служебные и «тематические» слова: они есть почти в каждой новости о Реале и сходства не доказывают
_STOP = set(
    "и в во на с со по о об от до за из к ко у не что как это его ее их он она они был была были будет "
    "после перед против матч матче матча матчей года году реал реала реалу реалом мадрид мадрида клуб клуба "
    "заявил рассказал ответил высказался считает может могут про для при уже еще все всех также этом "
    "игрок игрока игроки если под три гола голы меня тоже слова его".split())


def title_tokens(title: str) -> set[str]:
    t = unicodedata.normalize("NFKC", title).lower().replace("ё", "е")
    return {w[:5] for w in _WORD.findall(t) if len(w) > 2 and w not in _STOP}


def same_story(a: str, b: str) -> bool:
    """Два заголовка об одном событии: общих основ ≥ 4 и ≥ 50 % короткого, или ≥ 3 и ≥ 60 %.

    Подобрано на реальной выборке: «Тебас отреагировал на возможное наказание…» ≈ «Тебас о
    возможном наказании…», «Реал близок к продлению с Беллингемом» ≈ «Реал и Беллингем продлят…».
    """
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    ov = inter / min(len(ta), len(tb))
    return (inter >= 4 and ov >= 0.5) or (inter >= 3 and ov >= 0.6)


def _ts(x: dict) -> float:
    p = x.get("published")
    try:
        return datetime.strptime(p, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() if p else 0.0
    except ValueError:
        return 0.0


def dedupe(items: list[dict], window_s: float = 36 * 3600) -> list[dict]:
    """Одна новость из разных лент → одна запись (самая ранняя), прочие источники — в `also`.

    Сначала по ссылке (у Sports.ru топ и тег — одни и те же статьи), затем — между разными
    сайтами — по похожести заголовков в пределах 36 ч. Внутри одного сайта похожие заголовки —
    обычно разные новости (продолжение сюжета), их не склеиваем.
    """
    out: list[dict] = []
    by_id: dict[str, dict] = {}
    for it in sorted(items, key=lambda x: (_ts(x) or 9e18, x["id"])):
        if it["id"] in by_id:
            keep = by_id[it["id"]]
            keep["tagged"] = bool(keep.get("tagged") or it.get("tagged"))
            keep["image"] = keep.get("image") or it.get("image")
            keep["summary"] = keep.get("summary") or it.get("summary")
            continue
        # уже склеенная раньше (запись из прошлого снимка помнит id дублей) — или похожая с другого сайта
        dup = next((k for k in out if it["id"] in k.get("also_ids", ())), None)
        if dup is None:
            dup = next((k for k in out if k["site"] != it["site"]
                        and it["site"] not in k.get("also_sites", [])
                        and abs(_ts(k) - _ts(it)) <= window_s and same_story(k["title"], it["title"])), None)
        if dup:
            dup.setdefault("also", [])
            dup.setdefault("also_sites", [])
            dup.setdefault("also_ids", [])
            if it["source"] not in dup["also"] and it["source"] != dup["source"]:
                dup["also"].append(it["source"])
            if it["site"] not in dup["also_sites"]:
                dup["also_sites"].append(it["site"])
            if it["id"] not in dup["also_ids"]:
                dup["also_ids"].append(it["id"])
            dup["image"] = dup.get("image") or it.get("image")
            dup["summary"] = dup.get("summary") or it.get("summary")
            by_id[it["id"]] = dup
            continue
        it = dict(it)
        out.append(it)
        by_id[it["id"]] = it
    return out


# ===================================================================== видео YouTube

_ATOM = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
         "media": "http://search.yahoo.com/mrss/"}
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

# эмодзи и всё, что их склеивает: пиктограммы, флаги, вариационные селекторы, ZWJ, тоны кожи
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U0001FC00-\U0001FFFF☀-➿⌀-⏿⬀-⯿←-⇿"
    "⤀-⥿〰〽㊗㊙Ⓜ︎️‍⃣\U000E0020-\U000E007F]+")
_HASHTAGS_TAIL = re.compile(r"(?:\s*#[\w-]+)+\s*$")
_CHANNEL_TAIL = re.compile(r"\s*[|·—-]\s*Real\s+Madrid\s*(?:CF|C\.F\.)?\s*$", re.I)


def clean_video_title(title: str | None) -> str:
    s = _EMOJI.sub(" ", html.unescape(title or ""))
    s = _HASHTAGS_TAIL.sub("", s)
    s = _WS.sub(" ", s).strip(" |·—–-")
    s2 = _CHANNEL_TAIL.sub("", s).strip(" |·—–-")
    s = s2 or s
    return s or "Real Madrid"


def video_kind(title: str, short: bool) -> str:
    t = title.upper()
    if short:
        return "short"
    if t.startswith(("HIGHLIGHTS", "RESUMEN", "RESUMEN Y GOLES")) or "| HIGHLIGHTS" in t:
        return "highlights"
    if t.startswith(("GOALS", "GOLES")):
        return "goals"
    return "video"


def yt_thumb(video_id: str) -> str:
    return f"/img/yt/{video_id}.jpg"


def youtube_id(url: str | None) -> str | None:
    if not url:
        return None
    p = urlsplit(url)
    host = p.netloc.lower().removeprefix("www.").removeprefix("m.")
    vid = None
    if host == "youtu.be":
        vid = p.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        if p.path == "/watch":
            vid = (parse_qs(p.query).get("v") or [None])[0]
        elif p.path.startswith(("/shorts/", "/embed/", "/live/", "/v/")):
            vid = p.path.split("/")[2]
    elif host.endswith("ytimg.com"):
        parts = p.path.split("/")
        vid = parts[2] if len(parts) > 2 and parts[1] in ("vi", "vi_webp") else None
    return vid if vid and _VIDEO_ID.match(vid) else None


def parse_youtube(body: bytes | str) -> list[dict]:
    raw = body.encode("utf-8") if isinstance(body, str) else body
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValueError(f"youtube: XML не разобран: {e}") from e
    out = []
    for e in root.findall("a:entry", _ATOM):
        vid = (e.findtext("yt:videoId", namespaces=_ATOM) or "").strip()
        if not _VIDEO_ID.match(vid):
            continue
        link = e.find("a:link[@rel='alternate']", _ATOM)
        href = link.get("href") if link is not None else ""
        # отдельной метки у шортов в RSS нет — их выдаёт ссылка /shorts/
        short = "/shorts/" in (href or "")
        raw_title = e.findtext("a:title", namespaces=_ATOM) or ""
        title = clean_video_title(raw_title)
        stats = e.find("media:group/media:community/media:statistics", _ATOM)
        views = stats.get("views") if stats is not None else None
        out.append({
            "id": vid, "title": title, "raw_title": raw_title,
            "published": iso_utc_z(e.findtext("a:published", namespaces=_ATOM)),
            "thumb": yt_thumb(vid),
            "url": f"https://www.youtube.com/shorts/{vid}" if short else f"https://www.youtube.com/watch?v={vid}",
            "short": short, "kind": video_kind(title, short),
            "views": int(views) if views and views.isdigit() else None,
            "channel": "Real Madrid",
        })
    return out


def iso_utc_z(s: str | None) -> str | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_sources() -> dict[str, RssSource]:
    return {name: RssSource(name) for name in MEDIA_SOURCES}


# ===================================================================== снимки

NEWS_KEEP_S = 7 * 86400     # новости в снимке храним неделю (лента Sports.ru-топ — всего 20 строк)
NEWS_KEEP_N = 150
VIDEOS_KEEP_N = 40          # RSS YouTube отдаёт только 15 последних


def merge_news(old: list[dict], fresh: list[dict], squad_ids=None, now: float | None = None) -> list[dict]:
    """Старый снимок + свежие новости → отфильтровано, без дублей, новые сверху, не старше недели.

    Старые записи тоже прогоняются через фильтр: поменялся состав или правила — лишнее уходит.
    """
    now = now or time.time()
    pool = [i for i in [*old, *fresh] if is_about_rm(i, squad_ids)]
    out = dedupe(pool)
    out = [i for i in out if not i.get("published") or now - _ts(i) <= NEWS_KEEP_S]
    out.sort(key=lambda x: (_ts(x), x["id"]), reverse=True)
    return out[:NEWS_KEEP_N]


def merge_videos(old: list[dict], fresh: list[dict]) -> list[dict]:
    by_id = {v["id"]: v for v in old}
    by_id.update({v["id"]: v for v in fresh})       # свежие данные (заголовок, просмотры) важнее
    out = sorted(by_id.values(), key=lambda v: (v.get("published") or "", v["id"]), reverse=True)
    return out[:VIDEOS_KEEP_N]


_CLUB_NOISE = re.compile(r"\b(?:fc|cf|ac|as|ss|sc|cd|club)\b|[^a-z0-9 ]")


def _name_key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(_CLUB_NOISE.sub(" ", s).split())


def match_highlights(finished: list[dict], match_snaps: dict[str, dict], videos: list[dict],
                     limit: int = 5) -> list[dict]:
    """Обзоры последних матчей. Источник — `highlights` в снимке матча (FotMob даёт ссылку на
    официальный канал); если там пусто — ролик «HIGHLIGHTS | A x-y B» с канала по названиям команд
    и дате (не раньше начала матча и не позже 3 суток после)."""
    out = []
    hl_videos = [v for v in videos if v.get("kind") == "highlights"]
    for f in sorted(finished, key=lambda f: f.get("kickoff") or "", reverse=True):
        m = match_snaps.get(str(f["id"])) or {}
        vid = youtube_id(((m.get("highlights") or {}).get("url")))
        origin = "match"
        if not vid:
            ko = iso_utc_z(f.get("kickoff"))
            names = [_name_key(f["home"]["name"]), _name_key(f["away"]["name"])]
            for v in hl_videos:
                t = _name_key(v.get("raw_title") or v["title"])
                if all(n and n in t for n in names) and ko and v.get("published") and \
                        0 <= _ts({"published": v["published"]}) - _ts({"published": ko}) <= 3 * 86400:
                    vid, origin = v["id"], "youtube"
                    break
        if not vid:
            continue
        hs, as_ = f["home"].get("score"), f["away"].get("score")
        out.append({
            "match_id": f["id"], "video_id": vid,
            "title": f"{f['home']['name']} {hs}:{as_} {f['away']['name']}" if hs is not None else
                     f"{f['home']['name']} — {f['away']['name']}",
            "home": {k: f["home"].get(k) for k in ("id", "name", "score", "logo")},
            "away": {k: f["away"].get(k) for k in ("id", "name", "score", "logo")},
            "tournament": {k: (f.get("tournament") or {}).get(k) for k in ("id", "name")},
            "kickoff": f.get("kickoff"), "thumb": yt_thumb(vid),
            "url": f"https://www.youtube.com/watch?v={vid}", "origin": origin,
        })
        if len(out) >= limit:
            break
    return out
