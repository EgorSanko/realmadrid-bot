"""src/parsers/footybite.py — footybite.do schedule scraper.

Finds Real Madrid match stream URLs via footybite search.
Used by /api/footybite/schedule and /api/footybite/setup (routes/streams.py).

State:
- _FOOTYBITE_BASE: https://www.footybite.do
- _footybite_cache: 60s TTL
"""
import re as _fb_re
from urllib.parse import urljoin as _fb_urljoin
import requests


# ============ FOOTYBITE STREAM SOURCE ============
import re as _fb_re
from urllib.parse import urljoin as _fb_urljoin
_FOOTYBITE_BASE = 'https://www.footybite.do'
_footybite_cache = {'data': None, 'time': 0}
_FOOTYBITE_TTL = 60

def _fb_fetch(url: str, timeout: int = 12) -> str:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception as _e:
        print(f'fb fetch err {url}: {_e}', flush=True)
    return ''

def _footybite_schedule_parse() -> list:
    """Find Real Madrid matches on footybite homepage / search."""
    matches = []
    seen_ids = set()
    queries = ['real madrid', 'real-madrid']
    for q in queries:
        html = _fb_fetch(f'{_FOOTYBITE_BASE}/search?q={q}')
        if not html:
            html = _fb_fetch(f'{_FOOTYBITE_BASE}/?search={q}')
        if not html:
            continue
        # Match links shaped like /Real-Madrid-vs-Foo/12345 OR full URL https://www.footybite.do/Foo-vs-Real-Madrid/12345
        for m in _fb_re.finditer(r'href="((?:https?://[^"]*)?/?[A-Za-z][^"]*[Rr]eal[-_ ][Mm]adrid[^"]*/(\d+))"', html):
            href, mid = m.group(1), m.group(2)
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            url = href if href.startswith('http') else _fb_urljoin(_FOOTYBITE_BASE, href)
            # Extract teams from URL slug
            slug_part = url.rsplit('/', 1)[0]
            slug = slug_part.rsplit('/', 1)[-1]
            parts = slug.split('-vs-')
            home = parts[0].replace('-', ' ').strip() if len(parts) > 0 else ''
            away = parts[1].replace('-', ' ').strip() if len(parts) > 1 else ''
            matches.append({
                'id': mid,
                'url': url,
                'home': home,
                'away': away,
                'time': '',
                'status': 'live',
                'league': 'Football',
            })
    return matches
