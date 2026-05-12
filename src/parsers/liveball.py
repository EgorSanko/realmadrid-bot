"""src/parsers/liveball.py — LiveBall schedule parser.

Source: liveball.website (mirrors: liveball7.icu, q31/q28.liveball.st).
Used as fallback display of Real Madrid match schedule when sheets/FotMob are slow.

Module state:
- _liveball_schedule_cache: 5min TTL
- _liveball_mirrors / _liveball_working_mirror: domain pinning
- _liveball_domain_cache: 10min TTL on current working mirror

Functions:
- _get_liveball_domain() — resolves working mirror with health-check
- _parse_liveball_schedule() — HTML scrape + parse → list[dict]
"""
import requests
import time as _time
from typing import List, Dict


# ============ LIVEBALL SCHEDULE PARSER ============

_liveball_schedule_cache = {'data': None, 'time': 0, 'ttl': 300}  # 5 min
_LIVEBALL_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
_LIVEBALL_TEAM_ID = 541  # Real Madrid on LiveBall

_liveball_mirrors = ['https://liveball7.icu', 'https://q31.liveball.st', 'https://q28.liveball.st']
_liveball_working_mirror = None


_liveball_domain_cache = {'domain': None, 'time': 0, 'ttl': 600}  # 10 min cache

def _get_liveball_domain():
    """Get current LiveBall working domain with mirror rotation + 10 min cache"""
    global _liveball_working_mirror
    import time as _t
    now = _t.time()

    # Use cached domain if fresh (skip all network calls)
    if _liveball_domain_cache['domain'] and (now - _liveball_domain_cache['time']) < _liveball_domain_cache['ttl']:
        return _liveball_domain_cache['domain']

    # 1. Try cached working mirror (quick HEAD, 3s timeout)
    if _liveball_working_mirror:
        try:
            r = requests.head(f'{_liveball_working_mirror}/team/{_LIVEBALL_TEAM_ID}',
                             headers=_LIVEBALL_HEADERS, timeout=3, allow_redirects=True)
            if r.status_code == 200:
                _liveball_domain_cache['domain'] = _liveball_working_mirror
                _liveball_domain_cache['time'] = now
                return _liveball_working_mirror
        except:
            _liveball_working_mirror = None

    # 2. Try liveball.website redirect (most reliable gateway)
    try:
        resp = requests.get('https://liveball.website/', headers=_LIVEBALL_HEADERS, timeout=5, allow_redirects=True)
        text = resp.text
        m = re.search(r'href="(https://liveball[^"]+)"', text)
        if m:
            domain = m.group(1).rstrip('/')
            try:
                r = requests.head(f'{domain}/team/{_LIVEBALL_TEAM_ID}',
                                 headers=_LIVEBALL_HEADERS, timeout=5, allow_redirects=True)
                if r.status_code == 200:
                    _liveball_working_mirror = domain
                    _liveball_domain_cache['domain'] = domain
                    _liveball_domain_cache['time'] = now
                    return domain
            except:
                # Domain from redirect doesn't work, but save it as fallback
                _liveball_working_mirror = domain
    except:
        pass

    # 3. Try known mirrors
    for mirror in _liveball_mirrors:
        try:
            r = requests.head(f'{mirror}/team/{_LIVEBALL_TEAM_ID}',
                             headers=_LIVEBALL_HEADERS, timeout=5, allow_redirects=True)
            if r.status_code == 200:
                final = r.url.split('/team/')[0] if '/team/' in r.url else mirror
                _liveball_working_mirror = final
                _liveball_domain_cache['domain'] = final
                _liveball_domain_cache['time'] = now
                return final
        except:
            continue

    # All failed — cache the failure for 2 min to avoid retrying immediately
    fallback = _liveball_working_mirror or 'https://liveball7.icu'
    _liveball_domain_cache['domain'] = fallback
    _liveball_domain_cache['time'] = now
    _liveball_domain_cache['ttl'] = 120  # Shorter TTL on failure
    return fallback


def _parse_liveball_schedule():
    """Parse LiveBall Real Madrid team page for upcoming & live matches"""
    import time as _t
    now = _t.time()

    if _liveball_schedule_cache['data'] is not None and (now - _liveball_schedule_cache['time']) < _liveball_schedule_cache['ttl']:
        return _liveball_schedule_cache['data']
    # Also cache failures for 60s to avoid hammering dead mirrors
    if _liveball_schedule_cache.get('failed_at') and (now - _liveball_schedule_cache['failed_at']) < 120:
        return _liveball_schedule_cache.get('data') or []

    try:
        domain = _get_liveball_domain()
        url = f'{domain}/team/{_LIVEBALL_TEAM_ID}'
        resp = requests.get(url, headers=_LIVEBALL_HEADERS, timeout=8, allow_redirects=True)
        resp.raise_for_status()

        # Update domain from final redirect URL
        if '/team/' in resp.url:
            domain = resp.url.split('/team/')[0]

        soup = BeautifulSoup(resp.text, 'html.parser')
        matches = []

        sections = soup.select('section.leagues_section')

        # --- Section 1: past/finished + possibly LIVE matches ---
        if sections:
            sec1 = sections[0]
            live_div = sec1.select_one('.live')
            if live_div:
                current_league = ''
                current_date = ''
                for child in live_div.children:
                    if not hasattr(child, 'get'):
                        continue
                    cls = child.get('class', []) or []

                    if 'small_l' in cls:
                        current_league = child.get_text(strip=True)
                    elif child.name == 'span' and 'date_tour' in cls:
                        current_date = child.get_text(strip=True)
                    elif 'live_block2' in cls:
                        link = child.select_one('a.match_a')
                        if not link:
                            continue
                        href = link.get('href', '')
                        match_id = href.rstrip('/').split('/')[-1] if '/match/' in href else ''
                        if not match_id:
                            continue

                        home_el = link.select_one('.team_title_left')
                        away_el = link.select_one('.team_title_right')
                        score_el = link.select_one('.score')
                        home = home_el.get_text(strip=True) if home_el else ''
                        away = away_el.get_text(strip=True) if away_el else ''
                        score = score_el.get_text(strip=True) if score_el else ''

                        # Check for LIVE indicator
                        live_el = child.select_one('.live_icon, .is_live, .tm_live')
                        score_cls = score_el.get('class', []) if score_el else []
                        is_live = bool(live_el) or 'live_score' in score_cls or 'is_live' in ' '.join(cls)

                        # Only include LIVE matches from section 1, skip finished
                        if is_live and home and away:
                            matches.append({
                                'id': match_id,
                                'home': home,
                                'away': away,
                                'league': current_league,
                                'date': current_date,
                                'time': 'LIVE',
                                'score': score,
                                'status': 'live',
                                'url': f'{domain}/match/{match_id}',
                            })

        # --- Section 2: upcoming matches ---
        if len(sections) > 1:
            sec2 = sections[1]
            live_div = sec2.select_one('.live')
            if live_div:
                current_league = ''
                current_date = ''
                for child in live_div.children:
                    if not hasattr(child, 'get'):
                        continue
                    cls = child.get('class', []) or []

                    if 'small_l' in cls:
                        current_league = child.get_text(strip=True)
                    elif child.name == 'span' and 'date_tour' in cls:
                        current_date = child.get_text(strip=True)
                    elif 'live_block2' in cls:
                        link = child.select_one('a.match_a')
                        if not link:
                            continue
                        href = link.get('href', '')
                        match_id = href.rstrip('/').split('/')[-1] if '/match/' in href else ''
                        if not match_id:
                            continue

                        home_el = link.select_one('.team_title_left')
                        away_el = link.select_one('.team_title_right')
                        vs_el = link.select_one('.vs') or link.select_one('.score')
                        home = home_el.get_text(strip=True) if home_el else ''
                        away = away_el.get_text(strip=True) if away_el else ''
                        time_str = vs_el.get_text(strip=True) if vs_el else ''

                        if home and away:
                            matches.append({
                                'id': match_id,
                                'home': home,
                                'away': away,
                                'league': current_league,
                                'date': current_date,
                                'time': time_str if time_str and ':' in time_str else '',
                                'score': '',
                                'status': 'upcoming',
                                'url': f'{domain}/match/{match_id}',
                            })

        _liveball_schedule_cache['data'] = matches
        _liveball_schedule_cache['time'] = now
        print(f"LiveBall: parsed {len(matches)} RM matches from {domain}/team/{_LIVEBALL_TEAM_ID}")
        return matches

    except Exception as e:
        print(f"LiveBall parse error: {e}")
        _liveball_schedule_cache['failed_at'] = now
        return _liveball_schedule_cache.get('data') or []
