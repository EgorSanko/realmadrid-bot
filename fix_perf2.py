#!/usr/bin/env python3
"""
Fix 1: Leon cache → multi-key dict (no more thrashing)
Fix 2: Bundle endpoint returns cached result if <15s old
"""

API_FILE = "/root/realmadrid-bot-fixed/api.py"

with open(API_FILE, "r", encoding="utf-8") as f:
    api = f.read()

# ============================================================
# Fix 1: Replace single-slot Leon cache with multi-key dict
# ============================================================

old_leon_cache = """_leon_cache = {
    'data': None,       # Результат get_leon_live_match
    'time': 0,          # Когда записали
    'key': '',          # Ключ кэша (opponent)
    'ttl_prematch': 120, # Секунд для премэтча (was 30)
    'ttl_live': 45,      # Секунд для лайва (was 15)
}

def _get_leon_cached(target_opponent: str = None) -> Dict:
    \"\"\"Обёртка с кэшированием запросов к Leon\"\"\"
    now = _time.time()
    cache_key = target_opponent or '__live__'

    # Проверяем кэш
    if (_leon_cache['data'] and _leon_cache['key'] == cache_key):
        is_live = _leon_cache['data'].get('is_live', False)
        ttl = _leon_cache['ttl_live'] if is_live else _leon_cache['ttl_prematch']
        age = now - _leon_cache['time']
        if age < ttl:
            print(f"Leon CACHE HIT (age={age:.0f}s, ttl={ttl}s)")
            return _leon_cache['data']

    # Кэш устарел — запрашиваем заново
    result = get_leon_live_match(target_opponent)
    _leon_cache['data'] = result
    _leon_cache['time'] = now
    _leon_cache['key'] = cache_key
    print(f"Leon CACHE MISS → fetched fresh data")
    return result"""

new_leon_cache = """_leon_cache_dict = {}  # {cache_key: {'data': ..., 'time': ...}}
_leon_ttl_prematch = 120
_leon_ttl_live = 45

def _get_leon_cached(target_opponent: str = None) -> Dict:
    \"\"\"Обёртка с кэшированием запросов к Leon (multi-key)\"\"\"
    now = _time.time()
    cache_key = target_opponent or '__live__'

    # Проверяем кэш для этого ключа
    cached = _leon_cache_dict.get(cache_key)
    if cached and cached.get('data'):
        is_live = cached['data'].get('is_live', False)
        ttl = _leon_ttl_live if is_live else _leon_ttl_prematch
        age = now - cached['time']
        if age < ttl:
            print(f"Leon CACHE HIT [{cache_key}] (age={age:.0f}s, ttl={ttl}s)")
            return cached['data']

    # Кэш устарел — запрашиваем заново
    result = get_leon_live_match(target_opponent)
    _leon_cache_dict[cache_key] = {'data': result, 'time': now}
    print(f"Leon CACHE MISS [{cache_key}] → fetched fresh data")
    return result"""

if old_leon_cache in api:
    api = api.replace(old_leon_cache, new_leon_cache)
    print("[OK] Leon cache → multi-key dict")
else:
    print("[WARN] Leon cache block not found")

# ============================================================
# Fix 2: Add bundle cache check at top of get_bundle
# ============================================================

old_bundle_top = """    _bundle_start = _bt.time()
    bundle = {}

    # User (fast — just DB lookup)
    user = None"""

new_bundle_top = """    _bundle_start = _bt.time()

    # Return cached bundle if fresh (avoid redundant heavy calls)
    if _bundle_cache['data'] and (_bt.time() - _bundle_cache['time']) < _bundle_cache['ttl']:
        # Still need to refresh user-specific data
        cached = dict(_bundle_cache['data'])
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
                    cached['predictions'] = sheets_client.get_user_predictions(user_id, limit=20)
            except:
                pass
        print(f"Bundle CACHED: {_bt.time()-_bundle_start:.2f}s", flush=True)
        return cached

    bundle = {}

    # User (fast — just DB lookup)
    user = None"""

if old_bundle_top in api:
    api = api.replace(old_bundle_top, new_bundle_top)
    print("[OK] Added bundle cache check at top")
else:
    print("[WARN] Bundle top block not found")

with open(API_FILE, "w", encoding="utf-8") as f:
    f.write(api)

print("\n[DONE] Performance fixes v2 applied")
