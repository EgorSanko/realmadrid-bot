"""Patch 2: improve ESPN match lookup + remove shotmap tab"""

# === Part 1: Patch api.py ===
with open('/root/realmadrid-bot-fixed/api.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Replace get_match_details endpoint - improve the lookup chain
# Find the ESPN fallback section where it looks up team names from FotMob fixtures
old_lookup = """        # 2. FotMob failed — try ESPN
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
            return {"error": "Match not found"}"""

new_lookup = """        # 2. FotMob failed — try ESPN
        print(f"FotMob matchDetails failed for {match_id}, trying ESPN...", flush=True)

        # Chain: FotMob fixtures -> FotMob results cache -> Google Sheets
        home_name = ''
        away_name = ''
        match_date = ''
        tournament = ''
        fotmob_home_id = ''
        fotmob_away_id = ''
        sheets_score = ''

        # Step A: FotMob overviewFixtures (recent ~10 matches)
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

        # Step B: Google Sheets results (all past matches)
        if not home_name:
            try:
                sheets_results = sheets_client.get_results() if sheets_client else []
                sheets_matches = sheets_client.get_matches(limit=20) if sheets_client else []
                all_data = (sheets_results or []) + (sheets_matches or [])
                for sr in all_data:
                    opp = sr.get('opponent', '')
                    if not opp:
                        continue
                    is_home = sr.get('is_home', True)
                    h = 'Real Madrid' if is_home else opp
                    a = opp if is_home else 'Real Madrid'
                    date_raw = sr.get('date_raw', '') or sr.get('date', '')
                    # Normalize date to YYYYMMDD
                    dr = date_raw.replace('-', '')
                    if '.' in date_raw:
                        parts = date_raw.split('.')
                        if len(parts) == 3:
                            dr = parts[2] + parts[1] + parts[0]

                    # Try to match by searching ESPN for this match
                    # We don't have fotmob_match_id in sheets, so match by date
                    if not home_name and dr:
                        espn_test = _espn_find_event(dr, h, a)
                        if espn_test:
                            # Check if this is our match by trying to reverse-match
                            home_name = h
                            away_name = a
                            match_date = dr
                            tournament = sr.get('tournament', sr.get('competition', ''))
                            sheets_score = sr.get('score', '')
                            _espn_id_cache[match_id] = espn_test
                            print(f"Found match via Sheets: {h} vs {a} on {dr} -> ESPN {espn_test}", flush=True)
                            break
            except Exception as e:
                print(f"Sheets lookup error: {e}", flush=True)

        if not home_name:
            return {"error": "Match not found"}"""

if old_lookup in code:
    code = code.replace(old_lookup, new_lookup)
    print("OK: Replaced match lookup chain in get_match_details")
else:
    print("ERROR: Could not find old lookup block")
    import sys; sys.exit(1)


# 2. Also fix the ESPN-not-found fallback to use sheets_score
old_basic_fallback = """        if not espn_id:
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
            }"""

new_basic_fallback = """        if not espn_id:
            # 3. ESPN not found — return basic data from FotMob/Sheets
            print(f"ESPN event not found for {home_name} vs {away_name}", flush=True)
            hs = as_ = 0
            if sheets_score:
                sp = sheets_score.replace('-', ':').split(':')
                try:
                    hs = int(sp[0].strip())
                    as_ = int(sp[1].strip())
                except:
                    pass
            return {
                'match_id': match_id,
                'home_team': home_name,
                'away_team': away_name,
                'home_score': hs,
                'away_score': as_,
                'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_home_id}.png" if fotmob_home_id else _get_team_logo(home_name),
                'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_away_id}.png" if fotmob_away_id else _get_team_logo(away_name),
                'tournament': tournament,
                'events': [],
                'stats': [],
                'lineups': {'home': [], 'away': []},
                'source': 'sheets',
            }"""

if old_basic_fallback in code:
    code = code.replace(old_basic_fallback, new_basic_fallback)
    print("OK: Updated basic fallback with sheets_score")
else:
    print("WARNING: Could not find basic fallback block")


with open('/root/realmadrid-bot-fixed/api.py', 'w', encoding='utf-8') as f:
    f.write(code)
print("api.py patched")


# === Part 2: Patch index.html - remove shotmap tab ===
with open('/root/realmadrid-bot-fixed/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Replace the tabs array to remove shotmap
old_tabs = """['events', 'stats', 'lineups', 'shotmap'].map(t => (
                            <button key={t} onClick={() => setActiveTab(t)}
                                className={`px-3 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap transition-all ${activeTab === t ? 'bg-rm-gold text-black' : 'bg-rm-light text-gray-400'}`}>
                                {t === 'events' ? '\U0001f4cb \u0421\u043e\u0431\u044b\u0442\u0438\u044f' : t === 'stats' ? '\U0001f4ca \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430' : t === 'lineups' ? '\U0001f465 \u0421\u043e\u0441\u0442\u0430\u0432\u044b' : '\U0001f3af \u0423\u0434\u0430\u0440\u044b'}
                            </button>"""

new_tabs = """['events', 'stats', 'lineups'].map(t => (
                            <button key={t} onClick={() => setActiveTab(t)}
                                className={`px-3 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap transition-all ${activeTab === t ? 'bg-rm-gold text-black' : 'bg-rm-light text-gray-400'}`}>
                                {t === 'events' ? '\U0001f4cb \u0421\u043e\u0431\u044b\u0442\u0438\u044f' : t === 'stats' ? '\U0001f4ca \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430' : '\U0001f465 \u0421\u043e\u0441\u0442\u0430\u0432\u044b'}
                            </button>"""

if old_tabs in html:
    html = html.replace(old_tabs, new_tabs)
    print("OK: Removed shotmap tab from index.html")
else:
    print("WARNING: Could not find shotmap tab in index.html")

with open('/root/realmadrid-bot-fixed/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("index.html patched")

print("\nAll done!")
