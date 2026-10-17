"""Текст новости со страницы источника: свой разбор для каждого из трёх сайтов + белый список HTML.

Библиотеки общего назначения (trafilatura, readability) проверены на сохранённых страницах:
текст находят, но теряют лид Sports.ru, подзаголовки, фото в тексте и подписи к ним, а в
«Чемпионат» тащат «Материалы по теме». Вёрстка у трёх сайтов стабильная и простая, поэтому —
свой разбор на lxml: контейнер статьи → разрешённые блоки → безопасный HTML.

Безопасность: HTML не «чистится» от лишнего, а строится заново только из разрешённых тегов и
атрибутов (p, h2, h3, blockquote, ul/ol/li, strong/em, a, img, figure/figcaption, br). Текст и
значения атрибутов экранируются. Ссылки — только http(s), с rel="noopener nofollow". Картинки —
только через наш /img/news/... (media.news_image_path), чужие удаляются вместе с <figure>.

Всё здесь — чистые функции: тесты гоняют их на сохранённых реальных страницах.
"""
import html as _html
import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from lxml import etree
from lxml import html as LH

from . import media

# --------------------------------------------------------------------------- белый список

BLOCK = {"p", "h2", "h3", "blockquote", "ul", "ol", "li", "figure", "figcaption"}
INLINE = {"strong", "em", "a", "br", "img"}
RENAME = {"b": "strong", "i": "em", "h1": "h2", "h4": "h3", "h5": "h3", "h6": "h3", "q": "em", "cite": "em"}
# вместе с содержимым: код, стили, встраивания, формы, медиа, реклама
DROP = {"script", "style", "iframe", "frame", "frameset", "object", "embed", "noscript", "template", "svg",
        "math", "form", "input", "button", "select", "option", "textarea", "label", "video", "audio", "source",
        "track", "canvas", "map", "area", "link", "meta", "head", "title", "base", "applet", "dialog", "nav",
        "aside", "footer", "header", "table"}
VOID = {"br", "img"}
_WS = re.compile(r"[ \t\r\n\f\v  ​]+")
_ESC = _html.escape


def _attr(v: str) -> str:
    return _ESC(v, quote=True)


class Ctx:
    """Окружение разбора: адрес страницы (для относительных ссылок) и картинки статьи."""

    def __init__(self, base_url: str):
        self.base = base_url
        self.images: list[str] = []

    def href(self, raw: str | None) -> str | None:
        if not raw:
            return None
        raw = raw.strip()
        if raw.startswith("#"):
            return None
        u = urljoin(self.base, raw)
        p = urlsplit(u)
        if p.scheme not in ("http", "https") or not p.netloc:
            return None          # javascript:, data:, mailto: и прочее — без ссылки, только текст
        return u

    def img(self, el) -> str | None:
        """Наш путь /img/news/... для <img> (src, data-src, data-lazy, srcset) или None."""
        cands = [el.get("data-src"), el.get("data-lazy"), el.get("data-original"), el.get("src")]
        srcset = el.get("srcset") or ""
        if srcset:
            cands.append(srcset.split(",")[-1].strip().split(" ")[0])
        for c in cands:
            if not c or c.startswith("data:") or c.endswith(".svg"):
                continue
            path = media.news_image_path(urljoin(self.base, c.strip()))
            if path:
                return path
        return None


def _text(s: str | None) -> str:
    return _ESC(_WS.sub(" ", s or ""), quote=False)


def render(el, ctx: Ctx, with_tail: bool = True) -> str:
    """Элемент lxml → безопасный HTML (только белый список). with_tail — с текстом после элемента."""
    tail = _text(el.tail) if with_tail else ""
    if not isinstance(el.tag, str):        # комментарий, инструкция
        return tail
    tag = RENAME.get(el.tag.lower(), el.tag.lower())
    if tag in DROP:
        return tail
    if tag == "img":
        src = ctx.img(el)
        if not src:
            return tail
        ctx.images.append(src)
        attrs = f' src="{_attr(src)}" alt="{_attr(_WS.sub(" ", el.get("alt") or "").strip())}" loading="lazy"'
        for dim in ("width", "height"):
            v = (el.get(dim) or "").strip()
            if v.isdigit() and 0 < int(v) < 10000:
                attrs += f' {dim}="{v}"'
        return f"<img{attrs}>" + tail
    if tag == "br":
        return "<br>" + tail
    inner = _text(el.text) + "".join(render(k, ctx) for k in el)
    if tag == "a":
        href = ctx.href(el.get("href"))
        if not href or not inner.strip():
            return inner + tail
        return f'<a href="{_attr(href)}" rel="noopener nofollow">{inner}</a>' + tail
    if tag in BLOCK or tag in INLINE:
        if tag in ("strong", "em") and not inner.strip():
            return inner + tail
        return f"<{tag}>{inner}</{tag}>" + tail
    return inner + tail                       # div, span, picture… — только содержимое


def _plain(s: str) -> str:
    return _WS.sub(" ", re.sub(r"<[^>]+>", " ", s)).strip()


def block(el, ctx: Ctx, as_tag: str | None = None) -> str | None:
    """Один блок статьи. Пустые абзацы и фигуры без картинки — None."""
    if as_tag:
        inner = _text(el.text) + "".join(render(k, ctx) for k in el)
        out = f"<{as_tag}>{inner.strip()}</{as_tag}>"
    else:
        out = render(el, ctx, with_tail=False).strip()
    if not out:
        return None
    if out.startswith("<figure") and "<img" not in out:
        return None
    if "<img" not in out and not _plain(out):
        return None
    return out


def figure(img_el, caption: str | None, ctx: Ctx) -> str | None:
    src = ctx.img(img_el)
    if not src:
        return None
    ctx.images.append(src)
    cap = _WS.sub(" ", caption or "").strip()
    out = f'<figure><img src="{_attr(src)}" alt="{_attr(cap)}" loading="lazy">'
    if cap:
        out += f"<figcaption>{_ESC(cap, quote=False)}</figcaption>"
    return out + "</figure>"


# --------------------------------------------------------------------------- метаданные

def _meta(doc, prop: str) -> str | None:
    for el in doc.xpath(f'//meta[@property="{prop}" or @name="{prop}"]'):
        v = (el.get("content") or "").strip()
        if v:
            return _html.unescape(v)
    return None


def _ld(doc) -> list[dict]:
    out = []
    for s in doc.xpath('//script[@type="application/ld+json"]'):
        try:
            d = json.loads(s.text or "")
        except ValueError:
            continue
        for x in (d if isinstance(d, list) else [d]):
            if isinstance(x, dict):
                out.append(x)
    return out


def _article_ld(doc) -> dict:
    return next((x for x in _ld(doc) if x.get("@type") in ("NewsArticle", "Article", "BlogPosting")), {})


def iso_z(s: str | None) -> str | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ld_author(ld: dict) -> str | None:
    a = ld.get("author")
    if isinstance(a, list):
        names = [x.get("name") for x in a if isinstance(x, dict) and x.get("name")]
        return ", ".join(names) or None
    if isinstance(a, dict):
        return a.get("name")
    return a if isinstance(a, str) else None


def _first_text(doc, css: str) -> str | None:
    for el in doc.cssselect(css):
        t = _WS.sub(" ", el.text_content()).strip()
        if t:
            return t
    return None


def _hero(src_url: str | None, base: str) -> str | None:
    return media.news_image_path(urljoin(base, src_url)) if src_url else None


# --------------------------------------------------------------------------- сайты

def _championat(doc, url: str) -> dict:
    ctx = Ctx(url)
    box = next(iter(doc.cssselect("#articleBody, .article-content")), None)
    blocks = []
    if box is not None:
        for k in box:
            if not isinstance(k.tag, str):
                continue
            cls = k.get("class") or ""
            if k.tag == "div" and "content-photo" in cls:
                img = next(iter(k.cssselect("img")), None)
                cap = _first_text(k, ".content-photo__desc")
                b = figure(img, cap, ctx) if img is not None else None
            elif k.tag in ("p", "h2", "h3", "h4", "blockquote", "ul", "ol", "figure"):
                b = block(k, ctx)
            else:
                b = None          # баннеры, «Материалы по теме», плеер, виджет матча
            if b:
                blocks.append(b)
    hero_el = next(iter(doc.cssselect(".article-head__photo img")), None)
    hero = Ctx(url).img(hero_el) if hero_el is not None else None
    ld = _article_ld(doc)
    if not hero:
        hero = _hero(_meta(doc, "og:image"), url)
    photo = None
    origin = None
    for p in doc.cssselect(".article-source p"):
        t = _WS.sub(" ", p.text_content()).strip()
        if t.startswith("Заглавное фото"):
            photo = t.split(":", 1)[-1].strip() or None
        elif t.startswith("Источник"):
            origin = t.split(":", 1)[-1].strip() or None
    return {
        "title": _first_text(doc, ".article-head__title, h1") or ld.get("headline") or _meta(doc, "og:title"),
        "lead": None, "blocks": blocks, "images": ctx.images,
        "image": hero, "image_caption": f"Фото: {photo}" if photo else None,
        "author": _first_text(doc, ".article-head__author-name") or _meta(doc, "author") or _ld_author(ld),
        "published": iso_z(ld.get("datePublished")), "origin": origin,
    }


def _sportsru(doc, url: str) -> dict:
    ctx = Ctx(url)
    box = next(iter(doc.cssselect(".structured-body-wrapper")), None)
    blocks = []
    if box is not None:
        for k in box:
            if not isinstance(k.tag, str):
                continue
            typ = k.get("type")
            if k.tag == "figure":
                img = next(iter(k.cssselect("img")), None)
                cap = _first_text(k, "figcaption")
                b = figure(img, cap, ctx) if img is not None else None
            elif k.tag == "a" or (k.tag == "div" and typ not in ("text", "quote", "list")):
                b = None          # рекламные места, виджеты матча/прогноза, промо-картинки со ссылкой
            elif k.tag in ("p", "h2", "h3", "h4", "blockquote", "ul", "ol"):
                b = block(k, ctx)
            else:
                b = block(k, ctx, as_tag="p")
            if b:
                blocks.append(b)
    ld = _article_ld(doc)
    lead = _first_text(doc, ".news-content__first-paragraph")
    author = _first_text(doc, ".news-source__publisher .news-source__value") or _ld_author(ld)
    origin = _first_text(doc, ".news-source__source .news-source__value")
    published = iso_z(ld.get("datePublished")) or iso_z(_meta(doc, "article:published_time"))
    if not published:
        t = next(iter(doc.cssselect('[data-test="published-date"][datetime]')), None)   # блоги
        published = iso_z(t.get("datetime")) if t is not None else None
    return {
        "title": ld.get("headline") or _meta(doc, "og:title") or _first_text(doc, "h1"),
        "lead": lead, "blocks": blocks, "images": ctx.images,
        "image": _hero(_meta(doc, "og:image"), url), "image_caption": None,
        "author": author, "published": published, "origin": origin,
        # блоги Sports.ru начинаются с того же фото, что и og:image (в другом размере) — второй раз не показываем
        "hero_in_text": any(b.startswith("<figure") for b in blocks[:2]),
    }


def _sportexpress(doc, url: str) -> dict:
    ctx = Ctx(url)
    box = next(iter(doc.cssselect(".se-material-page__content")), None)
    blocks = []
    if box is not None:
        for k in box:
            if not isinstance(k.tag, str):
                continue
            if k.tag in ("p", "h2", "h3", "h4", "blockquote", "ul", "ol", "figure"):
                b = block(k, ctx)
            else:
                b = None          # «лупа», баннеры, анонсы других материалов
            if b:
                blocks.append(b)
    ld = _article_ld(doc)
    t = next(iter(doc.cssselect("time.se-material-page__date")), None)
    authors = [_WS.sub(" ", a.text_content()).strip() for a in doc.cssselect(".se-material-page__authors .se-author__name")]
    return {
        "title": _first_text(doc, "h1.se-material-page__title, h1") or ld.get("headline") or _meta(doc, "og:title"),
        "lead": None, "blocks": blocks, "images": ctx.images,
        # og:image у «Спорт-Экспресса» — сгенерированная карточка с заголовком (img-gen), не фото: не берём
        "image": None, "image_caption": None,
        "author": ", ".join(a for a in authors if a) or _ld_author(ld),
        "published": iso_z(t.get("datetime") if t is not None else None) or iso_z(ld.get("datePublished")),
        "origin": None,
    }


PARSERS = {"championat": _championat, "sportsru": _sportsru, "sportexpress": _sportexpress}

# рекламные и «подписочные» абзацы в конце статей: «Подписывайся на канал «СЭ» в Max»,
# «Где получить фрибеты за регистрацию? Здесь» (Sports.ru) и т. п.
_PROMO = re.compile(r"^(?:Подписыва\w+ на|Подпишись на|Где получить фрибет|Читайте нас в|Больше новостей в|"
                    r"Присоединяйтесь к|Все новости .{0,40} в (?:Telegram|Max|VK))", re.I)

MIN_CHARS = 120   # меньше — считаем, что текст не нашли (вёрстка поменялась, заглушка, капча)


_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?([A-Za-z0-9_-]+)""", re.I)


def _decode(raw: bytes) -> str:
    """Байты страницы → текст: кодировка из <meta charset>, по умолчанию UTF-8 (все три сайта)."""
    m = _CHARSET.search(raw[:4096])
    enc = m.group(1).decode("ascii").lower() if m else "utf-8"
    try:
        return raw.decode(enc, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


class NoArticle(ValueError):
    """Страница получена, но текста статьи на ней нет."""


def extract(site: str, url: str, page: bytes | str) -> dict:
    """Страница источника → статья. Нет текста — NoArticle (сборщик повторит позже, API покажет лид)."""
    if site not in PARSERS:
        raise NoArticle(f"{site}: разбор не написан")
    text_ = page if isinstance(page, str) else _decode(page)
    if not text_.strip():
        raise NoArticle("пустая страница")
    try:
        doc = LH.document_fromstring(text_)
    except (etree.ParserError, ValueError) as e:
        raise NoArticle(f"HTML не разобран: {e}") from e
    a = PARSERS[site](doc, url)
    a["blocks"] = [b for b in a["blocks"] if not _PROMO.match(_plain(b))]
    text = " ".join(_plain(b) for b in a["blocks"])
    lead = a["lead"]
    if lead and a["blocks"] and _plain(a["blocks"][0]).startswith(lead.rstrip(".…")):
        lead = None       # лид совпадает с первым абзацем — не дублируем
    chars = len(text) + len(lead or "")
    if not a["blocks"] or chars < MIN_CHARS:
        raise NoArticle(f"{site}: текст не найден ({len(a['blocks'])} блоков, {chars} символов)")
    title = _WS.sub(" ", a["title"] or "").strip()
    return {
        "title": title or None,
        "lead": lead,
        "html": "\n".join(a["blocks"]),
        "image": a["image"],
        "image_caption": a["image_caption"],
        "author": (a["author"] or None),
        "published": a["published"],
        "origin": a["origin"],
        "chars": chars,
        "words": len((lead or "").split()) + len(text.split()),
        "images": len(a["images"]),
        "parser": site,
        "hero_in_text": bool(a.get("hero_in_text")),
    }


# --------------------------------------------------------------------------- ссылки на свои новости

_HREF = re.compile(r'<a href="([^"]+)" rel="noopener nofollow">')


def link_internal(html_text: str, known: dict[str, str]) -> str:
    """Ссылки на новости, которые есть у нас (canonical id → aid), — на внутренний экран /news/<aid>."""
    if not known:
        return html_text

    def sub(m):
        aid = known.get(media.canonical_url(_html.unescape(m.group(1))))
        return f'<a href="/news/{aid}" data-internal="1">' if aid else m.group(0)

    return _HREF.sub(sub, html_text)
