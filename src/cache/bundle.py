"""src/cache/bundle.py — Bundle endpoint caching helpers.

Centralized cache for /api/bundle (the everything-in-one-request aggregator).

State:
- _bundle_cache: 10s prematch TTL, 2s live TTL ("BK-feel" per RM cache TTLs note)

Helpers:
- _build_bundle_from_caches() — reads from all sub-caches (Leon, FotMob, sheets,
  match_details, news, prizes, etc.) and assembles the bundle dict. NO external
  API calls — pure cache read. Cache warmer keeps sub-caches fresh.
- _build_live_markets(odds, home_team, away_team, score) — turns Leon odds dict
  into list of bet markets for the UI. Pure parser.

External dependencies (lazy-imported from api.py inside functions to avoid circular
import): cache_warmer state, FotMob/Leon parser cache dicts.
"""
from typing import List


_bundle_cache = {'data': None, 'time': 0, 'ttl': 10, 'ttl_live': 2}


def _build_bundle_from_caches():
    """Build bundle by reading from existing sub-caches - NO external API calls.
    Each sub-function already has its own cache, so this is fast."""
    from urllib.parse import quote
    import os
    from api import (
        _leon_cache_dict, _fotmob_team_cache, sheets_client,
        _get_team_logo, FOTMOB_RM_ID, _AVATAR_DIR,
        _news_scrape_cache, get_streams_data, _register_team,
        _fotmob_standings_cache, _fotmob_live_cache, _analytics_cache,
    )
    from database import get_leaderboard
    bundle = {}

    # --- Next match (reads from leon cache + sheets) ---
    try:
        leon_live = None
        live_cache = _leon_cache_dict.get('__live__')
        if live_cache and live_cache.get('data'):
            leon_live = live_cache['data']

        if leon_live and leon_live.get('is_live'):
            # Live match - build from leon cache
            live_odds = leon_live.get('live_odds', {})
            sheets_match_id = None
            try:
                matches = sheets_client.get_matches(limit=5)
                leon_home = leon_live.get('home_team', '')
                leon_away = leon_live.get('away_team', '')
                for m in (matches or []):
                    opp = m.get('opponent', '')
                    if opp and (opp in leon_home or opp in leon_away or
                                leon_home in (opp or '') or leon_away in (opp or '')):
                        sheets_match_id = m.get('id')
                        break
            except:
                pass
            live_markets = _build_live_markets(live_odds, leon_live.get('home_team', ''), leon_live.get('away_team', ''), leon_live.get('score', '0:0')) if live_odds else []
            bundle['match'] = {
                'id': sheets_match_id,
                'home_team': leon_live.get('home_team', ''),
                'away_team': leon_live.get('away_team', ''),
                'home_logo': _get_team_logo(leon_live.get('home_team', '')),
                'away_logo': _get_team_logo(leon_live.get('away_team', '')),
                'is_live': True,
                'score': leon_live.get('score', ''),
                'minute': leon_live.get('minute', ''),
                'odds': live_odds,
                'bet_markets': live_markets,
                'leon_id': leon_live.get('leon_id'),
                'bets_suspended': leon_live.get('bets_suspended', False),
            }
        else:
            # Prematch - from sheets + leon prematch cache
            matches = sheets_client.get_matches(limit=1)
            if matches:
                m = matches[0]
                opp = m.get('opponent', '')
                home = 'Real Madrid' if m.get('is_home') else opp
                away = opp if m.get('is_home') else 'Real Madrid'
                # Try leon prematch cache
                leon_pm = None
                pm_cache = _leon_cache_dict.get(opp)
                if pm_cache and pm_cache.get('data'):
                    leon_pm = pm_cache['data']
                odds = leon_pm.get('live_odds', leon_pm.get('prematch_odds', {})) if leon_pm else {}
                bet_markets = _build_live_markets(odds, home, away) if odds else []
                bundle['match'] = {
                    'id': m.get('id'),
                    'home_team': home,
                    'away_team': away,
                    'home_logo': _get_team_logo(home),
                    'away_logo': _get_team_logo(away),
                    'date': f"{m.get('date')} {m.get('time')}",
                    'competition': m.get('tournament'),
                    'odds': odds,
                    'bet_markets': bet_markets,
                    'leon_id': leon_pm.get('leon_id') if leon_pm else None,
                }
            else:
                bundle['match'] = None
    except Exception as e:
        print(f"Bundle/match error: {e}", flush=True)
        bundle['match'] = None

    # --- Results (from fotmob team cache) ---
    try:
        team_data = _fotmob_team_cache.get(FOTMOB_RM_ID, {}).get('data')
        if team_data:
            overview = team_data.get('overview', {})
            fixtures = overview.get('overviewFixtures', [])
            results = []
            for f in fixtures:
                status = f.get('status', {})
                if not status.get('finished'):
                    continue
                home = f.get('home', {})
                away = f.get('away', {})
                match_id = f.get('id')
                _register_team(home.get('name', ''), home.get('id'))
                _register_team(away.get('name', ''), away.get('id'))
                score_str = status.get('scoreStr', '')
                home_score = home.get('score', 0) or 0
                away_score = away.get('score', 0) or 0
                if not score_str and (home_score or away_score):
                    score_str = f"{home_score} - {away_score}"
                is_home = home.get('id') == FOTMOB_RM_ID
                if is_home:
                    opponent = away.get('name', '')
                    gf, ga = home_score, away_score
                else:
                    opponent = home.get('name', '')
                    gf, ga = away_score, home_score
                result_str = 'win' if gf > ga else ('loss' if gf < ga else 'draw')
                # Format date from ISO to dd.mm.yyyy
                raw_date = status.get('utcTime', '')
                try:
                    dt = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                    fmt_date = dt.strftime('%d.%m.%Y')
                except:
                    fmt_date = raw_date[:10] if raw_date else ''
                results.append({
                    'match_id': match_id,
                    'home_team': home.get('name', ''),
                    'away_team': away.get('name', ''),
                    'home_logo': _get_team_logo(home.get('name', '')),
                    'away_logo': _get_team_logo(away.get('name', '')),
                    'home_score': home_score,
                    'away_score': away_score,
                    'score': f"{home_score}:{away_score}",
                    'result': result_str,
                    'is_home': is_home,
                    'opponent': opponent,
                    'competition': f.get('tournament', {}).get('name', ''),
                    'date': fmt_date,
                })
            bundle['results'] = list(reversed(results[-15:]))  # Last 15 matches, newest first
        else:
            bundle['results'] = []
    except Exception as e:
        print(f"Bundle/results error: {e}", flush=True)
        bundle['results'] = []

    # --- Upcoming matches (from sheets - fast DB) ---
    try:
        matches = sheets_client.get_matches(limit=10)
        upcoming = []
        for m in (matches or []):
            home = 'Real Madrid' if m.get('is_home') else m.get('opponent')
            away = m.get('opponent') if m.get('is_home') else 'Real Madrid'
            upcoming.append({
                'id': m.get('id'),
                'home_team': home,
                'away_team': away,
                'home_logo': _get_team_logo(home),
                'away_logo': _get_team_logo(away),
                'date': f"{m.get('date')} {m.get('time')}",
                'competition': m.get('tournament'),
            })
        bundle['matches'] = upcoming
    except Exception as e:
        print(f"Bundle/upcoming error: {e}", flush=True)
        bundle['matches'] = []

    # --- Standings (from fotmob standings cache) ---
    try:
        bundle['standings'] = _fotmob_standings_cache.get('data') or []
    except:
        bundle['standings'] = []

    # --- Leaderboard (fast DB call) ---
    try:
        leaders = get_leaderboard(limit=100)
        bundle['leaderboard'] = [
            {
                'user_id': l.get('user_id'),
                'first_name': l.get('first_name', ''),
                'username': l.get('username', ''),
                'balance': l.get('balance', 0),
                'total_bets': l.get('total_bets', 0),
                'won_bets': l.get('won_bets', 0),
                # Avatar N+1 fix: only set photo_url if file exists on disk.
                # Empty → frontend renders initials placeholder, zero requests.
                'photo_url': (
                    f"/api/avatar/{l.get('user_id')}"
                    if l.get('user_id') and os.path.exists(f"{_AVATAR_DIR}/{l.get('user_id')}.jpg")
                    else ''
                ),
            }
            for l in leaders
        ]
    except Exception as e:
        print(f"Bundle/leaderboard error: {e}", flush=True)
        bundle['leaderboard'] = []

    # --- Live match (Leon-only core + safe FotMob enrichment) ---
    # См. match_state.py + Obsidian/09 - Аудит 2026-05/PRINCIPLES.md
    try:
        from src.cache.match_state import resolve_match_state, build_live_payload
        leon_live_data = (_leon_cache_dict.get('__live__') or {}).get('data')
        core = resolve_match_state(leon_live_data)
        if core.is_live:
            fotmob_raw = _fotmob_live_cache.get('data') if _fotmob_live_cache else None
            bundle['live'] = build_live_payload(
                core, fotmob_raw,
                _get_team_logo, _build_live_markets,
            )
        else:
            bundle['live'] = None
    except Exception as e:
        print(f"Bundle/live error: {e}", flush=True)
        bundle['live'] = None

        # --- News (from news scrape cache) ---
    try:
        bundle['news'] = _news_scrape_cache.get('data', [])[:10]
    except:
        bundle['news'] = []

    # --- Streams (from file - fast) ---
    try:
        streams_data = get_streams_data()
        active = []
        for s in streams_data.get('streams', []):
            if not s.get('active', True):
                continue
            entry = {'name': s.get('name', ''), 'url': s.get('url', ''), 'type': s.get('type', 'hls')}
            if s.get('type') == 'acestream' and s.get('ace_id'):
                entry['http_url'] = f"/ace/getstream?id={s['ace_id']}&.mp4"
            # parse_url убран для type=iframe — URL уже готов, не нужен парсинг
            active.append(entry)
        bundle['streams'] = active
    except:
        bundle['streams'] = []

    # --- Analytics (from analytics cache, fresh-only) ---
    try:
        _a = _analytics_cache.get('data')
        if _a and not _a.get('error'):
            bundle['analytics'] = _a
        else:
            bundle['analytics'] = None
    except:
        bundle['analytics'] = None

    return bundle


def _build_live_markets(odds: dict, home_team: str = '', away_team: str = '', score: str = '0:0') -> list:
    """Build ALL bet markets from odds, with team names in categories"""
    markets = []
    h = home_team or 'Хозяева'
    a = away_team or 'Гости'

    # Parse score for smart filtering
    try:
        parts = score.replace('-', ':').split(':')
        hs = int(parts[0])
        as_ = int(parts[1])
    except:
        hs, as_ = 0, 0
    total_goals = hs + as_
    both_scored = hs > 0 and as_ > 0

    def _collect(prefix, max_line=None, current_value=0):
        """Собираем over/under пары ДИНАМИЧЕСКИ из odds dict"""
        bets = []
        lines_found = set()
        for key in odds:
            if key.startswith(f'{prefix}_over_') or key.startswith(f'{prefix}_under_'):
                line = key.replace(f'{prefix}_over_', '').replace(f'{prefix}_under_', '')
                try:
                    line_val = float(line)
                    if max_line and line_val > max_line:
                        continue
                    # Скрываем линии которые уже пройдены (результат очевиден)
                    if current_value > 0 and line_val < current_value:
                        continue
                    lines_found.add(line)
                except ValueError:
                    continue
        for line in sorted(lines_found, key=lambda x: float(x)):
            if odds.get(f'{prefix}_over_{line}'):
                bets.append({"key": f"{prefix}_over_{line}", "name": f"Б {line}", "odds": odds[f'{prefix}_over_{line}'], "line": float(line)})
                if odds.get(f'{prefix}_under_{line}'):
                    bets.append({"key": f"{prefix}_under_{line}", "name": f"М {line}", "odds": odds[f'{prefix}_under_{line}'], "line": float(line)})
        return bets

    # 1. Исход матча
    if odds.get('home'):
        markets.append({
            "type": "match_result", "category": "Исход матча", "bets": [
                {"key": "home", "name": "П1", "odds": odds.get('home', 0)},
                {"key": "draw", "name": "X", "odds": odds.get('draw', 0)},
                {"key": "away", "name": "П2", "odds": odds.get('away', 0)},
            ]
        })

    # 2. Двойной шанс
    if odds.get('dc_1x'):
        markets.append({
            "type": "double_chance", "category": "Двойной шанс", "bets": [
                {"key": "dc_1x", "name": "1X", "odds": odds.get('dc_1x', 0)},
                {"key": "dc_x2", "name": "X2", "odds": odds.get('dc_x2', 0)},
                {"key": "dc_12", "name": "12", "odds": odds.get('dc_12', 0)},
            ]
        })

    # 3. Тотал голов (макс линия 10.5 — всё выше не голы)
    total_bets = _collect('total', max_line=10.5, current_value=total_goals)
    if total_bets:
        markets.append({"type": "total_goals", "category": "Тотал голов", "bets": total_bets})

    # 4. Обе забьют (скрываем в live — некорректно работает при голах)
    if odds.get('btts_yes') and total_goals == 0:
        markets.append({
            "type": "btts", "category": "Обе забьют", "bets": [
                {"key": "btts_yes", "name": "Да", "odds": odds.get('btts_yes', 0)},
                {"key": "btts_no", "name": "Нет", "odds": odds.get('btts_no', 0)},
            ]
        })

    # 5. Результат без ничьей
    if odds.get('dnb_home'):
        markets.append({
            "type": "dnb", "category": "Результат без ничьей", "bets": [
                {"key": "dnb_home", "name": f"П1 ({h})", "odds": odds.get('dnb_home', 0)},
                {"key": "dnb_away", "name": f"П2 ({a})", "odds": odds.get('dnb_away', 0)},
            ]
        })

    # 6. Кто забьёт первый гол (скрываем если голы уже были)
    if odds.get('first_goal_home') and total_goals == 0:
        markets.append({
            "type": "first_goal", "category": "Кто забьёт первый гол", "bets": [
                {"key": "first_goal_home", "name": f"1 ({h})", "odds": odds.get('first_goal_home', 0)},
                {"key": "first_goal_none", "name": "Не будет", "odds": odds.get('first_goal_none', 0)},
                {"key": "first_goal_away", "name": f"2 ({a})", "odds": odds.get('first_goal_away', 0)},
            ]
        })

    # 7. Фора
    handicap_bets = []
    h_lines = set()
    for key in odds:
        if key.startswith('handicap_home_') or key.startswith('handicap_away_'):
            line = key.replace('handicap_home_', '').replace('handicap_away_', '')
            h_lines.add(line)
    for line in sorted(h_lines, key=lambda x: float(x)):
        if odds.get(f'handicap_home_{line}'):
            handicap_bets.append({"key": f"handicap_home_{line}", "name": f"Ф1 ({line})", "odds": odds[f'handicap_home_{line}'], "line": float(line)})
        if odds.get(f'handicap_away_{line}'):
            handicap_bets.append({"key": f"handicap_away_{line}", "name": f"Ф2 ({line})", "odds": odds[f'handicap_away_{line}'], "line": float(line)})
    if handicap_bets:
        markets.append({"type": "handicap", "category": "Фора", "bets": handicap_bets})

    # 8. Точный счёт
    score_bets = []
    score_keys = sorted(
        [k for k in odds if k.startswith('score_')],
        key=lambda x: odds[x]  # сортируем по кэфу (от низкого к высокому = от вероятного)
    )
    for key in score_keys[:15]:  # максимум 15 вариантов
        score = key.replace('score_', '').replace('-', ':')
        score_bets.append({"key": key, "name": score, "odds": odds[key]})
    if score_bets:
        markets.append({"type": "correct_score", "category": "Точный счёт", "bets": score_bets})

    # 9. Чёт/Нечёт
    if odds.get('total_even') and odds.get('total_odd'):
        markets.append({
            "type": "odd_even", "category": "Чёт/Нечёт голов", "bets": [
                {"key": "total_even", "name": "Чёт", "odds": odds.get('total_even', 0)},
                {"key": "total_odd", "name": "Нечёт", "odds": odds.get('total_odd', 0)},
            ]
        })

    # 10. ИТ хозяев (макс 7.5)
    home_bets = _collect('home', max_line=7.5, current_value=hs)
    if home_bets:
        markets.append({"type": "home_total", "category": f"ИТ хозяев ({h})", "bets": home_bets})

    # 11. ИТ гостей (макс 7.5)
    away_bets = _collect('away', max_line=7.5, current_value=as_)
    if away_bets:
        markets.append({"type": "away_total", "category": f"ИТ гостей ({a})", "bets": away_bets})

    # 12. Тотал угловых (макс 20)
    corner_bets = _collect('corners', max_line=20)
    if corner_bets:
        markets.append({"type": "total_corners", "category": "Тотал угловых", "bets": corner_bets})

    # 13. Угловые хозяев
    ch_bets = _collect('corners_home')
    if ch_bets:
        markets.append({"type": "corners_home", "category": f"Угловые хозяев ({h})", "bets": ch_bets})

    # 14. Угловые гостей
    ca_bets = _collect('corners_away')
    if ca_bets:
        markets.append({"type": "corners_away", "category": f"Угловые гостей ({a})", "bets": ca_bets})

    # 15. Тотал карточек (макс 12)
    card_bets = _collect('cards', max_line=12)
    if card_bets:
        markets.append({"type": "total_cards", "category": "Тотал карточек", "bets": card_bets})

    # 16. Карточки хозяев
    cdh_bets = _collect('cards_home')
    if cdh_bets:
        markets.append({"type": "cards_home", "category": f"Карточки хозяев ({h})", "bets": cdh_bets})

    # 17. Карточки гостей
    cda_bets = _collect('cards_away')
    if cda_bets:
        markets.append({"type": "cards_away", "category": f"Карточки гостей ({a})", "bets": cda_bets})

    # 18. Пенальти
    if odds.get('penalty_yes'):
        markets.append({
            "type": "penalty", "category": "Будет ли пенальти", "bets": [
                {"key": "penalty_yes", "name": "Да", "odds": odds.get('penalty_yes', 0)},
                {"key": "penalty_no", "name": "Нет", "odds": odds.get('penalty_no', 0)},
            ]
        })

    return markets
