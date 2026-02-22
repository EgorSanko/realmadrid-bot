"""Patch api.py: replace FotMob matchDetails with ESPN API fallback"""
import sys

with open('/root/realmadrid-bot-fixed/api.py', 'r', encoding='utf-8') as f:
    code = f.read()

# ============================================================
# 1. Add ESPN helper functions AFTER _fotmob_headers block
# ============================================================

espn_block = r'''

# ============ ESPN API (fallback for FotMob matchDetails) ============
ESPN_API = "http://site.api.espn.com/apis/site/v2/sports/soccer"
_ESPN_LEAGUES = ['esp.1', 'uefa.champions', 'uefa.europa', 'eng.1', 'ger.1', 'ita.1', 'fra.1', 'uefa.europa.conf']
_espn_id_cache = {}  # {fotmob_match_id: espn_event_id}
_espn_summary_cache = {}  # {espn_event_id: {'data': ..., 'time': ...}}
_ESPN_CACHE_TTL = 300  # 5 min

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


def _espn_get_summary(espn_event_id: str, league: str = None) -> dict:
    """Get ESPN match summary. Try all leagues if league not specified."""
    if not espn_event_id:
        return {}

    now = _time.time()
    cached = _espn_summary_cache.get(espn_event_id)
    if cached and (now - cached['time']) < _ESPN_CACHE_TTL:
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
    """Parse ESPN keyEvents into frontend-compatible format."""
    events = []
    if not summary:
        return events

    header = summary.get('header', {})
    h_comps = header.get('competitions', [{}])[0].get('competitors', [])
    home_team_id = ''
    for c in h_comps:
        if c.get('homeAway') == 'home':
            home_team_id = c.get('id', '')
            break

    for ke in summary.get('keyEvents', []):
        ev_type_raw = ke.get('type', {}).get('type', '')
        clock = ke.get('clock', {}).get('displayValue', '')
        minute = 0
        if clock:
            clean = clock.replace("'", '').replace("+", " ").strip()
            try:
                minute = int(clean.split()[0])
            except:
                pass

        if 'goal' in ev_type_raw or 'penalty---scored' in ev_type_raw:
            ev_type = 'Goal'
        elif 'yellow' in ev_type_raw:
            ev_type = 'YellowCard'
        elif 'red' in ev_type_raw:
            ev_type = 'RedCard'
        elif 'substitution' in ev_type_raw:
            ev_type = 'Substitution'
        elif ev_type_raw in ('kickoff', 'end-of-half', 'end', 'halftime'):
            continue
        else:
            continue

        team_data = ke.get('team', {})
        team_id = str(team_data.get('id', ''))
        is_home = (team_id == home_team_id) if team_id else True

        participants = ke.get('participants', [])
        player_name = ''
        if participants:
            player_name = participants[0].get('athlete', {}).get('displayName', '')

        assist = ''
        if len(participants) > 1:
            assist = participants[1].get('athlete', {}).get('displayName', '')

        short_text = ke.get('shortText', '')

        ev = {
            'minute': minute,
            'type': ev_type,
            'player': player_name,
            'is_home': is_home,
            'text': short_text,
        }
        if assist:
            ev['assist'] = assist
        if 'penalty' in ev_type_raw:
            ev['is_penalty'] = True
        if 'own-goal' in ev_type_raw:
            ev['is_own_goal'] = True

        events.append(ev)

    events.sort(key=lambda x: x.get('minute', 0))
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

'''

# Insert ESPN block before "# === TEAM LOGO CACHE ==="
marker = '# === TEAM LOGO CACHE ==='
if marker in code:
    code = code.replace(marker, espn_block + '\n' + marker)
    print("OK: Inserted ESPN helper functions")
else:
    print("ERROR: Could not find insertion marker")
    sys.exit(1)


# ============================================================
# 2. Replace /api/match/details/{match_id} endpoint
# ============================================================

# Find the endpoint by its decorator+function signature and replace up to the next @app or def at module level
import re

# Match from @app.get("/api/match/details/{match_id}") to next top-level definition
pattern = r'(@app\.get\("/api/match/details/\{match_id\}"\)\nasync def get_match_details\(match_id: int\):.*?)(\n(?:@app\.|_yt_cache|class ))'
m = re.search(pattern, code, re.DOTALL)
if m:
    old_endpoint = m.group(1)
    next_thing = m.group(2)

    new_endpoint = '''@app.get("/api/match/details/{match_id}")
async def get_match_details(match_id: int):
    """Детализация матча: FotMob -> ESPN fallback -> basic fallback"""
    try:
        # 1. Try FotMob first (may still work for some requests)
        md = _get_fotmob_match(match_id)
        if md:
            header = md.get('header', {})
            teams = header.get('teams', [])
            general = md.get('general', {})
            content = md.get('content', {})

            home_t = teams[0] if len(teams) > 0 else {}
            away_t = teams[1] if len(teams) > 1 else {}

            events = _parse_fotmob_events(md)
            stats = _parse_fotmob_match_stats(md)
            shotmap = _parse_fotmob_shotmap(md)
            momentum = _parse_fotmob_momentum(md)
            lineups = _parse_fotmob_lineups(md)

            man_of_match = None
            mf = content.get('matchFacts', {})
            motm = mf.get('playerOfTheMatch', {})
            if motm:
                man_of_match = {
                    'name': motm.get('name', {}).get('fullName', motm.get('name', '')),
                    'rating': motm.get('rating', {}).get('num', ''),
                    'team': motm.get('teamName', ''),
                }

            highlight_url = _find_youtube_highlight(home_t.get('name', ''), away_t.get('name', ''))

            return {
                'match_id': match_id,
                'home_team': home_t.get('name', ''),
                'away_team': away_t.get('name', ''),
                'home_score': home_t.get('score', 0) or 0,
                'away_score': away_t.get('score', 0) or 0,
                'home_id': home_t.get('id', ''),
                'away_id': away_t.get('id', ''),
                'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{home_t['id']}.png" if home_t.get('id') else '',
                'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{away_t['id']}.png" if away_t.get('id') else '',
                'tournament': general.get('leagueName', ''),
                'round': general.get('leagueRoundName', ''),
                'finished': general.get('finished', False),
                'started': general.get('started', False),
                'events': events,
                'stats': stats,
                'shotmap': shotmap,
                'momentum': momentum,
                'lineups': lineups,
                'man_of_match': man_of_match,
                'highlight_url': highlight_url,
                'source': 'fotmob',
            }

        # 2. FotMob failed — try ESPN
        print(f"FotMob matchDetails failed for {match_id}, trying ESPN...", flush=True)

        # Get team names from FotMob overviewFixtures (still works)
        home_name = ''
        away_name = ''
        match_date = ''
        tournament = ''
        fotmob_home_id = ''
        fotmob_away_id = ''
        try:
            team_data = _get_fotmob_team(FOTMOB_RM_ID)
            if team_data:
                ovf = team_data.get('overview', {}).get('overviewFixtures', [])
                for f in ovf:
                    if f.get('id') == match_id:
                        home_info = f.get('home', {})
                        away_info = f.get('away', {})
                        home_name = home_info.get('name', '')
                        away_name = away_info.get('name', '')
                        fotmob_home_id = home_info.get('id', '')
                        fotmob_away_id = away_info.get('id', '')
                        ts = f.get('status', {}).get('utcTime', '')
                        if ts:
                            match_date = ts[:10].replace('-', '')
                        tourn = f.get('tournament')
                        tournament = tourn.get('name', '') if isinstance(tourn, dict) else ''
                        break
        except Exception as e:
            print(f"FotMob fixtures lookup error: {e}", flush=True)

        if not home_name:
            return {"error": "Match not found"}

        # Find ESPN event
        espn_id = _espn_id_cache.get(match_id, '')
        if not espn_id and match_date:
            espn_id = _espn_find_event(match_date, home_name, away_name)
            if espn_id:
                _espn_id_cache[match_id] = espn_id

        if not espn_id:
            # 3. ESPN not found — return basic data from FotMob fixtures
            print(f"ESPN event not found for {home_name} vs {away_name}", flush=True)
            return {
                'match_id': match_id,
                'home_team': home_name,
                'away_team': away_name,
                'home_score': 0,
                'away_score': 0,
                'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_home_id}.png" if fotmob_home_id else _get_team_logo(home_name),
                'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_away_id}.png" if fotmob_away_id else _get_team_logo(away_name),
                'tournament': tournament,
                'events': [],
                'stats': [],
                'lineups': {'home': [], 'away': []},
                'source': 'basic',
            }

        # Get ESPN summary
        summary = _espn_get_summary(espn_id)
        if not summary:
            return {"error": "ESPN data unavailable"}

        # Parse ESPN data
        h_comps = summary.get('header', {}).get('competitions', [{}])[0]
        competitors = h_comps.get('competitors', [])
        espn_home = {}
        espn_away = {}
        for c in competitors:
            if c.get('homeAway') == 'home':
                espn_home = c
            else:
                espn_away = c

        espn_home_team = espn_home.get('team', {})
        espn_away_team = espn_away.get('team', {})

        home_logo = ''
        away_logo = ''
        if fotmob_home_id:
            home_logo = f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_home_id}.png"
        elif espn_home_team.get('logos'):
            home_logo = espn_home_team['logos'][0].get('href', '')
        if fotmob_away_id:
            away_logo = f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_away_id}.png"
        elif espn_away_team.get('logos'):
            away_logo = espn_away_team['logos'][0].get('href', '')

        events = _espn_parse_events(summary)
        stats = _espn_parse_stats(summary)
        lineups = _espn_parse_lineups(summary)

        status = h_comps.get('status', {}).get('type', {})
        finished = status.get('completed', False)
        started = status.get('name', '') != 'STATUS_SCHEDULED'

        highlight_url = _find_youtube_highlight(home_name or espn_home_team.get('displayName', ''), away_name or espn_away_team.get('displayName', ''))

        print(f"ESPN match details OK: {espn_id} -> {home_name} vs {away_name}, events={len(events)}, stats={len(stats)}", flush=True)

        return {
            'match_id': match_id,
            'espn_id': espn_id,
            'home_team': home_name or espn_home_team.get('displayName', ''),
            'away_team': away_name or espn_away_team.get('displayName', ''),
            'home_score': int(espn_home.get('score', 0) or 0),
            'away_score': int(espn_away.get('score', 0) or 0),
            'home_id': str(fotmob_home_id),
            'away_id': str(fotmob_away_id),
            'home_logo': home_logo,
            'away_logo': away_logo,
            'tournament': tournament or summary.get('header', {}).get('league', {}).get('name', ''),
            'finished': finished,
            'started': started,
            'events': events,
            'stats': stats,
            'shotmap': [],
            'momentum': [],
            'lineups': lineups,
            'man_of_match': None,
            'highlight_url': highlight_url,
            'source': 'espn',
        }
    except Exception as e:
        print(f"Match details error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {"error": str(e)}
'''

    code = code[:m.start()] + new_endpoint + next_thing + code[m.end():]
    print("OK: Replaced /api/match/details endpoint")
else:
    print("ERROR: Could not find /api/match/details endpoint")
    sys.exit(1)


# ============================================================
# 3. Replace FotMob matchDetails in get_fotmob_live_match
# ============================================================

old_live = """        # 3. \u041f\u043e\u043b\u0443\u0447\u0438\u0442\u044c matchDetails
        match_data = _get_fotmob_match(match_id)
        if not match_data:
            return {'is_live': False}

        # 4. \u041f\u0430\u0440\u0441\u0438\u043c \u0432\u0441\u0451
        result = _parse_fotmob_live_match(match_data, match_id)"""

new_live = """        # 3. \u041f\u043e\u043b\u0443\u0447\u0438\u0442\u044c matchDetails (FotMob \u2192 ESPN fallback)
        match_data = _get_fotmob_match(match_id)
        if match_data:
            # 4. \u041f\u0430\u0440\u0441\u0438\u043c FotMob
            result = _parse_fotmob_live_match(match_data, match_id)
        else:
            # FotMob matchDetails blocked \u2014 ESPN fallback for live
            print(f"FotMob live matchDetails blocked, trying ESPN for {match_id}...", flush=True)
            home_name = ''
            away_name = ''
            fotmob_home_id = ''
            fotmob_away_id = ''
            for f in ov_fixtures:
                if f.get('id') == match_id:
                    home_name = f.get('home', {}).get('name', '')
                    away_name = f.get('away', {}).get('name', '')
                    fotmob_home_id = f.get('home', {}).get('id', '')
                    fotmob_away_id = f.get('away', {}).get('id', '')
                    break

            import datetime as _dt
            today = _dt.datetime.utcnow().strftime('%Y%m%d')
            espn_id = _espn_find_event(today, home_name, away_name) if home_name else ''
            summary = _espn_get_summary(espn_id) if espn_id else {}

            if summary:
                h_comps = summary.get('header', {}).get('competitions', [{}])[0]
                competitors = h_comps.get('competitors', [])
                espn_home = {}
                espn_away = {}
                for c in competitors:
                    if c.get('homeAway') == 'home':
                        espn_home = c
                    else:
                        espn_away = c

                espn_minute_raw = h_comps.get('status', {}).get('displayClock', '')
                espn_minute = espn_minute_raw.replace("'", '').strip() + "'" if espn_minute_raw else ''

                result = {
                    'is_live': True,
                    'match_id': match_id,
                    'home_team': home_name or espn_home.get('team', {}).get('displayName', ''),
                    'away_team': away_name or espn_away.get('team', {}).get('displayName', ''),
                    'home_score': int(espn_home.get('score', 0) or 0),
                    'away_score': int(espn_away.get('score', 0) or 0),
                    'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_home_id}.png" if fotmob_home_id else '',
                    'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_away_id}.png" if fotmob_away_id else '',
                    'minute': espn_minute,
                    'tournament': '',
                    'incidents': _espn_parse_events(summary),
                    'stats': _espn_parse_stats(summary),
                    'momentum': [],
                    'shotmap': [],
                    'lineups': _espn_parse_lineups(summary),
                    'bets_suspended': False,
                    'source': 'espn',
                }
            else:
                return {'is_live': False}"""

if old_live in code:
    code = code.replace(old_live, new_live)
    print("OK: Replaced live match matchDetails with ESPN fallback")
else:
    print("WARNING: Could not find live match matchDetails block (may already be replaced)")


# ============================================================
# 4. Replace H2H in analytics with ESPN fallback
# ============================================================

old_h2h = """        # 5. H2H \u0438\u0437 FotMob (\u0435\u0441\u043b\u0438 \u0435\u0441\u0442\u044c match_id)
        h2h = []
        if match_id:
            match_details = _get_fotmob_match(match_id)
            if match_details:
                h2h = _parse_fotmob_h2h(match_details)"""

new_h2h = """        # 5. H2H \u0438\u0437 FotMob (\u0435\u0441\u043b\u0438 \u0435\u0441\u0442\u044c match_id) + ESPN fallback
        h2h = []
        if match_id:
            match_details = _get_fotmob_match(match_id)
            if match_details:
                h2h = _parse_fotmob_h2h(match_details)

            # ESPN H2H fallback
            if not h2h and opp_name:
                try:
                    import datetime as _dt
                    today = _dt.datetime.utcnow().strftime('%Y%m%d')
                    espn_id = _espn_id_cache.get(match_id, '')
                    if not espn_id:
                        h = 'Real Madrid' if is_home else opp_name
                        a = opp_name if is_home else 'Real Madrid'
                        espn_id = _espn_find_event(today, h, a)
                    if espn_id:
                        summary = _espn_get_summary(espn_id)
                        if summary:
                            for g in summary.get('headToHeadGames', [])[:10]:
                                g_comps = g.get('competitions', [{}])[0]
                                g_teams = g_comps.get('competitors', [])
                                g_home = g_away = {}
                                for gt in g_teams:
                                    if gt.get('homeAway') == 'home':
                                        g_home = gt
                                    else:
                                        g_away = gt
                                g_date = g.get('date', '')[:10]
                                try:
                                    d = _dt.datetime.strptime(g_date, '%Y-%m-%d')
                                    g_date = d.strftime('%d.%m.%y')
                                except:
                                    pass
                                h2h.append({
                                    'home_team': g_home.get('team', {}).get('displayName', ''),
                                    'away_team': g_away.get('team', {}).get('displayName', ''),
                                    'score': str(g_home.get('score', '0')) + ':' + str(g_away.get('score', '0')),
                                    'date': g_date,
                                    'tournament': ''
                                })
                except Exception as e:
                    print(f"ESPN H2H fallback error: {e}", flush=True)"""

if old_h2h in code:
    code = code.replace(old_h2h, new_h2h)
    print("OK: Replaced H2H with ESPN fallback")
else:
    print("WARNING: Could not find H2H block")


# ============================================================
# 5. Update debug endpoint matchDetails note
# ============================================================

old_debug = """            result['h2h_fetch_status'] = mr.status_code
            if mr.status_code == 200:"""

new_debug = """            result['h2h_fetch_status'] = mr.status_code
            result['espn_fallback_available'] = True
            if mr.status_code == 200:"""

if old_debug in code:
    code = code.replace(old_debug, new_debug, 1)
    print("OK: Updated debug endpoint")
else:
    print("WARNING: Could not find debug block")


# ============================================================
# Write result
# ============================================================
with open('/root/realmadrid-bot-fixed/api.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("\nDone! api.py patched successfully.")
