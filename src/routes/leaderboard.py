"""src/routes/leaderboard.py — Leaderboard + global stats.

Эндпоинты:
- GET /api/leaderboard — топ игроков с avatar URL'ами
- GET /api/stats — глобальная статистика проекта
"""
import os
import time as _t
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["leaderboard"])

# Module-local cache (singleton)
_leaderboard_cache = {'data': None, 'time': 0, 'ttl': 10, 'limit': None}


def init(avatar_dir):
    @router.get("/leaderboard")
    async def get_leaderboard_endpoint(limit: int = 100):
        from database import get_leaderboard

        now = _t.time()
        c = _leaderboard_cache
        if c['data'] is not None and c['limit'] == limit and (now - c['time']) < c['ttl']:
            return c['data']

        leaders = get_leaderboard(limit=limit)
        # Avatar N+1 fix: only set photo_url if avatar file exists
        for l in leaders:
            uid = l.get('user_id')
            if uid and os.path.exists(f"{avatar_dir}/{uid}.jpg"):
                l['photo_url'] = f"/api/avatar/{uid}"
            else:
                l['photo_url'] = ''
        payload = {"leaderboard": leaders}
        c['data'] = payload
        c['time'] = now
        c['limit'] = limit
        return payload

    @router.get("/stats")
    async def get_stats():
        from database import get_global_stats
        return {"stats": get_global_stats()}
