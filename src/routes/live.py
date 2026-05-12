"""src/routes/live.py — Live match + odds endpoints.

Эндпоинты:
- GET /api/live — текущий live матч (Leon-only через match_state.py)
- GET /api/odds — кэфы на текущий/следующий матч RM

См. Obsidian/09 - Аудит 2026-05/PRINCIPLES.md — Leon primary, FotMob enrichment.

Note: /api/live/debug endpoint (~100 lines) остаётся в api.py как dev-only.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["live"])


def init():
    @router.get("/live")
    async def get_live_match():
        """LIVE матч Real Madrid. Leon — primary, FotMob — enrichment only."""
        from api import _get_leon_cached, _fotmob_live_cache, _get_team_logo, _build_live_markets
        from src.cache.match_state import resolve_match_state, build_live_payload
        try:
            leon_data = _get_leon_cached()
            core = resolve_match_state(leon_data)

            if not core.is_live:
                if leon_data and leon_data.get('leon_id'):
                    return {
                        "is_live": False,
                        "next_match": {
                            "home_team": leon_data.get('home_team'),
                            "away_team": leon_data.get('away_team'),
                            "kickoff": leon_data.get('kickoff'),
                            "pre_match_odds": leon_data.get('live_odds', {}),
                        },
                    }
                return {"is_live": False}

            fotmob_raw = _fotmob_live_cache.get('data') if _fotmob_live_cache else None
            result = build_live_payload(core, fotmob_raw, _get_team_logo, _build_live_markets)
            result['match_id'] = core.leon_id
            result['source'] = 'leon+fotmob' if fotmob_raw else 'leon'
            return result
        except Exception as e:
            print(f"Live error: {e}", flush=True)
            return {"is_live": False, "error": str(e)}

    @router.get("/odds")
    async def get_current_odds():
        """Кэфы на live или prematch матч из Leon (без сломанного fallback'а)."""
        from api import _get_leon_cached, sheets_client
        try:
            leon_data = _get_leon_cached()
            if leon_data:
                is_live = bool(leon_data.get('is_live'))
                odds = leon_data.get('live_odds') if is_live else leon_data.get('live_odds', {})
                return {
                    "success": True,
                    "source": "leon",
                    "match": f"{leon_data.get('home_team', '')} - {leon_data.get('away_team', '')}",
                    "home_team": leon_data.get('home_team'),
                    "away_team": leon_data.get('away_team'),
                    "kickoff": "LIVE" if is_live else leon_data.get('kickoff'),
                    "is_live": is_live,
                    "odds": odds or {},
                }
            # Sheets fallback
            odds_data = sheets_client.get_odds() if sheets_client else {}
            return {"success": True, "source": "sheets", "odds": odds_data}
        except Exception as e:
            print(f"Odds error: {e}", flush=True)
            return {"success": False, "error": str(e)}

    @router.get('/liveball/schedule')
    async def liveball_schedule():
        from api import _parse_liveball_schedule
        matches = _parse_liveball_schedule()
        return {'matches': matches, 'count': len(matches)}

