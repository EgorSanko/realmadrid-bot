"""src/routes/match_data.py — Match info endpoints (read-only aggregations).

Эндпоинты:
- GET /api/standings — таблица Ла Лиги (FotMob → Sheets fallback)
- GET /api/players — состав Real Madrid (Sofascore)
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["match-data"])


def init():
    @router.get("/standings")
    async def get_standings():
        from api import _get_fotmob_league_standings, sheets_client, _get_team_logo
        try:
            fotmob = _get_fotmob_league_standings()
            if fotmob:
                return {"standings": fotmob, "count": len(fotmob)}
            # Sheets fallback
            standings_raw = sheets_client.get_standings(limit=20) if sheets_client else []
            standings = []
            for row in standings_raw:
                team = row.get('team', '')
                standings.append({
                    'position': row.get('position', 0),
                    'team': team,
                    'logo': _get_team_logo(team),
                    'played': row.get('played', 0),
                    'won': row.get('won', 0),
                    'drawn': row.get('draw', 0),
                    'lost': row.get('lost', 0),
                    'points': row.get('points', 0),
                    'isRealMadrid': 'Real Madrid' in team,
                })
            return {"standings": standings, "count": len(standings)}
        except Exception as e:
            print(f"Standings error: {e}", flush=True)
            return {"standings": [], "error": str(e)}

    # /api/lineups, /api/ratings, /api/ratings/posts amputated 2026-05-11 (TG-channel parsers broken since unknown date)

    @router.get("/players")
    async def get_players():
        from api import get_sofascore_player_stats
        try:
            players = get_sofascore_player_stats()
            return {"players": players, "count": len(players)}
        except Exception as e:
            print(f"Players error: {e}", flush=True)
            return {"players": [], "error": str(e)}
