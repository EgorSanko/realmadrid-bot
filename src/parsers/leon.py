"""src/parsers/leon.py — Leon (leon.ru) bookmaker API parser.

Primary source for odds (live + prematch) per RM audit PRINCIPLES.

Module-level state:
- _leon_cache_dict: cache_key -> {'data': ..., 'time': ...}
- _leon_ttl_prematch=10s, _leon_ttl_live=2s (BK-feel TTLs per RM cache TTLs note)

Entry points:
- _get_leon_cached(target_opponent) — cached wrapper
- get_leon_live_match(target_opponent) — fresh fetch with anti-suspended logic
- _parse_leon_markets(markets) — parser for all market types

Helpers:
- _normalize_team_name (uses TEAM_NAME_MAP — Russian/Latin translation)
  Note: this is the Leon-specific version. FotMob has its own _normalize_team_name
  (accent removal) which lives in api.py — name collision was masked before extraction.
- _is_youth_match (filter out Castilla/Juvenil from first-team matches)
"""
import re
import requests
import time
from typing import Dict


# ============ LEON LIVE ODDS ============

LEON_API = "https://leon.ru/api-2/betline"
LEON_SOCCER_ID = 1970324836974595

_leon_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Origin': 'https://leon.ru',
    'Referer': 'https://leon.ru/',
}

# === КЭШИРОВАНИЕ LEON ===
import time as _time

_leon_cache_dict = {}  # {cache_key: {'data': ..., 'time': ...}}
_leon_ttl_prematch = 10
_leon_ttl_live = 2

def _get_leon_cached(target_opponent: str = None) -> Dict:
    """Обёртка с кэшированием запросов к Leon (multi-key)"""
    now = _time.time()
    cache_key = target_opponent or '__live__'

    # Проверяем кэш для этого ключа
    cached = _leon_cache_dict.get(cache_key)
    if cached and cached.get('data'):
        is_live = cached['data'].get('is_live', False)
        ttl = _leon_ttl_live if is_live else _leon_ttl_prematch
        age = now - cached['time']
        if age < ttl:
            print(f"Leon CACHE HIT [{cache_key}] (age={age:.0f}s, ttl={ttl}s)")
            return cached['data']

    # Кэш устарел — запрашиваем заново
    result = get_leon_live_match(target_opponent)
    _leon_cache_dict[cache_key] = {'data': result, 'time': now}
    print(f"Leon CACHE MISS [{cache_key}] → fetched fresh data")
    return result

def _parse_leon_markets(markets: list) -> Dict:
    """Универсальный парсер ВСЕХ рынков Leon API"""
    odds = {}
    open_markets = 0

    def _ou(runners, prefix):
        """Парсим Больше/Меньше"""
        for r in runners:
            if not r.get('open', True) or not r.get('price'): continue
            rn, p = r.get('name', ''), r.get('price', 0)
            if not p or p <= 1 or p > 1000: continue
            if 'Больше' in rn:
                line = rn.replace('Больше', '').replace('(', '').replace(')', '').strip()
                odds[f'{prefix}_over_{line}'] = p
            elif 'Меньше' in rn:
                line = rn.replace('Меньше', '').replace('(', '').replace(')', '').strip()
                odds[f'{prefix}_under_{line}'] = p

    def _12(runners, p1, p2):
        """Парсим 1/2 (фора)"""
        for r in runners:
            if not r.get('open', True) or not r.get('price'): continue
            rn, p = r.get('name', ''), r.get('price', 0)
            if not p or p <= 1 or p > 1000: continue
            if rn.startswith('1'):
                line = rn.replace('1', '', 1).replace('(', '').replace(')', '').strip()
                odds[f'{p1}_{line}'] = p
            elif rn.startswith('2'):
                line = rn.replace('2', '', 1).replace('(', '').replace(')', '').strip()
                odds[f'{p2}_{line}'] = p

    for market in markets:
        mn_orig = market.get('name', '')
        runners = market.get('runners', [])
        mn = mn_orig.lower()

        if not market.get('open', True): continue

        # === ТОЧНЫЙ СЧЁТ (до основного skip-фильтра) ===
        if ('точный счет' in mn or 'точный счёт' in mn) and 'тайм' not in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if not p or p <= 1 or p > 1000: continue
                if ':' in rn:
                    parts = rn.split(':')
                    if len(parts) == 2:
                        h_s, a_s = parts[0].strip(), parts[1].strip()
                        if h_s.isdigit() and a_s.isdigit():
                            odds[f'score_{h_s}-{a_s}'] = p
            open_markets += 1
            continue

        # === ЧЁТ/НЕЧЁТ ТОТАЛ ГОЛОВ (до основного skip-фильтра) ===
        if 'чет' in mn and 'нечет' in mn and 'тайм' not in mn and 'угловы' not in mn and 'карточ' not in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', '').lower(), r.get('price', 0)
                if not p or p <= 1 or p > 1000: continue
                if rn in ('чет', 'чёт'):
                    odds['total_even'] = p
                elif rn in ('нечет', 'нечёт'):
                    odds['total_odd'] = p
            open_markets += 1
            continue

        # Пропускаем таймы и экзотику
        if 'тайм' in mn or 'половин' in mn or 'точн' in mn or 'чет/нечет' in mn: continue

        # === ИСХОД 1X2 ===
        if 'исход' in mn and ('1х2' in mn or '1x2' in mn):
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if p and p > 1 and p <= 1000:
                    if rn == '1': odds['home'] = p
                    elif rn in ('X', 'Х'): odds['draw'] = p
                    elif rn == '2': odds['away'] = p
            open_markets += 1

        # === ДВОЙНОЙ ШАНС/ИСХОД (не угловые) ===
        elif 'двойной' in mn and ('шанс' in mn or 'исход' in mn) and 'угловы' not in mn and 'карточ' not in mn and 'желт' not in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if p and p > 1 and p <= 1000:
                    if rn in ('1X', '1Х'): odds['dc_1x'] = p
                    elif rn in ('X2', 'Х2'): odds['dc_x2'] = p
                    elif rn == '12': odds['dc_12'] = p
            open_markets += 1

        # === ОБЕ ЗАБЬЮТ ===
        elif 'обе' in mn and 'забь' in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if p and p > 1 and p <= 1000:
                    if rn == 'Да': odds['btts_yes'] = p
                    elif rn == 'Нет': odds['btts_no'] = p
            open_markets += 1

        # === РЕЗУЛЬТАТ НЕ ВКЛЮЧАЯ НИЧЬЮ ===
        elif 'результат' in mn and 'ничью' in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if p and p > 1 and p <= 1000:
                    if rn == '1': odds['dnb_home'] = p
                    elif rn == '2': odds['dnb_away'] = p
            open_markets += 1

        # === КТО ЗАБЬЁТ ПЕРВЫЙ ГОЛ ===
        elif ('первый гол' in mn or '1-й гол' in mn) and 'как ' not in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if p and p > 1 and p <= 1000:
                    if rn == '1': odds['first_goal_home'] = p
                    elif rn == '2': odds['first_goal_away'] = p
                    elif 'не будет' in rn.lower(): odds['first_goal_none'] = p
            open_markets += 1

        # === ПЕНАЛЬТИ ===
        elif 'пенал' in mn and 'будет' in mn and 'серия' not in mn and 'команда' not in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if not p or p <= 1 or p > 1000: continue
                if rn == 'Да': odds['penalty_yes'] = p
                elif rn == 'Нет': odds['penalty_no'] = p
            open_markets += 1

        # === УГЛОВЫЕ ===
        elif 'угловы' in mn:
            if any(x in mn for x in ['кто', 'фора', 'двойной', 'чет', 'точн']): continue
            if 'хозяев' in mn: _ou(runners, 'corners_home')
            elif 'гостей' in mn: _ou(runners, 'corners_away')
            else: _ou(runners, 'corners')
            open_markets += 1

        # === КАРТОЧКИ (включая жёлтые) ===
        elif 'карточ' in mn or ('желт' in mn and 'тотал' in mn):
            if any(x in mn for x in ['кто', 'фора', 'чет', 'точн']): continue
            if 'хозяев' in mn: _ou(runners, 'cards_home')
            elif 'гостей' in mn: _ou(runners, 'cards_away')
            else: _ou(runners, 'cards')
            open_markets += 1

        # === ФОРА (обычная, не угловые) ===
        elif mn == 'фора' or ('фора' in mn and 'азиат' not in mn and 'угловы' not in mn):
            _12(runners, 'handicap_home', 'handicap_away')
            open_markets += 1

        # === ТОТАЛ ХОЗЯЕВ (только голы) ===
        elif 'тотал' in mn and 'хозяев' in mn and 'угловы' not in mn and 'карточ' not in mn and 'удар' not in mn and 'фол' not in mn and 'офсайд' not in mn and 'аут' not in mn:
            _ou(runners, 'home')
            open_markets += 1

        # === ТОТАЛ ГОСТЕЙ (только голы) ===
        elif 'тотал' in mn and 'гостей' in mn and 'угловы' not in mn and 'карточ' not in mn and 'удар' not in mn and 'фол' not in mn and 'офсайд' not in mn and 'аут' not in mn:
            _ou(runners, 'away')
            open_markets += 1

        # === ТОТАЛ ГОЛОВ (общий) — ТОЛЬКО точные названия ===
        elif mn in ('тотал', 'тотал голов', 'тотал матча'):
            _ou(runners, 'total')
            open_markets += 1
        elif 'тотал' in mn and 'хозяев' not in mn and 'гостей' not in mn and 'угловы' not in mn and 'карточ' not in mn:
            # Логируем что пропускаем — для дебага
            print(f"Leon SKIPPED unknown total market: '{mn_orig}'")

    print(f"Leon parsed: {len(odds)} odds, {open_markets} markets")
    # Log corners and cards specifically
    special = {k: v for k, v in odds.items() if any(x in k for x in ['corners', 'cards', 'dnb', 'first_goal', 'penalty', 'score_', 'total_even', 'total_odd'])}
    if special:
        print(f"Leon special markets: {special}")
    return {'odds': odds, 'open_markets': open_markets}


TEAM_NAME_MAP = {
    'Пари Сен-Жермен': 'ПСЖ',
    'Пари Сен Жермен': 'ПСЖ',
    'Paris Saint-Germain': 'ПСЖ',
    'Paris Saint Germain': 'ПСЖ',
    'Paris SG': 'ПСЖ',
    'Париж': 'ПСЖ',
    'Атлетико': 'Атлетико Мадрид',
    'Бавария Мюнхен': 'Бавария',
    'Манчестер Сити': 'Ман Сити',
    'Манчестер Юнайтед': 'Ман Юнайтед',
    'Боруссия Дортмунд': 'Дортмунд',
    'Интер Милан': 'Интер',
    'Интернационале': 'Интер',
}

def _normalize_team_name(name: str) -> str:
    """Нормализуем названия команд"""
    if not name:
        return name
    # Точное совпадение
    if name in TEAM_NAME_MAP:
        return TEAM_NAME_MAP[name]
    # Частичное
    for key, val in TEAM_NAME_MAP.items():
        if key.lower() in name.lower():
            return val
    return name


# Youth/reserve team suffixes to exclude from first-team match selection
_YOUTH_SUFFIXES = re.compile(
    r'(castilla|juvenil|youth|u[_-]?\d{2}|under[_-]?\d{2})'
    r'|(?:real\s+madrid|реал\s+мадрид)\s+[bc234]'
    r'|[bc234]\s*$',
    re.IGNORECASE
)

def _is_youth_match(name: str) -> bool:
    """Return True if event name contains youth/reserve team indicators."""
    # Check for numbered suffixes like "Real Madrid 3" or "Реал Мадрид 3"
    if _YOUTH_SUFFIXES.search(name):
        return True
    # Check for " B " or " C " between team names (e.g. "Реал Мадрид Б - Райо Валлекано 2")
    parts = re.split(r'\s*-\s*', name)
    for part in parts:
        part = part.strip()
        # "реал мадрид 3", "real madrid c", "real madrid b"
        if re.search(r'(?:real\s+madrid|реал\s+мадрид)\s+[а-яa-z0-9]$', part, re.IGNORECASE):
            suffix = part.split()[-1].lower()
            if suffix in ('b', 'c', 'б', 'в', '2', '3', '4', 'ii', 'iii', 'iv'):
                return True
    return False


def get_leon_live_match(target_opponent: str = None) -> Dict:
    """Получить матч Real Madrid с полными коэффициентами из Leon (двухшаговый запрос)
    target_opponent: если указан, ищем конкретный матч по сопернику
    """
    try:
        # ШАГ 1: Находим событие Real Madrid через /events/all
        url = f'{LEON_API}/events/all?ctag=ru-RU&sport_id={LEON_SOCCER_ID}&hideClosed=true&flags=reg,urlv2,mm2,rrc,nodup'
        response = requests.get(url, headers=_leon_headers, timeout=15)

        if response.status_code != 200:
            return {'is_live': False}

        data = response.json()
        events = data.get('events', [])
        # Сортируем: live матчи первыми
        events.sort(key=lambda e: (e.get('betline') != 'inplay', e.get('kickoff', 0)))

        leon_event = None
        leon_event_fallback = None
        for event in events:
            name = event.get('name', '')
            name_default = event.get('nameDefault', '')
            # Пропускаем киберспорт (там скобки с никами)
            if '(' in name:
                continue
            # Пропускаем outright-маркеты (например 'Ла Лига - без Реал Мадрид – Победитель')
            if event.get('betline') == 'outright':
                continue
            if 'Real Madrid' in name_default and '?' not in name and ' - ' in name and not _is_youth_match(name_default) and not _is_youth_match(name):
                # Если ищем конкретного соперника
                if target_opponent:
                    opp_lower = target_opponent.lower()
                    name_lower = name.lower() + ' ' + name_default.lower()
                    # Убираем "real" и "madrid" из поиска (они есть в каждом матче RM)
                    skip_words = {'real', 'madrid', 'fc', 'cf', 'club'}
                    opp_words = [w for w in opp_lower.split() if len(w) > 3 and w not in skip_words]
                    # Проверяем совпадение: полное имя ИЛИ ключевые слова соперника
                    if opp_lower in name_lower or (opp_words and any(word in name_lower for word in opp_words)):
                        leon_event = event
                        break
                    else:
                        if not leon_event_fallback:
                            leon_event_fallback = event
                else:
                    leon_event = event
                    break

        # Если не нашли конкретного соперника, НЕ используем фолбэк для prematch
        # (чтобы не показывать ПСЖ вместо Sociedad)
        if not leon_event and target_opponent:
            print(f"Leon: opponent '{target_opponent}' not found, skipping (fallback was: {leon_event_fallback.get('name') if leon_event_fallback else 'none'})")
            return {'is_live': False}
        if not leon_event:
            leon_event = leon_event_fallback

        if not leon_event:
            return {'is_live': False}

        event_id = leon_event.get('id')
        is_live = leon_event.get('betline') == 'inplay' or leon_event.get('matchPhase') == 'IN_PLAY'

        # Парсим команды
        name = leon_event.get('name', '')
        teams = name.split(' - ')
        home_team = _normalize_team_name(teams[0].strip() if len(teams) > 0 else '')
        away_team = _normalize_team_name(teams[1].strip() if len(teams) > 1 else '')

        # ШАГ 2: Получаем ПОЛНЫЕ рынки через /event/all?eventId={id}
        detail_url = f'{LEON_API}/event/all?ctag=ru-RU&eventId={event_id}&flags=reg,urlv2,mm2,rrc,nodup'
        detail_resp = requests.get(detail_url, headers=_leon_headers, timeout=15)

        odds = {}
        open_markets = 0
        bets_suspended = False

        if detail_resp.status_code == 200:
            detail_data = detail_resp.json()
            markets = detail_data.get('markets', [])
            parsed = _parse_leon_markets(markets)
            odds = parsed['odds']
            open_markets = parsed['open_markets']
            print(f"Leon detail API: {len(markets)} markets, {len(odds)} odds parsed, open={open_markets}")
        else:
            # Фолбэк - используем данные из events/all (менее точные)
            markets = leon_event.get('markets', [])
            parsed = _parse_leon_markets(markets)
            odds = parsed['odds']
            open_markets = parsed['open_markets']
            print(f"Leon fallback: {len(markets)} markets, {len(odds)} odds")

        # Если live и нет открытых рынков - ставки suspended
        if is_live and (len(odds) == 0 or open_markets == 0):
            bets_suspended = True

        return {
            'is_live': is_live,
            'bets_suspended': bets_suspended,
            'leon_id': event_id,
            'home_team': home_team,
            'away_team': away_team,
            'name_default': leon_event.get('nameDefault', ''),
            'kickoff': leon_event.get('kickoff'),
            'live_odds': odds,
            'markets_count': open_markets,
            'open_markets': open_markets,
            'liveStatus': leon_event.get('liveStatus'),
            'score': leon_event.get('liveStatus', {}).get('score') if leon_event.get('liveStatus') else None,
            'minute': leon_event.get('liveStatus', {}).get('progress') if leon_event.get('liveStatus') else None,
            'stage': leon_event.get('liveStatus', {}).get('stage') if leon_event.get('liveStatus') else None,
            'home_stats': leon_event.get('liveStatus', {}).get('homeStatistics') if leon_event.get('liveStatus') else None,
            'away_stats': leon_event.get('liveStatus', {}).get('awayStatistics') if leon_event.get('liveStatus') else None
        }

    except Exception as e:
        print(f"Leon API error: {e}")
        import traceback
        traceback.print_exc()
        return {'is_live': False, 'error': str(e)}
