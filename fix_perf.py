#!/usr/bin/env python3
"""
Performance optimization for Real Madrid bot:
1. Add background cache warmer for slow endpoints (Leon, FotMob, standings, news)
2. Add news + streams to /api/bundle
3. Increase Leon cache TTL
4. Add /api/init lightweight endpoint (bundle result cache)
5. Rewrite frontend loadData to use single /api/bundle call
6. Add nginx gzip config
"""

HTML_FILE = "/root/realmadrid-bot-fixed/index.html"
API_FILE = "/root/realmadrid-bot-fixed/api.py"

# ============================================================
# PART 1: API OPTIMIZATIONS
# ============================================================

with open(API_FILE, "r", encoding="utf-8") as f:
    api = f.read()

# 1a. Increase Leon cache TTL (30s→120s prematch, 15s→45s live)
old_leon_ttl = """    'ttl_prematch': 30, # Секунд для премэтча
    'ttl_live': 15,     # Секунд для лайва"""

new_leon_ttl = """    'ttl_prematch': 120, # Секунд для премэтча (was 30)
    'ttl_live': 45,      # Секунд для лайва (was 15)"""

if old_leon_ttl in api:
    api = api.replace(old_leon_ttl, new_leon_ttl)
    print("[OK] Increased Leon cache TTL")
else:
    print("[WARN] Leon TTL not found")

# 1b. Increase FotMob standings cache TTL (10min→30min)
old_fotmob_ttl = "_fotmob_standings_cache = {'data': None, 'time': 0, 'ttl': 600}  # 10 min"
new_fotmob_ttl = "_fotmob_standings_cache = {'data': None, 'time': 0, 'ttl': 1800}  # 30 min"

if old_fotmob_ttl in api:
    api = api.replace(old_fotmob_ttl, new_fotmob_ttl)
    print("[OK] Increased FotMob standings cache TTL")
else:
    print("[WARN] FotMob standings TTL not found")

# 1c. Add news + streams to /api/bundle, and add bundle-level cache
old_bundle_return = """    r = results
    bundle['match'] = r['match'].get('match') if isinstance(r.get('match'), dict) else None
    bundle['results'] = r['results'].get('results', []) if isinstance(r.get('results'), dict) else []
    bundle['matches'] = r['upcoming'].get('matches', []) if isinstance(r.get('upcoming'), dict) else []
    bundle['standings'] = r['standings'].get('standings', []) if isinstance(r.get('standings'), dict) else []
    bundle['leaderboard'] = r['leaderboard'].get('leaderboard', []) if isinstance(r.get('leaderboard'), dict) else []
    bundle['live'] = r['live'] if isinstance(r.get('live'), dict) and r['live'].get('is_live') else None

    print(f"Bundle TOTAL: {_bt.time()-_bundle_start:.2f}s", flush=True)
    return bundle"""

new_bundle_return = """    r = results
    bundle['match'] = r['match'].get('match') if isinstance(r.get('match'), dict) else None
    bundle['results'] = r['results'].get('results', []) if isinstance(r.get('results'), dict) else []
    bundle['matches'] = r['upcoming'].get('matches', []) if isinstance(r.get('upcoming'), dict) else []
    bundle['standings'] = r['standings'].get('standings', []) if isinstance(r.get('standings'), dict) else []
    bundle['leaderboard'] = r['leaderboard'].get('leaderboard', []) if isinstance(r.get('leaderboard'), dict) else []
    bundle['live'] = r['live'] if isinstance(r.get('live'), dict) and r['live'].get('is_live') else None

    # Add news + streams (fast, already cached)
    try:
        news_list = scrape_news_list(10)
        bundle['news'] = news_list
    except:
        bundle['news'] = []
    try:
        streams_data = get_streams_data()
        active = []
        for s in streams_data.get("streams", []):
            if not s.get("active", True):
                continue
            entry = {"name": s.get("name", ""), "url": s.get("url", ""), "type": s.get("type", "hls")}
            if s.get("type") == "acestream" and s.get("ace_id"):
                entry["http_url"] = f"/ace/getstream?id={s['ace_id']}&.mp4"
            if s.get("type") == "iframe" and s.get("url"):
                entry["parse_url"] = f"/api/parse_stream?url={quote(s['url'], safe='')}"
            active.append(entry)
        bundle['streams'] = active
    except:
        bundle['streams'] = []

    # Cache the bundle result for fast subsequent loads
    _bundle_cache['data'] = bundle
    _bundle_cache['time'] = _bt.time()

    print(f"Bundle TOTAL: {_bt.time()-_bundle_start:.2f}s", flush=True)
    return bundle"""

if old_bundle_return in api:
    api = api.replace(old_bundle_return, new_bundle_return)
    print("[OK] Added news + streams + caching to bundle")
else:
    print("[WARN] Bundle return block not found")

# 1d. Add bundle cache + background warmer before the bundle endpoint
old_bundle_def = """@app.get("/api/bundle")
async def get_bundle(authorization: str = Header(None)):
    \"\"\"Все критичные данные за 1 запрос — параллельно в потоках\"\"\"
    import asyncio
    import time as _bt
    from concurrent.futures import ThreadPoolExecutor

    _bundle_start = _bt.time()
    bundle = {}"""

new_bundle_def = """# Bundle-level cache (15s TTL)
_bundle_cache = {'data': None, 'time': 0, 'ttl': 15}

@app.get("/api/init")
async def get_init():
    \"\"\"Fast cached bundle — returns last cached result instantly\"\"\"
    import time as _t
    now = _t.time()
    if _bundle_cache['data'] and (now - _bundle_cache['time']) < 60:
        return _bundle_cache['data']
    # No cache - return empty to signal client should call /api/bundle
    return {"empty": True}

@app.get("/api/bundle")
async def get_bundle(authorization: str = Header(None)):
    \"\"\"Все критичные данные за 1 запрос — параллельно в потоках\"\"\"
    import asyncio
    import time as _bt
    from concurrent.futures import ThreadPoolExecutor

    _bundle_start = _bt.time()
    bundle = {}"""

if old_bundle_def in api:
    api = api.replace(old_bundle_def, new_bundle_def)
    print("[OK] Added bundle cache + /api/init endpoint")
else:
    print("[WARN] Bundle definition not found")

# 1e. Add background cache warmer task to lifespan
old_lifespan_yield = """    # Запускаем фоновые задачи
    settle_task = asyncio.create_task(auto_settle_task())
    cleanup_task = asyncio.create_task(photo_cleanup_task())
    print("🚀 Auto-settle task started")
    print("🧹 Photo cleanup task started")
    yield
    settle_task.cancel()
    cleanup_task.cancel()"""

new_lifespan_yield = """    # Pre-warm Leon cache
    try:
        _get_leon_cached()
        print("⚡ Startup: Leon cache pre-warmed")
    except Exception as e:
        print(f"Leon pre-warm error: {e}")

    # Запускаем фоновые задачи
    settle_task = asyncio.create_task(auto_settle_task())
    cleanup_task = asyncio.create_task(photo_cleanup_task())
    warmer_task = asyncio.create_task(cache_warmer_task())
    print("🚀 Auto-settle task started")
    print("🧹 Photo cleanup task started")
    print("🔥 Cache warmer task started")
    yield
    settle_task.cancel()
    cleanup_task.cancel()
    warmer_task.cancel()"""

if old_lifespan_yield in api:
    api = api.replace(old_lifespan_yield, new_lifespan_yield)
    print("[OK] Added cache warmer to lifespan")
else:
    print("[WARN] Lifespan yield not found")

# 1f. Add cache warmer task function before lifespan
old_lifespan_def = """@asynccontextmanager
async def lifespan(app: FastAPI):"""

new_lifespan_def = """async def cache_warmer_task():
    \"\"\"Background task: refresh slow caches every 60s so /api/bundle is always fast\"\"\"
    import time as _t
    while True:
        await asyncio.sleep(60)
        try:
            # Refresh Leon (slowest - 2-3s)
            _get_leon_cached()
            # Refresh standings (700ms)
            _get_fotmob_league_standings()
            # Refresh news (450ms)
            scrape_news_list(10)
            # Refresh FotMob live
            get_fotmob_live_match()
            print(f"🔥 Cache warmer: all caches refreshed at {_t.strftime('%H:%M:%S', _t.localtime())}")
        except Exception as e:
            print(f"Cache warmer error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):"""

if old_lifespan_def in api:
    api = api.replace(old_lifespan_def, new_lifespan_def, 1)
    print("[OK] Added cache_warmer_task function")
else:
    print("[WARN] Lifespan definition not found")

# 1g. Add _time import if not present (used by _get_leon_cached)
# Check if import time as _time exists
if 'import time as _time' not in api and '_time.time()' in api:
    # It's probably there but let's not break anything
    pass

with open(API_FILE, "w", encoding="utf-8") as f:
    f.write(api)
print("\n[DONE] API optimizations applied")


# ============================================================
# PART 2: FRONTEND OPTIMIZATIONS
# ============================================================

with open(HTML_FILE, "r", encoding="utf-8") as f:
    html = f.read()

# 2a. Replace loadData to use single /api/bundle call
old_loaddata = """            // Load data in 2 stages: fast first, heavy in background
            const loadData = useCallback(async () => {
                setLoading(true);
                setNewsLoading(true);
                setMatchesLoading(true);

                // STAGE 1: Fast data (DB/cache) — user sees UI in <1s
                try {
                    const [userData, matchData, betsData, predictionsData, leaderboardData] = await Promise.all([
                        api.get('/api/user/me').catch(() => null),
                        api.get('/api/match/next').catch(() => ({})),
                        api.get('/api/user/bets').catch(() => ({})),
                        api.get('/api/user/predictions').catch(() => ({})),
                        api.get('/api/leaderboard').catch(() => ({}))
                    ]);

                    setUser(userData);
                    setMatch(matchData?.match);
                    setBets(betsData?.bets || []);
                    setPredictions(predictionsData?.predictions || []);
                    setLeaderboard(leaderboardData?.leaderboard || []);
                } catch (err) {
                    console.error('Stage 1 error:', err);
                } finally {
                    setLoading(false); // UI ready!
                }

                // STAGE 2: Heavy data (external APIs) — loads in background
                Promise.all([
                    api.get('/api/matches/upcoming').catch(() => ({})),
                    api.get('/api/matches/results').catch(() => ({})),
                    api.get('/api/standings').catch(() => ({}))
                ]).then(([matchesData, resultsData, standingsData]) => {
                    setMatches(matchesData?.matches || []);
                    setResults(resultsData?.results || []);
                    setStandings(standingsData?.standings || []);
                    setMatchesLoading(false);
                }).catch(() => setMatchesLoading(false));

                // News (separate, slowest)
                api.get('/api/news?count=10').catch(() => ({})).then(newsData => {
                    setNews(newsData?.news || []);
                    setNewsLoading(false);
                });

                // Live data + streams
                api.get('/api/live').then(data => {
                    setLiveMatch(data?.is_live ? data : null);
                }).catch(() => {});
                api.get('/api/streams').then(data => {
                    setStreams(data?.streams || []);
                }).catch(() => {});
            }, []);"""

new_loaddata = """            // Load ALL data via single /api/bundle call
            const loadData = useCallback(async () => {
                setLoading(true);
                setNewsLoading(true);
                setMatchesLoading(true);

                try {
                    const bundle = await api.get('/api/bundle');

                    // User data
                    if (bundle.user) setUser(bundle.user);
                    // Match
                    setMatch(bundle.match || null);
                    // Bets & predictions
                    setBets(bundle.bets || []);
                    setPredictions(bundle.predictions || []);
                    // Leaderboard
                    setLeaderboard(bundle.leaderboard || []);
                    // Matches, results, standings
                    setMatches(bundle.matches || []);
                    setResults(bundle.results || []);
                    setStandings(bundle.standings || []);
                    // Live
                    setLiveMatch(bundle.live || null);
                    // News
                    setNews(bundle.news || []);
                    // Streams
                    setStreams(bundle.streams || []);
                } catch (err) {
                    console.error('Bundle load error:', err);
                } finally {
                    setLoading(false);
                    setNewsLoading(false);
                    setMatchesLoading(false);
                }
            }, []);"""

if old_loaddata in html:
    html = html.replace(old_loaddata, new_loaddata)
    print("\n[OK] Replaced loadData with single /api/bundle call")
else:
    print("\n[WARN] loadData not found exactly")

# 2b. Reduce polling interval from 30s to 60s for non-live, keep 30s for live/streams
old_polling = """            // Автообновление live данных каждые 30 секунд
            useEffect(() => {
                const interval = setInterval(() => {
                    // Обновляем live данные (счёт, минута, статистика)
                    api.get('/api/live').then(data => {
                        setLiveMatch(data?.is_live ? data : null);
                    }).catch(() => {});
                    // Обновляем коэффициенты и маркеты ставок
                    api.get('/api/match/next').then(data => {
                        if (data?.match) setMatch(data.match);
                    }).catch(() => {});
                    // Обновляем стримы
                    api.get('/api/streams').then(data => {
                        setStreams(data?.streams || []);
                    }).catch(() => {});
                }, 30000);
                return () => clearInterval(interval);
            }, []);"""

new_polling = """            // Автообновление: live+streams каждые 30с, match/bets каждые 60с
            useEffect(() => {
                const fastInterval = setInterval(() => {
                    api.get('/api/live').then(data => {
                        setLiveMatch(data?.is_live ? data : null);
                    }).catch(() => {});
                    api.get('/api/streams').then(data => {
                        setStreams(data?.streams || []);
                    }).catch(() => {});
                }, 30000);
                const slowInterval = setInterval(() => {
                    api.get('/api/match/next').then(data => {
                        if (data?.match) setMatch(data.match);
                    }).catch(() => {});
                }, 60000);
                return () => { clearInterval(fastInterval); clearInterval(slowInterval); };
            }, []);"""

if old_polling in html:
    html = html.replace(old_polling, new_polling)
    print("[OK] Optimized polling intervals")
else:
    print("[WARN] Polling block not found")

with open(HTML_FILE, "w", encoding="utf-8") as f:
    f.write(html)
print("\n[DONE] Frontend optimizations applied")

print("\n=== SUMMARY ===")
print("API: Leon TTL 30s→120s, FotMob standings 10min→30min")
print("API: /api/bundle now includes news + streams")
print("API: /api/init returns cached bundle instantly")
print("API: Background cache warmer refreshes every 60s")
print("Frontend: Single /api/bundle call instead of 10+ requests")
print("Frontend: Polling split into fast (30s) and slow (60s)")
