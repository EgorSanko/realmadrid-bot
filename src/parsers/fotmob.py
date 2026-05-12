"""src/parsers/fotmob.py — pure FotMob parsers (no HTTP, no caches).

10 stateless functions that take FotMob API dict input and return parsed data.
Used by routes/match.py, routes/debug.py, routes/live.py via lazy imports
re-exported from api.py for backward compat.

HTTP wrappers, caches (_fotmob_*_cache), team helpers (_register_team,
_normalize_team_name, _get_team_logo), sheets fallback wiring — all STAY in api.py
because they need access to `sheets_client` (circular import otherwise).

Parsers exported:
  _parse_fotmob_form        — team form from overview.teamForm (W/L/D + scores)
  _parse_fotmob_h2h         — head-to-head from match content.h2h
  _find_next_fotmob_match   — next fixture from team_data.fixtures
  _parse_fotmob_match_stats — match stats (possession, shots, etc.)
  _parse_fotmob_lineups     — starting XI with ratings + formation
  _parse_fotmob_live_match  — live match state (score + minute + events)
  _parse_fotmob_events      — goals/cards/subs from incidents
  _parse_fotmob_stats       — alias for _parse_fotmob_match_stats
  _parse_fotmob_momentum    — momentum chart points
  _parse_fotmob_shotmap     — shotmap with xG
"""
import re
import time as _time
import requests
import json
import os
import traceback
from typing import List, Dict

# Constants used by parsers (mirrored from api.py for self-containment)
FOTMOB_RM_ID = 8633  # Real Madrid team ID on FotMob


def _parse_fotmob_form(team_data: dict) -> list:
    """Парсим форму команды из FotMob team data"""
    form = []
    try:
        team_id = team_data.get('details', {}).get('id', FOTMOB_RM_ID)
        team_name = team_data.get('details', {}).get('name', 'Real Madrid')

        # Пробуем несколько путей к матчам
        last_matches = []
        form_source = ''

        # Path 1: overview.teamForm (best — has resultString, tooltipText with scores)
        overview = team_data.get('overview', {})
        team_form = overview.get('teamForm', [])
        if isinstance(team_form, list) and team_form:
            # teamForm has different structure, parse directly
            for tf in team_form[:10]:
                tt = tf.get('tooltipText', {})
                home_id = tf.get('home', {}).get('id', 0)
                is_our = tf.get('home', {}).get('isOurTeam', False) or home_id == team_id

                hs = tt.get('homeScore', 0) or 0
                as_ = tt.get('awayScore', 0) or 0
                gf = hs if is_our else as_
                ga = as_ if is_our else hs
                opp_name = tt.get('awayTeam', '') if is_our else tt.get('homeTeam', '')

                res = tf.get('resultString', '')
                if not res:
                    if gf > ga: res = 'W'
                    elif gf < ga: res = 'L'
                    else: res = 'D'

                ts = tf.get('date', {}).get('utcTime', '') if isinstance(tf.get('date'), dict) else ''
                date_str = ''
                if ts:
                    try:
                        dt = datetime.strptime(str(ts)[:10], '%Y-%m-%d')
                        date_str = dt.strftime('%d.%m')
                    except:
                        date_str = str(ts)[:10]

                form.append({
                    'opponent': opp_name,
                    'goals_for': int(gf),
                    'goals_against': int(ga),
                    'result': res,
                    'is_home': is_our,
                    'score': f"{int(hs)}:{int(as_)}",
                    'date': date_str,
                    'tournament': tf.get('tournamentName', '')
                })
            print(f"FotMob form: {len(form)} matches from teamForm", flush=True)
            return list(reversed(form))  # newest first

        # Path 2: overview.overviewFixtures (finished only, reverse chronological)
        ov_fixtures = overview.get('overviewFixtures', [])
        if isinstance(ov_fixtures, list):
            finished_ov = [f for f in ov_fixtures if f.get('status', {}).get('finished')]
            if finished_ov:
                last_matches = list(reversed(finished_ov))
                form_source = 'overviewFixtures'
                print(f"FotMob form: found {len(last_matches)} via overviewFixtures", flush=True)

        # Path 3: overview.lastXMatches / lastMatches
        if not last_matches:
            for key in ['lastXMatches', 'lastMatches']:
                lm = overview.get(key)
                if lm:
                    if isinstance(lm, dict):
                        last_matches = lm.get('lastMatchesRaw', []) or lm.get('matches', []) or lm.get('data', [])
                    elif isinstance(lm, list):
                        last_matches = lm
                    if last_matches:
                        form_source = key
                        print(f"FotMob form: found {len(last_matches)} via overview.{key}", flush=True)
                        break

        # Path 2: fixtures.allFixtures.fixtures (finished only)
        if not last_matches:
            fixtures = team_data.get('fixtures', {})
            all_fix = fixtures.get('allFixtures', {})
            if isinstance(all_fix, dict):
                fix_list = all_fix.get('fixtures', [])
            elif isinstance(all_fix, list):
                fix_list = all_fix
            else:
                fix_list = []
            finished = [f for f in fix_list if f.get('status', {}).get('finished')]
            if finished:
                last_matches = finished[-10:]
                print(f"FotMob form: found {len(last_matches)} via fixtures (finished)", flush=True)

        # Path 3: history.historicalTableData or recentMatches
        if not last_matches:
            for key in ['recentMatches', 'historicMatches']:
                rm = team_data.get(key, [])
                if rm:
                    last_matches = rm[:10]
                    print(f"FotMob form: found {len(last_matches)} via {key}", flush=True)
                    break

        if not last_matches:
            print(f"FotMob form: no matches found. Keys: {list(team_data.keys())}", flush=True)
            if overview:
                print(f"FotMob overview keys: {list(overview.keys())}", flush=True)
            return []

        for m in last_matches[:10]:
            home = m.get('home', {})
            away = m.get('away', {})
            home_name = home.get('name', home.get('shortName', ''))
            away_name = away.get('name', away.get('shortName', ''))

            # Try multiple score paths
            home_score = home.get('score')
            away_score = away.get('score')

            # Fallback: status.scoreStr "0 - 2"
            if home_score is None or away_score is None:
                score_str = m.get('status', {}).get('scoreStr', '')
                if ' - ' in score_str:
                    parts = score_str.split(' - ')
                    try:
                        home_score = int(parts[0].strip())
                        away_score = int(parts[1].strip())
                    except:
                        pass

            if home_score is None: home_score = 0
            if away_score is None: away_score = 0

            is_home = home.get('id') == team_id or team_name.lower() in home_name.lower()
            gf = int(home_score) if is_home else int(away_score)
            ga = int(away_score) if is_home else int(home_score)
            opp = away_name if is_home else home_name

            if gf > ga: res = 'W'
            elif gf < ga: res = 'L'
            else: res = 'D'

            # Дата
            ts = m.get('status', {}).get('utcTime', '') or m.get('timeTS', '') or ''
            date_str = ''
            if ts:
                try:
                    dt = datetime.strptime(str(ts)[:10], '%Y-%m-%d')
                    date_str = dt.strftime('%d.%m')
                except:
                    date_str = str(ts)[:10]

            tournament = ''
            tourn = m.get('tournament') or m.get('league') or {}
            if isinstance(tourn, dict):
                tournament = tourn.get('name', '')

            form.append({
                'opponent': opp,
                'goals_for': gf,
                'goals_against': ga,
                'result': res,
                'is_home': is_home,
                'score': f"{int(home_score)}:{int(away_score)}",
                'date': date_str,
                'tournament': tournament
            })
    except Exception as e:
        print(f"FotMob form parse error: {e}", flush=True)
        import traceback
        traceback.print_exc()
    return form


def _parse_fotmob_h2h(match_data: dict) -> list:
    """Парсим H2H из FotMob match details
    Структура: content.h2h.matches[] -> status.scoreStr = "1 - 2", home.name, away.name
    """
    h2h = []
    try:
        content = match_data.get('content', {})
        h2h_data = content.get('h2h', {})
        meetings = h2h_data.get('matches', [])

        if not meetings:
            print(f"FotMob H2H: no matches. Keys: {list(h2h_data.keys())}", flush=True)
            return []

        print(f"FotMob H2H: found {len(meetings)} meetings", flush=True)

        for m in meetings[:10]:
            home = m.get('home', {})
            away = m.get('away', {})
            status = m.get('status', {})

            # Score is in status.scoreStr like "1 - 2"
            score_str = status.get('scoreStr', '')
            hs, as_ = 0, 0
            if score_str and ' - ' in score_str:
                parts = score_str.split(' - ')
                try:
                    hs = int(parts[0].strip())
                    as_ = int(parts[1].strip())
                except (ValueError, IndexError):
                    pass

            # Date
            ts = status.get('utcTime', '') or m.get('time', {}).get('utcTime', '')
            date_str = ''
            if ts:
                try:
                    dt = datetime.strptime(str(ts)[:10], '%Y-%m-%d')
                    date_str = dt.strftime('%d.%m.%y')
                except:
                    date_str = str(ts)[:10]

            league = m.get('league', {})
            tournament = league.get('name', '') if isinstance(league, dict) else ''

            h2h.append({
                'home_team': home.get('name', ''),
                'away_team': away.get('name', ''),
                'score': f"{hs}:{as_}",
                'date': date_str,
                'tournament': tournament
            })
    except Exception as e:
        print(f"FotMob H2H parse error: {e}", flush=True)
    return h2h


def _find_next_fotmob_match(team_data: dict) -> dict:
    """Найти следующий матч из FotMob team data"""
    try:
        fixtures = team_data.get('fixtures', {})
        all_fix = fixtures.get('allFixtures', {})

        # Path 1: nextMatch
        next_match = None
        if isinstance(all_fix, dict):
            next_match = all_fix.get('nextMatch')

        if not next_match:
            # Path 2: overview.nextMatch
            next_match = team_data.get('overview', {}).get('nextMatch')

        if next_match:
            home = next_match.get('home', {})
            away = next_match.get('away', {})
            is_home = home.get('id') == FOTMOB_RM_ID or 'Real Madrid' in home.get('name', '')
            opp = away.get('name', '') if is_home else home.get('name', '')
            tourn = next_match.get('tournament') or next_match.get('league') or {}
            print(f"FotMob next match: {opp}, id={next_match.get('id')}", flush=True)
            return {
                'match_id': next_match.get('id'),
                'opponent': opp,
                'opponent_id': away.get('id') if is_home else home.get('id'),
                'is_home': is_home,
                'tournament': tourn.get('name', '') if isinstance(tourn, dict) else ''
            }

        # Path 3: ищем в списке fixtures незавершённый
        fix_list = all_fix.get('fixtures', []) if isinstance(all_fix, dict) else (all_fix if isinstance(all_fix, list) else [])
        for f in fix_list:
            if not f.get('status', {}).get('finished', False):
                home = f.get('home', {})
                away = f.get('away', {})
                is_home = home.get('id') == FOTMOB_RM_ID or 'Real Madrid' in home.get('name', '')
                opp = away.get('name', '') if is_home else home.get('name', '')
                tourn = f.get('tournament') or f.get('league') or {}
                return {
                    'match_id': f.get('id'),
                    'opponent': opp,
                    'opponent_id': away.get('id') if is_home else home.get('id'),
                    'is_home': is_home,
                    'tournament': tourn.get('name', '') if isinstance(tourn, dict) else ''
                }

        print(f"FotMob: no next match found. fixtures keys: {list(fixtures.keys())}", flush=True)
    except Exception as e:
        print(f"FotMob next match error: {e}", flush=True)
    return {}

# /api/match/analytics/debug moved to src/routes/debug.py
# /api/match/analytics moved to src/routes/match.py


_match_details_cache = {}  # match_id -> {data, time}
_MATCH_DETAILS_TTL_FINISHED = 3600   # 1h for finished
_MATCH_DETAILS_TTL_LIVE = 30          # 30s for live


def _parse_fotmob_match_stats(md: dict) -> list:
    """Парсим статистику матча — пробуем все возможные структуры FotMob"""
    stats = []
    try:
        content = md.get('content', {})
        stats_data = content.get('stats', {})

        if not stats_data:
            # Try matchFacts fallback
            stats_data = content.get('matchFacts', {}).get('matchStats', {})

        print(f"FotMob stats_data type={type(stats_data).__name__}, keys={list(stats_data.keys()) if isinstance(stats_data, dict) else 'N/A'}", flush=True)

        def to_num(v):
            s = str(v).replace('%', '').replace(',', '.')
            try: return float(s)
            except: return 0

        def parse_sections(sections_list):
            """Parse a list of sections [{title, stats: [{title, stats: [h, a]}]}]"""
            for section in sections_list:
                if not isinstance(section, dict):
                    continue
                section_name = section.get('title', '')
                section_stats = section.get('stats', [])
                if not isinstance(section_stats, list):
                    continue
                for s in section_stats:
                    if not isinstance(s, dict):
                        continue
                    title = s.get('title', s.get('key', ''))
                    stat_arr = s.get('stats', [])
                    if isinstance(stat_arr, list) and len(stat_arr) >= 2:
                        stats.append({
                            'title': title,
                            'section': section_name,
                            'home': stat_arr[0],
                            'away': stat_arr[1],
                            'home_num': to_num(stat_arr[0]),
                            'away_num': to_num(stat_arr[1]),
                        })

        if isinstance(stats_data, dict):
            for key in stats_data:
                val = stats_data[key]
                print(f"  stats key={key}, val_type={type(val).__name__}", flush=True)
                if isinstance(val, list):
                    # Direct sections list
                    parse_sections(val)
                elif isinstance(val, dict):
                    # Nested: {"All": [...], "FirstHalf": [...], ...}
                    print(f"    nested keys={list(val.keys())}", flush=True)
                    if 'All' in val:
                        all_val = val['All']
                        print(f"    All type={type(all_val).__name__}, len={len(all_val) if isinstance(all_val, (list,dict)) else 'N/A'}", flush=True)
                        if isinstance(all_val, list):
                            parse_sections(all_val)
                        elif isinstance(all_val, dict):
                            # Maybe All is itself a dict of sections
                            for ak in all_val:
                                av = all_val[ak]
                                if isinstance(av, list):
                                    parse_sections(av)
                    else:
                        for sub_key in val:
                            sub_val = val[sub_key]
                            if isinstance(sub_val, list):
                                parse_sections(sub_val)
                                break
        elif isinstance(stats_data, list):
            parse_sections(stats_data)

        print(f"FotMob match stats: {len(stats)} parsed (before dedup)", flush=True)

        # Deduplicate by title (keep first occurrence) and filter None values
        seen = set()
        deduped = []
        for s in stats:
            if s['home'] is None or s['away'] is None:
                continue
            key = s['title']
            if key not in seen:
                seen.add(key)
                deduped.append(s)
        stats = deduped
        print(f"FotMob match stats: {len(stats)} after dedup", flush=True)
    except Exception as e:
        print(f"FotMob match stats error: {e}", flush=True)
    return stats


def _parse_fotmob_lineups(md: dict) -> dict:
    """Парсим составы с рейтингами из matchDetails"""
    result = {'home': [], 'away': [], 'home_formation': '', 'away_formation': '', 'home_rating': '', 'away_rating': ''}
    try:
        content = md.get('content', {})
        lineup_data = content.get('lineup', {})

        if not lineup_data:
            return result

        for side_key, out_key in [('homeTeam', 'home'), ('awayTeam', 'away')]:
            side = lineup_data.get(side_key, {})
            if not isinstance(side, dict):
                continue

            result[f'{out_key}_formation'] = side.get('formation', '')
            # Team rating
            team_rating = side.get('rating', '')
            if isinstance(team_rating, dict):
                result[f'{out_key}_rating'] = str(team_rating.get('num', ''))
            else:
                result[f'{out_key}_rating'] = str(team_rating) if team_rating else ''

            starters = side.get('starters', [])
            subs = side.get('subs', [])

            def parse_player(p, is_sub=False):
                if not isinstance(p, dict):
                    return None

                # Name — can be string or dict
                name_data = p.get('name', '')
                if isinstance(name_data, dict):
                    name = name_data.get('fullName', name_data.get('shortName', ''))
                else:
                    name = str(name_data)

                # Rating — can be dict {num: "7.3"}, string, number, or in performance
                rating = ''
                rating_data = p.get('rating', p.get('fantasyScore', ''))
                if isinstance(rating_data, dict):
                    rating = str(rating_data.get('num', ''))
                elif rating_data:
                    rating = str(rating_data)

                # Also check performance.rating
                if not rating:
                    perf = p.get('performance', {})
                    if isinstance(perf, dict):
                        r = perf.get('rating', '')
                        if r:
                            rating = str(r)

                return {
                    'name': name,
                    'number': p.get('shirtNumber', p.get('shirt', p.get('number', ''))),
                    'position': p.get('positionStringShort', p.get('position', p.get('role', ''))),
                    'rating': rating,
                    'is_captain': p.get('isCaptain', False),
                    'substitute': is_sub,
                    'minutes_played': p.get('minutesPlayed', None),
                    'x': p.get('verticalLayout', {}).get('x', None) if isinstance(p.get('verticalLayout'), dict) else None,
                    'y': p.get('verticalLayout', {}).get('y', None) if isinstance(p.get('verticalLayout'), dict) else None,
                    'hx': p.get('horizontalLayout', {}).get('x', None) if isinstance(p.get('horizontalLayout'), dict) else None,
                    'hy': p.get('horizontalLayout', {}).get('y', None) if isinstance(p.get('horizontalLayout'), dict) else None,
                    'image': f"https://images.fotmob.com/image_resources/playerimages/{p['id']}.png" if p.get('id') else None,
                }

            # Starters — can be flat list or nested [[GK], [DEF...], [MID...], [FWD...]]
            for item in starters:
                if isinstance(item, list):
                    for p in item:
                        parsed = parse_player(p, False)
                        if parsed:
                            result[out_key].append(parsed)
                elif isinstance(item, dict):
                    parsed = parse_player(item, False)
                    if parsed:
                        result[out_key].append(parsed)

            # Subs
            for item in subs:
                if isinstance(item, list):
                    for p in item:
                        parsed = parse_player(p, True)
                        if parsed:
                            result[out_key].append(parsed)
                elif isinstance(item, dict):
                    parsed = parse_player(item, True)
                    if parsed:
                        result[out_key].append(parsed)

        print(f"FotMob lineups: home={len(result['home'])}, away={len(result['away'])}", flush=True)
    except Exception as e:
        print(f"FotMob lineups error: {e}", flush=True)
    return result


def _parse_fotmob_live_match(md: dict, match_id: int) -> dict:
    """Парсим matchDetails в live данные"""
    try:
        header = md.get('header', {})
        teams = header.get('teams', [])

        home_team_data = teams[0] if len(teams) > 0 else {}
        away_team_data = teams[1] if len(teams) > 1 else {}

        home_team = home_team_data.get('name', '')
        away_team = away_team_data.get('name', '')
        home_score = home_team_data.get('score', 0) or 0
        away_score = away_team_data.get('score', 0) or 0

        # Minute
        general = md.get('general', {})
        match_status = general.get('matchTimeUTCDate') or ''
        started = general.get('started', False)
        finished = general.get('finished', False)

        # Get minute from header status
        header_status = md.get('header', {}).get('status', {})
        minute = header_status.get('liveTime', {}).get('short', '')
        if not minute:
            minute = header_status.get('reason', {}).get('short', '')

        # Tournament
        tournament = general.get('leagueName', '')

        # Events
        events = _parse_fotmob_events(md)

        # Stats
        stats = _parse_fotmob_stats(md)

        # Momentum
        momentum = _parse_fotmob_momentum(md)

        # Shotmap
        shotmap = _parse_fotmob_shotmap(md)

        # Lineups
        lineups = _parse_fotmob_lineups(md)

        return {
            'is_live': True,
            'match_id': match_id,
            'home_team': home_team,
            'away_team': away_team,
            'home_score': int(home_score),
            'away_score': int(away_score),
            'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{home_team_data.get('id','')}.png" if home_team_data.get('id') else '',
            'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{away_team_data.get('id','')}.png" if away_team_data.get('id') else '',
            'minute': minute,
            'tournament': tournament,
            'incidents': events,
            'stats': stats,
            'momentum': momentum,
            'shotmap': shotmap,
            'lineups': lineups,
            'fotmob_url': f'https://www.fotmob.com/matches/{match_id}',
            'bets_suspended': False,
        }
    except Exception as e:
        print(f"FotMob parse live error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {'is_live': False, 'error': str(e)}


def _parse_fotmob_events(md: dict) -> list:
    """Парсим события из matchDetails (goals, cards, subs)"""
    events = []
    try:
        content = md.get('content', {})
        match_facts = content.get('matchFacts', {})

        # Events in matchFacts.events.events
        events_data = match_facts.get('events', {})
        if isinstance(events_data, dict):
            events_list = events_data.get('events', [])
        elif isinstance(events_data, list):
            events_list = events_data
        else:
            events_list = []

        header_teams = md.get('header', {}).get('teams', [{}, {}])
        home_id = header_teams[0].get('id', 0) if len(header_teams) > 0 else 0

        for ev in events_list:
            ev_type = ev.get('type', '')
            minute = ev.get('time', ev.get('timeStr', 0))
            if isinstance(minute, str):
                minute = minute.replace("'", "").strip()
                try:
                    minute = int(minute.split('+')[0])
                except:
                    minute = 0

            is_home = ev.get('isHome', False)
            # Alternative: check team id
            if 'teamId' in ev:
                is_home = ev['teamId'] == home_id

            if ev_type == 'Goal':
                player = ev.get('nameStr', ev.get('player', {}).get('name', ''))
                assist = ''
                if ev.get('assistStr'):
                    assist = ev['assistStr'].replace('assist by ', '').replace('Assist: ', '')
                elif ev.get('assist', {}).get('name'):
                    assist = ev['assist']['name']

                new_score = ev.get('newScore', [])
                score_str = f"{new_score[0]}-{new_score[1]}" if len(new_score) >= 2 else ''

                events.append({
                    'type': 'goal',
                    'minute': minute,
                    'player': player,
                    'assist': assist or None,
                    'home': is_home,
                    'score': score_str,
                    'own_goal': ev.get('ownGoal', False),
                    'penalty': ev.get('isPenalty', False) or 'pen' in str(ev.get('goalDescription', '')).lower(),
                })
            elif ev_type == 'Card':
                card = ev.get('card', '')
                player = ev.get('nameStr', ev.get('player', {}).get('name', ''))
                card_type = 'yellow'
                if 'Red' in card or 'red' in card:
                    card_type = 'red'
                elif 'Yellow' in card and 'Red' in card:
                    card_type = 'second_yellow'

                events.append({
                    'type': card_type,
                    'minute': minute,
                    'player': player,
                    'home': is_home,
                })
            elif ev_type == 'Substitution':
                swap = ev.get('swap', [])
                player_in = swap[0].get('name', '') if len(swap) > 0 else ev.get('nameStr', '')
                player_out = swap[1].get('name', '') if len(swap) > 1 else ''

                events.append({
                    'type': 'sub',
                    'minute': minute,
                    'player_in': player_in,
                    'player_out': player_out,
                    'home': is_home,
                })
            elif ev_type == 'Half':
                events.append({
                    'type': 'half',
                    'minute': minute,
                    'text': ev.get('nameStr', 'HT'),
                    'home': True,
                })

    except Exception as e:
        print(f"FotMob events parse error: {e}", flush=True)
    return events


def _parse_fotmob_stats(md: dict) -> list:
    """Парсим статистику из matchDetails — same as match_stats"""
    return _parse_fotmob_match_stats(md)


def _parse_fotmob_momentum(md: dict) -> list:
    """Парсим momentum из matchDetails"""
    try:
        content = md.get('content', {})
        momentum = content.get('momentum', {})
        if isinstance(momentum, dict):
            main = momentum.get('main', {})
            data = main.get('data', [])
            if data:
                return data  # [{minute: X, value: Y}, ...]
        elif isinstance(momentum, list):
            return momentum
    except Exception as e:
        print(f"FotMob momentum error: {e}", flush=True)
    return []


def _parse_fotmob_shotmap(md: dict) -> list:
    """Парсим shotmap из matchDetails"""
    shots = []
    try:
        content = md.get('content', {})
        shotmap_data = content.get('shotmap', {})

        if isinstance(shotmap_data, dict):
            shots_list = shotmap_data.get('shots', [])
        elif isinstance(shotmap_data, list):
            shots_list = shotmap_data
        else:
            shots_list = []

        header_teams = md.get('header', {}).get('teams', [{}, {}])
        home_id = header_teams[0].get('id', 0) if len(header_teams) > 0 else 0

        for shot in shots_list:
            is_home = shot.get('teamId', 0) == home_id
            shots.append({
                'x': shot.get('x', 0),
                'y': shot.get('y', 0),
                'xG': shot.get('expectedGoals', 0),
                'result': shot.get('eventType', ''),  # Goal, Miss, AttemptSaved, Blocked
                'player': shot.get('playerName', shot.get('fullName', '')),
                'minute': shot.get('min', 0),
                'home': is_home,
                'on_target': shot.get('isOnTarget', False),
                'blocked': shot.get('isBlocked', False),
            })
    except Exception as e:
        print(f"FotMob shotmap error: {e}", flush=True)
    return shots


# ============ FotMob caches + HTTP wrappers (from Block A) ============
# === ПРЕДМАТЧЕВАЯ АНАЛИТИКА (FotMob + Sheets fallback) ===
FOTMOB_API = "https://www.fotmob.com/api"

def _fetch_fotmob_via_html(path_type: str, entity_id, slug: str = '') -> dict:
    """Fetch FotMob data by scraping __NEXT_DATA__ from HTML pages.
    Falls back to this when API returns 404 (Cloudflare blocking).
    path_type: 'teams', 'leagues', or 'matches'
    """
    import re as _re
    url_map = {
        'teams': f'https://www.fotmob.com/teams/{entity_id}/overview/{slug}',
        'leagues': f'https://www.fotmob.com/leagues/{entity_id}/overview/{slug}',
        'matches': f'https://www.fotmob.com/matches/{entity_id}/matchfacts',
    }
    url = url_map.get(path_type, '')
    if not url:
        return {}
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"FotMob HTML {path_type}/{entity_id}: HTTP {resp.status_code}")
            return {}
        m = _re.search(r'__NEXT_DATA__[^>]*>({.*?})</script>', resp.text)
        if not m:
            print(f"FotMob HTML {path_type}/{entity_id}: no __NEXT_DATA__")
            return {}
        data = json.loads(m.group(1))
        fallback = data.get('props', {}).get('pageProps', {}).get('fallback', {})
        # Key format: "team-8633", "league-87", etc.
        key_prefix = path_type.rstrip('s')  # teams -> team, leagues -> league, matches -> match
        for k, v in fallback.items():
            if k.startswith(f'{key_prefix}-{entity_id}') or k.startswith(f'{key_prefix}fact-{entity_id}'):
                print(f"FotMob HTML {path_type}/{entity_id}: OK ({len(str(v))//1024}KB)")
                return v
        # Try first key
        if fallback:
            first_key = list(fallback.keys())[0]
            v = fallback[first_key]
            print(f"FotMob HTML {path_type}/{entity_id}: OK via key '{first_key}' ({len(str(v))//1024}KB)")
            return v
        return {}
    except Exception as e:
        print(f"FotMob HTML {path_type}/{entity_id} error: {e}")
        return {}
FOTMOB_RM_ID = 8633  # Real Madrid team ID on FotMob

_fotmob_headers = {    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',    'Accept': 'application/json, text/plain, */*',    'Accept-Language': 'en-US,en;q=0.9',    'Referer': 'https://www.fotmob.com/',    'Origin': 'https://www.fotmob.com',    'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',    'sec-ch-ua-mobile': '?0',    'sec-ch-ua-platform': '"Windows"',    'sec-fetch-dest': 'empty',    'sec-fetch-mode': 'cors',    'sec-fetch-site': 'same-origin',}



# === ESPN parser moved to src/parsers/espn.py ===
from src.parsers.espn import (
    ESPN_API, _ESPN_LEAGUES, _espn_id_cache, _espn_summary_cache,
    _ESPN_CACHE_TTL, _ESPN_CACHE_TTL_LIVE,
    _espn_find_event, _espn_get_summary,
    _espn_parse_events, _espn_parse_stats, _espn_parse_lineups,
)

# === TEAM LOGO CACHE ===
_team_logo_map = {
    # Real Madrid
    'real madrid': 8633, 'real madrid cf': 8633,
    # La Liga 2024/25
    'atletico madrid': 9906, 'atlético madrid': 9906, 'atletico de madrid': 9906,
    'atlético de madrid': 9906, 'atletico': 9906,
    'barcelona': 8634, 'fc barcelona': 8634,
    'athletic club': 10368, 'athletic bilbao': 10368, 'athletic': 10368,
    'villarreal': 10205, 'villarreal cf': 10205,
    'real betis': 8603, 'betis': 8603,
    'mallorca': 8661, 'rcd mallorca': 8661,
    'girona': 7732, 'girona fc': 7732,
    'real sociedad': 8560, 'sociedad': 8560,
    'rayo vallecano': 8370, 'rayo': 8370,
    'osasuna': 8371, 'ca osasuna': 8371,
    'celta vigo': 9910, 'celta de vigo': 9910, 'celta': 9910,
    'sevilla': 8302, 'sevilla fc': 8302,
    'getafe': 8305, 'getafe cf': 8305,
    'valencia': 10267, 'valencia cf': 10267,
    'espanyol': 8558, 'rcd espanyol': 8558,
    'alaves': 9866, 'deportivo alaves': 9866, 'deportivo alavés': 9866, 'alavés': 9866,
    'leganes': 7854, 'cd leganes': 7854, 'leganés': 7854, 'cd leganés': 7854,
    'las palmas': 8306, 'ud las palmas': 8306,
    'real valladolid': 10281, 'valladolid': 10281,
    # Champions League
    'liverpool': 8650, 'liverpool fc': 8650,
    'manchester city': 8456, 'man city': 8456,
    'bayern munich': 9823, 'fc bayern münchen': 9823, 'bayern münchen': 9823, 'bayern': 9823,
    'paris saint-germain': 9847, 'psg': 9847, 'paris sg': 9847,
    'inter': 8636, 'inter milan': 8636, 'internazionale': 8636,
    'ac milan': 8564, 'milan': 8564,
    'juventus': 9885, 'juventus fc': 9885,
    'borussia dortmund': 9789, 'dortmund': 9789,
    'arsenal': 9825, 'arsenal fc': 9825,
    'chelsea': 8455, 'chelsea fc': 8455,
    'manchester united': 10260, 'man utd': 10260, 'man united': 10260,
    'tottenham': 8586, 'tottenham hotspur': 8586, 'spurs': 8586,
    'napoli': 9875, 'ssc napoli': 9875,
    'benfica': 9772, 'sl benfica': 9772,
    'porto': 9773, 'fc porto': 9773,
    'sporting cp': 9768, 'sporting lisbon': 9768, 'sporting': 9768,
    'monaco': 9829, 'as monaco': 9829,
    'atalanta': 8524, 'atalanta bc': 8524,
    'roma': 8686, 'as roma': 8686,
    'lazio': 8543, 'ss lazio': 8543,
    'bayer leverkusen': 8178, 'leverkusen': 8178,
    'rb leipzig': 178475, 'leipzig': 178475,
    'lille': 8639, 'losc lille': 8639, 'losc': 8639,
    'brest': 8521, 'stade brestois': 8521,
    'aston villa': 10252, 'villa': 10252,
    'stuttgart': 10269, 'vfb stuttgart': 10269,
    'celtic': 9925, 'celtic fc': 9925,
    'feyenoord': 10235, 'feyenoord rotterdam': 10235,
    'salzburg': 10013, 'rb salzburg': 10013, 'red bull salzburg': 10013,
    'club brugge': 8342, 'brugge': 8342,
    'shakhtar donetsk': 9728, 'shakhtar': 9728,
    'dinamo zagreb': 8572, 'gnk dinamo zagreb': 8572,
    'young boys': 7851, 'bsc young boys': 7851,
    'red star belgrade': 8547, 'crvena zvezda': 8547,
    'sparta prague': 9661, 'sparta praha': 9661,
    'bologna': 9857, 'bologna fc': 9857,
    # Copa del Rey / second division common opponents
    'elche': 10268, 'elche cf': 10268,
    'levante': 8581, 'levante ud': 8581,
    # Russian names (Leon returns names in Russian)
    'реал мадрид': 8633, 'реал': 8633,
    'атлетико мадрид': 9906, 'атлетико де мадрид': 9906, 'атлетико': 9906,
    'барселона': 8634, 'фк барселона': 8634,
    'атлетик бильбао': 10368, 'атлетик': 10368, 'атлетик клуб': 10368,
    'вильярреал': 10205,
    'реал бетис': 8603, 'бетис': 8603,
    'мальорка': 8661,
    'жирона': 7732,
    'реал сосьедад': 8560, 'сосьедад': 8560,
    'райо валлекано': 8370, 'райо': 8370,
    'осасуна': 8371,
    'сельта виго': 9910, 'сельта': 9910,
    'севилья': 8302,
    'хетафе': 8305,
    'валенсия': 10267,
    'эспаньол': 8558,
    'алавес': 9866, 'депортиво алавес': 9866,
    'леганес': 7854,
    'лас пальмас': 8306,
    'реал вальядолид': 10281, 'вальядолид': 10281,
    # CL Russian
    'ливерпуль': 8650,
    'манчестер сити': 8456, 'ман сити': 8456,
    'бавария': 9823, 'бавария мюнхен': 9823,
    'пари сен-жермен': 9847, 'псж': 9847, 'пари сен жермен': 9847,
    'интер': 8636, 'интер милан': 8636,
    'милан': 8564, 'ас милан': 8564,
    'ювентус': 9885,
    'боруссия дортмунд': 9789, 'дортмунд': 9789,
    'арсенал': 9825,
    'челси': 8455,
    'манчестер юнайтед': 10260, 'ман юнайтед': 10260,
    'тоттенхэм': 8586, 'тоттенхем': 8586,
    'наполи': 9875,
    'бенфика': 9772,
    'порту': 9773,
    'спортинг': 9768,
    'монако': 9829,
    'аталанта': 8524,
    'рома': 8686,
    'лацио': 8543,
    'байер леверкузен': 8178, 'леверкузен': 8178,
    'лейпциг': 178475, 'рб лейпциг': 178475,
    'лилль': 8639,
    'брест': 8521,
    'астон вилла': 10252,
    'штутгарт': 10269,
    'селтик': 9925,
    'фейеноорд': 10235,
    'зальцбург': 10013,
    'клуб брюгге': 8342, 'брюгге': 8342,
    'шахтер донецк': 9728, 'шахтер': 9728, 'шахтёр донецк': 9728, 'шахтёр': 9728,
    'эльче': 10268,
    'леванте': 8581,
}  # also auto-populated from FotMob on startup
_fotmob_standings_cache = {'data': None, 'time': 0, 'ttl': 1800}  # 30 min

def _register_team(name: str, team_id):
    """Register team name → FotMob ID mapping"""
    if name and team_id:
        _team_logo_map[name.lower().strip()] = int(team_id)
        # Also register short forms
        parts = name.split()
        if len(parts) > 1:
            for p in parts:
                if len(p) > 3 and p.lower() not in ('city', 'club', 'real', 'athletic', 'united'):
                    _team_logo_map[p.lower()] = int(team_id)

def _normalize_team_name(s: str) -> str:
    """Remove accents and normalize team name for matching"""
    return s.lower().strip().replace('á','a').replace('é','e').replace('í','i').replace('ó','o').replace('ú','u').replace('ä','a').replace('ö','o').replace('ü','u').replace('ñ','n')

def _get_team_logo(name: str) -> str:
    """Get team logo URL by name — smart fuzzy matching"""
    if not name:
        return ''
    key = name.lower().strip()
    key_norm = _normalize_team_name(name)

    # Direct match (with and without accents)
    for lookup in [key, key_norm]:
        tid = _team_logo_map.get(lookup)
        if tid:
            return f"https://images.fotmob.com/image_resources/logo/teamlogo/{tid}.png"

    # Try without common prefixes
    for prefix in ['real ', 'fc ', 'cf ', 'rcd ', 'ud ', 'cd ', 'rc ', 'sd ']:
        for lookup in [key, key_norm]:
            if lookup.startswith(prefix):
                tid = _team_logo_map.get(lookup[len(prefix):])
                if tid:
                    return f"https://images.fotmob.com/image_resources/logo/teamlogo/{tid}.png"

    # Substring match: full name must be contained, prefer longer (more specific) matches
    best_match = None
    best_len = 0
    for k, v in _team_logo_map.items():
        k_norm = _normalize_team_name(k)
        if k_norm in key_norm or key_norm in k_norm:
            if len(k_norm) > best_len:
                best_match = v
                best_len = len(k_norm)
    if best_match:
        return f"https://images.fotmob.com/image_resources/logo/teamlogo/{best_match}.png"

    # Word-level: require >50% of significant words to match
    stop = {'de', 'del', 'la', 'el', 'los', 'las', 'fc', 'cf'}
    key_words = set(w for w in key_norm.split() if len(w) > 2 and w not in stop)
    if key_words:
        best_match = None
        best_score = 0
        for k, v in _team_logo_map.items():
            k_words = set(w for w in _normalize_team_name(k).split() if len(w) > 2 and w not in stop)
            if not k_words:
                continue
            common = key_words & k_words
            score = len(common) / max(len(key_words), len(k_words))
            if score > 0.5 and score > best_score:
                best_match = v
                best_score = score
        if best_match:
            return f"https://images.fotmob.com/image_resources/logo/teamlogo/{best_match}.png"

    return ''
def _get_fotmob_league_standings(league_id: int = 87) -> list:
    """Fetch league standings from FotMob via /_next/data endpoint.
    FotMob deprecated /api/leagues — same pattern as matchDetails fix.
    """
    now = _time.time()
    if _fotmob_standings_cache['data'] and (now - _fotmob_standings_cache['time']) < _fotmob_standings_cache['ttl']:
        return _fotmob_standings_cache['data']
    try:
        bid = _get_fotmob_buildid()
        if not bid:
            print(f"FotMob standings: no buildId, returning stale cache", flush=True)
            return _fotmob_standings_cache.get('data') or []
        url = f"https://www.fotmob.com/_next/data/{bid}/leagues/{league_id}.json"
        r = requests.get(url, headers=_fotmob_headers, timeout=15)
        if r.status_code != 200:
            print(f"FotMob standings: status={r.status_code}", flush=True)
            return _fotmob_standings_cache.get('data') or []
        body = r.json()
        # Path: pageProps.table[0].data.table.all
        pp = body.get('pageProps', {})
        data = pp  # keep variable name for downstream code

        # Debug: log top-level keys and table structure
        print(f"FotMob standings: top keys={list(data.keys())}", flush=True)

        # Parse standings table — handle various FotMob response shapes
        table_data = data.get('table', [])
        print(f"FotMob standings: table type={type(table_data).__name__}, len={len(table_data) if isinstance(table_data, (list,dict)) else 'N/A'}", flush=True)

        rows = []

        def _extract_rows(obj, depth=0):
            """Recursively find the actual rows array"""
            if depth > 6:
                return []
            if isinstance(obj, list):
                if obj and isinstance(obj[0], dict):
                    if 'name' in obj[0] and ('pts' in obj[0] or 'points' in obj[0]):
                        return obj
                    for item in obj:
                        result = _extract_rows(item, depth+1)
                        if result:
                            return result
                return []
            elif isinstance(obj, dict):
                if depth <= 1:
                    print(f"  FotMob standings depth={depth}: keys={list(obj.keys())[:15]}", flush=True)
                for key in ['all', 'table', 'data', 'rows', 'lines']:
                    if key in obj:
                        result = _extract_rows(obj[key], depth+1)
                        if result:
                            return result
            return []

        rows = _extract_rows(table_data)

        if not rows:
            # Try alternative paths
            # Path 1: data['table'] is a list of groups -> [0]['data']['table']['all']
            # Path 2: data['table'] is a list -> [0]['table'] -> list of rows
            # Path 3: data['standings'] or data['tableData']
            for alt_key in ['standings', 'tableData', 'stat']:
                if alt_key in data:
                    rows = _extract_rows(data[alt_key])
                    if rows:
                        print(f"FotMob standings: found via alt key '{alt_key}'", flush=True)
                        break

            if not rows and isinstance(table_data, list) and table_data:
                # Log deep structure for debug
                first = table_data[0]
                if isinstance(first, dict):
                    print(f"FotMob standings: table[0] keys={list(first.keys())}", flush=True)
                    for k, v in first.items():
                        vtype = type(v).__name__
                        vlen = len(v) if isinstance(v, (list, dict)) else ''
                        vkeys = list(v.keys())[:8] if isinstance(v, dict) else (list(v[0].keys())[:8] if isinstance(v, list) and v and isinstance(v[0], dict) else '')
                        print(f"  FotMob standings: table[0]['{k}'] = {vtype}({vlen}) keys={vkeys}", flush=True)

        if not rows:
            print(f"FotMob standings: no rows found after all attempts!", flush=True)

        standings = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            team_name = row.get('name', row.get('teamName', ''))
            team_id = row.get('id', row.get('teamId', ''))

            _register_team(team_name, team_id)

            standings.append({
                'position': row.get('idx', row.get('position', row.get('rank', 0))),
                'team': team_name,
                'team_id': team_id,
                'logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{team_id}.png" if team_id else '',
                'played': row.get('played', 0),
                'won': row.get('wins', row.get('won', 0)),
                'drawn': row.get('draws', row.get('drawn', 0)),
                'lost': row.get('losses', row.get('lost', 0)),
                'gf': row.get('scoresStr', '').split('-')[0].strip() if row.get('scoresStr') else row.get('goalsFor', 0),
                'ga': row.get('scoresStr', '').split('-')[1].strip() if row.get('scoresStr') and '-' in row.get('scoresStr','') else row.get('goalsAgainst', 0),
                'gd': row.get('goalConDiff', row.get('goalDifference', 0)),
                'points': row.get('pts', row.get('points', 0)),
                'isRealMadrid': team_id == FOTMOB_RM_ID or 'Real Madrid' in team_name
            })

        if standings:
            print(f"FotMob league standings: {len(standings)} teams", flush=True)
            _fotmob_standings_cache['data'] = standings
            _fotmob_standings_cache['time'] = now
        else:
            print(f"FotMob standings: 0 teams parsed!", flush=True)
        return standings
    except Exception as e:
        import traceback
        print(f"FotMob league standings error: {e}\n{traceback.format_exc()}", flush=True)
        return _fotmob_standings_cache.get('data') or []

_analytics_cache = {'data': None, 'time': 0, 'ttl': 900}

_fotmob_team_cache = {}  # {team_id: {'data': ..., 'time': ...}}
_fotmob_team_ttl = 300  # 5 min

def _get_fotmob_team(team_id: int = FOTMOB_RM_ID) -> dict:
    """Получить данные команды с FotMob API (cached 5min)"""
    import time as _ft
    now = _ft.time()
    cached = _fotmob_team_cache.get(team_id)
    if cached and cached.get('data') and (now - cached['time']) < _fotmob_team_ttl:
        return cached['data']
    try:
        url = f"{FOTMOB_API}/teams?id={team_id}"
        r = requests.get(url, headers=_fotmob_headers, timeout=15)
        print(f"FotMob team {team_id}: API status={r.status_code}", flush=True)
        if r.status_code != 200:
            # HTML fallback: scrape __NEXT_DATA__ from team page
            html_data = _fetch_fotmob_via_html('teams', team_id)
            if html_data:
                _fotmob_team_cache[team_id] = {'data': html_data, 'time': now, 'ttl': 1800}
                # Register teams from fixtures for logo map
                overview = html_data.get('overview', {})
                for fx in overview.get('overviewFixtures', []):
                    h = fx.get('home', {})
                    a = fx.get('away', {})
                    _register_team(h.get('name', ''), h.get('id'))
                    _register_team(a.get('name', ''), a.get('id'))
                return html_data
            return cached['data'] if cached and cached.get('data') else {}
        data = r.json()
        _fotmob_team_cache[team_id] = {'data': data, 'time': now}
        return data
    except Exception as e:
        print(f"FotMob team error: {e}", flush=True)
        return cached['data'] if cached and cached.get('data') else {}

_fotmob_match_404_cache = {}  # match_id -> time_of_404
_FOTMOB_404_TTL = 300  # 5 min


# === FotMob fallback for upcoming matches (sheets_client.get_matches replacement) ===
def _fotmob_upcoming_matches(limit: int = 10):
    """Return list of upcoming RM fixtures from FotMob, shaped like sheets get_matches()."""
    try:
        team = _get_fotmob_team(FOTMOB_RM_ID) or {}
        fixtures = (team.get('overview') or {}).get('overviewFixtures', []) or []
        import datetime as _dtfu
        now_utc = _dtfu.datetime.utcnow()
        out = []
        for f in fixtures:
            st = (f.get('status') or {})
            if st.get('finished') or st.get('started'):
                continue
            ut = st.get('utcTime') or (f.get('date', {}) or {}).get('utcTime') or f.get('utcTime')
            if not ut:
                continue
            try:
                dt = _dtfu.datetime.strptime(str(ut)[:19], '%Y-%m-%dT%H:%M:%S')
            except Exception:
                continue
            if dt < now_utc - _dtfu.timedelta(minutes=10):
                continue
            home = f.get('home') or {}
            away = f.get('away') or {}
            is_home = (home.get('id') == FOTMOB_RM_ID)
            opp = (away.get('name') if is_home else home.get('name')) or ''
            msk = dt + _dtfu.timedelta(hours=3)
            tour = ''
            try:
                tour = (f.get('tournament') or {}).get('name') or (f.get('tournament') or {}).get('leagueName') or ''
            except Exception:
                tour = ''
            out.append({
                'id': str(f.get('id') or ''),
                'date': msk.strftime('%d.%m.%Y'),
                'date_raw': msk.strftime('%Y-%m-%d'),
                'time': msk.strftime('%H:%M'),
                'tournament': tour or 'La Liga',
                'opponent': opp,
                'is_home': is_home,
                'home_crest': '',
                'away_crest': '',
            })
        out.sort(key=lambda x: x.get('date_raw', '') + ' ' + x.get('time', ''))
        return out[:limit]
    except Exception as _e:
        print(f'fotmob upcoming fallback err: {_e}', flush=True)
        return []


def _sheets_get_matches_with_fallback(limit: int = 5, *args, **kwargs):
    return _fotmob_upcoming_matches(limit) or []
# (sheets_client monkey-patch moved to api.py post-import)
# patch_lines_removed_here
# === end FotMob fallback ===

# === FotMob Next.js endpoint (replaces deprecated /api/matchDetails) ===
_fotmob_buildid_cache = {'value': None, 'time': 0, 'ttl': 3600}  # 1h

def _get_fotmob_buildid() -> str:
    """Scrape current Next.js buildId from fotmob.com homepage. Cached 1h."""
    import time as _tn
    now = _tn.time()
    if _fotmob_buildid_cache['value'] and (now - _fotmob_buildid_cache['time']) < _fotmob_buildid_cache['ttl']:
        return _fotmob_buildid_cache['value']
    try:
        r = requests.get('https://www.fotmob.com/', headers=_fotmob_headers, timeout=10)
        if r.status_code != 200:
            return _fotmob_buildid_cache.get('value', '')  # fallback to stale
        import re
        m = re.search(r'"buildId":"([^"]+)"', r.text)
        if m:
            _fotmob_buildid_cache['value'] = m.group(1)
            _fotmob_buildid_cache['time'] = now
            print(f'FotMob buildId refreshed: {m.group(1)}', flush=True)
            return m.group(1)
    except Exception as _e:
        print(f'buildId fetch err: {_e}', flush=True)
    return _fotmob_buildid_cache.get('value', '') or ''


def _get_fotmob_match(match_id: int) -> dict:
    """Получить детали матча с FotMob через /_next/data/<buildId>/matches/<slug>.json.

    FotMob deprecated /api/matchDetails (returns 404 for finished matches).
    New flow:
      1. GET /_next/data/<buildId>/match/<id>.json → body has __N_REDIRECT to slug URL
      2. GET /_next/data/<buildId>/matches/<slug>.json → real data with header/content/stats
    Возвращает совместимую структуру: header, content.stats, content.matchFacts, general и т.д.
    """
    import time as _tn
    _ent = _fotmob_match_404_cache.get(match_id)
    if _ent and (_tn.time() - _ent) < _FOTMOB_404_TTL:
        return {}
    try:
        bid = _get_fotmob_buildid()
        if not bid:
            print(f'FotMob match {match_id}: no buildId', flush=True)
            return {}

        # Step 1: get slug redirect
        url1 = f'https://www.fotmob.com/_next/data/{bid}/match/{match_id}.json'
        r1 = requests.get(url1, headers=_fotmob_headers, timeout=15)
        if r1.status_code != 200:
            print(f'FotMob match {match_id}: redirect step status={r1.status_code}', flush=True)
            _fotmob_match_404_cache[match_id] = _tn.time()
            return {}
        body1 = r1.json()
        pp1 = body1.get('pageProps', {})
        redirect = pp1.get('__N_REDIRECT')
        if not redirect:
            # Already has full data (no redirect)
            return pp1

        # Step 2: fetch the actual data via slug path
        slug_path = redirect.split('#')[0]  # /matches/<slug>/<code>
        url2 = f'https://www.fotmob.com/_next/data/{bid}{slug_path}.json'
        r2 = requests.get(url2, headers=_fotmob_headers, timeout=15)
        if r2.status_code != 200:
            print(f'FotMob match {match_id}: data step status={r2.status_code}', flush=True)
            _fotmob_match_404_cache[match_id] = _tn.time()
            return {}
        body2 = r2.json()
        return body2.get('pageProps', {})
    except Exception as e:
        print(f'FotMob match error {match_id}: {e}', flush=True)
        return {}


# ============ FotMob player ratings (Block B) ============
# === PLAYER RATINGS (FotMob lastLineupStats) ===
_fotmob_ratings_cache = {}
_RATINGS_CACHE_TTL = 3600  # 1 hour

def _get_match_ratings(match_id: int, home_team_id, away_team_id) -> dict:
    """Get player ratings from FotMob lastLineupStats for the given match.

    Returns full player data: rating, image, pitch position, events, subs.
    Only works if the match is the LAST match played by both teams.
    """
    cache_key = str(match_id)
    import time; now = time.time()
    cached = _fotmob_ratings_cache.get(cache_key)
    if cached and now - cached['time'] < _RATINGS_CACHE_TTL:
        return cached['data']

    result = {}
    pos_map = {0: 'GK', 1: 'DF', 2: 'MF', 3: 'FW'}
    pos_order = {'GK': 0, 'DF': 1, 'MF': 2, 'FW': 3}

    for team_id, side in [(home_team_id, 'home'), (away_team_id, 'away')]:
        if not team_id:
            continue
        try:
            team_data = _get_fotmob_team(int(team_id))
            if not team_data:
                continue
            ov = team_data.get('overview', {})
            lm = ov.get('lastMatch', {})

            if lm.get('id') != match_id:
                print(f"Ratings: team {team_id} lastMatch={lm.get('id')} != {match_id}, skip", flush=True)
                continue

            lls = ov.get('lastLineupStats', {})
            if not lls:
                continue

            players = []
            for is_starter, group in [(True, 'starters'), (False, 'subs')]:
                for p in lls.get(group, []):
                    perf = p.get('performance', {})
                    rating = perf.get('rating')
                    if not rating:
                        continue
                    pos_id = p.get('usualPlayingPositionId', -1)
                    pid = p.get('id', '')
                    hl = p.get('horizontalLayout', {})
                    events = perf.get('events', [])
                    sub_events = perf.get('substitutionEvents', [])
                    pdata = {
                        'name': p.get('name', ''),
                        'lastName': p.get('lastName', p.get('name', '').split()[-1] if p.get('name') else ''),
                        'rating': float(rating),
                        'position': pos_map.get(pos_id, 'MF'),
                        'number': p.get('shirtNumber', ''),
                        'starter': is_starter,
                        'imageUrl': f'https://images.fotmob.com/image_resources/playerimages/{pid}.png' if pid else '',
                    }
                    if is_starter and hl:
                        pdata['hx'] = hl.get('x', 0)
                        pdata['hy'] = hl.get('y', 0)
                    if events:
                        pdata['events'] = events
                    if sub_events:
                        pdata['subEvents'] = sub_events
                    players.append(pdata)

            players.sort(key=lambda x: (0 if x['starter'] else 1, pos_order.get(x['position'], 2)))

            coach = lls.get('coach', {})
            result[side] = players
            result[side + '_rating'] = lls.get('rating', 0)
            result[side + '_formation'] = lls.get('formation', '')
            if coach:
                result[side + '_coach'] = coach.get('name', '')
            print(f"Ratings: {side} team {team_id} -> {len(players)} players, avg={lls.get('rating')}", flush=True)
        except Exception as e:
            print(f"Ratings error for team {team_id}: {e}", flush=True)

    _fotmob_ratings_cache[cache_key] = {'data': result, 'time': now}
    return result


# ============ FotMob live match wrapper (Block C) ============
# === FOTMOB LIVE MATCH ===
_fotmob_live_cache = {'data': None, 'time': 0, 'ttl': 30}  # 30 sec cache

def get_fotmob_live_match() -> Dict:
    """Получить live матч Real Madrid из FotMob"""
    now = _time.time()
    cached = _fotmob_live_cache['data']
    if cached and (now - _fotmob_live_cache['time']) < _fotmob_live_cache['ttl']:
        return cached

    try:
        # 1. Force-refresh team data to get current hasOngoingMatch status
        # (team cache is 5min but match state changes faster)
        cached_team = _fotmob_team_cache.get(FOTMOB_RM_ID)
        if cached_team and (_time.time() - cached_team.get('time', 0)) > 60:
            # Stale for live detection — force refresh
            del _fotmob_team_cache[FOTMOB_RM_ID]
        team_data = _get_fotmob_team(FOTMOB_RM_ID)
        if not team_data:
            return {'is_live': False}

        overview = team_data.get('overview', {})
        has_ongoing = overview.get('hasOngoingMatch', False)

        if not has_ongoing:
            _fotmob_live_cache['data'] = {'is_live': False}
            _fotmob_live_cache['time'] = now
            return {'is_live': False}

        # 2. Найти live match ID из overviewFixtures
        match_id = None
        ov_fixtures = overview.get('overviewFixtures', [])
        for f in ov_fixtures:
            status = f.get('status', {})
            if status.get('started') and not status.get('finished'):
                match_id = f.get('id')
                break

        if not match_id:
            # Fallback: lastMatch if started and not finished
            lm = overview.get('lastMatch', {})
            if lm:
                lm_status = lm.get('status', {})
                if lm_status.get('started') and not lm_status.get('finished'):
                    match_id = lm.get('id')

        if not match_id:
            return {'is_live': False}

        print(f"FotMob LIVE: match_id={match_id}", flush=True)

        # 3. Получить matchDetails (FotMob -> ESPN fallback)
        match_data = _get_fotmob_match(match_id)
        if match_data:
            # 4. Парсим FotMob
            result = _parse_fotmob_live_match(match_data, match_id)
        else:
            # FotMob matchDetails blocked - ESPN fallback for live
            print(f"FotMob live matchDetails blocked, trying ESPN for {match_id}...", flush=True)
            home_name = ""
            away_name = ""
            fotmob_home_id = ""
            fotmob_away_id = ""
            for f in ov_fixtures:
                if f.get("id") == match_id:
                    home_name = f.get("home", {}).get("name", "")
                    away_name = f.get("away", {}).get("name", "")
                    fotmob_home_id = f.get("home", {}).get("id", "")
                    fotmob_away_id = f.get("away", {}).get("id", "")
                    break

            import datetime as _dt
            today = _dt.datetime.utcnow().strftime("%Y%m%d")
            espn_id = _espn_find_event(today, home_name, away_name) if home_name else ""
            summary = _espn_get_summary(espn_id, is_live=True) if espn_id else {}

            if summary:
                h_comps = summary.get("header", {}).get("competitions", [{}])[0]
                competitors = h_comps.get("competitors", [])
                espn_home = {}
                espn_away = {}
                for c in competitors:
                    if c.get("homeAway") == "home":
                        espn_home = c
                    else:
                        espn_away = c

                espn_minute_raw = h_comps.get("status", {}).get("displayClock", "")
                espn_minute = espn_minute_raw.replace("'", "").strip() + "'" if espn_minute_raw else ""

                result = {
                    "is_live": True,
                    "match_id": match_id,
                    "home_team": home_name or espn_home.get("team", {}).get("displayName", ""),
                    "away_team": away_name or espn_away.get("team", {}).get("displayName", ""),
                    "home_score": int(espn_home.get("score", 0) or 0),
                    "away_score": int(espn_away.get("score", 0) or 0),
                    "home_logo": f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_home_id}.png" if fotmob_home_id else "",
                    "away_logo": f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_away_id}.png" if fotmob_away_id else "",
                    "minute": espn_minute,
                    "tournament": "",
                    "incidents": _espn_parse_events(summary),
                    "stats": _espn_parse_stats(summary),
                    "momentum": [],
                    "shotmap": [],
                    "lineups": _espn_parse_lineups(summary),
                    "bets_suspended": False,
                    "source": "espn",
                }
            else:
                return {"is_live": False}

        _fotmob_live_cache['data'] = result
        _fotmob_live_cache['time'] = now
        return result

    except Exception as e:
        print(f"FotMob live error: {e}", flush=True)
        return {'is_live': False, 'error': str(e)}


# ============ FotMob recent matches (Block D) ============
def get_fotmob_recent_matches() -> list:
    """List of finished RM matches from FotMob, most recent first."""
    out = []
    try:
        team = _get_fotmob_team(FOTMOB_RM_ID) or {}
        fixtures = (team.get('overview') or {}).get('overviewFixtures', []) or []
        for f in fixtures:
            st = (f.get('status') or {})
            if not st.get('finished'):
                continue
            home = f.get('home') or {}
            away = f.get('away') or {}
            out.append({
                'matchId': str(f.get('id') or ''),
                'homeTeam': home.get('name', ''),
                'awayTeam': away.get('name', ''),
                'utcTime': st.get('utcTime', ''),
            })
    except Exception as _e:
        print(f'get_fotmob_recent_matches err: {_e}', flush=True)
    # newest first
    out.sort(key=lambda x: x.get('utcTime', ''), reverse=True)
    return out
