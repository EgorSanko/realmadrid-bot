"""
Real Madrid Bot API v1.0
REST API для Telegram Web App
"""

import os
import json
import hmac
import hashlib
import requests
import time
import time as _time  # used by various endpoints + caches
from contextlib import asynccontextmanager
import re
from urllib.parse import parse_qs, unquote, quote, urljoin
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict

from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# Moscow timezone (UTC+3)
MOSCOW_TZ = timezone(timedelta(hours=3))

def to_moscow_time(dt: datetime) -> datetime:
    """Конвертировать в московское время"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MOSCOW_TZ)

def format_moscow_time(dt: datetime, fmt: str = '%d.%m %H:%M') -> str:
    """Форматировать время по Москве"""
    return to_moscow_time(dt).strftime(fmt)

# Импортируем функции из существующей базы
from database import (
    _execute, get_or_create_user, get_user, get_user_bets, place_bet,
    get_user_predictions, make_prediction, get_leaderboard,
    can_claim_prize, claim_prize, get_global_stats, sell_bet
)

# Добавим update_balance если нет в database
try:
    from database import update_balance
except ImportError:
    def update_balance(user_id, amount, reason=""):
        """Обновить баланс пользователя"""
        user = get_user(user_id)
        if user:
            new_balance = user.get('balance', 0) + amount
            # Простое обновление через get_or_create
            from database import _execute
            _execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
            return True
        return False

from google_sheets import GoogleSheetsClient


import asyncio
from bs4 import BeautifulSoup

from src.parsers.news import (
    NEWS_SOURCE_URL, NEWS_SCRAPE_HEADERS, NEWS_SCRAPE_TTL,
    _news_scrape_cache, _article_cache,
    scrape_news_list, scrape_article,
)


from src.shared.avatars import cleanup_old_photos


from src.parsers.sofascore import (
    SOFASCORE_API, REAL_MADRID_TEAM_ID, LALIGA_TOURNAMENT_ID,
    _sofascore_headers,
    get_sofascore_live_match, get_sofascore_match_incidents,
    get_sofascore_recent_matches, get_sofascore_match_ratings,
    get_sofascore_laliga_standings, get_sofascore_player_stats,
)

from src.parsers.leon import (
    LEON_API, LEON_SOCCER_ID, _leon_headers,
    _leon_cache_dict, _leon_ttl_prematch, _leon_ttl_live,
    _get_leon_cached, _parse_leon_markets,
    TEAM_NAME_MAP,
    _YOUTH_SUFFIXES, _is_youth_match,
    get_leon_live_match,
)

# Создаём глобальный клиент
sheets_client = GoogleSheetsClient()

app = FastAPI(title="Real Madrid Bot API", version="1.0.0")


from src.routes import news as _routes_news
app.include_router(_routes_news.router)

# CORS для Web App
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене укажи конкретный домен
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BOT_TOKEN = os.getenv('TELEGRAM_TOKEN', '')

# Обработчик ошибок валидации
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"Validation error: {exc}")
    print(f"Request body: {await request.body()}")
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc.errors())}
    )


# ============ RATE LIMITING (in-memory sliding window) ============
import collections as _collections
import threading as _threading
_rate_buckets = _collections.defaultdict(_collections.deque)  # key -> deque[timestamps]
_rate_lock = _threading.Lock()

# (path_prefix, requests_per_minute, key_by) — key_by: 'ip' or 'user'
RATE_LIMITS = [
    ('/api/auth/code/request',  10, 'ip'),
    ('/api/auth/code/confirm',  30, 'ip'),
    ('/api/auth/code/check',    60, 'ip'),
    ('/api/bet/place',          30, 'user'),
    ('/api/quiz/answer',        10, 'user'),
    ('/api/quiz/question',      30, 'user'),
    ('/api/games/start',        10, 'user'),
    ('/api/games/result',       10, 'user'),
    ('/api/parse_stream',       60, 'ip'),
    ('/api/prize/claim',         5, 'user'),
    ('/api/news/article',       60, 'ip'),
]

def _client_ip_from_req(request) -> str:
    fwd = request.headers.get('x-forwarded-for', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.client.host if request.client else 'unknown'

def _rate_check(key: str, limit: int, window: int = 60) -> bool:
    """Sliding-window limiter. Returns True if allowed."""
    import time as _t
    now = _t.time()
    cutoff = now - window
    with _rate_lock:
        dq = _rate_buckets[key]
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True

@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    path = request.url.path
    for prefix, limit, by in RATE_LIMITS:
        if path.startswith(prefix):
            if by == 'ip':
                ident = _client_ip_from_req(request)
            else:
                # 'user' — key by Authorization header (Telegram initData / login widget qs)
                auth = request.headers.get('authorization', '')
                if auth:
                    ident = hashlib.md5(auth.encode()).hexdigest()[:16]
                else:
                    ident = _client_ip_from_req(request)
            key = f"{prefix}:{by}:{ident}"
            if not _rate_check(key, limit, 60):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests, slow down"}
                )
            break
    return await call_next(request)


# ============ АВТОРИЗАЦИЯ ============

from src.shared.avatars import _user_photos, _user_photos_fetched, _AVATAR_DIR, _fetch_and_save_avatar

from src.shared.tg_auth import verify_telegram_webapp, verify_telegram_login_widget


async def get_current_user(authorization: str = Header(None)) -> dict:
    """Dependency для получения текущего пользователя"""
    print(f"Authorization header: {authorization[:100] if authorization else 'None'}...")

    if not authorization:
        raise HTTPException(status_code=401, detail="No authorization header")

    user = verify_telegram_webapp(authorization)
    if not user:
        # Fall back to Telegram Login Widget signature scheme
        user = verify_telegram_login_widget(authorization)
    print(f"Verified user: {user}")

    if not user:
        raise HTTPException(status_code=401, detail="Invalid authorization")

    # Получаем или создаём пользователя в базе
    db_user = get_or_create_user(
        user_id=user['id'],
        username=user.get('username'),
        first_name=user.get('first_name'),
        last_name=user.get('last_name')
    )

    # Download avatar via Bot API for leaderboard
    if user['id'] not in _user_photos_fetched:
        _user_photos_fetched.add(user['id'])
        try:
            if _fetch_and_save_avatar(user['id']):
                _user_photos[user['id']] = True
        except Exception:
            pass

    return db_user


from src.shared.models import BetRequest, PredictionRequest, SellBetRequest, ClaimPrizeRequest


from src.cache.bundle import _bundle_cache, _build_bundle_from_caches, _build_live_markets

from src.routes import bundle as _routes_bundle
_routes_bundle.init(get_current_user)
app.include_router(_routes_bundle.router)


from src.routes import user as _routes_user
_routes_user.init(get_current_user)
app.include_router(_routes_user.router)


from src.routes import match as _routes_match
_routes_match.init()
app.include_router(_routes_match.router)


from src.parsers.fotmob import (
    # Constants
    FOTMOB_API, FOTMOB_RM_ID, _fotmob_headers,
    _FOTMOB_404_TTL, _RATINGS_CACHE_TTL, _fotmob_team_ttl,
    # Team logos / normalization
    _team_logo_map, _register_team, _normalize_team_name, _get_team_logo,
    # Caches
    _fotmob_standings_cache, _fotmob_team_cache, _fotmob_match_404_cache,
    _fotmob_buildid_cache, _fotmob_ratings_cache, _fotmob_live_cache,
    # HTTP / wrappers
    _fetch_fotmob_via_html, _get_fotmob_league_standings,
    _get_fotmob_team, _fotmob_upcoming_matches, _sheets_get_matches_with_fallback,
    _get_fotmob_buildid, _get_fotmob_match,
    _get_match_ratings, _match_details_cache, _MATCH_DETAILS_TTL_FINISHED, _MATCH_DETAILS_TTL_LIVE, _analytics_cache,
    get_fotmob_live_match, get_fotmob_recent_matches,
    # Pure parsers (already there since prior extraction)
    _parse_fotmob_form, _parse_fotmob_h2h, _find_next_fotmob_match,
    _parse_fotmob_match_stats, _parse_fotmob_lineups,
    _parse_fotmob_live_match, _parse_fotmob_events, _parse_fotmob_stats,
    _parse_fotmob_momentum, _parse_fotmob_shotmap,
)
sheets_client.get_matches = _sheets_get_matches_with_fallback
sheets_client.get_results = lambda *a, **k: []
sheets_client.get_odds = lambda *a, **k: {}
sheets_client.get_standings = lambda *a, **k: []
print('FotMob fallback wired into sheets_client.get_matches', flush=True)


from src.parsers.youtube import _yt_cache, _find_youtube_highlight


from src.services.anti_arb import _is_arb_against_existing


_leaderboard_cache = {'data': None, 'time': 0, 'limit': 0, 'ttl': 15}

from src.routes import leaderboard as _routes_leaderboard
_routes_leaderboard.init(_AVATAR_DIR)
app.include_router(_routes_leaderboard.router)
from src.routes import match_data as _routes_match_data
_routes_match_data.init()
app.include_router(_routes_match_data.router)
from src.routes import stream_proxy as _routes_stream_proxy
_routes_stream_proxy.init()
app.include_router(_routes_stream_proxy.router)
from src.routes import live as _routes_live
_routes_live.init()
app.include_router(_routes_live.router)
from src.routes import files as _routes_files
_routes_files.init()
app.include_router(_routes_files.router)


from src.routes import prizes as _routes_prizes
_routes_prizes.init(get_current_user, ClaimPrizeRequest)
app.include_router(_routes_prizes.router)


from src.shared.quiz_state import (
    QUIZ_QUESTIONS, QUIZ_POINTS, GAME_POINTS,
    quiz_cooldowns, quiz_question_started, quiz_asked_questions, _game_sessions,
    _get_last_game_time, _set_cooldown,
    load_quiz_questions,
)


from src.services.settlement import (
    _settled_matches,
    get_match_statistics, _ou_check, settle_bet_by_type,
    _notify_settled_bet, _notify_admins_settle,
    get_match_statistics_fotmob, _resolve_leon_bet_to_fotmob,
    settle_all_bets_advanced,
    auto_settle_task,
)


from src.cache.warmer import (
    photo_cleanup_task,
    _warmer_blocking_pass, _collect_warm_match_ids,
    warm_match_details_pass, live_warmer_task, cache_warmer_task,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-fetch standings to populate team logo map
    try:
        standings = _get_fotmob_league_standings()
        print(f"🏆 Startup: {len(standings)} standings teams, {len(_team_logo_map)} logos cached")
        # If standings empty, they'll be populated from team page fallback in _get_fotmob_league_standings

        # Also pre-fetch RM team data for fixtures logos
        team_data = _get_fotmob_team(FOTMOB_RM_ID)
        if team_data:
            for f in team_data.get('overview', {}).get('overviewFixtures', []):
                _register_team(f.get('home', {}).get('name', ''), f.get('home', {}).get('id'))
                _register_team(f.get('away', {}).get('name', ''), f.get('away', {}).get('id'))
            print(f"⚽ Startup: fixtures logos cached, total {len(_team_logo_map)} teams")
    except Exception as e:
        import traceback; traceback.print_exc(); print(f"Startup pre-fetch error: {e}")

    # Pre-warm LiveBall schedule
    try:
        lb_matches = _parse_liveball_schedule()
        print(f"\U0001f4fa Startup: {len(lb_matches)} LiveBall matches cached")
    except Exception as e:
        print(f"LiveBall pre-warm error: {e}")

    # Pre-warm news cache
    try:
        news = scrape_news_list(10)
        print(f"📰 Startup: {len(news)} news cached")
    except Exception as e:
        print(f"News pre-warm error: {e}")

    # Pre-warm Leon cache (both live + prematch)
    try:
        _get_leon_cached()
        matches = sheets_client.get_matches(limit=1)
        if matches:
            opp = matches[0].get('opponent', '')
            if opp:
                _get_leon_cached(target_opponent=opp)
        print("⚡ Startup: Leon cache pre-warmed (live + prematch)")
    except Exception as e:
        print(f"Leon pre-warm error: {e}")

    # Pre-warm bundle cache
    try:
        _warm_data = _build_bundle_from_caches()
        _warm_data['user'] = None
        _warm_data['bets'] = []
        _warm_data['predictions'] = []
        _bundle_cache['data'] = _warm_data
        import time as _st
        _bundle_cache['time'] = _st.time()
        print("📦 Startup: Bundle cache pre-warmed")
    except Exception as e:
        print(f"Bundle pre-warm error: {e}")

    # Запускаем фоновые задачи
    settle_task = asyncio.create_task(auto_settle_task())
    cleanup_task = asyncio.create_task(photo_cleanup_task())
    warmer_task = asyncio.create_task(cache_warmer_task())
    live_warmer = asyncio.create_task(live_warmer_task())
    print("🚀 Auto-settle task started")
    print("🧹 Photo cleanup task started")
    print("🔥 Cache warmer task started")
    print("⚡ Live warmer (1.5s) started")
    yield
    settle_task.cancel()
    cleanup_task.cancel()
    warmer_task.cancel()
    live_warmer.cancel()

app.router.lifespan_context = lifespan


from fastapi.responses import FileResponse


# ============ АДМИНКА ============

ADMIN_IDS = [1697882482]  # Список админов

from src.shared.models import AdminAddBalanceRequest

from src.routes import admin as _routes_admin
_routes_admin.init(get_current_user, AdminAddBalanceRequest)
app.include_router(_routes_admin.router)
from src.routes import streams as _routes_streams
_routes_streams.init()
app.include_router(_routes_streams.router)
from src.routes import bets as _routes_bets
_routes_bets.init(get_current_user, BetRequest, PredictionRequest, SellBetRequest, MOSCOW_TZ)
app.include_router(_routes_bets.router)
from src.routes import hls as _routes_hls
_routes_hls.init()
app.include_router(_routes_hls.router)
from src.routes import auth as _routes_auth
_routes_auth.init()
app.include_router(_routes_auth.router)
from src.routes import debug as _routes_debug
_routes_debug.init()
app.include_router(_routes_debug.router)
from src.routes import games as _routes_games
_routes_games.init(get_current_user)
app.include_router(_routes_games.router)


from src.shared.purchases_io import PURCHASES_FILE, RECEIPTS_DIR, PURCHASE_CONFIG, _load_purchases, _save_purchases


from src.routes import purchases as _routes_purchases
_routes_purchases.init(get_current_user)
app.include_router(_routes_purchases.router)


from src.shared.streams_io import STREAMS_FILE, get_streams_data


from src.parsers.liveball import (
    _liveball_schedule_cache, _LIVEBALL_HEADERS, _LIVEBALL_TEAM_ID,
    _liveball_mirrors, _liveball_domain_cache,
    _get_liveball_domain, _parse_liveball_schedule,
)


from src.routes import referral as _routes_referral
_routes_referral.init(get_current_user)
app.include_router(_routes_referral.router)


from src.services.referral_bonus import process_referral_bonus


# ============ ЗАПУСК ============


import time as _stream_time
_stream_viewers = {}  # client_id -> last_ping_ts
_VIEWER_TTL = 30  # seconds

from src.shared.models import _HeartbeatReq


from src.parsers.footybite import (
    _FOOTYBITE_BASE, _footybite_cache, _FOOTYBITE_TTL,
    _fb_fetch, _footybite_schedule_parse,
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
