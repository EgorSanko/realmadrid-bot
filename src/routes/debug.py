"""src/routes/debug.py - Dev-only diagnostic endpoints.

Endpoints (3):
- GET /api/match/analytics/debug : raw FotMob team overview + h2h
- GET /api/live/debug            : FotMob live detection smoketests
- GET /api/standings/debug       : FotMob standings raw structure

Helpers (FOTMOB_API, FOTMOB_RM_ID, _fotmob_headers, _team_logo_map, parsers)
stay in api.py — imported lazily.
"""
import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["debug"])


def init():
    @router.get("/match/analytics/debug")
    async def debug_analytics():
        """Debug: тест FotMob API — raw structure"""
        from api import FOTMOB_API, FOTMOB_RM_ID, _fotmob_headers, _find_next_fotmob_match
        import json as json_mod
        from fastapi.responses import JSONResponse
        try:
            r = requests.get(f"{FOTMOB_API}/teams?id={FOTMOB_RM_ID}", headers=_fotmob_headers, timeout=15)
            if r.status_code != 200:
                return {"error": f"FotMob status {r.status_code}"}
            data = r.json()
            ov = data.get('overview', {})

            result = {
                "overview_keys": list(ov.keys()),
            }

            # overviewFixtures sample
            ovf = ov.get('overviewFixtures', [])
            if isinstance(ovf, list):
                finished = [f for f in ovf if f.get('status', {}).get('finished')]
                result['ovFixtures_total'] = len(ovf)
                result['ovFixtures_finished'] = len(finished)
                if finished:
                    safe = json_mod.loads(json_mod.dumps(finished[-1], default=str))
                    result['ovFixtures_last'] = safe

            # teamForm sample
            tf = ov.get('teamForm', [])
            if tf:
                safe_tf = json_mod.loads(json_mod.dumps(tf[:2], default=str))
                result['teamForm_sample'] = safe_tf

            # H2H raw from matchDetails
            nm = _find_next_fotmob_match(data)
            result['next_match'] = nm
            if nm.get('match_id'):
                mr = requests.get(f"{FOTMOB_API}/matchDetails?matchId={nm['match_id']}", headers=_fotmob_headers, timeout=15)
                result['h2h_fetch_status'] = mr.status_code
                result['espn_fallback_available'] = True
                if mr.status_code == 200:
                    md = mr.json()
                    h2h_raw = md.get('content', {}).get('h2h', {})
                    if isinstance(h2h_raw, dict):
                        result['h2h_keys'] = list(h2h_raw.keys())
                        for k in h2h_raw:
                            v = h2h_raw[k]
                            if isinstance(v, list) and v:
                                result[f'h2h_{k}_len'] = len(v)
                                safe_h = json_mod.loads(json_mod.dumps(v[0], default=str))
                                result[f'h2h_{k}_0'] = safe_h

            return JSONResponse(content=result)
        except Exception as e:
            import traceback

    @router.get("/live/debug")
    async def debug_live():
        """Debug: test FotMob live detection"""
        from api import (FOTMOB_RM_ID, _get_fotmob_team, get_fotmob_live_match, _get_fotmob_match, _parse_fotmob_events, _parse_fotmob_stats, _parse_fotmob_momentum, _parse_fotmob_shotmap, _parse_fotmob_lineups)
        try:
            team_data = _get_fotmob_team(FOTMOB_RM_ID)
            if not team_data:
                return {"error": "FotMob unavailable"}
            ov = team_data.get('overview', {})
            result = {
                'hasOngoingMatch': ov.get('hasOngoingMatch', False),
                'nextMatch': ov.get('nextMatch'),
                'lastMatch': ov.get('lastMatch'),
            }
            # If there IS a live match, fetch details
            if ov.get('hasOngoingMatch'):
                live = get_fotmob_live_match()
                result['live_data_keys'] = list(live.keys()) if live else None
                result['events_count'] = len(live.get('incidents', []))
                result['stats_count'] = len(live.get('stats', []))
                result['momentum_count'] = len(live.get('momentum', []))
                result['shotmap_count'] = len(live.get('shotmap', []))

            # Test with last finished match to verify parsing
            last_match_id = None
            for f in ov.get('overviewFixtures', []):
                if f.get('status', {}).get('finished'):
                    last_match_id = f.get('id')
            if last_match_id:
                md = _get_fotmob_match(last_match_id)
                if md:
                    result['test_match_id'] = last_match_id
                    events = _parse_fotmob_events(md)
                    stats = _parse_fotmob_stats(md)
                    momentum = _parse_fotmob_momentum(md)
                    shotmap = _parse_fotmob_shotmap(md)
                    result['test_events'] = len(events)
                    result['test_events_sample'] = events[:3] if events else []
                    result['test_stats'] = len(stats)
                    result['test_stats_sample'] = stats[:3] if stats else []
                    # Debug: raw stats structure
                    content = md.get('content', {})
                    raw_stats = content.get('stats', {})
                    if isinstance(raw_stats, dict):
                        result['stats_keys'] = list(raw_stats.keys())
                        for k in raw_stats:
                            v = raw_stats[k]
                            if isinstance(v, list) and v:
                                result[f'stats_{k}_type'] = 'list'
                                result[f'stats_{k}_len'] = len(v)
                                import json as jmod
                                result[f'stats_{k}_first'] = jmod.loads(jmod.dumps(v[0], default=str))
                            elif isinstance(v, dict):
                                result[f'stats_{k}_type'] = 'dict'
                                result[f'stats_{k}_keys'] = list(v.keys())
                                # Show ALL sub-keys
                                for sk in v:
                                    sv = v[sk]
                                    if isinstance(sv, list):
                                        result[f'stats_{k}_{sk}_len'] = len(sv)
                                        if sv:
                                            import json as jmod
                                            result[f'stats_{k}_{sk}_first'] = jmod.loads(jmod.dumps(sv[0], default=str))
                                    elif isinstance(sv, dict):
                                        result[f'stats_{k}_{sk}_type'] = 'dict'
                                        result[f'stats_{k}_{sk}_keys'] = list(sv.keys())[:5]
                                    else:
                                        result[f'stats_{k}_{sk}_type'] = type(sv).__name__
                    # Also check shotmap raw
                    raw_shotmap = content.get('shotmap', {})
                    if isinstance(raw_shotmap, dict):
                        result['shotmap_keys'] = list(raw_shotmap.keys())
                        shots_list = raw_shotmap.get('shots', [])
                        if shots_list:
                            import json as jmod
                            result['shotmap_raw_first'] = jmod.loads(jmod.dumps(shots_list[0], default=str))
                    result['test_momentum'] = len(momentum)
                    result['test_shotmap'] = len(shotmap)
                    result['test_shotmap_sample'] = shotmap[:2] if shotmap else []

                    # Debug lineups
                    lineups = _parse_fotmob_lineups(md)
                    result['test_lineups_home'] = len(lineups.get('home', []))
                    result['test_lineups_away'] = len(lineups.get('away', []))
                    result['test_lineups_home_sample'] = lineups.get('home', [])[:2]
                    result['test_lineups_away_sample'] = lineups.get('away', [])[:2]

                    # Raw lineup structure
                    raw_lineup = content.get('lineup', {})
                    if isinstance(raw_lineup, dict):
                        result['lineup_keys'] = list(raw_lineup.keys())
                        for lk in raw_lineup:
                            lv = raw_lineup[lk]
                            if isinstance(lv, dict):
                                result[f'lineup_{lk}_keys'] = list(lv.keys())[:10]
                                # Check players/starters structure
                                starters = lv.get('starters', lv.get('players', []))
                                if isinstance(starters, list) and starters:
                                    import json as jmod
                                    first_p = starters[0]
                                    if isinstance(first_p, list) and first_p:
                                        result[f'lineup_{lk}_nested'] = True
                                        p = first_p[0] if first_p else {}
                                        result[f'lineup_{lk}_player_keys'] = list(p.keys()) if isinstance(p, dict) else type(p).__name__
                                        result[f'lineup_{lk}_first_player'] = jmod.loads(jmod.dumps(p, default=str)) if isinstance(p, dict) else None
                                    elif isinstance(first_p, dict):
                                        result[f'lineup_{lk}_player_keys'] = list(first_p.keys())
                                        result[f'lineup_{lk}_first_player'] = jmod.loads(jmod.dumps(first_p, default=str))
                            elif isinstance(lv, list):
                                result[f'lineup_{lk}_type'] = 'list'
                                result[f'lineup_{lk}_len'] = len(lv)

            return result
        except Exception as e:
            import traceback
            return {"error": str(e), "tb": traceback.format_exc()[-500:]}

    @router.get("/standings/debug")
    async def debug_standings():
        """Debug FotMob standings parsing"""
        from api import FOTMOB_API, _fotmob_headers, _team_logo_map, _get_fotmob_league_standings
        try:
            url = f"{FOTMOB_API}/leagues?id=87"
            r = requests.get(url, headers=_fotmob_headers, timeout=15)
            data = r.json()
            table_data = data.get('table', [])

            result = {
                'status': r.status_code,
                'table_type': type(table_data).__name__,
                'table_len': len(table_data) if isinstance(table_data, list) else 'N/A',
                'team_logo_map_count': len(_team_logo_map),
                'team_logo_map_sample': dict(list(_team_logo_map.items())[:10]),
            }

            if isinstance(table_data, list) and table_data:
                first = table_data[0]
                result['first_type'] = type(first).__name__
                if isinstance(first, dict):
                    result['first_keys'] = list(first.keys())
                    if 'table' in first:
                        tbl = first['table']
                        result['table_inner_type'] = type(tbl).__name__
                        if isinstance(tbl, dict):
                            result['table_inner_keys'] = list(tbl.keys())
                            if 'all' in tbl:
                                all_rows = tbl['all']
                                result['all_type'] = type(all_rows).__name__
                                result['all_len'] = len(all_rows) if isinstance(all_rows, list) else 'N/A'
                                if isinstance(all_rows, list) and all_rows:
                                    result['first_row_keys'] = list(all_rows[0].keys()) if isinstance(all_rows[0], dict) else str(all_rows[0])[:100]
                                    result['first_row_sample'] = {k: all_rows[0].get(k) for k in ['name', 'id', 'pts', 'played', 'wins', 'idx']} if isinstance(all_rows[0], dict) else None
                        elif isinstance(tbl, list) and tbl:
                            result['table_inner_len'] = len(tbl)
                            result['first_row_keys'] = list(tbl[0].keys()) if isinstance(tbl[0], dict) else str(tbl[0])[:100]

            # Also try the parsed result
            standings = _get_fotmob_league_standings()
            result['parsed_count'] = len(standings)
            if standings:
                result['first_team'] = standings[0]

            return result
        except Exception as e:
            import traceback
            return {"error": str(e), "traceback": traceback.format_exc()}

