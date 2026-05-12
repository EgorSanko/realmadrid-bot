"""src/routes/bundle.py — Bundle aggregator endpoints (Block 2.5).

Endpoints:
- GET /api/health  — простой healthcheck
- GET /api/init    — legacy alias of /api/bundle
- GET /api/bundle  — everything-in-one-request агрегатор

Per-request cache: 10s prematch TTL, 2s live TTL (managed via src/cache/bundle.py).
ETag support: anonymous clients with matching If-None-Match get 304 (no body).
Authenticated users skip ETag (user data is unique per request).
"""
from datetime import datetime
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["bundle"])


def init(get_current_user):
    from src.cache.bundle import _bundle_cache, _build_bundle_from_caches
    from database import get_user_bets, get_user_predictions

    @router.get("/health")
    async def health_check():
        """Проверка работоспособности API"""
        return {"status": "ok", "timestamp": datetime.now().isoformat()}

    # Bundle-level cache (90s TTL — warmer refreshes every 25s, so we never serve stale)
    # === Bundle cache + builders moved to src/cache/bundle.py ===
    from src.cache.bundle import _bundle_cache, _build_bundle_from_caches, _build_live_markets

    @router.get("/init")
    async def get_init(authorization: str = Header(None)):
        """Legacy alias of /api/bundle (kept for backward compat)."""
        return await get_bundle(authorization=authorization)

    @router.get("/bundle")
    async def get_bundle(authorization: str = Header(None),
                         if_none_match: str = Header(None)):
        """All critical data in 1 request - reads from sub-caches only, no external calls.
        Supports ETag/304: anonymous clients with matching If-None-Match get 304 (no body)."""
        import time as _bt
        from fastapi import Response

        _bundle_start = _bt.time()

        # Return cached bundle if fresh
        _is_live_cached = bool(_bundle_cache['data'] and (_bundle_cache['data'].get('live') or {}).get('is_live'))
        _ttl_now = _bundle_cache.get('ttl_live', 2) if _is_live_cached else _bundle_cache['ttl']
        if _bundle_cache['data'] and (_bt.time() - _bundle_cache['time']) < _ttl_now:
            # ETag = bundle build time. For unauthenticated clients we can short-circuit
            # with 304 (auth'd users have user-specific overlay so etag would be wrong).
            etag = f'W/"b{int(_bundle_cache["time"])}"'
            if not authorization and if_none_match and if_none_match == etag:
                return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})

            cached = dict(_bundle_cache['data'])
            # Overlay user-specific data
            if authorization:
                try:
                    user = await get_current_user(authorization)
                    if user:
                        user_id = user['user_id']
                        bets = get_user_bets(user_id, limit=1000)
                        cached['user'] = {
                            'user_id': user['user_id'],
                            'first_name': user.get('first_name', ''),
                            'username': user.get('username', ''),
                            'balance': user.get('balance', 0),
                            'bets_count': len(bets),
                            'bets_won': len([b for b in bets if b.get('status') == 'won']),
                        }
                        cached['bets'] = get_user_bets(user_id, limit=20)
                        cached['predictions'] = get_user_predictions(user_id, limit=20)
                except:
                    pass
            print(f"Bundle CACHED: {_bt.time()-_bundle_start:.3f}s", flush=True)
            # Return as JSONResponse so we can set ETag header (anonymous only — auth has user data)
            if not authorization:
                from fastapi.responses import JSONResponse
                return JSONResponse(content=cached, headers={"ETag": etag, "Cache-Control": "no-cache"})
            return cached

        # Cache miss - build bundle from sub-caches (NO external API calls)
        bundle = _build_bundle_from_caches()

        # User-specific data (fast DB lookups)
        user = None
        if authorization:
            try:
                user = await get_current_user(authorization)
            except:
                pass

        if user:
            user_id = user['user_id']
            bets = get_user_bets(user_id, limit=1000)
            bundle['user'] = {
                'user_id': user['user_id'],
                'first_name': user.get('first_name', ''),
                'username': user.get('username', ''),
                'balance': user.get('balance', 0),
                'bets_count': len(bets),
                'bets_won': len([b for b in bets if b.get('status') == 'won']),
            }
            bundle['bets'] = get_user_bets(user_id, limit=20)
            bundle['predictions'] = get_user_predictions(user_id, limit=20)
        else:
            bundle['user'] = None
            bundle['bets'] = []
            bundle['predictions'] = []

        # Cache the result
        _bundle_cache['data'] = bundle
        _bundle_cache['time'] = _bt.time()

        print(f"Bundle BUILT from sub-caches: {_bt.time()-_bundle_start:.3f}s", flush=True)
        return bundle
