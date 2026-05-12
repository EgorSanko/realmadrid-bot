"""src/parsers/football_video.py — Highlight finder from football-video.org.

Сайт публикует обзоры всех матчей RM на странице /clubs/real-madrid/.
URL post-а: /YYYY/MM/DD/{slug}-video-obzor-matcha/
Внутри popupwindow → rutube.ru/video/{id}.
RuTube embed работает в РФ без VPN и DNS-блокировок.

API:
- get_all_rm_highlights() → [{'date': 'YYYY-MM-DD', 'post_url': ..., 'rutube_embed': ...}]
- match_highlight(home, away, date_iso) → embed URL или None
"""
import re
import ssl
import urllib.request
import time as _time
from typing import Optional, List

CLUB_URL = 'https://football-video.org/clubs/real-madrid/'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

# Кеш всего архива обзоров. TTL 6ч — обзоры в архиве не меняются.
_cache = {'data': None, 'time': 0, 'ttl': 6 * 3600}


def _fetch(url: str, timeout: int = 15) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=timeout) as r:
            return r.read().decode('utf-8', 'ignore')
    except Exception as e:
        print(f'football_video fetch err {url}: {e}', flush=True)
        return None


def _extract_video_embed(post_html: str) -> Optional[str]:
    """Возвращает embed-URL первого видео в посте (RuTube или VK Sport).
    Поддерживает оба провайдера популярных для football-video.org."""
    # 1. RuTube — стандарт
    m = re.search(r"popupwindow\('(https?://rutube\.ru/video/([a-f0-9]+)/)'", post_html)
    if m:
        return f'https://rutube.ru/play/embed/{m.group(2)}?autoplay=1'
    # 2. VK Sport (vksport.vkvideo.ru/video-OID_VID)
    m = re.search(r"popupwindow\('(https?://vksport\.vkvideo\.ru/video-?\d+_?\d+)'", post_html)
    if m:
        # Эта страница плеера VK Sport — открывается в iframe напрямую
        return m.group(1)
    # 3. Generic fallback — любой popupwindow URL
    m = re.search(r"popupwindow\('(https?://[^']+)'", post_html)
    if m:
        return m.group(1)
    return None


def _refresh_cache():
    html = _fetch(CLUB_URL)
    if not html:
        return
    posts = re.findall(
        r'href="(https://football-video\.org/(\d{4})/(\d{2})/(\d{2})/[^"]+-video-obzor-matcha/?)"',
        html
    )
    seen = set()
    items = []
    for full_url, y, m, d in posts:
        # уникальные по URL
        clean = full_url.rstrip('/') + '/'
        if clean in seen: continue
        seen.add(clean)
        items.append({
            'date': f'{y}-{m}-{d}',
            'post_url': clean,
            'rutube_embed': None,  # ленивая загрузка
        })
    # Сразу подгружаем embed для первых 20 постов (горячие данные)
    for it in items[:20]:
        try:
            ph = _fetch(it['post_url'])
            if ph:
                emb = _extract_video_embed(ph)
                if emb:
                    it['rutube_embed'] = emb  # legacy ключ, может быть VK Sport URL
        except Exception:
            pass
    _cache['data'] = items
    _cache['time'] = _time.time()
    print(f'football_video: cached {len(items)} RM highlight posts', flush=True)


def get_all_rm_highlights(force: bool = False) -> List[dict]:
    age = _time.time() - _cache['time']
    if force or _cache['data'] is None or age > _cache['ttl']:
        _refresh_cache()
    return _cache['data'] or []


def _date_close(d1: str, d2: str) -> bool:
    """True если две YYYY-MM-DD даты в пределах ±1 дня. Посты часто
    публикуются на следующий день после матча, особенно вечерние."""
    if d1 == d2: return True
    try:
        from datetime import date
        y1, m1, dd1 = int(d1[0:4]), int(d1[5:7]), int(d1[8:10])
        y2, m2, dd2 = int(d2[0:4]), int(d2[5:7]), int(d2[8:10])
        return abs((date(y1, m1, dd1) - date(y2, m2, dd2)).days) <= 1
    except Exception:
        return False


def match_highlight(home: str, away: str, date_iso: str) -> Optional[str]:
    """Возвращает embed URL обзора матча (RuTube/VK), или None.
    Допускает сдвиг даты ±1 день — посты часто публикуются на следующий день."""
    # Точное совпадение приоритетнее
    items = get_all_rm_highlights()
    for it in items:
        if it['date'] == date_iso and it.get('rutube_embed'):
            return it['rutube_embed']
    # Fallback: ±1 день
    for it in items:
        if _date_close(it['date'], date_iso) and it.get('rutube_embed'):
            return it['rutube_embed']
    return None
