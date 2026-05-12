"""parsers/espn.py — ESPN API fallback parser.

Используется когда FotMob возвращает 404 для матча (например, после конца матча
данные исчезают раньше чем ESPN). Парсит scoreboard и summary endpoints.

См. Obsidian/Real Madrid/02 - Backend/ESPN fallback.md
"""
import time as _time
import requests




# ============ ESPN API (fallback for FotMob matchDetails) ============
ESPN_API = "http://site.api.espn.com/apis/site/v2/sports/soccer"
_ESPN_LEAGUES = ['esp.1', 'uefa.champions', 'uefa.europa', 'eng.1', 'ger.1', 'ita.1', 'fra.1', 'uefa.europa.conf']
_espn_id_cache = {}  # {fotmob_match_id: espn_event_id}
_espn_summary_cache = {}  # {espn_event_id: {'data': ..., 'time': ...}}
_ESPN_CACHE_TTL = 300  # 5 min (non-live default)
_ESPN_CACHE_TTL_LIVE = 30  # 30 sec for live matches


def _parse_standings_from_html(table_data, league_id: int = 87) -> list:
    """Parse standings from FotMob HTML __NEXT_DATA__ table structure"""
    if not table_data:
        return []
    try:
        rows = []
        # FotMob table structure varies - try multiple paths
        if isinstance(table_data, list):
            for t in table_data:
                if isinstance(t, dict):
                    tbl = t.get('data', {}).get('table', {})
                    rows = tbl.get('all', [])
                    if rows:
                        break
                    # Try 'lines' key
                    lines = tbl.get('lines', [])
                    if lines:
                        rows = lines
                        break
        elif isinstance(table_data, dict):
            tbl = table_data.get('data', {}).get('table', {})
            rows = tbl.get('all', [])

        if not rows:
            print(f"FotMob HTML standings: no rows found in table_data", flush=True)
            return []

        standings = []
        for row in rows:
            team_name = row.get('name', '')
            team_id_s = row.get('id', '')
            _register_team(team_name, team_id_s)
            scores = row.get('scoresStr', '0-0')
            gf = scores.split('-')[0].strip() if '-' in str(scores) else row.get('goalsFor', 0)
            ga = scores.split('-')[1].strip() if '-' in str(scores) else row.get('goalsAgainst', 0)
            standings.append({
                'position': row.get('idx', row.get('position', 0)),
                'team': team_name,
                'team_id': team_id_s,
                'logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{team_id_s}.png" if team_id_s else '',
                'played': row.get('played', 0),
                'won': row.get('wins', 0),
                'drawn': row.get('draws', 0),
                'lost': row.get('losses', 0),
                'gf': gf,
                'ga': ga,
                'gd': row.get('goalConDiff', row.get('gd', 0)),
                'points': row.get('pts', 0),
                'isRealMadrid': team_id_s == 8633 or team_name == 'Real Madrid',
            })
        if standings:
            _fotmob_standings_cache['data'] = standings
            _fotmob_standings_cache['time'] = _time.time()
            print(f"FotMob HTML standings: {len(standings)} teams parsed", flush=True)
        return standings
    except Exception as e:
        print(f"FotMob HTML standings parse error: {e}", flush=True)
        return []


def _espn_find_event(date_str: str, home_name: str, away_name: str) -> str:
    """Find ESPN event ID by date and team names.
    date_str: 'YYYYMMDD' or 'DD.MM.YYYY' or 'YYYY-MM-DD'
    """
    # Normalize date to YYYYMMDD
    ds = date_str.replace('-', '').replace('.', '')
    if len(ds) == 8:
        if not ds[:4].isdigit():  # DD.MM.YYYY -> YYYYMMDD
            parts = date_str.split('.')
            if len(parts) == 3:
                ds = parts[2] + parts[1] + parts[0]

    def _normalize(name):
        n = name.lower().strip()
        for rem in ['fc ', 'cf ', 'rcd ', 'ud ', 'rc ', 'sd ', 'sc ', 'sl ']:
            n = n.replace(rem, '')
        return n.strip()

    h_norm = _normalize(home_name)
    a_norm = _normalize(away_name)

    for league in _ESPN_LEAGUES:
        try:
            url = f"{ESPN_API}/{league}/scoreboard?dates={ds}"
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            for ev in data.get('events', []):
                comps = ev.get('competitions', [{}])[0]
                competitors = comps.get('competitors', [])
                if len(competitors) < 2:
                    continue
                espn_home = ''
                espn_away = ''
                for c in competitors:
                    tn = c.get('team', {}).get('displayName', '')
                    if c.get('homeAway') == 'home':
                        espn_home = tn
                    else:
                        espn_away = tn

                eh = _normalize(espn_home)
                ea = _normalize(espn_away)

                def _match(a, b):
                    if not a or not b:
                        return False
                    if a in b or b in a:
                        return True
                    wa = set(a.split())
                    wb = set(b.split())
                    common = wa & wb
                    return any(len(w) > 3 for w in common)

                if _match(h_norm, eh) and _match(a_norm, ea):
                    eid = str(ev.get('id', ''))
                    print(f"ESPN: found event {eid} for {home_name} vs {away_name} in {league}", flush=True)
                    return eid
        except Exception as e:
            print(f"ESPN scoreboard error ({league}): {e}", flush=True)

    print(f"ESPN: no event found for {home_name} vs {away_name} on {ds}", flush=True)
    return ''


def _espn_get_summary(espn_event_id: str, league: str = None, is_live: bool = False) -> dict:
    """Get ESPN match summary. Try all leagues if league not specified."""
    if not espn_event_id:
        return {}

    now = _time.time()
    cached = _espn_summary_cache.get(espn_event_id)
    ttl = _ESPN_CACHE_TTL_LIVE if is_live else _ESPN_CACHE_TTL
    if cached and (now - cached['time']) < ttl:
        return cached['data']

    leagues_to_try = [league] if league else _ESPN_LEAGUES
    for lg in leagues_to_try:
        try:
            url = f"{ESPN_API}/{lg}/summary?event={espn_event_id}"
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if data.get('header'):
                    _espn_summary_cache[espn_event_id] = {'data': data, 'time': now}
                    return data
        except:
            pass
    return {}


def _espn_parse_events(summary: dict) -> list:
    """Parse ESPN events into frontend-compatible format.

    Uses keyEvents for goals/yellow cards and header.details for red cards
    (red cards may only appear in details, not in keyEvents).
    Output format matches frontend expectations:
      type: 'goal' | 'yellow' | 'red' | 'half'
      home: bool, player: str, minute: str, score: str (goals only)
      assist: str (goals), penalty: bool, own_goal: bool
    """
    events = []
    if not summary:
        return events

    header = summary.get('header', {})
    comp = header.get('competitions', [{}])[0]
    competitors = comp.get('competitors', [])
    home_team_id = ''
    for c in competitors:
        if c.get('homeAway') == 'home':
            home_team_id = str(c.get('id', ''))
            break

    raw = []

    # --- keyEvents: goals, yellow cards, halftime ---
    for ke in summary.get('keyEvents', []):
        ev_type_info = ke.get('type', {})
        ev_type_raw = (ev_type_info.get('type', '') or '').lower()
        short_text = ke.get('shortText', '') or ''
        sort_val = ke.get('clock', {}).get('value', 0) or 0

        clock_disp = ke.get('clock', {}).get('displayValue', '')
        minute = ''
        if clock_disp:
            minute = clock_disp.replace("'", '').strip()

        if ev_type_raw == 'goal' or ('penalty' in ev_type_raw and 'scored' in ev_type_raw):
            ev_type = 'goal'
        elif ev_type_raw == 'yellow-card':
            ev_type = 'yellow'
        elif ev_type_raw in ('red-card', 'second-yellow-red-card', 'second-yellow'):
            ev_type = 'red'
        elif ev_type_raw == 'halftime':
            raw.append({'type': 'half', 'text': '\u041f\u0435\u0440\u0435\u0440\u044b\u0432', '_sort': sort_val})
            continue
        else:
            continue

        team_data = ke.get('team', {})
        team_id = str(team_data.get('id', ''))
        is_home = (team_id == home_team_id) if team_id else True

        participants = ke.get('participants', [])
        player_name = participants[0].get('athlete', {}).get('displayName', '') if participants else ''

        ev = {
            'minute': minute,
            'type': ev_type,
            'player': player_name,
            'home': is_home,
            '_sort': sort_val,
        }

        if ev_type == 'goal':
            if len(participants) > 1:
                ev['assist'] = participants[1].get('athlete', {}).get('displayName', '')
            st_low = short_text.lower()
            if 'penalty' in st_low or 'pen.' in st_low:
                ev['penalty'] = True
            if 'own goal' in st_low:
                ev['own_goal'] = True

        raw.append(ev)

    # --- details: red cards (may be absent from keyEvents) ---
    details = comp.get('details', [])
    for det in details:
        if not det.get('redCard', False):
            continue
        sort_val = det.get('clock', {}).get('value', 0) or 0
        if any(e for e in raw if e.get('type') == 'red' and abs(e.get('_sort', 0) - sort_val) < 10):
            continue
        clock_disp = det.get('clock', {}).get('displayValue', '')
        minute = ''
        if clock_disp:
            minute = clock_disp.replace("'", '').strip()
        team_data = det.get('team', {})
        team_id = str(team_data.get('id', ''))
        is_home = (team_id == home_team_id) if team_id else True
        participants = det.get('participants', [])
        player_name = participants[0].get('athlete', {}).get('displayName', '') if participants else ''
        raw.append({
            'minute': minute,
            'type': 'red',
            'player': player_name,
            'home': is_home,
            '_sort': sort_val,
        })

    # Sort by clock value
    raw.sort(key=lambda x: x.get('_sort', 0))

    # Compute running score for goals
    home_score = 0
    away_score = 0
    for ev in raw:
        if ev['type'] == 'goal':
            if ev.get('own_goal'):
                if ev['home']:
                    away_score += 1
                else:
                    home_score += 1
            else:
                if ev['home']:
                    home_score += 1
                else:
                    away_score += 1
            ev['score'] = f'{home_score}:{away_score}'
        ev.pop('_sort', None)
        events.append(ev)

    return events


def _espn_parse_stats(summary: dict) -> list:
    """Parse ESPN boxscore stats into frontend-compatible format."""
    stats = []
    if not summary:
        return stats

    bs = summary.get('boxscore', {})
    teams_data = bs.get('teams', [])
    if len(teams_data) < 2:
        return stats

    home_stats = {}
    away_stats = {}
    for s in teams_data[0].get('statistics', []):
        home_stats[s.get('name', '')] = s.get('displayValue', '0')
    for s in teams_data[1].get('statistics', []):
        away_stats[s.get('name', '')] = s.get('displayValue', '0')

    stat_map = [
        ('possessionPct', 'Владение мячом', '%'),
        ('totalShots', 'Удары', ''),
        ('shotsOnTarget', 'Удары в створ', ''),
        ('wonCorners', 'Угловые', ''),
        ('foulsCommitted', 'Фолы', ''),
        ('offsides', 'Офсайды', ''),
        ('yellowCards', 'Жёлтые карточки', ''),
        ('redCards', 'Красные карточки', ''),
        ('saves', 'Сейвы', ''),
        ('totalPasses', 'Передачи', ''),
        ('accuratePass', 'Точные передачи', ''),
        ('totalTackle', 'Отборы', ''),
        ('totalCross', 'Кроссы', ''),
        ('interceptions', 'Перехваты', ''),
    ]

    for key, title, suffix in stat_map:
        hv = home_stats.get(key, '')
        av = away_stats.get(key, '')
        if hv or av:
            stats.append({
                'title': title,
                'home': str(hv) + suffix if hv else '0',
                'away': str(av) + suffix if av else '0',
            })

    return stats


def _espn_parse_lineups(summary: dict) -> dict:
    """Parse ESPN rosters into frontend-compatible format."""
    result = {'home': [], 'away': []}
    if not summary:
        return result

    rosters = summary.get('rosters', [])

    for i, r in enumerate(rosters):
        side = 'home' if i == 0 else 'away'
        players = []
        for p in r.get('roster', []):
            ath = p.get('athlete', {})
            pos = p.get('position', {})
            player = {
                'name': ath.get('displayName', ''),
                'shirt': str(p.get('jersey', '')),
                'position': pos.get('abbreviation', '') if isinstance(pos, dict) else '',
                'is_starter': p.get('starter', False),
            }
            players.append(player)

        starters = [p for p in players if p.get('is_starter')]
        subs = [p for p in players if not p.get('is_starter')]
        result[side] = starters + subs

    return result
