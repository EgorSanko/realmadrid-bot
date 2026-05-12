"""src/cache/warmer.py — Background cache warmer tasks.

5 async/sync functions that keep sub-caches fresh, so /api/bundle is always fast.

Tasks (scheduled via api.lifespan):
- photo_cleanup_task         every 5min  — disk hygiene
- cache_warmer_task          every 25s   — refresh slow caches in thread executor
- live_warmer_task           every 1.5s  — Leon-only live refresh (BK-feel)
- warm_match_details_pass    in cache_warmer_task — prefill _match_details_cache
- _collect_warm_match_ids    helper — last 10 finished + next match IDs

All heavy I/O calls live in `_warmer_blocking_pass()` so the event loop stays
responsive. live_warmer_task runs Leon directly without the executor (1.5s
budget too tight).

External deps via lazy imports (api.py + src.parsers.fotmob + src.parsers.leon
+ src.parsers.news + src.cache.bundle + database).
"""
import asyncio
import time as _t


async def photo_cleanup_task():
    """Фоновая задача очистки старых фото каждые 5 минут"""
    from api import cleanup_old_photos
    while True:
        await asyncio.sleep(300)  # 5 минут
        try:
            await cleanup_old_photos()
        except Exception as e:
            print(f"Photo cleanup error: {e}")


def _warmer_blocking_pass():
    """Sync блок — выполняется в thread executor, чтобы не блокировать event loop.
    Все Leon/FotMob/Sheets/news вызовы внутри — синхронные и I/O-bound."""
    from api import sheets_client, _parse_liveball_schedule
    from src.parsers.leon import _get_leon_cached
    from src.parsers.fotmob import _get_fotmob_league_standings, get_fotmob_live_match
    from src.parsers.news import scrape_news_list
    from src.cache.bundle import _build_bundle_from_caches, _bundle_cache
    import time as _t
    # Refresh Leon live (slowest - 2-3s)
    try:
        _get_leon_cached()
    except Exception as _e:
        print(f"Leon live warm err: {_e}")
    # Also refresh Leon prematch (for next match opponent)
    try:
        matches = sheets_client.get_matches(limit=1)
        if matches:
            opp = matches[0].get('opponent', '')
            if opp:
                _get_leon_cached(target_opponent=opp)
    except:
        pass
    # Refresh standings (700ms)
    try:
        _get_fotmob_league_standings()
    except:
        pass
    # Refresh news (450ms)
    try:
        scrape_news_list(10)
    except:
        pass
    # Refresh FotMob live
    try:
        get_fotmob_live_match()
    except:
        pass
    # Refresh Sheets reads (cached 45s by _sheets_cached wrapper)
    try:
        sheets_client.get_matches(limit=20)
        sheets_client.get_results(limit=20)
        sheets_client.get_standings(limit=20)
        sheets_client.get_odds()
    except Exception as _se:
        print(f"Sheets warm err: {_se}")
    # Also warm the bundle cache
    try:
        _warm_data = _build_bundle_from_caches()
        _warm_data['user'] = None
        _warm_data['bets'] = []
        _warm_data['predictions'] = []
        _bundle_cache['data'] = _warm_data
        _bundle_cache['time'] = _t.time()
    except Exception as _we:
        print(f"Bundle warm error: {_we}")
    # Refresh LiveBall schedule in background
    try:
        _parse_liveball_schedule()
    except:
        pass


def _collect_warm_match_ids() -> list:
    from api import sheets_client
    """Pick recent results + upcoming matches from cached FotMob team data.
    These are exactly the IDs the frontend MatchesPage will request next."""
    ids = []
    try:
        team_data = _get_fotmob_team(FOTMOB_RM_ID)
        if not team_data:
            return ids
        fixtures = team_data.get('overview', {}).get('overviewFixtures', []) or []
        finished = []
        upcoming = []
        for f in fixtures:
            mid = f.get('id')
            if not mid:
                continue
            status = f.get('status', {}) or {}
            if status.get('finished'):
                finished.append(mid)
            elif not status.get('started'):
                upcoming.append(mid)
        # Last 10 finished + next 5 upcoming = covers what user will click on
        ids.extend(finished[-10:])
        ids.extend(upcoming[:5])
    except Exception as _e:
        print(f"warm match-ids collect err: {_e}")
    return ids


async def warm_match_details_pass():
    """Pre-fill _match_details_cache for the matches user is most likely to click.
    Skips already-cached entries. Sequential to avoid hammering FotMob/ESPN."""
    import time as _t
    from src.parsers.fotmob import _match_details_cache, _MATCH_DETAILS_TTL_LIVE, _MATCH_DETAILS_TTL_FINISHED
    # get_match_details lives in src.routes.match — need direct call to its body, so use api re-export
    # The route function name is also get_match_details; routes/match.py defines it inside init()
    # We need the wrapped routes.match endpoint. Easiest: do the fetch inline using FotMob.
    from src.parsers.fotmob import _get_fotmob_match
    ids = _collect_warm_match_ids()
    warmed = 0
    for mid in ids:
        cached = _match_details_cache.get(mid)
        if cached:
            data = cached.get('data') or {}
            ttl = _MATCH_DETAILS_TTL_LIVE if (data.get('started') and not data.get('finished')) else _MATCH_DETAILS_TTL_FINISHED
            if (_t.time() - cached['time']) < ttl:
                continue
        try:
            _get_fotmob_match(mid)  # Triggers caching internally; full enrichment happens on user request
            warmed += 1
        except Exception as _e:
            print(f"warm match {mid} err: {_e}")
    if warmed:
        print(f"🎯 Match details warmed: {warmed}/{len(ids)}", flush=True)


async def live_warmer_task():
    """Fast warmer: every 1.5s while live match is running, refresh Leon and
    rebuild bundle so /api/bundle returns per-second-fresh odds. Skips when no
    live match (cheap polling at 5s in idle state)."""
    import time as _t
    from src.parsers.leon import _get_leon_cached, _leon_cache_dict
    from src.cache.bundle import _build_bundle_from_caches, _bundle_cache
    while True:
        try:
            live_cache = _leon_cache_dict.get('__live__')
            is_live = bool(live_cache and live_cache.get('data') and live_cache['data'].get('is_live'))
            if is_live:
                # Refresh Leon (TTL=2s so this fetches fresh)
                await asyncio.to_thread(_get_leon_cached)
                # Rebuild bundle from caches and store
                try:
                    fresh = _build_bundle_from_caches()
                    fresh['user'] = None
                    fresh['bets'] = []
                    fresh['predictions'] = []
                    _bundle_cache['data'] = fresh
                    _bundle_cache['time'] = _t.time()
                except Exception as _be:
                    print(f'live warmer rebuild err: {_be}')
                await asyncio.sleep(1.5)
            else:
                await asyncio.sleep(5)
        except Exception as e:
            print(f'live warmer error: {e}')
            await asyncio.sleep(5)


async def cache_warmer_task():
    """Background task: refresh slow caches every 25s so /api/bundle is always fast.
    Все блокирующие I/O вызовы выполняются в thread (asyncio.to_thread), чтобы
    event loop не вставал на 2-3 секунды на каждой итерации."""
    import time as _t
    from src.parsers.fotmob import _analytics_cache
    while True:
        await asyncio.sleep(25)
        try:
            # Heavy I/O — в отдельном thread
            await asyncio.to_thread(_warmer_blocking_pass)
            # Analytics — async, throttled (нельзя в thread, дёргает другой async код)
            try:
                from src.routes import match as _routes_match
                _a_age = _t.time() - _analytics_cache.get('time', 0)
                if _routes_match._analytics_fn and (_a_age > 300 or not _analytics_cache.get('data')):
                    await _routes_match._analytics_fn(nocache=True)
            except Exception as _ae:
                print(f"Analytics warm err: {_ae}")
            # Match details prewarm — fills cache for matches user will click on
            try:
                await warm_match_details_pass()
            except Exception as _me:
                print(f"Match details warm err: {_me}")
            # football-video.org (RuTube обзоры) — раз в 6ч, в thread
            try:
                from src.parsers.football_video import _cache as _fv_cache, _refresh_cache as _fv_refresh
                age2 = _t.time() - _fv_cache.get('time', 0)
                if _fv_cache.get('data') is None or age2 > _fv_cache.get('ttl', 21600):
                    await asyncio.to_thread(_fv_refresh)
            except Exception as _fve:
                print(f"football_video warm err: {_fve}")
            # mysportslib video archive — раз в 6ч, в thread (15-30s HTTP)
            try:
                from src.parsers.mysportslib import _videos_cache as _msl_cache, _refresh_cache as _msl_refresh
                age = _t.time() - _msl_cache.get('time', 0)
                if _msl_cache.get('data') is None or age > _msl_cache.get('ttl', 21600):
                    await asyncio.to_thread(_msl_refresh)
            except Exception as _mle:
                print(f"mysportslib warm err: {_mle}")
            print(f"🔥 Cache warmer: all caches refreshed at {_t.strftime('%H:%M:%S', _t.localtime())}")
        except Exception as e:
            print(f"Cache warmer error: {e}")
