"""Машинный перевод RU→EN для `?lang=en`: бесплатный эндпоинт Google Translate (client=gtx, без ключа).

Кто переводит:
  * сборщик — заранее, фоновой задачей (Collector.tick_translate): заголовки и анонсы свежих новостей,
    заголовки видео, «Интересные факты» ближайших матчей. Не больше TRANSLATE_RATE_PER_MIN запросов
    в минуту, по TRANSLATE_BATCH коротких текстов в запросе (строки через \\n — Google их сохраняет);
  * API — только текст статьи и только по первому запросу `?lang=en` (ArticleTranslator), с общим
    бюджетом TRANSLATE_ARTICLE_BUDGET секунд. Не успели / Google не ответил — русский оригинал,
    `translated: false`; повтор для этой статьи не раньше TRANSLATE_ARTICLE_RETRY.
Готовые переводы — таблица translations в rm.sqlite3 (ключ — sha256 языка и исходного текста):
каждый текст переводится один раз; суточная очистка удаляет записи старше TRANSLATION_TTL_DAYS.

Клиент — Source (breaker, счётчики, DISABLED_SOURCES=gtranslate выключает перевод целиком).
Длинный текст — POST с телом формы, куски до CHUNK символов по границам строк (абзацев), длинный
абзац — по границам предложений. Ответ разошёлся по числу строк — кусок делится пополам и
переводится заново (в крайнем случае — по одной строке).

Тексты без кириллицы (английские заголовки YouTube, имена латиницей) не переводятся — отдаются как есть.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from collections import deque
from typing import Any, Callable, Generator, Iterable, Optional

import httpx
from lxml import etree
from lxml import html as LH

from . import config
from .sources.base import NotFound, Source, SourceError

log = logging.getLogger("translate")

URL = "https://translate.googleapis.com/translate_a/single"
SOURCE_LANG = "ru"
LANGS = ("en",)
CHUNK = 4500            # символов в одном запросе (лимит эндпоинта ~5000)

_CYR = re.compile("[А-Яа-яЁё]")
_WS = re.compile(r"\s+")
_SENT = re.compile(r"(?<=[.!?…»])\s+")


class TranslateError(SourceError):
    pass


def needs(text: Any) -> bool:
    """Есть что переводить: строка с кириллицей."""
    return isinstance(text, str) and bool(_CYR.search(text))


def cache_key(text: str, lang: str) -> str:
    return hashlib.sha256(f"{lang}\n{text}".encode("utf-8")).hexdigest()


def parse(data: Any) -> str:
    """Ответ translate_a/single (dt=t): [[[перевод, оригинал, …], …], …] → склеенный перевод."""
    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise ValueError("неожиданный ответ переводчика")
    return "".join(seg[0] for seg in data[0] if isinstance(seg, list) and seg and isinstance(seg[0], str))


# ===================================================================== куски и строки

def pieces(text: str, limit: int = CHUNK) -> list[str]:
    """Строка длиннее limit → куски по границам предложений (в крайнем случае — по словам)."""
    if len(text) <= limit:
        return [text]
    out: list[str] = []
    cur = ""
    for s in _SENT.split(text):
        while len(s) > limit:
            cut = s.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if cur:
                out.append(cur)
                cur = ""
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if cur and len(cur) + 1 + len(s) > limit:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}" if cur else s
    if cur:
        out.append(cur)
    return [p for p in out if p]


def groups(lines: list[str], limit: int = CHUNK, batch: Optional[int] = None) -> list[list[int]]:
    """Индексы строк → запросы: длина «строки через \\n» ≤ limit и не больше batch строк."""
    out: list[list[int]] = []
    cur: list[int] = []
    size = 0
    for i, s in enumerate(lines):
        add = len(s) + (1 if cur else 0)
        if cur and (size + add > limit or (batch and len(cur) >= batch)):
            out.append(cur)
            cur, size, add = [], 0, len(s)
        cur.append(i)
        size += add
    if cur:
        out.append(cur)
    return out


def plan(units: list[str], limit: int = CHUNK, batch: Optional[int] = None,
         max_requests: Optional[int] = None) -> Generator[str, str, list[str]]:
    """Без ввода-вывода: генератор отдаёт текст запроса, получает перевод, в конце возвращает
    переводы `units` (в том же порядке). Один и тот же алгоритм для async (сборщик) и sync (API)."""
    lines: list[tuple[int, str]] = []
    for i, u in enumerate(units):
        for p in pieces(_WS.sub(" ", u or "").strip(), limit):
            if p:
                lines.append((i, p))
    result = [""] * len(lines)
    todo = list(reversed(groups([s for _, s in lines], limit, batch)))
    sent = 0
    while todo:
        g = todo.pop()
        if max_requests is not None and sent >= max_requests:
            raise TranslateError(f"перевод: больше {max_requests} запросов")
        sent += 1
        out = yield "\n".join(lines[k][1] for k in g)
        got = out.split("\n")
        if len(got) == len(g):
            for k, t in zip(g, got):
                result[k] = t.strip()
        elif len(g) == 1:
            result[g[0]] = _WS.sub(" ", out).strip()
        else:  # Google склеил или разбил строки — половинами, чтобы не потерять соответствие
            mid = len(g) // 2
            todo.append(g[mid:])
            todo.append(g[:mid])
    joined: list[list[str]] = [[] for _ in units]
    for (i, _), t in zip(lines, result):
        joined[i].append(t)
    return [" ".join(x) for x in joined]


# ===================================================================== клиент

class GoogleTranslate(Source):
    """translate.googleapis.com (client=gtx). Async — для сборщика, sync — для API (пул потоков FastAPI)."""

    name = "gtranslate"

    def __init__(self, timeout: Optional[float] = None):
        super().__init__()
        self.timeout = timeout or config.TRANSLATE_TIMEOUT
        self.chars = 0
        self._aclient: Optional[httpx.AsyncClient] = None
        self._client: Optional[httpx.Client] = None
        self._lock = threading.Lock()

    def _kw(self) -> dict:
        kw: dict[str, Any] = {"headers": {"User-Agent": config.UA, "Accept": "application/json"},
                              "timeout": httpx.Timeout(self.timeout, connect=5.0), "follow_redirects": True}
        if config.TRANSLATE_PROXY:
            kw["proxy"] = config.TRANSLATE_PROXY
        return kw

    @staticmethod
    def _params(lang: str) -> dict:
        return {"client": "gtx", "sl": SOURCE_LANG, "tl": lang, "dt": "t"}

    @staticmethod
    def _decode(r: httpx.Response) -> str:
        if r.status_code == 404:
            raise NotFound(f"404 {URL}")
        r.raise_for_status()     # 429 «Sorry…» — тоже ошибка: breaker делает паузу
        return parse(r.json())

    # --- async (сборщик) ---
    async def _fetch(self, url, params):
        if self._aclient is None:
            self._aclient = httpx.AsyncClient(**self._kw())
        params = dict(params)
        q = params.pop("q")
        return self._decode(await self._aclient.post(url, params=params, data={"q": q}))

    async def translate(self, texts: list[str], lang: str = "en", batch: Optional[int] = None,
                        max_requests: Optional[int] = None) -> list[str]:
        gen = plan(texts, CHUNK, batch, max_requests)
        try:
            q = next(gen)
            while True:
                self.chars += len(q)
                q = gen.send(await self.get(URL, {**self._params(lang), "q": q}, kind="text"))
        except StopIteration as e:
            return e.value

    # --- sync (API) ---
    def get_sync(self, q: str, lang: str, timeout: float, kind: str = "article") -> str:
        """То же, что Source.get (breaker, счётчики), но синхронно и с таймаутом на запрос."""
        with self._lock:
            self._check()
            now = time.time()
            self.requests += 1
            self.by_kind[kind] = self.by_kind.get(kind, 0) + 1
            self._recent.append(now)
            while self._recent and self._recent[0] < now - 3600:
                self._recent.popleft()
            if self._client is None:
                self._client = httpx.Client(**self._kw())
        t0 = time.monotonic()
        try:
            r = self._client.post(URL, params=self._params(lang), data={"q": q},
                                  timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)))
            out = self._decode(r)
        except Exception as e:
            with self._lock:
                self._failure(e)
            raise TranslateError(f"{self.name}: {type(e).__name__}: {e}") from e
        finally:
            self.last_latency_ms = round((time.monotonic() - t0) * 1000)
        with self._lock:
            self._success()
        self.chars += len(q)
        return out

    def translate_sync(self, texts: list[str], lang: str = "en", deadline: Optional[float] = None,
                       max_requests: Optional[int] = None) -> list[str]:
        """deadline — time.monotonic(), к которому всё должно быть готово (иначе TranslateError)."""
        gen = plan(texts, CHUNK, None, max_requests)
        try:
            q = next(gen)
            while True:
                left = self.timeout if deadline is None else min(self.timeout, deadline - time.monotonic())
                if left < 0.5:
                    raise TranslateError("перевод: не уложились в бюджет")
                q = gen.send(self.get_sync(q, lang, left))
        except StopIteration as e:
            return e.value

    def requests_last_min(self, now: Optional[float] = None) -> int:
        now = now or time.time()
        return sum(1 for t in self._recent if t > now - 60)

    async def close(self):
        if self._aclient is not None:
            await self._aclient.aclose()
        if self._client is not None:
            self._client.close()


# ===================================================================== кэш (SQLite)

def lookup(conn: sqlite3.Connection, texts: Iterable[Optional[str]], lang: str) -> dict[str, str]:
    """Готовые переводы: исходный текст → перевод. Текст без кириллицы — сам себе перевод."""
    out: dict[str, str] = {}
    keys: dict[str, str] = {}
    for t in texts:
        if not t or t in out:
            continue
        if not needs(t):
            out[t] = t
        else:
            keys[cache_key(t, lang)] = t
    items = list(keys)
    for i in range(0, len(items), 400):
        part = items[i:i + 400]
        q = ",".join("?" * len(part))
        for k, v in conn.execute(f"SELECT key, text FROM translations WHERE kind='text' AND key IN ({q})", part):
            out[keys[k]] = v
    return out


def missing(conn: sqlite3.Connection, texts: Iterable[Optional[str]], lang: str) -> list[str]:
    """Тексты, которым нужен перевод, а его ещё нет (без повторов, порядок сохранён)."""
    todo = [t for t in dict.fromkeys(t for t in texts if needs(t))]
    have = lookup(conn, todo, lang)
    return [t for t in todo if t not in have]


def save(conn: sqlite3.Connection, pairs: dict[str, str], lang: str, now: Optional[float] = None) -> int:
    now = now or time.time()
    rows = [(cache_key(src, lang), lang, "text", dst, now) for src, dst in pairs.items() if needs(src) and dst]
    with conn:
        conn.executemany("INSERT OR REPLACE INTO translations(key, lang, kind, text, created_at) VALUES (?,?,?,?,?)",
                         rows)
    return len(rows)


def article_key(html_text: str, lang: str) -> str:
    return cache_key("article\n" + html_text, lang)


def cached_article(conn: sqlite3.Connection, html_text: str, lang: str) -> Optional[str]:
    row = conn.execute("SELECT text FROM translations WHERE key=?", (article_key(html_text, lang),)).fetchone()
    return row[0] if row else None


def save_article(conn: sqlite3.Connection, html_text: str, lang: str, translated: str,
                 now: Optional[float] = None) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO translations(key, lang, kind, text, created_at) VALUES (?,?,?,?,?)",
                     (article_key(html_text, lang), lang, "article", translated, now or time.time()))


def cleanup(conn: sqlite3.Connection, now: Optional[float] = None) -> dict:
    cutoff = (now or time.time()) - config.TRANSLATION_TTL_DAYS * 86400
    with conn:
        n = conn.execute("DELETE FROM translations WHERE created_at < ?", (cutoff,)).rowcount
    return {"translations": n}


# ===================================================================== HTML статьи
# html статьи строит app/sources/article.py из белого списка тегов — здесь меняется только текст,
# теги и атрибуты остаются (lxml экранирует текст заново). Абзац из текста и <br> — переводится
# по кускам между <br>; абзац целиком в <strong>/<em> — так же, разметка сохраняется; абзац со
# смешанной разметкой (ссылка или выделение посреди фразы) — переводится целиком как одна фраза,
# внутренние теги снимаются: отдельный перевод обрывков фраз портит и смысл, и имена.

TEXT_BLOCKS = {"p", "h2", "h3", "li", "blockquote", "figcaption"}
BLOCKS = {"p", "h2", "h3", "blockquote", "ul", "ol", "li", "figure", "figcaption"}
_EDGE_WS = re.compile(r"^(\s*)(.*?)(\s*)$", re.S)

Slot = tuple[str, Callable[[str], None]]


def _tag(el) -> Optional[str]:
    return el.tag.lower() if isinstance(el.tag, str) else None


def segment_html(html_text: str):
    """html → (корень, [(текст, применить_перевод)]). Пустой/битый html — (None, [])."""
    if not html_text or not html_text.strip():
        return None, []
    try:
        root = LH.fragment_fromstring(html_text, create_parent="div")
    except (etree.ParserError, ValueError):
        return None, []
    slots: list[Slot] = []

    def add(get: Callable[[], Optional[str]], put: Callable[[str], None]):
        raw = get()
        if not needs(raw):
            return
        lead, core, trail = _EDGE_WS.match(raw).groups()
        slots.append((core, lambda t, lead=lead, trail=trail: put(lead + t + trail)))

    def text_of(el):
        add(lambda: el.text, lambda v: setattr(el, "text", v))

    def tail_of(el):
        add(lambda: el.tail, lambda v: setattr(el, "tail", v))

    def segments(el):
        text_of(el)
        for k in el:
            if _tag(k):
                segments(k)
            tail_of(k)

    def whole(el):
        text = _WS.sub(" ", el.text_content()).strip()
        if not needs(text):
            return

        def put(v, el=el):
            for k in list(el):
                el.remove(k)
            el.text = v
        slots.append((text, put))

    def visit(el):
        tag = _tag(el)
        if tag is None:
            return
        desc = [d for d in el.iterdescendants() if _tag(d)]
        if tag in TEXT_BLOCKS and not any(_tag(d) in BLOCKS for d in desc):
            inline = [d for d in desc if _tag(d) != "br"]
            kids = [k for k in el if _tag(k)]
            only = (len(kids) == 1 and _tag(kids[0]) in ("strong", "em") and not (el.text or "").strip()
                    and not (kids[0].tail or "").strip()
                    and all(_tag(d) == "br" for d in kids[0].iterdescendants() if _tag(d)))
            if not inline or only or any(_tag(d) == "img" for d in inline):
                segments(el)
            else:
                whole(el)
            return
        text_of(el)
        for k in el:
            visit(k)
            tail_of(k)

    visit(root)
    return root, slots


def render_html(root) -> str:
    out = root.text or ""
    for k in root:
        out += etree.tostring(k, encoding="unicode", method="html", with_tail=True)
    return out


def apply(slots: list[Slot], translated: list[str]) -> None:
    for (_, put), t in zip(slots, translated):
        put(t)


# ===================================================================== API: статья по запросу

class ArticleTranslator:
    """Перевод текста статьи по первому запросу `?lang=en` (процесс API, пул потоков).

    Одна статья — один поток (остальные запросы в это время получают русский текст); не больше
    TRANSLATE_ARTICLE_RATE_PER_MIN статей в минуту; не вышло — повтор не раньше TRANSLATE_ARTICLE_RETRY;
    breaker клиента — как у остальных источников."""

    def __init__(self, client: Optional[GoogleTranslate] = None, clock: Callable[[], float] = time.time):
        self.client = client or GoogleTranslate()
        self.clock = clock
        self._lock = threading.Lock()
        self._busy: set[str] = set()
        self._failed: dict[str, float] = {}
        self._starts: deque = deque()

    def _admit(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            if key in self._busy or self._failed.get(key, 0) > now:
                return False
            while self._starts and self._starts[0] < now - 60:
                self._starts.popleft()
            if len(self._starts) >= config.TRANSLATE_ARTICLE_RATE_PER_MIN or not self.client.available():
                return False
            self._busy.add(key)
            self._starts.append(now)
            return True

    def _done(self, key: str, ok: bool) -> None:
        with self._lock:
            self._busy.discard(key)
            if ok:
                self._failed.pop(key, None)
            else:
                if len(self._failed) > 1000:
                    self._failed.clear()
                self._failed[key] = self.clock() + config.TRANSLATE_ARTICLE_RETRY

    def translate(self, conn: sqlite3.Connection, html_text: str, extras: list[Optional[str]], lang: str,
                  budget: Optional[float] = None) -> bool:
        """Перевести html статьи и короткие поля (лид, подпись, заголовок…) и записать в кэш.
        True — перевод html в кэше (короткие поля — сколько успели). Ошибки не бросает."""
        key = article_key(html_text, lang)
        if not self._admit(key):
            return False
        ok = False
        try:
            root, slots = segment_html(html_text)
            extra = missing(conn, extras, lang)
            units = [s[0] for s in slots] + extra
            deadline = time.monotonic() + (budget if budget is not None else config.TRANSLATE_ARTICLE_BUDGET)
            out = self.client.translate_sync(units, lang, deadline=deadline, max_requests=40) if units else []
            if root is not None:
                apply(slots, out[:len(slots)])
                translated = render_html(root)
            else:
                translated = html_text
            save(conn, dict(zip(extra, out[len(slots):])), lang)
            save_article(conn, html_text, lang, translated)
            ok = True
        except SourceError as e:
            log.info("article translate: %s", e)
        except Exception:
            log.exception("article translate: ошибка (отдаю оригинал)")
        finally:
            self._done(key, ok)
        return ok
