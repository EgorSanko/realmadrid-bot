"""src/parsers/mysportslib.py — Real Madrid match videos from mysportslib.blogspot.com.

Источник архива видео по матчам RM. Каждый пост содержит 1-3 embed-ссылки
с лейблами '1st Half', '2nd Half', 'Full Match' на видео-хостинги
(hgcloud.to, hglink.to, cybervynx.com).

Эти ссылки можно показать пользователю как обзор/повторы таймов.
"""
import re
import ssl
import unicodedata
import urllib.request
import time as _time
from typing import List, Optional

LABEL_URL = 'https://mysportslib.blogspot.com/search/label/Real%20Madrid'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

# In-memory cache. RM матчи в архив попадают через сутки-двое, обновлять
# чаще раза в 6ч смысла нет.
_videos_cache = {'data': None, 'time': 0, 'ttl': 6 * 3600}

# Маппинг лейблов из блога на наши коды.
_LABEL_MAP = {
    '1st half': 'half1',
    '2nd half': 'half2',
    'full match': 'full',
    'match': 'full',
    'extra time (if any)': 'extratime',
    'extra time': 'extratime',
    'penalties (if any)': 'penalties',
    'penalties': 'penalties',
    'highlights': 'highlights',
    'review': 'highlights',
    'resumen': 'highlights',
    'goals': 'goals',
    'la previa/pregame': 'pregame',
    'pregame/la previa': 'pregame',
    'previa': 'pregame',
    'la previa': 'pregame',
    'pregame': 'pregame',
}

# Поддерживаемые видеохостинги — embed-able через iframe.
_KNOWN_HOSTS = ('hgcloud.to', 'hglink.to', 'cybervynx.com', 'streamtape',
                'streamhide', 'mixdrop', 'doodstream', 'filemoon')


def _fetch(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, context=_ssl_ctx, timeout=timeout) as r:
        return r.read().decode('utf-8', 'ignore')


def _is_known_host(url: str) -> bool:
    return any(h in url for h in _KNOWN_HOSTS)


def _parse_title(title: str) -> Optional[dict]:
    """Из 'EL CLÁSICO: La Liga 25/26 - Matchday 35 - FC Barcelona vs Real Madrid CF - 10/05/2026'
    достаём {home, away, date(YYYY-MM-DD), competition}."""
    # Дата в конце: DD/MM/YYYY
    date_m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})\s*$', title)
    if not date_m:
        return None
    d, m, y = date_m.groups()
    date_iso = f'{y}-{int(m):02d}-{int(d):02d}'

    # Команды: последняя пара 'X vs Y' перед датой
    head = title[:date_m.start()].rstrip(' -')
    vs_m = re.search(r'-\s*([^-]+?)\s+vs\.?\s+([^-]+?)\s*$', head, re.IGNORECASE)
    if not vs_m:
        return None
    home = vs_m.group(1).strip()
    away = vs_m.group(2).strip()
    # Турнир: всё до последнего ' - X vs Y' блока, без префикса
    comp_segment = head[:vs_m.start()].rstrip(' -')
    # Убираем префикс типа 'FÚTBOL:' или 'EL CLÁSICO:'
    comp = re.sub(r'^[^:]+:\s*', '', comp_segment).strip()
    return {'home': home, 'away': away, 'date': date_iso, 'competition': comp}


def _parse_post_videos(html: str) -> List[dict]:
    """Извлекает [{type, url, provider}] из HTML поста."""
    videos = []
    # Паттерн: <b>LABEL:</b><a href="URL">  (между ними бывают пробелы/перенос)
    for m in re.finditer(
        r'<b>\s*([^<:]+?)\s*:</b>\s*<a[^>]+href=["\'](https?://[^"\']+)["\']',
        html,
    ):
        label = m.group(1).strip().lower()
        url = m.group(2)
        if not _is_known_host(url):
            continue
        vtype = _LABEL_MAP.get(label)
        if not vtype:
            continue
        provider = next((h for h in _KNOWN_HOSTS if h in url), 'unknown')
        videos.append({'type': vtype, 'url': url, 'provider': provider})

    return videos


def _fetch_post_list() -> List[dict]:
    """Грузит label-страницу, возвращает [{title, date, post_url, parsed}]."""
    html = _fetch(LABEL_URL)
    posts = []
    seen = set()
    for m in re.finditer(
        r"<h3[^>]*>\s*<a href='(https://mysportslib\.blogspot\.com/\d{4}/\d{2}/[^']+\.html)'[^>]*>([^<]+)</a>",
        html,
    ):
        url = m.group(1)
        if url in seen:
            continue
        seen.add(url)
        title = m.group(2).strip()
        parsed = _parse_title(title)
        if not parsed:
            continue
        posts.append({'title': title, 'post_url': url, **parsed})
    return posts


def _refresh_cache():
    """Заполняет _videos_cache. Идёт по последним 25 постам, для каждого
    качает HTML и извлекает видео-ссылки. Тяжёлая операция (~15-30s),
    запускается warmer-ом раз в 6ч."""
    try:
        posts = _fetch_post_list()
    except Exception as e:
        print(f'mysportslib: post list fetch error: {e}', flush=True)
        return

    items = []
    for p in posts[:25]:
        try:
            post_html = _fetch(p['post_url'])
            videos = _parse_post_videos(post_html)
        except Exception as e:
            print(f'mysportslib: post fetch error {p["post_url"]}: {e}', flush=True)
            videos = []
        if not videos:
            continue
        items.append({**p, 'videos': videos})

    _videos_cache['data'] = items
    _videos_cache['time'] = _time.time()
    print(f'mysportslib: cached {len(items)} RM video posts', flush=True)


def get_rm_videos(force_refresh: bool = False) -> List[dict]:
    """Возвращает закешированный список матчей RM с видео-ссылками."""
    age = _time.time() - _videos_cache['time']
    if force_refresh or _videos_cache['data'] is None or age > _videos_cache['ttl']:
        _refresh_cache()
    return _videos_cache['data'] or []


_ALIASES = {
    'mancity': 'manchestercity',
    'manunited': 'manchesterunited',
    'manutd': 'manchesterunited',
    'atleticomadrid': 'atletico',
    'athleticobilbao': 'athletic',
    'realbetisbalompie': 'realbetis',
    'realmadridcf': 'realmadrid',
}


def _norm(s: str) -> str:
    """Нормализует имя команды: акуты, регистр, мусорные слова, алиасы.
    'Manchester City' → 'manchestercity', 'Man City' → 'manchestercity'."""
    # Раскладываем юникод и убираем диакритику (é→e, á→a)
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r'\b(cf|fc|club|de|the|royal|el|sociedad|sad)\b', '', s)
    s = re.sub(r'[^a-z0-9]+', '', s)
    return _ALIASES.get(s, s)


def _team_match(a: str, b: str) -> bool:
    """Нечёткое совпадение двух нормализованных названий."""
    if not a or not b: return False
    if a == b: return True
    # Один в другом (Man City ⊂ Manchester City после норм-алиаса они равны,
    # но Real Madrid ⊂ Real Madrid CF проверяется здесь)
    return a in b or b in a


def match_videos_for(home: str, away: str, date_iso: str) -> Optional[dict]:
    """Ищет в кеше пост, соответствующий матчу (home, away, date_iso=YYYY-MM-DD).
    Совпадение по обеим командам и точной дате."""
    target_home = _norm(home)
    target_away = _norm(away)
    for item in get_rm_videos():
        if item['date'] != date_iso:
            continue
        ih = _norm(item['home'])
        ia = _norm(item['away'])
        if (_team_match(target_home, ih) and _team_match(target_away, ia)):
            return item
    return None
