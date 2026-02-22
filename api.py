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

# VK API для новостей
VK_GROUP_ID = 'realmadrid_news'
VK_SERVICE_KEY = os.getenv('VK_SERVICE_KEY', '283d7513283d7513283d75134e2b0323c52283d283d75134162b3f895b21d240a353119')

def get_vk_news(count: int = 5, filter_keywords: List[str] = None) -> List[Dict]:
    """Получить последние посты из VK группы Real Madrid"""
    try:
        url = "https://api.vk.com/method/wall.get"
        params = {
            'domain': VK_GROUP_ID,
            'count': 50,
            'v': '5.131',
            'access_token': VK_SERVICE_KEY
        }

        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if 'error' in data:
            print(f"VK API error: {data['error']}")
            return []

        if 'response' not in data:
            return []

        posts = []
        for item in data['response'].get('items', []):
            text = item.get('text', '')

            if not text or len(text) < 10:
                continue

            # Фильтрация по ключевым словам
            if filter_keywords:
                text_lower = text.lower()
                if not any(kw.lower() in text_lower for kw in filter_keywords):
                    continue

            post_id = item.get('id')
            owner_id = item.get('owner_id')
            date = datetime.fromtimestamp(item.get('date', 0))

            # Получаем медиа
            photo_url = None
            video_url = None
            media_type = 'text'

            if 'attachments' in item:
                for att in item['attachments']:
                    if att['type'] == 'photo' and not photo_url:
                        sizes = att['photo'].get('sizes', [])
                        if sizes:
                            best = max(sizes, key=lambda x: x.get('width', 0) * x.get('height', 0))
                            photo_url = best.get('url')
                            media_type = 'photo'
                    elif att['type'] == 'video' and not video_url:
                        video = att.get('video', {})
                        video_id = video.get('id')
                        video_owner = video.get('owner_id')
                        if video_id and video_owner:
                            video_url = f"https://vk.com/video{video_owner}_{video_id}"
                            images = video.get('image', [])
                            if images:
                                photo_url = images[-1].get('url')
                            media_type = 'video'

            posts.append({
                'text': text[:500] + ('...' if len(text) > 500 else ''),
                'date': date.strftime('%d.%m %H:%M'),
                'url': f"https://vk.com/wall{owner_id}_{post_id}",
                'photo_url': photo_url,
                'video_url': video_url,
                'media_type': media_type
            })

            if len(posts) >= count:
                break

        return posts

    except Exception as e:
        print(f"VK parse error: {e}")
        return []

def get_vk_lineups() -> List[Dict]:
    """Заглушка для совместимости"""
    return []


# ============ TELEGRAM CHANNEL PARSER (TELETHON) ============

import asyncio
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto

# API credentials
TG_API_ID = int(os.getenv('TG_API_ID', '34185547'))
TG_API_HASH = os.getenv('TG_API_HASH', '643cd6834f58c6756392a8d7128ebf7b')
TG_SESSION_PATH = '/app/data/tg_session'
TG_CHANNEL = 'realmadridcdf'

# Global client and lock
_tg_client = None
_tg_lock = asyncio.Lock()

# Cache for results
_tg_cache = {
    'news': {'data': [], 'time': 0},
    'lineups': {'data': [], 'time': 0},
    'ratings': {'data': [], 'time': 0}
}
CACHE_TTL = 900  # 15 minutes - reduce Telethon DB lock contention


async def get_tg_client():
    """Get or create Telethon client"""
    global _tg_client
    if _tg_client is None:
        _tg_client = TelegramClient(TG_SESSION_PATH, TG_API_ID, TG_API_HASH)
        await _tg_client.connect()
        if not await _tg_client.is_user_authorized():
            print("❌ Telethon not authorized!")
            return None
        print("✅ Telethon client connected")
    return _tg_client


async def get_telegram_messages(limit: int = 50, filter_keywords: list = None) -> List[Dict]:
    """Получить сообщения из канала через Telethon"""
    max_retries = 3
    for attempt in range(max_retries):
        async with _tg_lock:
            try:
                client = await get_tg_client()
                if not client:
                    return []

                # Создаём папки для медиа
                photo_dir = '/app/data/photos'
                video_dir = '/app/data/videos'
                os.makedirs(photo_dir, exist_ok=True)
                os.makedirs(video_dir, exist_ok=True)

                posts = []
                async for message in client.iter_messages(TG_CHANNEL, limit=limit):
                    if not message.text:
                        continue

                    text = message.text

                    # Фильтрация по ключевым словам
                    if filter_keywords:
                        found = False
                        for kw in filter_keywords:
                            if kw in text:
                                found = True
                                break
                        if not found:
                            continue

                    # Определяем тип медиа
                    photo_url = None
                    video_url = None
                    has_media = message.media is not None
                    media_type = 'text'

                    if has_media:
                        if isinstance(message.media, MessageMediaPhoto):
                            # Фото - скачиваем
                            media_type = 'photo'
                            try:
                                photo_path = f'{photo_dir}/{message.id}.jpg'
                                if not os.path.exists(photo_path):
                                    await client.download_media(message.media, photo_path)
                                    print(f"Downloaded photo: {message.id}.jpg")
                                photo_url = f'/api/photo/{message.id}.jpg'
                            except Exception as e:
                                print(f"Photo download error: {e}")
                        elif hasattr(message.media, 'document'):
                            # Проверяем, это видео или нет
                            doc = message.media.document
                            if doc and hasattr(doc, 'mime_type') and doc.mime_type and doc.mime_type.startswith('video'):
                                media_type = 'video'

                                # Скачиваем видео
                                try:
                                    video_path = f'{video_dir}/{message.id}.mp4'
                                    if not os.path.exists(video_path):
                                        print(f"Downloading video: {message.id}.mp4 ...")
                                        await client.download_media(message.media, video_path)
                                        print(f"Downloaded video: {message.id}.mp4")
                                    video_url = f'/api/video/{message.id}.mp4'
                                except Exception as e:
                                    print(f"Video download error: {e}")
                                    video_url = f"https://t.me/{TG_CHANNEL}/{message.id}"

                                # Пробуем получить превью видео
                                if hasattr(doc, 'thumbs') and doc.thumbs:
                                    try:
                                        thumb_path = f'{photo_dir}/thumb_{message.id}.jpg'
                                        if not os.path.exists(thumb_path):
                                            await client.download_media(message.media, thumb_path, thumb=-1)
                                            print(f"Downloaded video thumb: thumb_{message.id}.jpg")
                                        photo_url = f'/api/photo/thumb_{message.id}.jpg'
                                    except Exception as e:
                                        print(f"Video thumb error: {e}")

                    posts.append({
                        'id': message.id,
                        'text': text[:500] + ('...' if len(text) > 500 else ''),
                        'date': format_moscow_time(message.date),
                        'date_timestamp': message.date.timestamp(),
                        'url': f"https://t.me/{TG_CHANNEL}/{message.id}",
                        'photo_url': photo_url,
                        'video_url': video_url,
                        'has_media': has_media,
                        'media_type': media_type
                    })

                # Сортируем по дате - новые первые
                posts = sorted(posts, key=lambda x: x.get('date_timestamp', 0), reverse=True)
                print(f"TG Telethon: Found {len(posts)} posts (filter: {filter_keywords})")
                return posts

            except Exception as e:
                print(f"TG Telethon error (attempt {attempt+1}/{max_retries}): {e}")
                if 'database is locked' in str(e) and attempt < max_retries - 1:
                    import asyncio as _aio
                    await _aio.sleep(1)
                    continue
                return []
    return []


async def cleanup_old_photos():
    """Удалить старые медиа файлы"""
    import time
    import time; now = time.time()

    # Очистка фото (старше 1 часа)
    photo_dir = '/app/data/photos'
    if os.path.exists(photo_dir):
        for filename in os.listdir(photo_dir):
            filepath = os.path.join(photo_dir, filename)
            try:
                if os.path.isfile(filepath):
                    file_age = now - os.path.getmtime(filepath)
                    if file_age > 3600:  # 1 час
                        os.remove(filepath)
                        print(f"Deleted old photo: {filename}")
            except Exception as e:
                print(f"Cleanup error: {e}")

    # Очистка видео (старше 2 часов)
    video_dir = '/app/data/videos'
    if os.path.exists(video_dir):
        for filename in os.listdir(video_dir):
            filepath = os.path.join(video_dir, filename)
            try:
                if os.path.isfile(filepath):
                    file_age = now - os.path.getmtime(filepath)
                    if file_age > 7200:  # 2 часа
                        os.remove(filepath)
                        print(f"Deleted old video: {filename}")
            except Exception as e:
                print(f"Video cleanup error: {e}")


async def get_telegram_news_async(count: int = 10) -> List[Dict]:
    """Получить последние новости с кэшированием"""
    import time
    import time; now = time.time()

    # Проверяем кэш
    if _tg_cache['news']['data'] and (now - _tg_cache['news']['time']) < CACHE_TTL:
        return _tg_cache['news']['data'][:count]

    posts = await get_telegram_messages(limit=count * 2)
    result = posts[:count]

    # Сохраняем в кэш
    _tg_cache['news']['data'] = result
    _tg_cache['news']['time'] = now

    return result


async def get_telegram_lineups_async() -> List[Dict]:
    """Получить стартовые составы с кэшированием"""
    import time
    import time; now = time.time()

    if _tg_cache['lineups']['data'] and (now - _tg_cache['lineups']['time']) < CACHE_TTL:
        return _tg_cache['lineups']['data']

    result = await get_telegram_messages(limit=100, filter_keywords=['СТАРТОВЫЙ СОСТАВ'])

    _tg_cache['lineups']['data'] = result
    _tg_cache['lineups']['time'] = now

    return result


async def get_telegram_ratings_async() -> List[Dict]:
    """Получить оценки игроков с кэшированием"""
    import time
    import time; now = time.time()

    if _tg_cache['ratings']['data'] and (now - _tg_cache['ratings']['time']) < CACHE_TTL:
        return _tg_cache['ratings']['data']

    result = await get_telegram_messages(limit=100, filter_keywords=['Оценки за матч от SofaScore'])

    _tg_cache['ratings']['data'] = result
    _tg_cache['ratings']['time'] = now

    return result


# ============ SOFASCORE API ============

SOFASCORE_API = "https://api.sofascore.com/api/v1"
REAL_MADRID_TEAM_ID = 2829
LALIGA_TOURNAMENT_ID = 8  # La Liga

_sofascore_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# ============ LEON LIVE ODDS ============

LEON_API = "https://leon.ru/api-2/betline"
LEON_SOCCER_ID = 1970324836974595

_leon_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Origin': 'https://leon.ru',
    'Referer': 'https://leon.ru/',
}

# === КЭШИРОВАНИЕ LEON ===
import time as _time

_leon_cache = {
    'data': None,       # Результат get_leon_live_match
    'time': 0,          # Когда записали
    'key': '',          # Ключ кэша (opponent)
    'ttl_prematch': 30, # Секунд для премэтча
    'ttl_live': 15,     # Секунд для лайва
}

def _get_leon_cached(target_opponent: str = None) -> Dict:
    """Обёртка с кэшированием запросов к Leon"""
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
    return result

def _parse_leon_markets(markets: list) -> Dict:
    """Универсальный парсер ВСЕХ рынков Leon API"""
    odds = {}
    open_markets = 0

    def _ou(runners, prefix):
        """Парсим Больше/Меньше"""
        for r in runners:
            if not r.get('open', True) or not r.get('price'): continue
            rn, p = r.get('name', ''), r.get('price', 0)
            if not p or p <= 1 or p > 50: continue
            if 'Больше' in rn:
                line = rn.replace('Больше', '').replace('(', '').replace(')', '').strip()
                odds[f'{prefix}_over_{line}'] = p
            elif 'Меньше' in rn:
                line = rn.replace('Меньше', '').replace('(', '').replace(')', '').strip()
                odds[f'{prefix}_under_{line}'] = p

    def _12(runners, p1, p2):
        """Парсим 1/2 (фора)"""
        for r in runners:
            if not r.get('open', True) or not r.get('price'): continue
            rn, p = r.get('name', ''), r.get('price', 0)
            if not p or p <= 1 or p > 50: continue
            if rn.startswith('1'):
                line = rn.replace('1', '', 1).replace('(', '').replace(')', '').strip()
                odds[f'{p1}_{line}'] = p
            elif rn.startswith('2'):
                line = rn.replace('2', '', 1).replace('(', '').replace(')', '').strip()
                odds[f'{p2}_{line}'] = p

    for market in markets:
        mn_orig = market.get('name', '')
        runners = market.get('runners', [])
        mn = mn_orig.lower()

        if not market.get('open', True): continue

        # === ТОЧНЫЙ СЧЁТ (до основного skip-фильтра) ===
        if ('точный счет' in mn or 'точный счёт' in mn) and 'тайм' not in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if not p or p <= 1 or p > 50: continue
                if ':' in rn:
                    parts = rn.split(':')
                    if len(parts) == 2:
                        h_s, a_s = parts[0].strip(), parts[1].strip()
                        if h_s.isdigit() and a_s.isdigit():
                            odds[f'score_{h_s}-{a_s}'] = p
            open_markets += 1
            continue

        # === ЧЁТ/НЕЧЁТ ТОТАЛ ГОЛОВ (до основного skip-фильтра) ===
        if 'чет' in mn and 'нечет' in mn and 'тайм' not in mn and 'угловы' not in mn and 'карточ' not in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', '').lower(), r.get('price', 0)
                if not p or p <= 1 or p > 50: continue
                if rn in ('чет', 'чёт'):
                    odds['total_even'] = p
                elif rn in ('нечет', 'нечёт'):
                    odds['total_odd'] = p
            open_markets += 1
            continue

        # Пропускаем таймы и экзотику
        if 'тайм' in mn or 'половин' in mn or 'точн' in mn or 'чет/нечет' in mn: continue

        # === ИСХОД 1X2 ===
        if 'исход' in mn and ('1х2' in mn or '1x2' in mn):
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if p and p > 1 and p <= 50:
                    if rn == '1': odds['home'] = p
                    elif rn in ('X', 'Х'): odds['draw'] = p
                    elif rn == '2': odds['away'] = p
            open_markets += 1

        # === ДВОЙНОЙ ШАНС/ИСХОД (не угловые) ===
        elif 'двойной' in mn and ('шанс' in mn or 'исход' in mn) and 'угловы' not in mn and 'карточ' not in mn and 'желт' not in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if p and p > 1 and p <= 50:
                    if rn in ('1X', '1Х'): odds['dc_1x'] = p
                    elif rn in ('X2', 'Х2'): odds['dc_x2'] = p
                    elif rn == '12': odds['dc_12'] = p
            open_markets += 1

        # === ОБЕ ЗАБЬЮТ ===
        elif 'обе' in mn and 'забь' in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if p and p > 1 and p <= 50:
                    if rn == 'Да': odds['btts_yes'] = p
                    elif rn == 'Нет': odds['btts_no'] = p
            open_markets += 1

        # === РЕЗУЛЬТАТ НЕ ВКЛЮЧАЯ НИЧЬЮ ===
        elif 'результат' in mn and 'ничью' in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if p and p > 1 and p <= 50:
                    if rn == '1': odds['dnb_home'] = p
                    elif rn == '2': odds['dnb_away'] = p
            open_markets += 1

        # === КТО ЗАБЬЁТ ПЕРВЫЙ ГОЛ ===
        elif ('первый гол' in mn or '1-й гол' in mn) and 'как ' not in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if p and p > 1 and p <= 50:
                    if rn == '1': odds['first_goal_home'] = p
                    elif rn == '2': odds['first_goal_away'] = p
                    elif 'не будет' in rn.lower(): odds['first_goal_none'] = p
            open_markets += 1

        # === ПЕНАЛЬТИ ===
        elif 'пенал' in mn and 'будет' in mn and 'серия' not in mn and 'команда' not in mn:
            for r in runners:
                if not r.get('open', True) or not r.get('price'): continue
                rn, p = r.get('name', ''), r.get('price', 0)
                if not p or p <= 1 or p > 50: continue
                if rn == 'Да': odds['penalty_yes'] = p
                elif rn == 'Нет': odds['penalty_no'] = p
            open_markets += 1

        # === УГЛОВЫЕ ===
        elif 'угловы' in mn:
            if any(x in mn for x in ['кто', 'фора', 'двойной', 'чет', 'точн']): continue
            if 'хозяев' in mn: _ou(runners, 'corners_home')
            elif 'гостей' in mn: _ou(runners, 'corners_away')
            else: _ou(runners, 'corners')
            open_markets += 1

        # === КАРТОЧКИ (включая жёлтые) ===
        elif 'карточ' in mn or ('желт' in mn and 'тотал' in mn):
            if any(x in mn for x in ['кто', 'фора', 'чет', 'точн']): continue
            if 'хозяев' in mn: _ou(runners, 'cards_home')
            elif 'гостей' in mn: _ou(runners, 'cards_away')
            else: _ou(runners, 'cards')
            open_markets += 1

        # === ФОРА (обычная, не угловые) ===
        elif mn == 'фора' or ('фора' in mn and 'азиат' not in mn and 'угловы' not in mn):
            _12(runners, 'handicap_home', 'handicap_away')
            open_markets += 1

        # === ТОТАЛ ХОЗЯЕВ (только голы) ===
        elif 'тотал' in mn and 'хозяев' in mn and 'угловы' not in mn and 'карточ' not in mn and 'удар' not in mn and 'фол' not in mn and 'офсайд' not in mn and 'аут' not in mn:
            _ou(runners, 'home')
            open_markets += 1

        # === ТОТАЛ ГОСТЕЙ (только голы) ===
        elif 'тотал' in mn and 'гостей' in mn and 'угловы' not in mn and 'карточ' not in mn and 'удар' not in mn and 'фол' not in mn and 'офсайд' not in mn and 'аут' not in mn:
            _ou(runners, 'away')
            open_markets += 1

        # === ТОТАЛ ГОЛОВ (общий) — ТОЛЬКО точные названия ===
        elif mn in ('тотал', 'тотал голов', 'тотал матча'):
            _ou(runners, 'total')
            open_markets += 1
        elif 'тотал' in mn and 'хозяев' not in mn and 'гостей' not in mn and 'угловы' not in mn and 'карточ' not in mn:
            # Логируем что пропускаем — для дебага
            print(f"Leon SKIPPED unknown total market: '{mn_orig}'")

    print(f"Leon parsed: {len(odds)} odds, {open_markets} markets")
    # Log corners and cards specifically
    special = {k: v for k, v in odds.items() if any(x in k for x in ['corners', 'cards', 'dnb', 'first_goal', 'penalty', 'score_', 'total_even', 'total_odd'])}
    if special:
        print(f"Leon special markets: {special}")
    return {'odds': odds, 'open_markets': open_markets}


TEAM_NAME_MAP = {
    'Пари Сен-Жермен': 'ПСЖ',
    'Пари Сен Жермен': 'ПСЖ',
    'Paris Saint-Germain': 'ПСЖ',
    'Paris Saint Germain': 'ПСЖ',
    'Paris SG': 'ПСЖ',
    'Париж': 'ПСЖ',
    'Атлетико': 'Атлетико Мадрид',
    'Бавария Мюнхен': 'Бавария',
    'Манчестер Сити': 'Ман Сити',
    'Манчестер Юнайтед': 'Ман Юнайтед',
    'Боруссия Дортмунд': 'Дортмунд',
    'Интер Милан': 'Интер',
    'Интернационале': 'Интер',
}

def _normalize_team_name(name: str) -> str:
    """Нормализуем названия команд"""
    if not name:
        return name
    # Точное совпадение
    if name in TEAM_NAME_MAP:
        return TEAM_NAME_MAP[name]
    # Частичное
    for key, val in TEAM_NAME_MAP.items():
        if key.lower() in name.lower():
            return val
    return name


def get_leon_live_match(target_opponent: str = None) -> Dict:
    """Получить матч Real Madrid с полными коэффициентами из Leon (двухшаговый запрос)
    target_opponent: если указан, ищем конкретный матч по сопернику
    """
    try:
        # ШАГ 1: Находим событие Real Madrid через /events/all
        url = f'{LEON_API}/events/all?ctag=ru-RU&sport_id={LEON_SOCCER_ID}&hideClosed=true&flags=reg,urlv2,mm2,rrc,nodup'
        response = requests.get(url, headers=_leon_headers, timeout=15)

        if response.status_code != 200:
            return {'is_live': False}

        data = response.json()
        events = data.get('events', [])
        # Сортируем: live матчи первыми
        events.sort(key=lambda e: (e.get('betline') != 'inplay', e.get('kickoff', 0)))

        leon_event = None
        leon_event_fallback = None
        for event in events:
            name = event.get('name', '')
            name_default = event.get('nameDefault', '')
            # Пропускаем киберспорт (там скобки с никами)
            if '(' in name:
                continue
            if 'Real Madrid' in name_default and '?' not in name and ' - ' in name:
                # Если ищем конкретного соперника
                if target_opponent:
                    opp_lower = target_opponent.lower()
                    name_lower = name.lower() + ' ' + name_default.lower()
                    # Убираем "real" и "madrid" из поиска (они есть в каждом матче RM)
                    skip_words = {'real', 'madrid', 'fc', 'cf', 'club'}
                    opp_words = [w for w in opp_lower.split() if len(w) > 3 and w not in skip_words]
                    # Проверяем совпадение: полное имя ИЛИ ключевые слова соперника
                    if opp_lower in name_lower or (opp_words and any(word in name_lower for word in opp_words)):
                        leon_event = event
                        break
                    else:
                        if not leon_event_fallback:
                            leon_event_fallback = event
                else:
                    leon_event = event
                    break

        # Если не нашли конкретного соперника, НЕ используем фолбэк для prematch
        # (чтобы не показывать ПСЖ вместо Sociedad)
        if not leon_event and target_opponent:
            print(f"Leon: opponent '{target_opponent}' not found, skipping (fallback was: {leon_event_fallback.get('name') if leon_event_fallback else 'none'})")
            return {'is_live': False}
        if not leon_event:
            leon_event = leon_event_fallback

        if not leon_event:
            return {'is_live': False}

        event_id = leon_event.get('id')
        is_live = leon_event.get('betline') == 'inplay' or leon_event.get('matchPhase') == 'IN_PLAY'

        # Парсим команды
        name = leon_event.get('name', '')
        teams = name.split(' - ')
        home_team = _normalize_team_name(teams[0].strip() if len(teams) > 0 else '')
        away_team = _normalize_team_name(teams[1].strip() if len(teams) > 1 else '')

        # ШАГ 2: Получаем ПОЛНЫЕ рынки через /event/all?eventId={id}
        detail_url = f'{LEON_API}/event/all?ctag=ru-RU&eventId={event_id}&flags=reg,urlv2,mm2,rrc,nodup'
        detail_resp = requests.get(detail_url, headers=_leon_headers, timeout=15)

        odds = {}
        open_markets = 0
        bets_suspended = False

        if detail_resp.status_code == 200:
            detail_data = detail_resp.json()
            markets = detail_data.get('markets', [])
            parsed = _parse_leon_markets(markets)
            odds = parsed['odds']
            open_markets = parsed['open_markets']
            print(f"Leon detail API: {len(markets)} markets, {len(odds)} odds parsed, open={open_markets}")
        else:
            # Фолбэк - используем данные из events/all (менее точные)
            markets = leon_event.get('markets', [])
            parsed = _parse_leon_markets(markets)
            odds = parsed['odds']
            open_markets = parsed['open_markets']
            print(f"Leon fallback: {len(markets)} markets, {len(odds)} odds")

        # Если live и нет открытых рынков - ставки suspended
        if is_live and (len(odds) == 0 or open_markets == 0):
            bets_suspended = True

        return {
            'is_live': is_live,
            'bets_suspended': bets_suspended,
            'leon_id': event_id,
            'home_team': home_team,
            'away_team': away_team,
            'name_default': leon_event.get('nameDefault', ''),
            'kickoff': leon_event.get('kickoff'),
            'live_odds': odds,
            'markets_count': open_markets,
            'open_markets': open_markets,
            'liveStatus': leon_event.get('liveStatus'),
            'score': leon_event.get('liveStatus', {}).get('score') if leon_event.get('liveStatus') else None,
            'minute': leon_event.get('liveStatus', {}).get('progress') if leon_event.get('liveStatus') else None,
            'stage': leon_event.get('liveStatus', {}).get('stage') if leon_event.get('liveStatus') else None,
            'home_stats': leon_event.get('liveStatus', {}).get('homeStatistics') if leon_event.get('liveStatus') else None,
            'away_stats': leon_event.get('liveStatus', {}).get('awayStatistics') if leon_event.get('liveStatus') else None
        }

    except Exception as e:
        print(f"Leon API error: {e}")
        import traceback
        traceback.print_exc()
        return {'is_live': False, 'error': str(e)}

def get_sofascore_live_match() -> Dict:
    """Получить текущий LIVE матч Real Madrid (счёт, события)"""
    try:
        # Получаем следующие/текущие матчи
        url = f"{SOFASCORE_API}/team/{REAL_MADRID_TEAM_ID}/events/next/0"
        response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            return None

        data = response.json()
        events = data.get('events', [])

        for event in events:
            status = event.get('status', {})
            status_type = status.get('type', '')

            # inprogress = матч идёт сейчас
            if status_type == 'inprogress':
                home_team = event.get('homeTeam', {}).get('name', '')
                away_team = event.get('awayTeam', {}).get('name', '')
                home_score = event.get('homeScore', {}).get('current', 0)
                away_score = event.get('awayScore', {}).get('current', 0)

                # Минута матча
                minute = status.get('description', '')

                # Турнир
                tournament = event.get('tournament', {}).get('name', 'La Liga')

                # События матча (голы, карточки)
                match_id = event.get('id')
                incidents = get_sofascore_match_incidents(match_id) if match_id else []

                return {
                    'is_live': True,
                    'match_id': match_id,
                    'home_team': home_team,
                    'away_team': away_team,
                    'home_score': home_score,
                    'away_score': away_score,
                    'minute': minute,
                    'tournament': tournament,
                    'status': status_type,
                    'incidents': incidents,
                    'sofascore_url': f'https://www.sofascore.com/match/{match_id}'
                }

        return {'is_live': False}

    except Exception as e:
        print(f"SofaScore live error: {e}")
        return {'is_live': False, 'error': str(e)}


def get_sofascore_match_incidents(match_id: int) -> List[Dict]:
    """Получить события матча (голы, карточки, замены)"""
    try:
        url = f"{SOFASCORE_API}/event/{match_id}/incidents"
        response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        incidents = data.get('incidents', [])

        result = []
        for inc in incidents:
            inc_type = inc.get('incidentType', '')

            if inc_type == 'goal':
                result.append({
                    'type': 'goal',
                    'minute': inc.get('time', 0),
                    'player': inc.get('player', {}).get('name', ''),
                    'assist': inc.get('assist1', {}).get('name', '') if inc.get('assist1') else None,
                    'home': inc.get('isHome', False),
                    'score': f"{inc.get('homeScore', 0)}-{inc.get('awayScore', 0)}"
                })
            elif inc_type == 'card':
                card_type = inc.get('incidentClass', '')
                result.append({
                    'type': 'yellow' if card_type == 'yellow' else 'red',
                    'minute': inc.get('time', 0),
                    'player': inc.get('player', {}).get('name', ''),
                    'home': inc.get('isHome', False)
                })
            elif inc_type == 'substitution':
                result.append({
                    'type': 'sub',
                    'minute': inc.get('time', 0),
                    'player_in': inc.get('playerIn', {}).get('name', ''),
                    'player_out': inc.get('playerOut', {}).get('name', ''),
                    'home': inc.get('isHome', False)
                })

        return result

    except Exception as e:
        print(f"SofaScore incidents error: {e}")
        return []

def get_sofascore_recent_matches() -> List[Dict]:
    """Получить недавние матчи Real Madrid из SofaScore"""
    try:
        url = f"{SOFASCORE_API}/team/{REAL_MADRID_TEAM_ID}/events/last/0"
        response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        events = data.get('events', [])

        finished_matches = []
        for event in events[:10]:  # Последние 10
            status = event.get('status', {}).get('type', '')
            if status == 'finished':
                match_id = event.get('id')
                home_team = event.get('homeTeam', {}).get('name', '')
                away_team = event.get('awayTeam', {}).get('name', '')
                home_score = event.get('homeScore', {}).get('current', 0)
                away_score = event.get('awayScore', {}).get('current', 0)
                start_time = event.get('startTimestamp', 0)

                finished_matches.append({
                    'matchId': str(match_id),
                    'homeTeam': home_team,
                    'awayTeam': away_team,
                    'homeScore': home_score,
                    'awayScore': away_score,
                    'date': datetime.fromtimestamp(start_time).strftime('%d.%m.%Y'),
                    'status': 'FINISHED'
                })

        return finished_matches

    except Exception as e:
        print(f"SofaScore recent matches error: {e}")
        return []


def get_sofascore_match_ratings(match_id: int) -> Dict:
    """Получить оценки игроков за матч"""
    try:
        # Получаем lineups с рейтингами
        url = f"{SOFASCORE_API}/event/{match_id}/lineups"
        response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            return {}

        data = response.json()

        result = {'home': [], 'away': [], 'matchId': match_id}

        for side in ['home', 'away']:
            lineup = data.get(side, {})
            players = lineup.get('players', [])

            for player_group in players:
                for player_data in player_group if isinstance(player_group, list) else [player_group]:
                    player = player_data.get('player', {})
                    stats = player_data.get('statistics', {})

                    rating = stats.get('rating')
                    if rating:
                        result[side].append({
                            'name': player.get('shortName', player.get('name', '')),
                            'position': player_data.get('position', ''),
                            'rating': round(float(rating), 1),
                            'goals': stats.get('goals', 0),
                            'assists': stats.get('assists', 0),
                            'minutes': stats.get('minutesPlayed', 0)
                        })

            # Сортируем по рейтингу
            result[side] = sorted(result[side], key=lambda x: x['rating'], reverse=True)

        return result

    except Exception as e:
        print(f"SofaScore ratings error: {e}")
        return {}


def get_sofascore_laliga_standings() -> List[Dict]:
    """Получить таблицу Ла Лиги"""
    try:
        # Получаем текущий сезон
        url = f"{SOFASCORE_API}/unique-tournament/{LALIGA_TOURNAMENT_ID}/season/61643/standings/total"  # Season ID may need update
        response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            # Попробуем найти текущий сезон
            season_url = f"{SOFASCORE_API}/unique-tournament/{LALIGA_TOURNAMENT_ID}/seasons"
            season_resp = requests.get(season_url, headers=_sofascore_headers, timeout=10)
            if season_resp.status_code == 200:
                seasons = season_resp.json().get('seasons', [])
                if seasons:
                    current_season = seasons[0].get('id')
                    url = f"{SOFASCORE_API}/unique-tournament/{LALIGA_TOURNAMENT_ID}/season/{current_season}/standings/total"
                    response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        standings_data = data.get('standings', [])

        if not standings_data:
            return []

        rows = standings_data[0].get('rows', [])
        standings = []

        for row in rows:
            team = row.get('team', {})
            standings.append({
                'position': row.get('position', 0),
                'team': team.get('name', ''),
                'teamId': team.get('id'),
                'played': row.get('matches', 0),
                'won': row.get('wins', 0),
                'drawn': row.get('draws', 0),
                'lost': row.get('losses', 0),
                'goalsFor': row.get('scoresFor', 0),
                'goalsAgainst': row.get('scoresAgainst', 0),
                'goalDiff': row.get('scoresFor', 0) - row.get('scoresAgainst', 0),
                'points': row.get('points', 0),
                'isRealMadrid': team.get('id') == REAL_MADRID_TEAM_ID
            })

        return standings

    except Exception as e:
        print(f"SofaScore standings error: {e}")
        return []


def get_sofascore_player_stats() -> List[Dict]:
    """Получить статистику игроков Real Madrid"""
    try:
        url = f"{SOFASCORE_API}/team/{REAL_MADRID_TEAM_ID}/players"
        response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        players = data.get('players', [])

        player_stats = []
        for p in players:
            player = p.get('player', {})
            player_stats.append({
                'name': player.get('shortName', player.get('name', '')),
                'position': player.get('position', ''),
                'number': player.get('jerseyNumber'),
                'country': player.get('country', {}).get('name', ''),
                'age': player.get('age'),
                'height': player.get('height'),
                'marketValue': player.get('proposedMarketValue')
            })

        return player_stats

    except Exception as e:
        print(f"SofaScore player stats error: {e}")
        return []


# Создаём глобальный клиент
sheets_client = GoogleSheetsClient()

app = FastAPI(title="Real Madrid Bot API", version="1.0.0")

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


# ============ АВТОРИЗАЦИЯ ============

# Cache for user avatar photos (user_id -> True if downloaded)
_user_photos = {}
_user_photos_fetched = set()  # Track which users we already tried to fetch
_AVATAR_DIR = '/app/data/avatars'

def _fetch_and_save_avatar(user_id: int) -> bool:
    """Download user avatar via Telegram Bot API and save locally"""
    try:
        os.makedirs(_AVATAR_DIR, exist_ok=True)
        avatar_path = f"{_AVATAR_DIR}/{user_id}.jpg"

        # Skip if already exists and fresh (less than 24h)
        if os.path.exists(avatar_path):
            age = _time.time() - os.path.getmtime(avatar_path)
            if age < 86400:  # 24 hours
                return True

        # Get user profile photos
        resp = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos",
            params={"user_id": user_id, "limit": 1},
            timeout=5
        )
        data = resp.json()
        if not data.get('ok') or not data.get('result', {}).get('photos'):
            return False

        # Get medium size photo
        photo_sizes = data['result']['photos'][0]
        size = photo_sizes[min(1, len(photo_sizes)-1)]
        file_id = size['file_id']

        # Get file path
        resp2 = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
            params={"file_id": file_id},
            timeout=5
        )
        data2 = resp2.json()
        if not data2.get('ok'):
            return False

        file_path = data2['result']['file_path']
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

        # Download and save
        img_resp = requests.get(file_url, timeout=10)
        if img_resp.status_code == 200:
            with open(avatar_path, 'wb') as f:
                f.write(img_resp.content)
            return True
        return False
    except Exception as e:
        print(f"Avatar fetch error for {user_id}: {e}", flush=True)
        return False

def verify_telegram_webapp(init_data: str) -> dict:
    """
    Проверка подписи от Telegram Web App
    Возвращает данные пользователя если подпись валидна
    """
    try:
        parsed = dict(parse_qs(init_data))

        # Получаем hash
        received_hash = parsed.get('hash', [''])[0]

        # Собираем строку для проверки
        data_check = []
        for key, value in sorted(parsed.items()):
            if key != 'hash':
                data_check.append(f"{key}={value[0]}")
        data_check_string = '\n'.join(data_check)

        # Создаём secret key
        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        # Проверяем подпись
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if calculated_hash != received_hash:
            return None

        # Парсим user данные
        user_data = parsed.get('user', ['{}'])[0]
        user = json.loads(unquote(user_data))

        return user

    except Exception as e:
        print(f"Auth error: {e}")
        return None


async def get_current_user(authorization: str = Header(None)) -> dict:
    """Dependency для получения текущего пользователя"""
    print(f"Authorization header: {authorization[:100] if authorization else 'None'}...")

    if not authorization:
        raise HTTPException(status_code=401, detail="No authorization header")

    user = verify_telegram_webapp(authorization)
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


# ============ МОДЕЛИ ============

from typing import Union

class BetRequest(BaseModel):
    match_id: Union[str, int]  # Может быть строкой или числом
    bet_type: str  # 'home', 'draw', 'away', 'score_X-X'
    amount: int

class PredictionRequest(BaseModel):
    match_id: Union[str, int]
    prediction: str  # 'home', 'draw', 'away'

class SellBetRequest(BaseModel):
    bet_id: int

class ClaimPrizeRequest(BaseModel):
    prize_id: int
    contact: str
    size: Optional[str] = None  # Для футболки
    phone: Optional[str] = None  # Для TG Premium
    address: Optional[str] = None  # Для PlayStation


# ============ ЭНДПОИНТЫ ============

@app.get("/api/health")
async def health_check():
    """Проверка работоспособности API"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/api/bundle")
async def get_bundle(authorization: str = Header(None)):
    """Все критичные данные за 1 запрос — параллельно в потоках"""
    import asyncio
    import time as _bt
    from concurrent.futures import ThreadPoolExecutor

    _bundle_start = _bt.time()
    bundle = {}

    # User (fast — just DB lookup)
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
        bundle['predictions'] = sheets_client.get_user_predictions(user_id, limit=20)
    else:
        bundle['user'] = None
        bundle['bets'] = []
        bundle['predictions'] = []

    print(f"  bundle/user: {_bt.time()-_bundle_start:.2f}s", flush=True)

    # Run all blocking IO calls in parallel threads
    loop = asyncio.get_event_loop()

    def _call_sync(fn_name):
        """Run async endpoint in new event loop inside thread"""
        import asyncio as _aio
        import time as _t
        _s = _t.time()
        _loop = _aio.new_event_loop()
        try:
            if fn_name == 'match':
                r = _loop.run_until_complete(get_next_match())
            elif fn_name == 'results':
                r = _loop.run_until_complete(get_match_results())
            elif fn_name == 'upcoming':
                r = _loop.run_until_complete(get_upcoming_matches())
            elif fn_name == 'standings':
                r = _loop.run_until_complete(get_standings())
            elif fn_name == 'leaderboard':
                r = _loop.run_until_complete(get_leaderboard_endpoint())
            elif fn_name == 'live':
                r = _loop.run_until_complete(get_live_match())
            else:
                r = {}
            print(f"  bundle/{fn_name}: {_t.time()-_s:.2f}s", flush=True)
            return r
        except Exception as e:
            print(f"  bundle/{fn_name}: ERROR {e} ({_t.time()-_s:.2f}s)", flush=True)
            return {}
        finally:
            _loop.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            'match': loop.run_in_executor(pool, _call_sync, 'match'),
            'results': loop.run_in_executor(pool, _call_sync, 'results'),
            'upcoming': loop.run_in_executor(pool, _call_sync, 'upcoming'),
            'standings': loop.run_in_executor(pool, _call_sync, 'standings'),
            'leaderboard': loop.run_in_executor(pool, _call_sync, 'leaderboard'),
            'live': loop.run_in_executor(pool, _call_sync, 'live'),
        }

        results = {}
        for key, future in futures.items():
            try:
                results[key] = await asyncio.wait_for(future, timeout=20)
            except:
                results[key] = {}

    r = results
    bundle['match'] = r['match'].get('match') if isinstance(r.get('match'), dict) else None
    bundle['results'] = r['results'].get('results', []) if isinstance(r.get('results'), dict) else []
    bundle['matches'] = r['upcoming'].get('matches', []) if isinstance(r.get('upcoming'), dict) else []
    bundle['standings'] = r['standings'].get('standings', []) if isinstance(r.get('standings'), dict) else []
    bundle['leaderboard'] = r['leaderboard'].get('leaderboard', []) if isinstance(r.get('leaderboard'), dict) else []
    bundle['live'] = r['live'] if isinstance(r.get('live'), dict) and r['live'].get('is_live') else None

    print(f"Bundle TOTAL: {_bt.time()-_bundle_start:.2f}s", flush=True)
    return bundle


@app.get("/api/user/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Получить данные текущего пользователя"""
    # Получаем ставки для подсчёта
    bets = get_user_bets(user['user_id'], limit=1000)
    bets_count = len(bets)
    bets_won = len([b for b in bets if b.get('status') == 'won'])

    # Получаем прогнозы
    predictions = get_user_predictions(user['user_id'], limit=1000)
    predictions_total = len(predictions)
    predictions_correct = len([p for p in predictions if p.get('status') in ['correct', 'won']])
    predictions_incorrect = len([p for p in predictions if p.get('status') in ['incorrect', 'lost']])

    # Исправляем -0
    total_won = user.get('total_won', 0)
    if total_won == 0 or total_won == -0:
        total_won = 0

    return {
        "user_id": user['user_id'],
        "username": user.get('username'),
        "first_name": user.get('first_name'),
        "balance": user['balance'],
        "total_wagered": user.get('total_wagered', 0),
        "total_won": total_won,
        "bets_count": bets_count,
        "bets_won": bets_won,
        "predictions_total": predictions_total,
        "predictions_correct": predictions_correct,
        "predictions_incorrect": predictions_incorrect,
        "created_at": user.get('created_at')
    }


@app.get("/api/user/bets")
async def get_my_bets(user: dict = Depends(get_current_user), limit: int = 20):
    """Получить ставки пользователя"""
    bets = get_user_bets(user['user_id'], limit=limit)
    return {"bets": bets}


@app.get("/api/user/predictions")
async def get_my_predictions(user: dict = Depends(get_current_user), limit: int = 20):
    """Получить прогнозы пользователя"""
    predictions = get_user_predictions(user['user_id'], limit=limit)
    return {"predictions": predictions}


@app.get("/api/user/transactions")
async def get_user_transactions(user: dict = Depends(get_current_user), limit: int = 50):
    """Получить историю транзакций пользователя из таблицы transactions"""
    try:
        transactions = _execute(
            """SELECT transaction_id, type, amount, balance_before, balance_after,
                      description, reference_id, created_at
               FROM transactions
               WHERE user_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user['user_id'], limit)
        ) or []

        # Форматируем для фронтенда с иконками
        type_info_map = {
            'bet': {'icon': '🎰', 'name': 'Ставка'},
            'bet_place': {'icon': '🎰', 'name': 'Ставка'},
            'bet_win': {'icon': '🎰✅', 'name': 'Выигрыш ставки'},
            'bet_lose': {'icon': '🎰❌', 'name': 'Проигрыш ставки'},
            'bet_sell': {'icon': '💰', 'name': 'Продажа ставки'},
            'prediction_win': {'icon': '🔮✅', 'name': 'Правильный прогноз'},
            'prediction_lose': {'icon': '🔮❌', 'name': 'Неправильный прогноз'},
            'bonus': {'icon': '🎁', 'name': 'Бонус'},
            'deposit': {'icon': '💳', 'name': 'Пополнение'},
            'admin_add': {'icon': '👑➕', 'name': 'Начисление от админа'},
            'admin_remove': {'icon': '👑➖', 'name': 'Списание от админа'},
            'prize': {'icon': '🏆', 'name': 'Приз'},
        }

        result = []
        for tx in transactions:
            tx_type = tx['type']
            info = type_info_map.get(tx_type, {'icon': '💫', 'name': tx_type})

            result.append({
                'id': tx['transaction_id'],
                'type': tx_type,
                'type_name': info['name'],
                'icon': info['icon'],
                'amount': tx['amount'],
                'balance_before': tx['balance_before'],
                'balance_after': tx['balance_after'],
                'description': tx['description'],
                'reference_id': tx['reference_id'],
                'created_at': tx['created_at']
            })

        return {"transactions": result}
    except Exception as e:
        print(f"Transactions error: {e}")
        import traceback
        traceback.print_exc()
        return {"transactions": [], "error": str(e)}



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

@app.get("/api/match/next")
async def get_next_match():
    """Получить следующий матч с коэффициентами и всеми типами ставок"""
    try:
        # Check for live match FIRST
        leon_live = _get_leon_cached()
        if leon_live and leon_live.get("is_live"):
            live_odds = leon_live.get("live_odds", {})

            # Ищем Sheets matchId для этого матча (чтобы расчёт ставок работал!)
            sheets_match_id = None
            try:
                matches = sheets_client.get_matches(limit=5)
                leon_home = leon_live.get("home_team", "")
                leon_away = leon_live.get("away_team", "")
                for m in (matches or []):
                    # Пробуем найти матч по командам
                    opp = m.get('opponent', '')
                    if opp and (opp in leon_home or opp in leon_away or
                                leon_home in (opp or '') or leon_away in (opp or '')):
                        sheets_match_id = m.get('id')
                        break
                    # Или по home_team/away_team если есть
                    h = m.get('home_team', '')
                    a = m.get('away_team', '')
                    if (h and (h in leon_home or leon_home in h)) or \
                       (a and (a in leon_away or leon_away in a)):
                        sheets_match_id = m.get('id')
                        break
            except Exception as e:
                print(f"Sheets lookup error: {e}")

            # Используем Sheets ID если нашли, иначе Leon ID
            match_id = str(sheets_match_id) if sheets_match_id else str(leon_live.get("leon_id", ""))
            print(f"Live match ID: sheets={sheets_match_id}, leon={leon_live.get('leon_id')}, using={match_id}")

            return {
                "match": {
                    "id": match_id,
                    "leon_id": str(leon_live.get("leon_id", "")),
                    "home_team": leon_live.get("home_team", ""),
                    "away_team": leon_live.get("away_team", ""),
                    "home_logo": _get_team_logo(leon_live.get("home_team", "")),
                    "away_logo": _get_team_logo(leon_live.get("away_team", "")),
                    "date": "LIVE",
                    "competition": leon_live.get("stage", "La Liga"),
                    "is_live": True,
                    "score": leon_live.get("score", "0:0"),
                    "minute": leon_live.get("minute", ""),
                    "odds": {
                        "home": live_odds.get("home", 0),
                        "draw": live_odds.get("draw", 0),
                        "away": live_odds.get("away", 0),
                    },
                    "bet_markets": _build_live_markets(live_odds, leon_live.get("home_team", ""), leon_live.get("away_team", ""), leon_live.get("score", "0:0")),
                    "bets_suspended": leon_live.get("bets_suspended", False),
                }
            }

        # No live match - get next from Google Sheets
        matches = sheets_client.get_matches(limit=1)
        odds = sheets_client.get_odds()

        if not matches:
            return {"match": None}

        match = matches[0]

        # Проверяем что матч ещё не начался (с запасом 5 минут)
        try:
            mt = datetime.strptime(f"{match.get('date')} {match.get('time')}", '%d.%m.%Y %H:%M')
            mt = mt.replace(tzinfo=MOSCOW_TZ)
            now = datetime.now(MOSCOW_TZ)

            if now >= mt - timedelta(minutes=5):
                # Match started - check if live
                leon_live = _get_leon_cached()
                if leon_live and leon_live.get("is_live"):
                    live_odds = leon_live.get("live_odds", {})
                    # Используем Sheets match_id (уже загружен выше!)
                    return {
                        "match": {
                            "id": str(match.get('id', '')),
                            "leon_id": str(leon_live.get("leon_id", "")),
                            "home_team": leon_live.get("home_team", ""),
                            "away_team": leon_live.get("away_team", ""),
                            "home_logo": _get_team_logo(leon_live.get("home_team", "")),
                            "away_logo": _get_team_logo(leon_live.get("away_team", "")),
                            "date": "LIVE",
                            "competition": leon_live.get("stage", "La Liga"),
                            "is_live": True,
                            "score": leon_live.get("score", "0:0"),
                            "minute": leon_live.get("minute", ""),
                            "odds": {
                                "home": live_odds.get("home", 0),
                                "draw": live_odds.get("draw", 0),
                                "away": live_odds.get("away", 0),
                            },
                            "bet_markets": _build_live_markets(live_odds, leon_live.get("home_team", ""), leon_live.get("away_team", ""), leon_live.get("score", "0:0")),
                            "bets_suspended": leon_live.get("bets_suspended", False),
                        }
                    }
                else:
                    return {"match": None, "message": "Bets closed"}
        except ValueError:
            pass

        # Основные коэфы - ТОЛЬКО из Leon (двухшаговый запрос)
        sheets_opponent = match.get('opponent', '')

        # Команды ВСЕГДА берём из Sheets (Leon может вернуть другой матч!)
        if match.get('is_home'):
            sheets_home = "Real Madrid"
            sheets_away = sheets_opponent
        else:
            sheets_home = sheets_opponent
            sheets_away = "Real Madrid"

        leon_prematch = _get_leon_cached(target_opponent=sheets_opponent)

        # Проверяем что Leon вернул ПРАВИЛЬНЫЙ матч (того же соперника)
        leon_match_valid = False
        if leon_prematch and leon_prematch.get('live_odds'):
            leon_home = leon_prematch.get('home_team', '')
            leon_away = leon_prematch.get('away_team', '')
            # Используем nameDefault (английские имена) для точного сравнения
            name_default = leon_prematch.get('name_default', '')
            all_names = (leon_home + ' ' + leon_away + ' ' + name_default).lower()

            # Проверяем что соперник из Sheets есть в Leon матче
            opp_lower = sheets_opponent.lower()
            skip_words = {'real', 'madrid', 'club', 'fc', 'cf'}
            opp_words = [w for w in opp_lower.split() if len(w) > 3 and w not in skip_words]

            if opp_lower in all_names or (opp_words and any(w in all_names for w in opp_words)):
                leon_match_valid = True
                print(f"Prematch: Leon match VALID for '{sheets_opponent}': {leon_home} vs {leon_away} (default: {name_default})")
            else:
                print(f"Prematch: Leon match MISMATCH! Sheets='{sheets_opponent}', Leon='{leon_home} vs {leon_away}', default='{name_default}' - ignoring")

        if leon_match_valid:
            leon_odds = leon_prematch.get('live_odds', {})
            home_odds = leon_odds.get('home', 0)
            draw_odds = leon_odds.get('draw', 0)
            away_odds = leon_odds.get('away', 0)
            bet_markets = _build_live_markets(leon_odds, sheets_home, sheets_away)
        else:
            # Leon не нашёл или вернул другой матч - показываем без кэфов
            home_odds = 0
            draw_odds = 0
            away_odds = 0
            bet_markets = []

        return {
            "match": {
                "id": match.get('id'),
                "home_team": sheets_home,
                "away_team": sheets_away,
                "home_logo": _get_team_logo(sheets_home),
                "away_logo": _get_team_logo(sheets_away),
                "date": f"{match.get('date')} {match.get('time')}",
                "competition": match.get('tournament'),
                "odds": {
                    "home": home_odds,
                    "draw": draw_odds,
                    "away": away_odds,
                },
                "bet_markets": bet_markets,
                "leon_source": leon_match_valid
            }
        }
    except Exception as e:
        print(f"Error getting match: {e}")
        return {"match": None, "error": str(e)}


@app.get("/api/matches/upcoming")
async def get_upcoming_matches():
    """Получить список предстоящих матчей"""
    matches = sheets_client.get_matches(limit=10)
    if not matches:
        return {"matches": []}

    result = []
    for m in matches:
        home = "Real Madrid" if m.get('is_home') else m.get('opponent')
        away = m.get('opponent') if m.get('is_home') else "Real Madrid"
        result.append({
            "id": m.get('id'),
            "home_team": home,
            "away_team": away,
            "home_logo": _get_team_logo(home),
            "away_logo": _get_team_logo(away),
            "date": f"{m.get('date')} {m.get('time')}",
            "competition": m.get('tournament')
        })

    return {"matches": result}


@app.get("/api/matches/results")
async def get_match_results():
    """Получить результаты прошедших матчей — FotMob с match_id для детализации"""
    try:
        team_data = _get_fotmob_team(FOTMOB_RM_ID)
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

                # Register team logos
                _register_team(home.get('name', ''), home.get('id'))
                _register_team(away.get('name', ''), away.get('id'))

                # Score from status.scoreStr or home/away scores
                score_str = status.get('scoreStr', '')
                home_score = home.get('score', 0) or 0
                away_score = away.get('score', 0) or 0
                if not score_str and (home_score or away_score):
                    score_str = f"{home_score} - {away_score}"

                is_home = home.get('id') == FOTMOB_RM_ID

                if is_home:
                    opponent = away.get('name', '')
                    gf = home_score
                    ga = away_score
                else:
                    opponent = home.get('name', '')
                    gf = away_score
                    ga = home_score

                if gf > ga:
                    result = 'win'
                elif gf < ga:
                    result = 'loss'
                else:
                    result = 'draw'

                # Date
                utc = status.get('utcTime', '')
                date_str = ''
                if utc:
                    try:
                        dt = datetime.strptime(utc[:10], '%Y-%m-%d')
                        date_str = dt.strftime('%d.%m.%Y')
                    except:
                        date_str = utc[:10]

                tournament = f.get('tournament', {}).get('name', '') if isinstance(f.get('tournament'), dict) else ''

                results.append({
                    "match_id": match_id,
                    "opponent": opponent,
                    "score": f"{home_score}:{away_score}",
                    "date": date_str,
                    "competition": tournament,
                    "is_home": is_home,
                    "result": result,
                    "home_team": home.get('name', ''),
                    "away_team": away.get('name', ''),
                    "home_score": home_score,
                    "away_score": away_score,
                    "home_logo": f"https://images.fotmob.com/image_resources/logo/teamlogo/{home.get('id','')}.png" if home.get('id') else '',
                    "away_logo": f"https://images.fotmob.com/image_resources/logo/teamlogo/{away.get('id','')}.png" if away.get('id') else '',
                })

            # Reverse so newest first
            results.reverse()

            if results:
                return {"results": results[:10]}

        # Fallback to Sheets
        sheets_results = sheets_client.get_results()
        if sheets_results:
            return {"results": [{"opponent": r.get('opponent',''), "score": r.get('score',''), "date": r.get('date',''), "competition": r.get('tournament',''), "is_home": r.get('is_home',True), "result": r.get('result',''), "match_id": None} for r in sheets_results]}

        return {"results": []}
    except Exception as e:
        print(f"Results error: {e}", flush=True)
        return {"results": []}




# === ПРЕДМАТЧЕВАЯ АНАЛИТИКА (FotMob + Sheets fallback) ===
FOTMOB_API = "https://www.fotmob.com/api"
FOTMOB_RM_ID = 8633  # Real Madrid team ID on FotMob

_fotmob_headers = {    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',    'Accept': 'application/json, text/plain, */*',    'Accept-Language': 'en-US,en;q=0.9',    'Referer': 'https://www.fotmob.com/',    'Origin': 'https://www.fotmob.com',    'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',    'sec-ch-ua-mobile': '?0',    'sec-ch-ua-platform': '"Windows"',    'sec-fetch-dest': 'empty',    'sec-fetch-mode': 'cors',    'sec-fetch-site': 'same-origin',}



# ============ ESPN API (fallback for FotMob matchDetails) ============
ESPN_API = "http://site.api.espn.com/apis/site/v2/sports/soccer"
_ESPN_LEAGUES = ['esp.1', 'uefa.champions', 'uefa.europa', 'eng.1', 'ger.1', 'ita.1', 'fra.1', 'uefa.europa.conf']
_espn_id_cache = {}  # {fotmob_match_id: espn_event_id}
_espn_summary_cache = {}  # {espn_event_id: {'data': ..., 'time': ...}}
_ESPN_CACHE_TTL = 300  # 5 min

def _espn_find_event(date_str: str, home_name: str, away_name: str) -> str:
    """Find ESPN event ID by date and team names.
    date_str: 'YYYYMMDD' or 'DD.MM.YYYY' or 'YYYY-MM-DD'
    """
    # Normalize date to YYYYMMDD
    ds = date_str.replace('-', '').replace('.', '')
    if len(ds) == 8:
        if not ds[:4].isdigit():  # DD.MM.YYYY -> YYYYMMDD
            parts = date_str.split('.')
            if len(parts) == 3:
                ds = parts[2] + parts[1] + parts[0]

    def _normalize(name):
        n = name.lower().strip()
        for rem in ['fc ', 'cf ', 'rcd ', 'ud ', 'rc ', 'sd ', 'sc ', 'sl ']:
            n = n.replace(rem, '')
        return n.strip()

    h_norm = _normalize(home_name)
    a_norm = _normalize(away_name)

    for league in _ESPN_LEAGUES:
        try:
            url = f"{ESPN_API}/{league}/scoreboard?dates={ds}"
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            for ev in data.get('events', []):
                comps = ev.get('competitions', [{}])[0]
                competitors = comps.get('competitors', [])
                if len(competitors) < 2:
                    continue
                espn_home = ''
                espn_away = ''
                for c in competitors:
                    tn = c.get('team', {}).get('displayName', '')
                    if c.get('homeAway') == 'home':
                        espn_home = tn
                    else:
                        espn_away = tn

                eh = _normalize(espn_home)
                ea = _normalize(espn_away)

                def _match(a, b):
                    if not a or not b:
                        return False
                    if a in b or b in a:
                        return True
                    wa = set(a.split())
                    wb = set(b.split())
                    common = wa & wb
                    return any(len(w) > 3 for w in common)

                if _match(h_norm, eh) and _match(a_norm, ea):
                    eid = str(ev.get('id', ''))
                    print(f"ESPN: found event {eid} for {home_name} vs {away_name} in {league}", flush=True)
                    return eid
        except Exception as e:
            print(f"ESPN scoreboard error ({league}): {e}", flush=True)

    print(f"ESPN: no event found for {home_name} vs {away_name} on {ds}", flush=True)
    return ''


def _espn_get_summary(espn_event_id: str, league: str = None) -> dict:
    """Get ESPN match summary. Try all leagues if league not specified."""
    if not espn_event_id:
        return {}

    now = _time.time()
    cached = _espn_summary_cache.get(espn_event_id)
    if cached and (now - cached['time']) < _ESPN_CACHE_TTL:
        return cached['data']

    leagues_to_try = [league] if league else _ESPN_LEAGUES
    for lg in leagues_to_try:
        try:
            url = f"{ESPN_API}/{lg}/summary?event={espn_event_id}"
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if data.get('header'):
                    _espn_summary_cache[espn_event_id] = {'data': data, 'time': now}
                    return data
        except:
            pass
    return {}


def _espn_parse_events(summary: dict) -> list:
    """Parse ESPN events into frontend-compatible format.

    Uses keyEvents for goals/yellow cards and header.details for red cards
    (red cards may only appear in details, not in keyEvents).
    Output format matches frontend expectations:
      type: 'goal' | 'yellow' | 'red' | 'half'
      home: bool, player: str, minute: str, score: str (goals only)
      assist: str (goals), penalty: bool, own_goal: bool
    """
    events = []
    if not summary:
        return events

    header = summary.get('header', {})
    comp = header.get('competitions', [{}])[0]
    competitors = comp.get('competitors', [])
    home_team_id = ''
    for c in competitors:
        if c.get('homeAway') == 'home':
            home_team_id = str(c.get('id', ''))
            break

    raw = []

    # --- keyEvents: goals, yellow cards, halftime ---
    for ke in summary.get('keyEvents', []):
        ev_type_info = ke.get('type', {})
        ev_type_raw = (ev_type_info.get('type', '') or '').lower()
        short_text = ke.get('shortText', '') or ''
        sort_val = ke.get('clock', {}).get('value', 0) or 0

        clock_disp = ke.get('clock', {}).get('displayValue', '')
        minute = ''
        if clock_disp:
            minute = clock_disp.replace("'", '').strip()

        if ev_type_raw == 'goal' or ('penalty' in ev_type_raw and 'scored' in ev_type_raw):
            ev_type = 'goal'
        elif ev_type_raw == 'yellow-card':
            ev_type = 'yellow'
        elif ev_type_raw in ('red-card', 'second-yellow-red-card', 'second-yellow'):
            ev_type = 'red'
        elif ev_type_raw == 'halftime':
            raw.append({'type': 'half', 'text': '\u041f\u0435\u0440\u0435\u0440\u044b\u0432', '_sort': sort_val})
            continue
        else:
            continue

        team_data = ke.get('team', {})
        team_id = str(team_data.get('id', ''))
        is_home = (team_id == home_team_id) if team_id else True

        participants = ke.get('participants', [])
        player_name = participants[0].get('athlete', {}).get('displayName', '') if participants else ''

        ev = {
            'minute': minute,
            'type': ev_type,
            'player': player_name,
            'home': is_home,
            '_sort': sort_val,
        }

        if ev_type == 'goal':
            if len(participants) > 1:
                ev['assist'] = participants[1].get('athlete', {}).get('displayName', '')
            st_low = short_text.lower()
            if 'penalty' in st_low or 'pen.' in st_low:
                ev['penalty'] = True
            if 'own goal' in st_low:
                ev['own_goal'] = True

        raw.append(ev)

    # --- details: red cards (may be absent from keyEvents) ---
    details = comp.get('details', [])
    for det in details:
        if not det.get('redCard', False):
            continue
        sort_val = det.get('clock', {}).get('value', 0) or 0
        if any(e for e in raw if e.get('type') == 'red' and abs(e.get('_sort', 0) - sort_val) < 10):
            continue
        clock_disp = det.get('clock', {}).get('displayValue', '')
        minute = ''
        if clock_disp:
            minute = clock_disp.replace("'", '').strip()
        team_data = det.get('team', {})
        team_id = str(team_data.get('id', ''))
        is_home = (team_id == home_team_id) if team_id else True
        participants = det.get('participants', [])
        player_name = participants[0].get('athlete', {}).get('displayName', '') if participants else ''
        raw.append({
            'minute': minute,
            'type': 'red',
            'player': player_name,
            'home': is_home,
            '_sort': sort_val,
        })

    # Sort by clock value
    raw.sort(key=lambda x: x.get('_sort', 0))

    # Compute running score for goals
    home_score = 0
    away_score = 0
    for ev in raw:
        if ev['type'] == 'goal':
            if ev.get('own_goal'):
                if ev['home']:
                    away_score += 1
                else:
                    home_score += 1
            else:
                if ev['home']:
                    home_score += 1
                else:
                    away_score += 1
            ev['score'] = f'{home_score}:{away_score}'
        ev.pop('_sort', None)
        events.append(ev)

    return events


def _espn_parse_stats(summary: dict) -> list:
    """Parse ESPN boxscore stats into frontend-compatible format."""
    stats = []
    if not summary:
        return stats

    bs = summary.get('boxscore', {})
    teams_data = bs.get('teams', [])
    if len(teams_data) < 2:
        return stats

    home_stats = {}
    away_stats = {}
    for s in teams_data[0].get('statistics', []):
        home_stats[s.get('name', '')] = s.get('displayValue', '0')
    for s in teams_data[1].get('statistics', []):
        away_stats[s.get('name', '')] = s.get('displayValue', '0')

    stat_map = [
        ('possessionPct', 'Владение мячом', '%'),
        ('totalShots', 'Удары', ''),
        ('shotsOnTarget', 'Удары в створ', ''),
        ('wonCorners', 'Угловые', ''),
        ('foulsCommitted', 'Фолы', ''),
        ('offsides', 'Офсайды', ''),
        ('yellowCards', 'Жёлтые карточки', ''),
        ('redCards', 'Красные карточки', ''),
        ('saves', 'Сейвы', ''),
        ('totalPasses', 'Передачи', ''),
        ('accuratePass', 'Точные передачи', ''),
        ('totalTackle', 'Отборы', ''),
        ('totalCross', 'Кроссы', ''),
        ('interceptions', 'Перехваты', ''),
    ]

    for key, title, suffix in stat_map:
        hv = home_stats.get(key, '')
        av = away_stats.get(key, '')
        if hv or av:
            stats.append({
                'title': title,
                'home': str(hv) + suffix if hv else '0',
                'away': str(av) + suffix if av else '0',
            })

    return stats


def _espn_parse_lineups(summary: dict) -> dict:
    """Parse ESPN rosters into frontend-compatible format."""
    result = {'home': [], 'away': []}
    if not summary:
        return result

    rosters = summary.get('rosters', [])

    for i, r in enumerate(rosters):
        side = 'home' if i == 0 else 'away'
        players = []
        for p in r.get('roster', []):
            ath = p.get('athlete', {})
            pos = p.get('position', {})
            player = {
                'name': ath.get('displayName', ''),
                'shirt': str(p.get('jersey', '')),
                'position': pos.get('abbreviation', '') if isinstance(pos, dict) else '',
                'is_starter': p.get('starter', False),
            }
            players.append(player)

        starters = [p for p in players if p.get('is_starter')]
        subs = [p for p in players if not p.get('is_starter')]
        result[side] = starters + subs

    return result


# === TEAM LOGO CACHE ===
_team_logo_map = {
    'real madrid': 8633,
}  # auto-populated from FotMob on startup and when standings/results load
_fotmob_standings_cache = {'data': None, 'time': 0, 'ttl': 600}  # 10 min

def _register_team(name: str, team_id):
    """Register team name → FotMob ID mapping"""
    if name and team_id:
        _team_logo_map[name.lower().strip()] = int(team_id)
        # Also register short forms
        parts = name.split()
        if len(parts) > 1:
            for p in parts:
                if len(p) > 3 and p.lower() not in ('city', 'club', 'real', 'athletic', 'united'):
                    _team_logo_map[p.lower()] = int(team_id)

def _get_team_logo(name: str) -> str:
    """Get team logo URL by name — smart fuzzy matching"""
    if not name:
        return ''
    key = name.lower().strip()

    # Direct match
    tid = _team_logo_map.get(key)
    if tid:
        return f"https://images.fotmob.com/image_resources/logo/teamlogo/{tid}.png"

    # Try without common prefixes/suffixes
    for prefix in ['real ', 'fc ', 'cf ', 'rcd ', 'ud ', 'cd ', 'rc ', 'sd ']:
        if key.startswith(prefix):
            tid = _team_logo_map.get(key[len(prefix):])
            if tid:
                return f"https://images.fotmob.com/image_resources/logo/teamlogo/{tid}.png"

    # Try partial match both ways
    for k, v in _team_logo_map.items():
        if k in key or key in k:
            return f"https://images.fotmob.com/image_resources/logo/teamlogo/{v}.png"
        # Also try splitting on spaces — "Atletico Madrid" should match "Atlético de Madrid"
        key_words = set(key.replace('á','a').replace('é','e').replace('í','i').replace('ó','o').replace('ú','u').split())
        k_words = set(k.replace('á','a').replace('é','e').replace('í','i').replace('ó','o').replace('ú','u').split())
        # If at least 1 significant word (>3 chars) matches
        common = key_words & k_words
        if any(len(w) > 3 for w in common):
            return f"https://images.fotmob.com/image_resources/logo/teamlogo/{v}.png"

    return ''

def _get_fotmob_league_standings(league_id: int = 87) -> list:
    """Fetch La Liga standings from FotMob with team IDs and logos"""
    now = _time.time()
    if _fotmob_standings_cache['data'] and (now - _fotmob_standings_cache['time']) < _fotmob_standings_cache['ttl']:
        return _fotmob_standings_cache['data']
    try:
        url = f"{FOTMOB_API}/leagues?id={league_id}"
        r = requests.get(url, headers=_fotmob_headers, timeout=15)
        if r.status_code != 200:
            print(f"FotMob standings HTTP {r.status_code}", flush=True)
            return _fotmob_standings_cache.get('data') or []
        data = r.json()

        # Debug: log top-level keys and table structure
        print(f"FotMob standings: top keys={list(data.keys())}", flush=True)

        # Parse standings table — handle various FotMob response shapes
        table_data = data.get('table', [])
        print(f"FotMob standings: table type={type(table_data).__name__}, len={len(table_data) if isinstance(table_data, (list,dict)) else 'N/A'}", flush=True)

        rows = []

        def _extract_rows(obj, depth=0):
            """Recursively find the actual rows array"""
            if depth > 6:
                return []
            if isinstance(obj, list):
                if obj and isinstance(obj[0], dict):
                    if 'name' in obj[0] and ('pts' in obj[0] or 'points' in obj[0]):
                        return obj
                    for item in obj:
                        result = _extract_rows(item, depth+1)
                        if result:
                            return result
                return []
            elif isinstance(obj, dict):
                if depth <= 1:
                    print(f"  FotMob standings depth={depth}: keys={list(obj.keys())[:15]}", flush=True)
                for key in ['all', 'table', 'data', 'rows', 'lines']:
                    if key in obj:
                        result = _extract_rows(obj[key], depth+1)
                        if result:
                            return result
            return []

        rows = _extract_rows(table_data)

        if not rows:
            # Try alternative paths
            # Path 1: data['table'] is a list of groups -> [0]['data']['table']['all']
            # Path 2: data['table'] is a list -> [0]['table'] -> list of rows
            # Path 3: data['standings'] or data['tableData']
            for alt_key in ['standings', 'tableData', 'stat']:
                if alt_key in data:
                    rows = _extract_rows(data[alt_key])
                    if rows:
                        print(f"FotMob standings: found via alt key '{alt_key}'", flush=True)
                        break

            if not rows and isinstance(table_data, list) and table_data:
                # Log deep structure for debug
                first = table_data[0]
                if isinstance(first, dict):
                    print(f"FotMob standings: table[0] keys={list(first.keys())}", flush=True)
                    for k, v in first.items():
                        vtype = type(v).__name__
                        vlen = len(v) if isinstance(v, (list, dict)) else ''
                        vkeys = list(v.keys())[:8] if isinstance(v, dict) else (list(v[0].keys())[:8] if isinstance(v, list) and v and isinstance(v[0], dict) else '')
                        print(f"  FotMob standings: table[0]['{k}'] = {vtype}({vlen}) keys={vkeys}", flush=True)

        if not rows:
            print(f"FotMob standings: no rows found after all attempts!", flush=True)

        standings = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            team_name = row.get('name', row.get('teamName', ''))
            team_id = row.get('id', row.get('teamId', ''))

            _register_team(team_name, team_id)

            standings.append({
                'position': row.get('idx', row.get('position', row.get('rank', 0))),
                'team': team_name,
                'team_id': team_id,
                'logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{team_id}.png" if team_id else '',
                'played': row.get('played', 0),
                'won': row.get('wins', row.get('won', 0)),
                'drawn': row.get('draws', row.get('drawn', 0)),
                'lost': row.get('losses', row.get('lost', 0)),
                'gf': row.get('scoresStr', '').split('-')[0].strip() if row.get('scoresStr') else row.get('goalsFor', 0),
                'ga': row.get('scoresStr', '').split('-')[1].strip() if row.get('scoresStr') and '-' in row.get('scoresStr','') else row.get('goalsAgainst', 0),
                'gd': row.get('goalConDiff', row.get('goalDifference', 0)),
                'points': row.get('pts', row.get('points', 0)),
                'isRealMadrid': team_id == FOTMOB_RM_ID or 'Real Madrid' in team_name
            })

        if standings:
            print(f"FotMob league standings: {len(standings)} teams", flush=True)
            _fotmob_standings_cache['data'] = standings
            _fotmob_standings_cache['time'] = now
        else:
            print(f"FotMob standings: 0 teams parsed!", flush=True)
        return standings
    except Exception as e:
        import traceback
        print(f"FotMob league standings error: {e}\n{traceback.format_exc()}", flush=True)
        return _fotmob_standings_cache.get('data') or []

_analytics_cache = {'data': None, 'time': 0, 'ttl': 300}

def _get_fotmob_team(team_id: int = FOTMOB_RM_ID) -> dict:
    """Получить данные команды с FotMob API"""
    try:
        url = f"{FOTMOB_API}/teams?id={team_id}"
        r = requests.get(url, headers=_fotmob_headers, timeout=15)
        print(f"FotMob team {team_id}: status={r.status_code}", flush=True)
        if r.status_code != 200:
            return {}
        return r.json()
    except Exception as e:
        print(f"FotMob team error: {e}", flush=True)
        return {}

def _get_fotmob_match(match_id: int) -> dict:
    """Получить детали матча с FotMob (H2H, статистика)"""
    try:
        url = f"{FOTMOB_API}/matchDetails?matchId={match_id}"
        r = requests.get(url, headers=_fotmob_headers, timeout=15)
        print(f"FotMob match {match_id}: status={r.status_code}", flush=True)
        if r.status_code != 200:
            return {}
        return r.json()
    except Exception as e:
        print(f"FotMob match error: {e}", flush=True)
        return {}

def _parse_fotmob_form(team_data: dict) -> list:
    """Парсим форму команды из FotMob team data"""
    form = []
    try:
        team_id = team_data.get('details', {}).get('id', FOTMOB_RM_ID)
        team_name = team_data.get('details', {}).get('name', 'Real Madrid')

        # Пробуем несколько путей к матчам
        last_matches = []
        form_source = ''

        # Path 1: overview.teamForm (best — has resultString, tooltipText with scores)
        overview = team_data.get('overview', {})
        team_form = overview.get('teamForm', [])
        if isinstance(team_form, list) and team_form:
            # teamForm has different structure, parse directly
            for tf in team_form[:10]:
                tt = tf.get('tooltipText', {})
                home_id = tf.get('home', {}).get('id', 0)
                is_our = tf.get('home', {}).get('isOurTeam', False) or home_id == team_id

                hs = tt.get('homeScore', 0) or 0
                as_ = tt.get('awayScore', 0) or 0
                gf = hs if is_our else as_
                ga = as_ if is_our else hs
                opp_name = tt.get('awayTeam', '') if is_our else tt.get('homeTeam', '')

                res = tf.get('resultString', '')
                if not res:
                    if gf > ga: res = 'W'
                    elif gf < ga: res = 'L'
                    else: res = 'D'

                ts = tf.get('date', {}).get('utcTime', '') if isinstance(tf.get('date'), dict) else ''
                date_str = ''
                if ts:
                    try:
                        dt = datetime.strptime(str(ts)[:10], '%Y-%m-%d')
                        date_str = dt.strftime('%d.%m')
                    except:
                        date_str = str(ts)[:10]

                form.append({
                    'opponent': opp_name,
                    'goals_for': int(gf),
                    'goals_against': int(ga),
                    'result': res,
                    'is_home': is_our,
                    'score': f"{int(hs)}:{int(as_)}",
                    'date': date_str,
                    'tournament': tf.get('tournamentName', '')
                })
            print(f"FotMob form: {len(form)} matches from teamForm", flush=True)
            return list(reversed(form))  # newest first

        # Path 2: overview.overviewFixtures (finished only, reverse chronological)
        ov_fixtures = overview.get('overviewFixtures', [])
        if isinstance(ov_fixtures, list):
            finished_ov = [f for f in ov_fixtures if f.get('status', {}).get('finished')]
            if finished_ov:
                last_matches = list(reversed(finished_ov))
                form_source = 'overviewFixtures'
                print(f"FotMob form: found {len(last_matches)} via overviewFixtures", flush=True)

        # Path 3: overview.lastXMatches / lastMatches
        if not last_matches:
            for key in ['lastXMatches', 'lastMatches']:
                lm = overview.get(key)
                if lm:
                    if isinstance(lm, dict):
                        last_matches = lm.get('lastMatchesRaw', []) or lm.get('matches', []) or lm.get('data', [])
                    elif isinstance(lm, list):
                        last_matches = lm
                    if last_matches:
                        form_source = key
                        print(f"FotMob form: found {len(last_matches)} via overview.{key}", flush=True)
                        break

        # Path 2: fixtures.allFixtures.fixtures (finished only)
        if not last_matches:
            fixtures = team_data.get('fixtures', {})
            all_fix = fixtures.get('allFixtures', {})
            if isinstance(all_fix, dict):
                fix_list = all_fix.get('fixtures', [])
            elif isinstance(all_fix, list):
                fix_list = all_fix
            else:
                fix_list = []
            finished = [f for f in fix_list if f.get('status', {}).get('finished')]
            if finished:
                last_matches = finished[-10:]
                print(f"FotMob form: found {len(last_matches)} via fixtures (finished)", flush=True)

        # Path 3: history.historicalTableData or recentMatches
        if not last_matches:
            for key in ['recentMatches', 'historicMatches']:
                rm = team_data.get(key, [])
                if rm:
                    last_matches = rm[:10]
                    print(f"FotMob form: found {len(last_matches)} via {key}", flush=True)
                    break

        if not last_matches:
            print(f"FotMob form: no matches found. Keys: {list(team_data.keys())}", flush=True)
            if overview:
                print(f"FotMob overview keys: {list(overview.keys())}", flush=True)
            return []

        for m in last_matches[:10]:
            home = m.get('home', {})
            away = m.get('away', {})
            home_name = home.get('name', home.get('shortName', ''))
            away_name = away.get('name', away.get('shortName', ''))

            # Try multiple score paths
            home_score = home.get('score')
            away_score = away.get('score')

            # Fallback: status.scoreStr "0 - 2"
            if home_score is None or away_score is None:
                score_str = m.get('status', {}).get('scoreStr', '')
                if ' - ' in score_str:
                    parts = score_str.split(' - ')
                    try:
                        home_score = int(parts[0].strip())
                        away_score = int(parts[1].strip())
                    except:
                        pass

            if home_score is None: home_score = 0
            if away_score is None: away_score = 0

            is_home = home.get('id') == team_id or team_name.lower() in home_name.lower()
            gf = int(home_score) if is_home else int(away_score)
            ga = int(away_score) if is_home else int(home_score)
            opp = away_name if is_home else home_name

            if gf > ga: res = 'W'
            elif gf < ga: res = 'L'
            else: res = 'D'

            # Дата
            ts = m.get('status', {}).get('utcTime', '') or m.get('timeTS', '') or ''
            date_str = ''
            if ts:
                try:
                    dt = datetime.strptime(str(ts)[:10], '%Y-%m-%d')
                    date_str = dt.strftime('%d.%m')
                except:
                    date_str = str(ts)[:10]

            tournament = ''
            tourn = m.get('tournament') or m.get('league') or {}
            if isinstance(tourn, dict):
                tournament = tourn.get('name', '')

            form.append({
                'opponent': opp,
                'goals_for': gf,
                'goals_against': ga,
                'result': res,
                'is_home': is_home,
                'score': f"{int(home_score)}:{int(away_score)}",
                'date': date_str,
                'tournament': tournament
            })
    except Exception as e:
        print(f"FotMob form parse error: {e}", flush=True)
        import traceback
        traceback.print_exc()
    return form

def _parse_fotmob_h2h(match_data: dict) -> list:
    """Парсим H2H из FotMob match details
    Структура: content.h2h.matches[] -> status.scoreStr = "1 - 2", home.name, away.name
    """
    h2h = []
    try:
        content = match_data.get('content', {})
        h2h_data = content.get('h2h', {})
        meetings = h2h_data.get('matches', [])

        if not meetings:
            print(f"FotMob H2H: no matches. Keys: {list(h2h_data.keys())}", flush=True)
            return []

        print(f"FotMob H2H: found {len(meetings)} meetings", flush=True)

        for m in meetings[:10]:
            home = m.get('home', {})
            away = m.get('away', {})
            status = m.get('status', {})

            # Score is in status.scoreStr like "1 - 2"
            score_str = status.get('scoreStr', '')
            hs, as_ = 0, 0
            if score_str and ' - ' in score_str:
                parts = score_str.split(' - ')
                try:
                    hs = int(parts[0].strip())
                    as_ = int(parts[1].strip())
                except (ValueError, IndexError):
                    pass

            # Date
            ts = status.get('utcTime', '') or m.get('time', {}).get('utcTime', '')
            date_str = ''
            if ts:
                try:
                    dt = datetime.strptime(str(ts)[:10], '%Y-%m-%d')
                    date_str = dt.strftime('%d.%m.%y')
                except:
                    date_str = str(ts)[:10]

            league = m.get('league', {})
            tournament = league.get('name', '') if isinstance(league, dict) else ''

            h2h.append({
                'home_team': home.get('name', ''),
                'away_team': away.get('name', ''),
                'score': f"{hs}:{as_}",
                'date': date_str,
                'tournament': tournament
            })
    except Exception as e:
        print(f"FotMob H2H parse error: {e}", flush=True)
    return h2h

def _find_next_fotmob_match(team_data: dict) -> dict:
    """Найти следующий матч из FotMob team data"""
    try:
        fixtures = team_data.get('fixtures', {})
        all_fix = fixtures.get('allFixtures', {})

        # Path 1: nextMatch
        next_match = None
        if isinstance(all_fix, dict):
            next_match = all_fix.get('nextMatch')

        if not next_match:
            # Path 2: overview.nextMatch
            next_match = team_data.get('overview', {}).get('nextMatch')

        if next_match:
            home = next_match.get('home', {})
            away = next_match.get('away', {})
            is_home = home.get('id') == FOTMOB_RM_ID or 'Real Madrid' in home.get('name', '')
            opp = away.get('name', '') if is_home else home.get('name', '')
            tourn = next_match.get('tournament') or next_match.get('league') or {}
            print(f"FotMob next match: {opp}, id={next_match.get('id')}", flush=True)
            return {
                'match_id': next_match.get('id'),
                'opponent': opp,
                'opponent_id': away.get('id') if is_home else home.get('id'),
                'is_home': is_home,
                'tournament': tourn.get('name', '') if isinstance(tourn, dict) else ''
            }

        # Path 3: ищем в списке fixtures незавершённый
        fix_list = all_fix.get('fixtures', []) if isinstance(all_fix, dict) else (all_fix if isinstance(all_fix, list) else [])
        for f in fix_list:
            if not f.get('status', {}).get('finished', False):
                home = f.get('home', {})
                away = f.get('away', {})
                is_home = home.get('id') == FOTMOB_RM_ID or 'Real Madrid' in home.get('name', '')
                opp = away.get('name', '') if is_home else home.get('name', '')
                tourn = f.get('tournament') or f.get('league') or {}
                return {
                    'match_id': f.get('id'),
                    'opponent': opp,
                    'opponent_id': away.get('id') if is_home else home.get('id'),
                    'is_home': is_home,
                    'tournament': tourn.get('name', '') if isinstance(tourn, dict) else ''
                }

        print(f"FotMob: no next match found. fixtures keys: {list(fixtures.keys())}", flush=True)
    except Exception as e:
        print(f"FotMob next match error: {e}", flush=True)
    return {}

@app.get("/api/match/analytics/debug")
async def debug_analytics():
    """Debug: тест FotMob API — raw structure"""
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
        return {"error": str(e), "tb": traceback.format_exc()[-500:]}

@app.get("/api/match/analytics")
async def get_match_analytics(nocache: bool = False):
    """Предматчевая аналитика: FotMob + Sheets fallback"""
    now = _time.time()
    cached = _analytics_cache['data']
    if not nocache and cached and not cached.get('error') and (now - _analytics_cache['time']) < _analytics_cache['ttl']:
        return cached

    try:
        # 1. Данные команды из FotMob
        team_data = _get_fotmob_team(FOTMOB_RM_ID)

        # 2. Следующий матч
        next_match = _find_next_fotmob_match(team_data) if team_data else {}
        opp_name = next_match.get('opponent', '')
        is_home = next_match.get('is_home', True)
        tournament = next_match.get('tournament', '')
        match_id = next_match.get('match_id')
        opp_id = next_match.get('opponent_id')

        # Фолбэк на Sheets если FotMob не дал следующий матч
        if not opp_name:
            try:
                matches = sheets_client.get_matches(limit=1)
                if matches:
                    m = matches[0]
                    opp_name = m.get('opponent', '')
                    is_home = m.get('is_home', True)
                    tournament = m.get('tournament', m.get('competition', ''))
            except:
                pass

        if not opp_name:
            return {"error": "Матч не найден"}

        # 3. Форма Real Madrid из FotMob
        rm_form = _parse_fotmob_form(team_data) if team_data else []

        # Фолбэк на Sheets если FotMob не дал форму
        if not rm_form:
            all_results = sheets_client.get_results() or []
            for r in all_results[:10]:
                score = r.get('score', '0:0')
                parts = score.replace('-', ':').split(':')
                try:
                    if r.get('is_home', True):
                        gf, ga = int(parts[0].strip()), int(parts[1].strip())
                    else:
                        ga, gf = int(parts[0].strip()), int(parts[1].strip())
                except (ValueError, IndexError):
                    gf, ga = 0, 0
                res_str = r.get('result', '')
                if res_str == 'win': res = 'W'
                elif res_str == 'loss': res = 'L'
                elif res_str == 'draw': res = 'D'
                elif gf > ga: res = 'W'
                elif gf < ga: res = 'L'
                else: res = 'D'
                rm_form.append({
                    'opponent': r.get('opponent', ''), 'goals_for': gf, 'goals_against': ga,
                    'result': res, 'is_home': r.get('is_home', True),
                    'score': score, 'date': r.get('date', ''), 'tournament': r.get('tournament', '')
                })

        # 4. Форма соперника из FotMob
        opp_form = []
        if opp_id:
            opp_data = _get_fotmob_team(opp_id)
            if opp_data:
                opp_form = _parse_fotmob_form(opp_data)

        # 5. H2H из FotMob (если есть match_id) + ESPN fallback
        h2h = []
        if match_id:
            match_details = _get_fotmob_match(match_id)
            if match_details:
                h2h = _parse_fotmob_h2h(match_details)

            # ESPN H2H fallback
            if not h2h and opp_name:
                try:
                    import datetime as _dt
                    today = _dt.datetime.utcnow().strftime('%Y%m%d')
                    espn_id = _espn_id_cache.get(match_id, '')
                    if not espn_id:
                        h = 'Real Madrid' if is_home else opp_name
                        a = opp_name if is_home else 'Real Madrid'
                        espn_id = _espn_find_event(today, h, a)
                    if espn_id:
                        summary = _espn_get_summary(espn_id)
                        if summary:
                            for g in summary.get('headToHeadGames', [])[:10]:
                                g_comps = g.get('competitions', [{}])[0]
                                g_teams = g_comps.get('competitors', [])
                                g_home = g_away = {}
                                for gt in g_teams:
                                    if gt.get('homeAway') == 'home':
                                        g_home = gt
                                    else:
                                        g_away = gt
                                g_date = g.get('date', '')[:10]
                                try:
                                    d = _dt.datetime.strptime(g_date, '%Y-%m-%d')
                                    g_date = d.strftime('%d.%m.%y')
                                except:
                                    pass
                                h2h.append({
                                    'home_team': g_home.get('team', {}).get('displayName', ''),
                                    'away_team': g_away.get('team', {}).get('displayName', ''),
                                    'score': str(g_home.get('score', '0')) + ':' + str(g_away.get('score', '0')),
                                    'date': g_date,
                                    'tournament': ''
                                })
                except Exception as e:
                    print(f"ESPN H2H fallback error: {e}", flush=True)

        # 6. Статистика
        def calc_stats(form, n=5):
            f = form[:n]
            if not f: return {}
            wins = sum(1 for m in f if m['result'] == 'W')
            draws = sum(1 for m in f if m['result'] == 'D')
            losses = sum(1 for m in f if m['result'] == 'L')
            gf = sum(m['goals_for'] for m in f)
            ga = sum(m['goals_against'] for m in f)
            cnt = len(f)
            return {
                'matches': cnt, 'wins': wins, 'draws': draws, 'losses': losses,
                'goals_for': gf, 'goals_against': ga,
                'avg_goals_for': round(gf / cnt, 1), 'avg_goals_against': round(ga / cnt, 1),
                'avg_total': round((gf + ga) / cnt, 1),
                'clean_sheets': sum(1 for m in f if m['goals_against'] == 0),
                'btts': sum(1 for m in f if m['goals_for'] > 0 and m['goals_against'] > 0),
            }

        # 7. H2H статистика
        h2h_stats = {}
        if h2h:
            rm_w = rm_l = h2h_d = 0
            for m in h2h:
                try:
                    s = m['score'].split(':')
                    hs, as_ = int(s[0]), int(s[1])
                    if 'Real Madrid' in m.get('home_team', ''):
                        if hs > as_: rm_w += 1
                        elif hs < as_: rm_l += 1
                        else: h2h_d += 1
                    else:
                        if as_ > hs: rm_w += 1
                        elif as_ < hs: rm_l += 1
                        else: h2h_d += 1
                except: pass
            h2h_stats = {'rm_wins': rm_w, 'opp_wins': rm_l, 'draws': h2h_d, 'total': len(h2h)}

        # 8. Серия
        streak = ''
        if rm_form:
            first_res = rm_form[0]['result']
            count = sum(1 for m in rm_form if m['result'] == first_res)
            for i, m in enumerate(rm_form):
                if m['result'] != first_res:
                    count = i
                    break
            label = {'W': 'побед', 'D': 'ничьих', 'L': 'поражений'}.get(first_res, '')
            if count > 1:
                streak = f"{count} {label} подряд"

        result = {
            "opponent": opp_name,
            "is_home": is_home,
            "tournament": tournament,
            "rm_form": rm_form[:5],
            "rm_stats": calc_stats(rm_form, 5),
            "opp_form": opp_form[:5],
            "opp_stats": calc_stats(opp_form, 5),
            "streak": streak,
            "h2h": h2h[:8],
            "h2h_stats": h2h_stats,
            "source": "fotmob" if team_data else "sheets"
        }

        _analytics_cache['data'] = result
        _analytics_cache['time'] = now
        return result

    except Exception as e:
        print(f"Analytics error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


@app.get("/api/match/details/{match_id}")
async def get_match_details(match_id: int):
    """Детализация матча: FotMob -> ESPN fallback -> basic fallback"""
    try:
        # 1. Try FotMob first (may still work for some requests)
        md = _get_fotmob_match(match_id)
        if md:
            header = md.get('header', {})
            teams = header.get('teams', [])
            general = md.get('general', {})
            content = md.get('content', {})

            home_t = teams[0] if len(teams) > 0 else {}
            away_t = teams[1] if len(teams) > 1 else {}

            events = _parse_fotmob_events(md)
            stats = _parse_fotmob_match_stats(md)
            shotmap = _parse_fotmob_shotmap(md)
            momentum = _parse_fotmob_momentum(md)
            lineups = _parse_fotmob_lineups(md)

            man_of_match = None
            mf = content.get('matchFacts', {})
            motm = mf.get('playerOfTheMatch', {})
            if motm:
                man_of_match = {
                    'name': motm.get('name', {}).get('fullName', motm.get('name', '')),
                    'rating': motm.get('rating', {}).get('num', ''),
                    'team': motm.get('teamName', ''),
                }

            highlight_url = _find_youtube_highlight(home_t.get('name', ''), away_t.get('name', ''))

            return {
                'match_id': match_id,
                'home_team': home_t.get('name', ''),
                'away_team': away_t.get('name', ''),
                'home_score': home_t.get('score', 0) or 0,
                'away_score': away_t.get('score', 0) or 0,
                'home_id': home_t.get('id', ''),
                'away_id': away_t.get('id', ''),
                'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{home_t['id']}.png" if home_t.get('id') else '',
                'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{away_t['id']}.png" if away_t.get('id') else '',
                'tournament': general.get('leagueName', ''),
                'round': general.get('leagueRoundName', ''),
                'finished': general.get('finished', False),
                'started': general.get('started', False),
                'events': events,
                'stats': stats,
                'shotmap': shotmap,
                'momentum': momentum,
                'lineups': lineups,
                'man_of_match': man_of_match,
                'highlight_url': highlight_url,
                'source': 'fotmob',
            }

        # 2. FotMob failed — try ESPN
        print(f"FotMob matchDetails failed for {match_id}, trying ESPN...", flush=True)

        # Chain: FotMob fixtures -> FotMob results cache -> Google Sheets
        home_name = ''
        away_name = ''
        match_date = ''
        tournament = ''
        fotmob_home_id = ''
        fotmob_away_id = ''
        sheets_score = ''

        # Step A: FotMob overviewFixtures (recent ~10 matches)
        try:
            team_data = _get_fotmob_team(FOTMOB_RM_ID)
            if team_data:
                ovf = team_data.get('overview', {}).get('overviewFixtures', [])
                for f in ovf:
                    if f.get('id') == match_id:
                        home_info = f.get('home', {})
                        away_info = f.get('away', {})
                        home_name = home_info.get('name', '')
                        away_name = away_info.get('name', '')
                        fotmob_home_id = home_info.get('id', '')
                        fotmob_away_id = away_info.get('id', '')
                        ts = f.get('status', {}).get('utcTime', '')
                        if ts:
                            match_date = ts[:10].replace('-', '')
                        tourn = f.get('tournament')
                        tournament = tourn.get('name', '') if isinstance(tourn, dict) else ''
                        break
        except Exception as e:
            print(f"FotMob fixtures lookup error: {e}", flush=True)

        # Step B: Google Sheets results (all past matches)
        if not home_name:
            try:
                sheets_results = sheets_client.get_results() if sheets_client else []
                sheets_matches = sheets_client.get_matches(limit=20) if sheets_client else []
                all_data = (sheets_results or []) + (sheets_matches or [])
                for sr in all_data:
                    opp = sr.get('opponent', '')
                    if not opp:
                        continue
                    is_home = sr.get('is_home', True)
                    h = 'Real Madrid' if is_home else opp
                    a = opp if is_home else 'Real Madrid'
                    date_raw = sr.get('date_raw', '') or sr.get('date', '')
                    # Normalize date to YYYYMMDD
                    dr = date_raw.replace('-', '')
                    if '.' in date_raw:
                        parts = date_raw.split('.')
                        if len(parts) == 3:
                            dr = parts[2] + parts[1] + parts[0]

                    # Try to match by searching ESPN for this match
                    # We don't have fotmob_match_id in sheets, so match by date
                    if not home_name and dr:
                        espn_test = _espn_find_event(dr, h, a)
                        if espn_test:
                            # Check if this is our match by trying to reverse-match
                            home_name = h
                            away_name = a
                            match_date = dr
                            tournament = sr.get('tournament', sr.get('competition', ''))
                            sheets_score = sr.get('score', '')
                            _espn_id_cache[match_id] = espn_test
                            print(f"Found match via Sheets: {h} vs {a} on {dr} -> ESPN {espn_test}", flush=True)
                            break
            except Exception as e:
                print(f"Sheets lookup error: {e}", flush=True)

        if not home_name:
            return {"error": "Match not found"}

        # Find ESPN event
        espn_id = _espn_id_cache.get(match_id, '')
        if not espn_id and match_date:
            espn_id = _espn_find_event(match_date, home_name, away_name)
            if espn_id:
                _espn_id_cache[match_id] = espn_id

        if not espn_id:
            # 3. ESPN not found — return basic data from FotMob/Sheets
            print(f"ESPN event not found for {home_name} vs {away_name}", flush=True)
            hs = as_ = 0
            if sheets_score:
                sp = sheets_score.replace('-', ':').split(':')
                try:
                    hs = int(sp[0].strip())
                    as_ = int(sp[1].strip())
                except:
                    pass
            return {
                'match_id': match_id,
                'home_team': home_name,
                'away_team': away_name,
                'home_score': hs,
                'away_score': as_,
                'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_home_id}.png" if fotmob_home_id else _get_team_logo(home_name),
                'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_away_id}.png" if fotmob_away_id else _get_team_logo(away_name),
                'tournament': tournament,
                'events': [],
                'stats': [],
                'lineups': {'home': [], 'away': []},
                'source': 'sheets',
            }

        # Get ESPN summary
        summary = _espn_get_summary(espn_id)
        if not summary:
            return {"error": "ESPN data unavailable"}

        # Parse ESPN data
        h_comps = summary.get('header', {}).get('competitions', [{}])[0]
        competitors = h_comps.get('competitors', [])
        espn_home = {}
        espn_away = {}
        for c in competitors:
            if c.get('homeAway') == 'home':
                espn_home = c
            else:
                espn_away = c

        espn_home_team = espn_home.get('team', {})
        espn_away_team = espn_away.get('team', {})

        home_logo = ''
        away_logo = ''
        if fotmob_home_id:
            home_logo = f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_home_id}.png"
        elif espn_home_team.get('logos'):
            home_logo = espn_home_team['logos'][0].get('href', '')
        if fotmob_away_id:
            away_logo = f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_away_id}.png"
        elif espn_away_team.get('logos'):
            away_logo = espn_away_team['logos'][0].get('href', '')

        events = _espn_parse_events(summary)
        stats = _espn_parse_stats(summary)
        lineups = _espn_parse_lineups(summary)

        status = h_comps.get('status', {}).get('type', {})
        finished = status.get('completed', False)
        started = status.get('name', '') != 'STATUS_SCHEDULED'

        highlight_url = _find_youtube_highlight(home_name or espn_home_team.get('displayName', ''), away_name or espn_away_team.get('displayName', ''))

        # Get player ratings from FotMob
        ratings_data = {}
        if fotmob_home_id or fotmob_away_id:
            try:
                ratings_data = _get_match_ratings(match_id, fotmob_home_id, fotmob_away_id)
            except Exception as e:
                print(f"Ratings fetch error: {e}", flush=True)

        print(f"ESPN match details OK: {espn_id} -> {home_name} vs {away_name}, events={len(events)}, stats={len(stats)}, ratings={'yes' if ratings_data.get('home') else 'no'}", flush=True)

        return {
            'match_id': match_id,
            'espn_id': espn_id,
            'home_team': home_name or espn_home_team.get('displayName', ''),
            'away_team': away_name or espn_away_team.get('displayName', ''),
            'home_score': int(espn_home.get('score', 0) or 0),
            'away_score': int(espn_away.get('score', 0) or 0),
            'home_id': str(fotmob_home_id),
            'away_id': str(fotmob_away_id),
            'home_logo': home_logo,
            'away_logo': away_logo,
            'tournament': tournament or summary.get('header', {}).get('league', {}).get('name', ''),
            'finished': finished,
            'started': started,
            'events': events,
            'stats': stats,
            'shotmap': [],
            'momentum': [],
            'lineups': lineups,
            'man_of_match': None,
            'highlight_url': highlight_url,
            'source': 'espn',
            'ratings': ratings_data,
        }
    except Exception as e:
        print(f"Match details error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

# === PLAYER RATINGS (FotMob lastLineupStats) ===
_fotmob_ratings_cache = {}
_RATINGS_CACHE_TTL = 3600  # 1 hour

def _get_match_ratings(match_id: int, home_team_id, away_team_id) -> dict:
    """Get player ratings from FotMob lastLineupStats for the given match.

    Returns full player data: rating, image, pitch position, events, subs.
    Only works if the match is the LAST match played by both teams.
    """
    cache_key = str(match_id)
    import time; now = time.time()
    cached = _fotmob_ratings_cache.get(cache_key)
    if cached and now - cached['time'] < _RATINGS_CACHE_TTL:
        return cached['data']

    result = {}
    pos_map = {0: 'GK', 1: 'DF', 2: 'MF', 3: 'FW'}
    pos_order = {'GK': 0, 'DF': 1, 'MF': 2, 'FW': 3}

    for team_id, side in [(home_team_id, 'home'), (away_team_id, 'away')]:
        if not team_id:
            continue
        try:
            team_data = _get_fotmob_team(int(team_id))
            if not team_data:
                continue
            ov = team_data.get('overview', {})
            lm = ov.get('lastMatch', {})

            if lm.get('id') != match_id:
                print(f"Ratings: team {team_id} lastMatch={lm.get('id')} != {match_id}, skip", flush=True)
                continue

            lls = ov.get('lastLineupStats', {})
            if not lls:
                continue

            players = []
            for is_starter, group in [(True, 'starters'), (False, 'subs')]:
                for p in lls.get(group, []):
                    perf = p.get('performance', {})
                    rating = perf.get('rating')
                    if not rating:
                        continue
                    pos_id = p.get('usualPlayingPositionId', -1)
                    pid = p.get('id', '')
                    hl = p.get('horizontalLayout', {})
                    events = perf.get('events', [])
                    sub_events = perf.get('substitutionEvents', [])
                    pdata = {
                        'name': p.get('name', ''),
                        'lastName': p.get('lastName', p.get('name', '').split()[-1] if p.get('name') else ''),
                        'rating': float(rating),
                        'position': pos_map.get(pos_id, 'MF'),
                        'number': p.get('shirtNumber', ''),
                        'starter': is_starter,
                        'imageUrl': f'https://images.fotmob.com/image_resources/playerimages/{pid}.png' if pid else '',
                    }
                    if is_starter and hl:
                        pdata['hx'] = hl.get('x', 0)
                        pdata['hy'] = hl.get('y', 0)
                    if events:
                        pdata['events'] = events
                    if sub_events:
                        pdata['subEvents'] = sub_events
                    players.append(pdata)

            players.sort(key=lambda x: (0 if x['starter'] else 1, pos_order.get(x['position'], 2)))

            coach = lls.get('coach', {})
            result[side] = players
            result[side + '_rating'] = lls.get('rating', 0)
            result[side + '_formation'] = lls.get('formation', '')
            if coach:
                result[side + '_coach'] = coach.get('name', '')
            print(f"Ratings: {side} team {team_id} -> {len(players)} players, avg={lls.get('rating')}", flush=True)
        except Exception as e:
            print(f"Ratings error for team {team_id}: {e}", flush=True)

    _fotmob_ratings_cache[cache_key] = {'data': result, 'time': now}
    return result


_yt_cache = {}  # {opponent: {url, time}}

def _find_youtube_highlight(home_team: str, away_team: str) -> str:
    """Find actual YouTube highlight video from RM official channel"""
    try:
        import urllib.parse, re

        rm_aliases = ['real madrid', 'real', 'madrid']
        if any(a in home_team.lower() for a in rm_aliases):
            opponent = away_team
        else:
            opponent = home_team
        opponent = opponent.strip()
        if not opponent:
            return None

        # Check cache (1 hour)
        cache_key = opponent.lower()
        cached = _yt_cache.get(cache_key)
        if cached and (_time.time() - cached['time']) < 3600:
            return cached['url']

        # Fetch YT channel search page
        search_url = f"https://www.youtube.com/@realmadrid/search?query={urllib.parse.quote(opponent)}"
        r = requests.get(search_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        })

        if r.status_code != 200:
            print(f"YouTube search: status={r.status_code}", flush=True)
            _yt_cache[cache_key] = {'url': search_url, 'time': _time.time()}
            return search_url

        # Extract first videoId from page HTML/JSON
        video_ids = re.findall(r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"', r.text)

        if video_ids:
            seen = set()
            for vid in video_ids:
                if vid not in seen:
                    video_url = f"https://www.youtube.com/watch?v={vid}"
                    print(f"YouTube highlight for {opponent}: {video_url}", flush=True)
                    _yt_cache[cache_key] = {'url': video_url, 'time': _time.time()}
                    return video_url
                seen.add(vid)

        print(f"YouTube: no videoId found for {opponent}", flush=True)
        _yt_cache[cache_key] = {'url': search_url, 'time': _time.time()}
        return search_url

    except Exception as e:
        print(f"YouTube highlight error: {e}", flush=True)
        return None

def _parse_fotmob_match_stats(md: dict) -> list:
    """Парсим статистику матча — пробуем все возможные структуры FotMob"""
    stats = []
    try:
        content = md.get('content', {})
        stats_data = content.get('stats', {})

        if not stats_data:
            # Try matchFacts fallback
            stats_data = content.get('matchFacts', {}).get('matchStats', {})

        print(f"FotMob stats_data type={type(stats_data).__name__}, keys={list(stats_data.keys()) if isinstance(stats_data, dict) else 'N/A'}", flush=True)

        def to_num(v):
            s = str(v).replace('%', '').replace(',', '.')
            try: return float(s)
            except: return 0

        def parse_sections(sections_list):
            """Parse a list of sections [{title, stats: [{title, stats: [h, a]}]}]"""
            for section in sections_list:
                if not isinstance(section, dict):
                    continue
                section_name = section.get('title', '')
                section_stats = section.get('stats', [])
                if not isinstance(section_stats, list):
                    continue
                for s in section_stats:
                    if not isinstance(s, dict):
                        continue
                    title = s.get('title', s.get('key', ''))
                    stat_arr = s.get('stats', [])
                    if isinstance(stat_arr, list) and len(stat_arr) >= 2:
                        stats.append({
                            'title': title,
                            'section': section_name,
                            'home': stat_arr[0],
                            'away': stat_arr[1],
                            'home_num': to_num(stat_arr[0]),
                            'away_num': to_num(stat_arr[1]),
                        })

        if isinstance(stats_data, dict):
            for key in stats_data:
                val = stats_data[key]
                print(f"  stats key={key}, val_type={type(val).__name__}", flush=True)
                if isinstance(val, list):
                    # Direct sections list
                    parse_sections(val)
                elif isinstance(val, dict):
                    # Nested: {"All": [...], "FirstHalf": [...], ...}
                    print(f"    nested keys={list(val.keys())}", flush=True)
                    if 'All' in val:
                        all_val = val['All']
                        print(f"    All type={type(all_val).__name__}, len={len(all_val) if isinstance(all_val, (list,dict)) else 'N/A'}", flush=True)
                        if isinstance(all_val, list):
                            parse_sections(all_val)
                        elif isinstance(all_val, dict):
                            # Maybe All is itself a dict of sections
                            for ak in all_val:
                                av = all_val[ak]
                                if isinstance(av, list):
                                    parse_sections(av)
                    else:
                        for sub_key in val:
                            sub_val = val[sub_key]
                            if isinstance(sub_val, list):
                                parse_sections(sub_val)
                                break
        elif isinstance(stats_data, list):
            parse_sections(stats_data)

        print(f"FotMob match stats: {len(stats)} parsed (before dedup)", flush=True)

        # Deduplicate by title (keep first occurrence) and filter None values
        seen = set()
        deduped = []
        for s in stats:
            if s['home'] is None or s['away'] is None:
                continue
            key = s['title']
            if key not in seen:
                seen.add(key)
                deduped.append(s)
        stats = deduped
        print(f"FotMob match stats: {len(stats)} after dedup", flush=True)
    except Exception as e:
        print(f"FotMob match stats error: {e}", flush=True)
    return stats

def _parse_fotmob_lineups(md: dict) -> dict:
    """Парсим составы с рейтингами из matchDetails"""
    result = {'home': [], 'away': [], 'home_formation': '', 'away_formation': '', 'home_rating': '', 'away_rating': ''}
    try:
        content = md.get('content', {})
        lineup_data = content.get('lineup', {})

        if not lineup_data:
            return result

        for side_key, out_key in [('homeTeam', 'home'), ('awayTeam', 'away')]:
            side = lineup_data.get(side_key, {})
            if not isinstance(side, dict):
                continue

            result[f'{out_key}_formation'] = side.get('formation', '')
            # Team rating
            team_rating = side.get('rating', '')
            if isinstance(team_rating, dict):
                result[f'{out_key}_rating'] = str(team_rating.get('num', ''))
            else:
                result[f'{out_key}_rating'] = str(team_rating) if team_rating else ''

            starters = side.get('starters', [])
            subs = side.get('subs', [])

            def parse_player(p, is_sub=False):
                if not isinstance(p, dict):
                    return None

                # Name — can be string or dict
                name_data = p.get('name', '')
                if isinstance(name_data, dict):
                    name = name_data.get('fullName', name_data.get('shortName', ''))
                else:
                    name = str(name_data)

                # Rating — can be dict {num: "7.3"}, string, number, or in performance
                rating = ''
                rating_data = p.get('rating', p.get('fantasyScore', ''))
                if isinstance(rating_data, dict):
                    rating = str(rating_data.get('num', ''))
                elif rating_data:
                    rating = str(rating_data)

                # Also check performance.rating
                if not rating:
                    perf = p.get('performance', {})
                    if isinstance(perf, dict):
                        r = perf.get('rating', '')
                        if r:
                            rating = str(r)

                return {
                    'name': name,
                    'number': p.get('shirtNumber', p.get('shirt', p.get('number', ''))),
                    'position': p.get('positionStringShort', p.get('position', p.get('role', ''))),
                    'rating': rating,
                    'is_captain': p.get('isCaptain', False),
                    'substitute': is_sub,
                    'minutes_played': p.get('minutesPlayed', None),
                    'x': p.get('verticalLayout', {}).get('x', None) if isinstance(p.get('verticalLayout'), dict) else None,
                    'y': p.get('verticalLayout', {}).get('y', None) if isinstance(p.get('verticalLayout'), dict) else None,
                    'hx': p.get('horizontalLayout', {}).get('x', None) if isinstance(p.get('horizontalLayout'), dict) else None,
                    'hy': p.get('horizontalLayout', {}).get('y', None) if isinstance(p.get('horizontalLayout'), dict) else None,
                    'image': f"https://images.fotmob.com/image_resources/playerimages/{p['id']}.png" if p.get('id') else None,
                }

            # Starters — can be flat list or nested [[GK], [DEF...], [MID...], [FWD...]]
            for item in starters:
                if isinstance(item, list):
                    for p in item:
                        parsed = parse_player(p, False)
                        if parsed:
                            result[out_key].append(parsed)
                elif isinstance(item, dict):
                    parsed = parse_player(item, False)
                    if parsed:
                        result[out_key].append(parsed)

            # Subs
            for item in subs:
                if isinstance(item, list):
                    for p in item:
                        parsed = parse_player(p, True)
                        if parsed:
                            result[out_key].append(parsed)
                elif isinstance(item, dict):
                    parsed = parse_player(item, True)
                    if parsed:
                        result[out_key].append(parsed)

        print(f"FotMob lineups: home={len(result['home'])}, away={len(result['away'])}", flush=True)
    except Exception as e:
        print(f"FotMob lineups error: {e}", flush=True)
    return result

@app.post("/api/bet/place")
async def place_bet_endpoint(bet: BetRequest, user: dict = Depends(get_current_user)):
    """Сделать ставку"""
    print(f"Place bet request: match_id={bet.match_id}, bet_type={bet.bet_type}, amount={bet.amount}")
    print(f"User: {user}")

    # Проверяем баланс
    if bet.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше 0")

    if bet.amount > user['balance']:
        raise HTTPException(status_code=400, detail="Недостаточно очков")

    # Получаем матч
    matches = sheets_client.get_matches(limit=1)
    odds_data = sheets_client.get_odds()

    if not matches:
        raise HTTPException(status_code=404, detail="Матч не найден")

    match = matches[0]

    # Проверяем время - нельзя ставить за 5 минут до матча и во время матча
    try:
        mt = datetime.strptime(f"{match.get('date')} {match.get('time')}", '%d.%m.%Y %H:%M')
        mt = mt.replace(tzinfo=MOSCOW_TZ)  # Время матча по Москве
        now = datetime.now(MOSCOW_TZ)  # Текущее время по Москве

        if now >= mt - timedelta(minutes=5):
            raise HTTPException(status_code=400, detail="Ставки закрыты (до матча менее 5 минут)")
    except ValueError:
        pass

    # Определяем коэффициент из Leon API
    opponent = match.get('opponent', '')
    leon_data = _get_leon_cached(target_opponent=opponent)
    leon_odds = leon_data.get('live_odds', {}) if leon_data else {}

    # Fallback: попробовать без opponent
    if not leon_odds:
        leon_data = _get_leon_cached()
        leon_odds = leon_data.get('live_odds', {}) if leon_data else {}

    # Проверяем bets_suspended
    if leon_data and leon_data.get('bets_suspended'):
        raise HTTPException(status_code=400, detail="Ставки приостановлены (пересчёт коэффициентов)")

    if bet.bet_type.startswith('score_'):
        odds = 30.0
    elif bet.bet_type in leon_odds and leon_odds[bet.bet_type]:
        odds = leon_odds[bet.bet_type]
    else:
        # Попробуем найти с нормализацией (точка/запятая в линиях)
        normalized_key = bet.bet_type.replace(',', '.')
        alt_key = bet.bet_type.replace('.', ',')
        if normalized_key in leon_odds and leon_odds[normalized_key]:
            odds = leon_odds[normalized_key]
        elif alt_key in leon_odds and leon_odds[alt_key]:
            odds = leon_odds[alt_key]
        else:
            print(f"Bet type '{bet.bet_type}' not found. Available keys: {list(leon_odds.keys())[:20]}")
            raise HTTPException(status_code=400, detail=f"Коэффициент для '{bet.bet_type}' не найден в Leon")

    # Формируем названия команд
    home_team = "Real Madrid" if match.get('is_home') else match.get('opponent')
    away_team = match.get('opponent') if match.get('is_home') else "Real Madrid"
    match_date = f"{match.get('date')} {match.get('time')}"

    # Делаем ставку
    bet_id = place_bet(
        user_id=user['user_id'],
        match_id=bet.match_id,
        bet_type=bet.bet_type,
        amount=bet.amount,
        odds=odds,
        home_team=home_team,
        away_team=away_team,
        match_date=match_date
    )

    if not bet_id:
        raise HTTPException(status_code=500, detail="Ошибка создания ставки")

    # Проверяем реферальный бонус (первая ставка)
    try:
        user_bets = get_user_bets(user['user_id'])
        if len(user_bets) == 1:  # Это первая ставка
            process_referral_bonus(user['user_id'])
    except Exception as e:
        print(f"Referral check error: {e}")

    return {
        "success": True,
        "bet_id": bet_id,
        "amount": bet.amount,
        "odds": odds,
        "potential_win": int(bet.amount * odds)
    }


@app.post("/api/bet/sell")
async def sell_bet_endpoint(req: SellBetRequest, user: dict = Depends(get_current_user)):
    """Продать ставку за 50%"""

    # Получаем ставку
    bets = get_user_bets(user['user_id'])
    bet = None
    for b in bets:
        if b['bet_id'] == req.bet_id and b['status'] == 'pending':
            bet = b
            break

    if not bet:
        raise HTTPException(status_code=404, detail="Ставка не найдена")

    # Проверяем что матч не начался (с московским временем)
    try:
        mt = datetime.strptime(bet['match_date'], '%d.%m.%Y %H:%M')
        mt = mt.replace(tzinfo=MOSCOW_TZ)  # Время матча по Москве
        now = datetime.now(MOSCOW_TZ)  # Текущее время по Москве

        if now >= mt - timedelta(minutes=1):
            raise HTTPException(status_code=400, detail="Нельзя продать - матч скоро начнётся или уже идёт")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail="Ошибка проверки времени матча")

    sell_price = max(1, bet['amount'] // 2)

    if sell_bet(req.bet_id, user['user_id'], sell_price):
        return {
            "success": True,
            "sell_price": sell_price,
            "message": f"Ставка продана за {sell_price} очков"
        }
    else:
        raise HTTPException(status_code=500, detail="Ошибка продажи")


class LiveBetRequest(BaseModel):
    match_id: str
    bet_type: str
    amount: int
    odds: float  # Коэффициент передаётся с фронта (live меняются)


@app.post("/api/bet/live")
async def place_live_bet(bet: LiveBetRequest, user: dict = Depends(get_current_user)):
    """Сделать LIVE ставку"""
    print(f"Live bet request: match_id={bet.match_id}, bet_type={bet.bet_type}, amount={bet.amount}, odds={bet.odds}")

    # Проверяем баланс
    if bet.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше 0")

    if bet.amount > user['balance']:
        raise HTTPException(status_code=400, detail="Недостаточно очков")

    # Проверяем что матч реально live (через SofaScore)
    live_match = get_sofascore_live_match()
    leon_data = _get_leon_cached()
    leon_is_live = leon_data and leon_data.get('is_live')
    if (not live_match or not live_match.get('is_live')) and not leon_is_live:
        raise HTTPException(status_code=400, detail="Нет live матча")

    # Получаем актуальные коэффициенты из Leon


    # Проверяем что ставки не suspended
    if leon_data and leon_data.get('bets_suspended'):
        raise HTTPException(status_code=400, detail="Ставки временно приостановлены")

    # Обновляем коэффициент если изменился
    if leon_data and leon_data.get('live_odds'):
        current_odds = leon_data.get('live_odds', {}).get(bet.bet_type)
        if current_odds and current_odds != bet.odds:
            # Коэффициент изменился - используем актуальный
            bet.odds = current_odds
            print(f"Odds updated to: {current_odds}")

    # Формируем названия команд
    home_team = (live_match or {}).get('home_team', '') or (leon_data or {}).get('home_team', '')
    away_team = (live_match or {}).get('away_team', '') or (leon_data or {}).get('away_team', '')
    minute = (live_match or {}).get('minute', '') or (leon_data or {}).get('minute', '')
    score = leon_data.get('score', '0:0') if leon_data and leon_data.get('score') else f"{(live_match or {}).get('home_score', 0)}:{(live_match or {}).get('away_score', 0)}"

    # Делаем ставку с пометкой LIVE
    bet_id = place_bet(
        user_id=user['user_id'],
        match_id=bet.match_id,
        bet_type=f"LIVE_{bet.bet_type}",  # Помечаем как live
        amount=bet.amount,
        odds=bet.odds,
        home_team=home_team,
        away_team=away_team,
        match_date=f"LIVE {minute} ({score})"
    )

    if not bet_id:
        raise HTTPException(status_code=500, detail="Ошибка создания ставки")

    return {
        "success": True,
        "bet_id": bet_id,
        "amount": bet.amount,
        "odds": bet.odds,
        "potential_win": int(bet.amount * bet.odds),
        "is_live": True,
        "minute": minute,
        "score": score
    }


@app.post("/api/prediction/make")
async def make_prediction_endpoint(req: PredictionRequest, user: dict = Depends(get_current_user)):
    """Сделать прогноз на матч"""
    print(f"Make prediction: match_id={req.match_id}, prediction={req.prediction}, user={user['user_id']}")

    # Проверяем валидность прогноза
    if req.prediction not in ['home', 'draw', 'away']:
        raise HTTPException(status_code=400, detail="Неверный тип прогноза")

    # Получаем матч
    matches = sheets_client.get_matches(limit=1)
    if not matches:
        raise HTTPException(status_code=404, detail="Матч не найден")

    match = matches[0]

    # Проверяем что матч не начался (с московским временем)
    try:
        match_time = datetime.strptime(f"{match.get('date')} {match.get('time')}", '%d.%m.%Y %H:%M')
        match_time = match_time.replace(tzinfo=MOSCOW_TZ)
        now = datetime.now(MOSCOW_TZ)

        if now >= match_time - timedelta(minutes=5):
            raise HTTPException(status_code=400, detail="Прогнозы закрыты (до матча менее 5 минут)")
    except ValueError:
        pass

    # Формируем данные
    home_team = "Real Madrid" if match.get('is_home') else match.get('opponent')
    away_team = match.get('opponent') if match.get('is_home') else "Real Madrid"
    match_date = f"{match.get('date')} {match.get('time')}"

    # Делаем прогноз
    prediction_id = make_prediction(
        user_id=user['user_id'],
        match_id=str(req.match_id),
        prediction=req.prediction,
        home_team=home_team,
        away_team=away_team,
        match_date=match_date
    )

    if not prediction_id:
        raise HTTPException(status_code=400, detail="Прогноз на этот матч уже сделан!")

    return {
        "success": True,
        "prediction_id": prediction_id,
        "message": "Прогноз принят!"
    }


@app.post("/api/prediction/make")
async def make_prediction_endpoint(pred: PredictionRequest, user: dict = Depends(get_current_user)):
    """Сделать бесплатный прогноз"""

    matches = sheets_client.get_matches(limit=1)
    if not matches:
        raise HTTPException(status_code=404, detail="Матч не найден")

    match = matches[0]
    home_team = "Real Madrid" if match.get('is_home') else match.get('opponent')
    away_team = match.get('opponent') if match.get('is_home') else "Real Madrid"
    match_date = f"{match.get('date')} {match.get('time')}"

    pred_id = make_prediction(
        user_id=user['user_id'],
        match_id=pred.match_id,
        prediction=pred.prediction,
        home_team=home_team,
        away_team=away_team,
        match_date=match_date
    )

    if not pred_id:
        raise HTTPException(status_code=400, detail="Прогноз уже сделан")

    return {"success": True, "prediction_id": pred_id}


@app.get("/api/leaderboard")
async def get_leaderboard_endpoint(limit: int = 100):
    """Получить рейтинг игроков"""
    leaders = get_leaderboard(limit=limit)

    # Fetch missing avatars in background (max 10 at a time)
    from concurrent.futures import ThreadPoolExecutor
    missing_uids = []
    for l in leaders:
        uid = l.get('user_id')
        if uid and uid not in _user_photos_fetched:
            avatar_path = f"{_AVATAR_DIR}/{uid}.jpg"
            if os.path.exists(avatar_path):
                _user_photos[uid] = True
                _user_photos_fetched.add(uid)
            else:
                missing_uids.append(uid)

    if missing_uids:
        fetch_uids = missing_uids[:10]
        try:
            with ThreadPoolExecutor(max_workers=5) as pool:
                results = list(pool.map(_fetch_and_save_avatar, fetch_uids))
            for uid, ok in zip(fetch_uids, results):
                _user_photos_fetched.add(uid)
                if ok:
                    _user_photos[uid] = True
        except Exception as e:
            print(f"Batch avatar fetch error: {e}", flush=True)

    # Set photo_url as local API URL
    for l in leaders:
        uid = l.get('user_id')
        avatar_path = f"{_AVATAR_DIR}/{uid}.jpg"
        l['photo_url'] = f"/api/avatar/{uid}" if (uid in _user_photos or os.path.exists(avatar_path)) else ''

    return {"leaderboard": leaders}


@app.get("/api/avatar/{user_id}")
async def get_avatar(user_id: int):
    """Serve user avatar image"""
    from fastapi.responses import FileResponse, Response
    avatar_path = f"{_AVATAR_DIR}/{user_id}.jpg"
    if os.path.exists(avatar_path):
        return FileResponse(
            avatar_path,
            media_type='image/jpeg',
            headers={"Cache-Control": "public, max-age=3600"}
        )
    # Try to fetch on-the-fly
    if _fetch_and_save_avatar(user_id) and os.path.exists(avatar_path):
        _user_photos[user_id] = True
        return FileResponse(
            avatar_path,
            media_type='image/jpeg',
            headers={"Cache-Control": "public, max-age=3600"}
        )
    # Return 1x1 transparent pixel as fallback
    return Response(
        content=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82',
        media_type='image/png',
        status_code=200,
        headers={"Cache-Control": "public, max-age=300"}
    )


@app.get("/api/stats")
async def get_stats():
    """Получить глобальную статистику"""
    stats = get_global_stats()
    return {"stats": stats}


@app.get("/api/prizes")
async def get_prizes(user: dict = Depends(get_current_user)):
    """Получить список призов"""
    prizes = [
        {"id": 1, "name": "Telegram Premium 3 мес", "cost": 1000, "icon": "⭐", "requires": "phone"},
        {"id": 2, "name": "Футболка Real Madrid", "cost": 1500, "icon": "👕", "requires": "size"},
        {"id": 3, "name": "PlayStation 5", "cost": 50000, "icon": "🎮", "requires": "address"},
    ]

    can_claim = can_claim_prize(user['user_id'])

    return {
        "prizes": prizes,
        "user_balance": user['balance'],
        "can_claim": can_claim
    }


@app.post("/api/prize/claim")
async def claim_prize_endpoint(req: ClaimPrizeRequest, user: dict = Depends(get_current_user)):
    """Запросить приз"""
    # Список призов с названиями
    prizes_map = {
        1: {"name": "Telegram Premium 3 мес", "cost": 1000, "icon": "⭐"},
        2: {"name": "Футболка Real Madrid", "cost": 1500, "icon": "👕"},
        3: {"name": "PlayStation 5", "cost": 50000, "icon": "🎮"},
    }

    prize_info = prizes_map.get(req.prize_id)
    if not prize_info:
        raise HTTPException(status_code=400, detail="Приз не найден")

    # Формируем полный контакт с доп. данными
    contact_info = req.contact
    if req.size:
        contact_info += f" | Размер: {req.size}"
    if req.phone:
        contact_info += f" | Телефон: {req.phone}"
    if req.address:
        contact_info += f" | Адрес: {req.address}"

    success, message = claim_prize(user['user_id'], req.prize_id, contact_info)

    if not success:
        raise HTTPException(status_code=400, detail=message)

    # Обновляем описание транзакции с правильным названием приза
    try:
        from database import _execute
        _execute(
            """UPDATE transactions SET description = ?
               WHERE transaction_id = (
                   SELECT transaction_id FROM transactions
                   WHERE user_id = ? AND type = 'prize'
                   ORDER BY created_at DESC LIMIT 1
               )""",
            (f"Заявка на приз: {prize_info['name']}", user['user_id'])
        )
    except Exception as e:
        print(f"Failed to update prize description: {e}")

    # Уведомление админу через Telegram
    try:
        username = user.get('username', '') or user.get('first_name', '') or str(user['user_id'])
        text = (
            f"🏆 <b>Заявка на приз!</b>\n\n"
            f"👤 @{username}\n"
            f"{prize_info['icon']} {prize_info['name']}\n"
            f"💰 Стоимость: {prize_info['cost']} очков\n"
            f"📞 Контакт: {contact_info}"
        )
        import requests as req_lib
        for admin_id in ADMIN_IDS:
            req_lib.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": admin_id, "text": text, "parse_mode": "HTML"},
                timeout=5
            )
    except Exception as e:
        print(f"Failed to notify admin: {e}")

    return {"success": True, "message": message}


# ============ НОВОСТИ И СОСТАВЫ ============

# Кэш для новостей (обновляется каждые 5 минут, всегда хранит 10 последних)
_news_cache = {'data': [], 'time': None}
_NEWS_CACHE_TTL = timedelta(minutes=5)

@app.get("/api/news")
async def get_news(count: int = 10):
    """Получить новости из Telegram канала (с кэшированием)"""
    global _news_cache

    try:
        need_update = False

        # Проверяем нужно ли обновить кэш
        if not _news_cache['data']:
            need_update = True
        elif not _news_cache['time']:
            need_update = True
        elif datetime.now() - _news_cache['time'] > _NEWS_CACHE_TTL:
            need_update = True

        # Если есть кэш - сразу отдаём его
        if _news_cache['data'] and not need_update:
            return {"news": _news_cache['data'][:count], "count": len(_news_cache['data'][:count])}

        # Пытаемся обновить
        try:
            news = await get_telegram_news_async(count=10)  # Всегда запрашиваем 10
            if news:
                _news_cache = {'data': news, 'time': datetime.now()}
                return {"news": news[:count], "count": len(news[:count])}
        except Exception as e:
            print(f"News fetch error: {e}")

        # Если не удалось обновить - возвращаем старый кэш
        if _news_cache['data']:
            return {"news": _news_cache['data'][:count], "count": len(_news_cache['data'][:count])}

        return {"news": [], "count": 0}

    except Exception as e:
        print(f"News error: {e}")
        if _news_cache['data']:
            return {"news": _news_cache['data'][:count], "count": len(_news_cache['data'][:count])}
        return {"news": [], "error": str(e)}


@app.get("/api/lineups")
async def get_lineups():
    """Получить стартовые составы из Telegram"""
    try:
        lineups = await get_telegram_lineups_async()
        return {"lineups": lineups[:5], "count": len(lineups[:5])}
    except Exception as e:
        print(f"Lineups error: {e}")
        return {"lineups": [], "error": str(e)}


# === FOTMOB LIVE MATCH ===
_fotmob_live_cache = {'data': None, 'time': 0, 'ttl': 30}  # 30 sec cache

def get_fotmob_live_match() -> Dict:
    """Получить live матч Real Madrid из FotMob"""
    now = _time.time()
    cached = _fotmob_live_cache['data']
    if cached and (now - _fotmob_live_cache['time']) < _fotmob_live_cache['ttl']:
        return cached

    try:
        # 1. Проверяем team page на hasOngoingMatch
        team_data = _get_fotmob_team(FOTMOB_RM_ID)
        if not team_data:
            return {'is_live': False}

        overview = team_data.get('overview', {})
        has_ongoing = overview.get('hasOngoingMatch', False)

        if not has_ongoing:
            _fotmob_live_cache['data'] = {'is_live': False}
            _fotmob_live_cache['time'] = now
            return {'is_live': False}

        # 2. Найти live match ID из overviewFixtures
        match_id = None
        ov_fixtures = overview.get('overviewFixtures', [])
        for f in ov_fixtures:
            status = f.get('status', {})
            if status.get('started') and not status.get('finished'):
                match_id = f.get('id')
                break

        if not match_id:
            # Fallback: lastMatch if started and not finished
            lm = overview.get('lastMatch', {})
            if lm:
                lm_status = lm.get('status', {})
                if lm_status.get('started') and not lm_status.get('finished'):
                    match_id = lm.get('id')

        if not match_id:
            return {'is_live': False}

        print(f"FotMob LIVE: match_id={match_id}", flush=True)

        # 3. Получить matchDetails (FotMob -> ESPN fallback)
        match_data = _get_fotmob_match(match_id)
        if match_data:
            # 4. Парсим FotMob
            result = _parse_fotmob_live_match(match_data, match_id)
        else:
            # FotMob matchDetails blocked - ESPN fallback for live
            print(f"FotMob live matchDetails blocked, trying ESPN for {match_id}...", flush=True)
            home_name = ""
            away_name = ""
            fotmob_home_id = ""
            fotmob_away_id = ""
            for f in ov_fixtures:
                if f.get("id") == match_id:
                    home_name = f.get("home", {}).get("name", "")
                    away_name = f.get("away", {}).get("name", "")
                    fotmob_home_id = f.get("home", {}).get("id", "")
                    fotmob_away_id = f.get("away", {}).get("id", "")
                    break

            import datetime as _dt
            today = _dt.datetime.utcnow().strftime("%Y%m%d")
            espn_id = _espn_find_event(today, home_name, away_name) if home_name else ""
            summary = _espn_get_summary(espn_id) if espn_id else {}

            if summary:
                h_comps = summary.get("header", {}).get("competitions", [{}])[0]
                competitors = h_comps.get("competitors", [])
                espn_home = {}
                espn_away = {}
                for c in competitors:
                    if c.get("homeAway") == "home":
                        espn_home = c
                    else:
                        espn_away = c

                espn_minute_raw = h_comps.get("status", {}).get("displayClock", "")
                espn_minute = espn_minute_raw.replace("'", "").strip() + "'" if espn_minute_raw else ""

                result = {
                    "is_live": True,
                    "match_id": match_id,
                    "home_team": home_name or espn_home.get("team", {}).get("displayName", ""),
                    "away_team": away_name or espn_away.get("team", {}).get("displayName", ""),
                    "home_score": int(espn_home.get("score", 0) or 0),
                    "away_score": int(espn_away.get("score", 0) or 0),
                    "home_logo": f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_home_id}.png" if fotmob_home_id else "",
                    "away_logo": f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_away_id}.png" if fotmob_away_id else "",
                    "minute": espn_minute,
                    "tournament": "",
                    "incidents": _espn_parse_events(summary),
                    "stats": _espn_parse_stats(summary),
                    "momentum": [],
                    "shotmap": [],
                    "lineups": _espn_parse_lineups(summary),
                    "bets_suspended": False,
                    "source": "espn",
                }
            else:
                return {"is_live": False}

        _fotmob_live_cache['data'] = result
        _fotmob_live_cache['time'] = now
        return result

    except Exception as e:
        print(f"FotMob live error: {e}", flush=True)
        return {'is_live': False, 'error': str(e)}

def _parse_fotmob_live_match(md: dict, match_id: int) -> dict:
    """Парсим matchDetails в live данные"""
    try:
        header = md.get('header', {})
        teams = header.get('teams', [])

        home_team_data = teams[0] if len(teams) > 0 else {}
        away_team_data = teams[1] if len(teams) > 1 else {}

        home_team = home_team_data.get('name', '')
        away_team = away_team_data.get('name', '')
        home_score = home_team_data.get('score', 0) or 0
        away_score = away_team_data.get('score', 0) or 0

        # Minute
        general = md.get('general', {})
        match_status = general.get('matchTimeUTCDate') or ''
        started = general.get('started', False)
        finished = general.get('finished', False)

        # Get minute from header status
        header_status = md.get('header', {}).get('status', {})
        minute = header_status.get('liveTime', {}).get('short', '')
        if not minute:
            minute = header_status.get('reason', {}).get('short', '')

        # Tournament
        tournament = general.get('leagueName', '')

        # Events
        events = _parse_fotmob_events(md)

        # Stats
        stats = _parse_fotmob_stats(md)

        # Momentum
        momentum = _parse_fotmob_momentum(md)

        # Shotmap
        shotmap = _parse_fotmob_shotmap(md)

        # Lineups
        lineups = _parse_fotmob_lineups(md)

        return {
            'is_live': True,
            'match_id': match_id,
            'home_team': home_team,
            'away_team': away_team,
            'home_score': int(home_score),
            'away_score': int(away_score),
            'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{home_team_data.get('id','')}.png" if home_team_data.get('id') else '',
            'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{away_team_data.get('id','')}.png" if away_team_data.get('id') else '',
            'minute': minute,
            'tournament': tournament,
            'incidents': events,
            'stats': stats,
            'momentum': momentum,
            'shotmap': shotmap,
            'lineups': lineups,
            'fotmob_url': f'https://www.fotmob.com/matches/{match_id}',
            'bets_suspended': False,
        }
    except Exception as e:
        print(f"FotMob parse live error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {'is_live': False, 'error': str(e)}

def _parse_fotmob_events(md: dict) -> list:
    """Парсим события из matchDetails (goals, cards, subs)"""
    events = []
    try:
        content = md.get('content', {})
        match_facts = content.get('matchFacts', {})

        # Events in matchFacts.events.events
        events_data = match_facts.get('events', {})
        if isinstance(events_data, dict):
            events_list = events_data.get('events', [])
        elif isinstance(events_data, list):
            events_list = events_data
        else:
            events_list = []

        header_teams = md.get('header', {}).get('teams', [{}, {}])
        home_id = header_teams[0].get('id', 0) if len(header_teams) > 0 else 0

        for ev in events_list:
            ev_type = ev.get('type', '')
            minute = ev.get('time', ev.get('timeStr', 0))
            if isinstance(minute, str):
                minute = minute.replace("'", "").strip()
                try:
                    minute = int(minute.split('+')[0])
                except:
                    minute = 0

            is_home = ev.get('isHome', False)
            # Alternative: check team id
            if 'teamId' in ev:
                is_home = ev['teamId'] == home_id

            if ev_type == 'Goal':
                player = ev.get('nameStr', ev.get('player', {}).get('name', ''))
                assist = ''
                if ev.get('assistStr'):
                    assist = ev['assistStr'].replace('assist by ', '').replace('Assist: ', '')
                elif ev.get('assist', {}).get('name'):
                    assist = ev['assist']['name']

                new_score = ev.get('newScore', [])
                score_str = f"{new_score[0]}-{new_score[1]}" if len(new_score) >= 2 else ''

                events.append({
                    'type': 'goal',
                    'minute': minute,
                    'player': player,
                    'assist': assist or None,
                    'home': is_home,
                    'score': score_str,
                    'own_goal': ev.get('ownGoal', False),
                    'penalty': ev.get('isPenalty', False) or 'pen' in str(ev.get('goalDescription', '')).lower(),
                })
            elif ev_type == 'Card':
                card = ev.get('card', '')
                player = ev.get('nameStr', ev.get('player', {}).get('name', ''))
                card_type = 'yellow'
                if 'Red' in card or 'red' in card:
                    card_type = 'red'
                elif 'Yellow' in card and 'Red' in card:
                    card_type = 'second_yellow'

                events.append({
                    'type': card_type,
                    'minute': minute,
                    'player': player,
                    'home': is_home,
                })
            elif ev_type == 'Substitution':
                swap = ev.get('swap', [])
                player_in = swap[0].get('name', '') if len(swap) > 0 else ev.get('nameStr', '')
                player_out = swap[1].get('name', '') if len(swap) > 1 else ''

                events.append({
                    'type': 'sub',
                    'minute': minute,
                    'player_in': player_in,
                    'player_out': player_out,
                    'home': is_home,
                })
            elif ev_type == 'Half':
                events.append({
                    'type': 'half',
                    'minute': minute,
                    'text': ev.get('nameStr', 'HT'),
                    'home': True,
                })

    except Exception as e:
        print(f"FotMob events parse error: {e}", flush=True)
    return events

def _parse_fotmob_stats(md: dict) -> list:
    """Парсим статистику из matchDetails — same as match_stats"""
    return _parse_fotmob_match_stats(md)

def _parse_fotmob_momentum(md: dict) -> list:
    """Парсим momentum из matchDetails"""
    try:
        content = md.get('content', {})
        momentum = content.get('momentum', {})
        if isinstance(momentum, dict):
            main = momentum.get('main', {})
            data = main.get('data', [])
            if data:
                return data  # [{minute: X, value: Y}, ...]
        elif isinstance(momentum, list):
            return momentum
    except Exception as e:
        print(f"FotMob momentum error: {e}", flush=True)
    return []

def _parse_fotmob_shotmap(md: dict) -> list:
    """Парсим shotmap из matchDetails"""
    shots = []
    try:
        content = md.get('content', {})
        shotmap_data = content.get('shotmap', {})

        if isinstance(shotmap_data, dict):
            shots_list = shotmap_data.get('shots', [])
        elif isinstance(shotmap_data, list):
            shots_list = shotmap_data
        else:
            shots_list = []

        header_teams = md.get('header', {}).get('teams', [{}, {}])
        home_id = header_teams[0].get('id', 0) if len(header_teams) > 0 else 0

        for shot in shots_list:
            is_home = shot.get('teamId', 0) == home_id
            shots.append({
                'x': shot.get('x', 0),
                'y': shot.get('y', 0),
                'xG': shot.get('expectedGoals', 0),
                'result': shot.get('eventType', ''),  # Goal, Miss, AttemptSaved, Blocked
                'player': shot.get('playerName', shot.get('fullName', '')),
                'minute': shot.get('min', 0),
                'home': is_home,
                'on_target': shot.get('isOnTarget', False),
                'blocked': shot.get('isBlocked', False),
            })
    except Exception as e:
        print(f"FotMob shotmap error: {e}", flush=True)
    return shots


@app.get("/api/live/debug")
async def debug_live():
    """Debug: test FotMob live detection"""
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

@app.get("/api/live")
async def get_live_match():
    """Получить текущий LIVE матч Real Madrid — FotMob + Leon"""
    try:
        # 1. FotMob live данные (счёт, события, статистика, momentum, shotmap)
        fotmob_live = get_fotmob_live_match()

        # 2. Leon коэффициенты
        leon_data = _get_leon_cached()

        is_live_fotmob = fotmob_live and fotmob_live.get('is_live')
        is_live_leon = leon_data and leon_data.get('is_live')

        if is_live_fotmob:
            result = fotmob_live.copy()

            # Add Leon live odds
            if leon_data and leon_data.get('live_odds'):
                result['live_odds'] = leon_data.get('live_odds', {})
                result['leon_id'] = leon_data.get('leon_id')
                result['bets_suspended'] = leon_data.get('bets_suspended', False)
            else:
                result['live_odds'] = {}
                result['bets_suspended'] = True

            # Add Leon stats as supplement
            if leon_data and leon_data.get('liveStatus'):
                ls = leon_data['liveStatus']
                result['leon_stats'] = {
                    'home': ls.get('homeStatistics', {}),
                    'away': ls.get('awayStatistics', {})
                }

            return result

        elif is_live_leon:
            # Fallback: Leon only (no FotMob)
            home_team = leon_data.get('home_team')
            away_team = leon_data.get('away_team')
            leon_score = leon_data.get('score', '0:0')
            if leon_score and ':' in str(leon_score):
                score_parts = str(leon_score).split(':')
                home_score = int(score_parts[0]) if score_parts[0].isdigit() else 0
                away_score = int(score_parts[1]) if score_parts[1].isdigit() else 0
            else:
                home_score = 0
                away_score = 0

            result = {
                'is_live': True,
                'match_id': None,
                'home_team': home_team,
                'away_team': away_team,
                'home_logo': _get_team_logo(home_team),
                'away_logo': _get_team_logo(away_team),
                'home_score': home_score,
                'away_score': away_score,
                'minute': leon_data.get('minute', ''),
                'tournament': leon_data.get('liveStatus', {}).get('stage', '') if leon_data.get('liveStatus') else '',
                'incidents': [],
                'stats': [],
                'momentum': [],
                'shotmap': [],
                'bets_suspended': False,
            }

            if leon_data.get('live_odds'):
                result['live_odds'] = leon_data.get('live_odds', {})
                result['leon_id'] = leon_data.get('leon_id')
                result['bets_suspended'] = leon_data.get('bets_suspended', False)

            if leon_data.get('liveStatus'):
                ls = leon_data['liveStatus']
                result['leon_stats'] = {
                    'home': ls.get('homeStatistics', {}),
                    'away': ls.get('awayStatistics', {})
                }

            return result

        elif leon_data and leon_data.get('leon_id'):
            return {
                "is_live": False,
                "next_match": {
                    "home_team": leon_data.get('home_team'),
                    "away_team": leon_data.get('away_team'),
                    "kickoff": leon_data.get('kickoff'),
                    "pre_match_odds": leon_data.get('live_odds', {})
                }
            }
        else:
            return {"is_live": False}
    except Exception as e:
        print(f"Live error: {e}", flush=True)
        return {"is_live": False, "error": str(e)}


@app.get("/api/odds")
async def get_current_odds():
    """Получить актуальные коэффициенты на следующий матч Real Madrid из Leon"""
    try:
        # First check for live match
        live_data = _get_leon_cached()
        if live_data and live_data.get('is_live') and live_data.get('live_odds'):
            return {
                "success": True,
                "source": "leon",
                "match": f"{live_data.get('home_team', '')} - {live_data.get('away_team', '')}",
                "home_team": live_data.get('home_team'),
                "away_team": live_data.get('away_team'),
                "kickoff": "LIVE",
                "is_live": True,
                "odds": live_data.get('live_odds', {})
            }

        # Fallback to prematch odds
        leon_data = get_leon_real_madrid_odds()
        if leon_data:
            return {
                "success": True,
                "source": "leon",
                "match": leon_data.get('name'),
                "home_team": leon_data.get('home_team'),
                "away_team": leon_data.get('away_team'),
                "kickoff": leon_data.get('kickoff'),
                "is_live": leon_data.get('is_live', False),
                "odds": leon_data.get('odds', {})
            }
        else:
            # Фолбэк на Google Sheets
            odds_data = sheets_client.get_odds() if sheets_client else {}
            return {
                "success": True,
                "source": "sheets",
                "odds": odds_data
            }
    except Exception as e:
        print(f"Odds error: {e}")
        return {"success": False, "error": str(e)}


# ============ ВИКТОРИНА ============

import random

# Вопросы викторины по сложности
# ============ ВИКТОРИНА ============

import json
import os

# Загрузка вопросов из JSON файлов
def load_quiz_questions():
    questions = {}
    quiz_dir = os.path.join(os.path.dirname(__file__), 'quiz_questions')

    for difficulty in ['easy', 'medium', 'hard', 'expert']:
        filepath = os.path.join(quiz_dir, f'{difficulty}.json')
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                questions[difficulty] = json.load(f)
                print(f"Loaded {len(questions[difficulty])} {difficulty} questions")
        except Exception as e:
            print(f"Error loading {difficulty} questions: {e}")
            questions[difficulty] = []

    return questions

QUIZ_QUESTIONS = load_quiz_questions()

QUIZ_POINTS = {'easy': 5, 'medium': 10, 'hard': 15, 'expert': 25}

# Cooldown хранилище (в памяти + БД для надёжности)
quiz_cooldowns = {}
quiz_question_started = {}
quiz_asked_questions = {}
_game_sessions = {}  # user_id -> {'started_at': datetime, 'result_submitted': bool}

def _get_last_game_time(user_id: int) -> float:
    """Получить время последней игры из БД"""
    # Сначала проверяем память
    if user_id in quiz_cooldowns:
        mem_time = quiz_cooldowns[user_id]
        if isinstance(mem_time, (int, float)):
            return mem_time
        elif isinstance(mem_time, datetime):
            return mem_time.timestamp()

    # Потом БД
    try:
        from database import _execute
        row = _execute(
            "SELECT created_at FROM transactions WHERE user_id = ? AND type IN ('game_win', 'quiz_win', 'bonus') AND description LIKE '%Игра%' ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        )
        if row:
            from datetime import datetime as dt
            ts = row[0].get('created_at', '')
            if ts:
                try:
                    t = dt.strptime(ts, '%Y-%m-%d %H:%M:%S')
                    return t.timestamp()
                except:
                    pass
    except:
        pass
    return 0

def _set_cooldown(user_id: int):
    """Установить cooldown в памяти"""
    quiz_cooldowns[user_id] = datetime.now().timestamp()

@app.get("/api/quiz/status")
async def get_quiz_status(user: dict = Depends(get_current_user)):
    """Проверить статус викторины для пользователя"""
    user_id = user['user_id']
    last_quiz = _get_last_game_time(user_id)
    now = datetime.now().timestamp()
    cooldown_end = last_quiz + 86400  # 24 часа

    if now < cooldown_end:
        remaining = int(cooldown_end - now)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        return {
            "available": False,
            "remaining_seconds": remaining,
            "remaining_text": f"{hours}ч {minutes}м"
        }

    return {"available": True, "remaining_seconds": 0}


@app.get("/api/quiz/question")
async def get_quiz_question(difficulty: str, user: dict = Depends(get_current_user)):
    """Получить вопрос викторины"""
    if difficulty not in QUIZ_QUESTIONS:
        raise HTTPException(status_code=400, detail="Неверная сложность")

    # Проверяем cooldown
    user_id = user['user_id']
    last_quiz = quiz_cooldowns.get(user_id, 0)
    now = datetime.now().timestamp()

    if now < last_quiz + 86400:
        raise HTTPException(status_code=400, detail="Викторина будет доступна позже")

    # Получаем список уже заданных вопросов для этого пользователя
    if user_id not in quiz_asked_questions:
        quiz_asked_questions[user_id] = {}
    if difficulty not in quiz_asked_questions[user_id]:
        quiz_asked_questions[user_id][difficulty] = []

    asked = quiz_asked_questions[user_id][difficulty]
    all_questions = QUIZ_QUESTIONS[difficulty]

    # Фильтруем уже заданные вопросы
    available = [q for q in all_questions if q["q"] not in asked]

    # Если все вопросы заданы - сбрасываем историю
    if not available:
        quiz_asked_questions[user_id][difficulty] = []
        available = all_questions

    # Выбираем случайный вопрос
    random.shuffle(available)
    question = available[0]

    # Запоминаем заданный вопрос
    quiz_asked_questions[user_id][difficulty].append(question["q"])

    # Ограничиваем историю последними 50 вопросами
    if len(quiz_asked_questions[user_id][difficulty]) > 50:
        quiz_asked_questions[user_id][difficulty] = quiz_asked_questions[user_id][difficulty][-50:]

    # Записываем время начала вопроса (для проверки таймера)
    quiz_question_started[user_id] = now

    return {
        "question": question["q"],
        "answers": question["a"],
        "difficulty": difficulty,
        "points": QUIZ_POINTS[difficulty],
        "timer_seconds": 15  # Таймер 15 секунд
    }


class QuizAnswerRequest(BaseModel):
    difficulty: str
    question: str
    answer_index: int

@app.post("/api/quiz/answer")
async def submit_quiz_answer(req: QuizAnswerRequest, user: dict = Depends(get_current_user)):
    """Ответить на вопрос викторины"""
    if req.difficulty not in QUIZ_QUESTIONS:
        raise HTTPException(status_code=400, detail="Неверная сложность")

    user_id = user['user_id']
    now = datetime.now().timestamp()

    # Проверяем cooldown (уже играл сегодня)
    last_quiz = quiz_cooldowns.get(user_id, 0)
    if now < last_quiz + 86400:
        raise HTTPException(status_code=400, detail="Викторина уже пройдена")

    # Проверяем таймер 30 секунд
    question_start = quiz_question_started.get(user_id, 0)
    if question_start > 0 and (now - question_start) > 35:  # 35 сек с запасом
        # Время вышло
        quiz_cooldowns[user_id] = now
        quiz_question_started.pop(user_id, None)
        return {
            "correct": False,
            "correct_index": -1,
            "points_earned": 0,
            "next_quiz_in": 86400,
            "timeout": True,
            "message": "Время вышло! (30 сек)"
        }

    # Ищем вопрос
    question_data = None
    for q in QUIZ_QUESTIONS[req.difficulty]:
        if q["q"] == req.question:
            question_data = q
            break

    if not question_data:
        raise HTTPException(status_code=400, detail="Вопрос не найден")

    # Проверяем ответ
    correct = req.answer_index == question_data["correct"]
    points = QUIZ_POINTS[req.difficulty] if correct else 0

    # Ставим cooldown
    quiz_cooldowns[user_id] = now
    quiz_question_started.pop(user_id, None)

    # Начисляем очки если правильно
    if correct and points > 0:
        try:
            from database import admin_add_bonus
            admin_add_bonus(user_id, points, 0, f"Викторина ({req.difficulty})")
        except Exception as e:
            print(f"Quiz points error: {e}")
            # Fallback - прямое обновление
            from database import get_connection
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (points, user_id))

    return {
        "correct": correct,
        "correct_index": question_data["correct"],
        "points_earned": points,
        "next_quiz_in": 86400
    }


# ============ MINI GAMES API ============

# Общий cooldown для всех игр (викторина + мини-игры)
GAME_POINTS = {
    'easy': 5,
    'medium': 10,
    'hard': 15,
    'expert': 25
}

@app.get("/api/games/status")
async def get_games_status(user: dict = Depends(get_current_user)):
    """Проверить доступность мини-игр (общий cooldown с викториной)"""
    user_id = user['user_id']
    now = datetime.now().timestamp()

    last_played = _get_last_game_time(user_id)
    remaining = (last_played + 86400) - now

    if remaining > 0:
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        return {
            "available": False,
            "remaining_seconds": remaining,
            "remaining_text": f"{hours}ч {minutes}м"
        }

    return {"available": True}


class GameStartRequest(BaseModel):
    game: str  # penalty, catch, runner
    difficulty: str


@app.post("/api/games/start")
async def start_game(req: GameStartRequest, user: dict = Depends(get_current_user)):
    """Начать игру - записывает попытку сразу при старте!"""
    user_id = user['user_id']
    now = datetime.now().timestamp()

    # Проверяем cooldown (из памяти + БД)
    last_played = _get_last_game_time(user_id)
    if now - last_played < 86400:
        raise HTTPException(status_code=400, detail="Игра уже сыграна сегодня")

    # Валидация
    if req.game not in ['penalty', 'catch', 'runner', 'memory']:
        raise HTTPException(status_code=400, detail="Неизвестная игра")

    if req.difficulty not in GAME_POINTS:
        raise HTTPException(status_code=400, detail="Неверная сложность")

    # Ставим cooldown СРАЗУ при старте
    _set_cooldown(user_id)
    _game_sessions[user_id] = {'started_at': now, 'result_submitted': False}

    return {
        "success": True,
        "game": req.game,
        "difficulty": req.difficulty,
        "message": "Игра началась! Попытка записана."
    }


class GameResultRequest(BaseModel):
    game: str  # penalty, catch, runner
    difficulty: str
    won: bool
    score: int


@app.post("/api/games/result")
async def submit_game_result(req: GameResultRequest, user: dict = Depends(get_current_user)):
    """Отправить результат мини-игры"""
    user_id = user['user_id']

    # Валидация
    if req.game not in ['penalty', 'catch', 'runner', 'memory']:
        raise HTTPException(status_code=400, detail="Неизвестная игра")

    if req.difficulty not in GAME_POINTS:
        raise HTTPException(status_code=400, detail="Неверная сложность")

    # Проверяем что игра была начата и результат ещё не отправлен
    session = _game_sessions.get(user_id)
    if session and session.get('result_submitted'):
        print(f"Double result blocked for user {user_id}")
        return {
            "success": True,
            "won": req.won,
            "points_earned": 0,
            "next_game_in": 86400
        }

    # Помечаем результат как отправленный
    if session:
        session['result_submitted'] = True
    _game_sessions[user_id] = {'started_at': datetime.now().timestamp(), 'result_submitted': True}

    # Начисляем очки если выиграл
    points = GAME_POINTS[req.difficulty] if req.won else 0

    if points > 0:
        try:
            from database import admin_add_bonus
            admin_add_bonus(user_id, points, 0, f"Игра {req.game} ({req.difficulty})")
        except Exception as e:
            print(f"Game points error: {e}")
            from database import get_connection
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (points, user_id))

    # Обновляем cooldown (подстраховка)
    _set_cooldown(user_id)

    return {
        "success": True,
        "won": req.won,
        "points_earned": points,
        "next_game_in": 86400
    }


@app.get("/api/ratings/posts")
async def get_ratings_posts():
    """Получить посты с оценками из Telegram"""
    try:
        ratings = await get_telegram_ratings_async()
        return {"ratings": ratings[:5], "count": len(ratings[:5])}
    except Exception as e:
        print(f"Ratings posts error: {e}")
        return {"ratings": [], "error": str(e)}


# ============ SOFASCORE ENDPOINTS ============

@app.get("/api/standings")
async def get_standings():
    """Получить таблицу Ла Лиги — FotMob с логотипами, fallback на Sheets"""
    try:
        # Try FotMob first (has logos)
        fotmob_standings = _get_fotmob_league_standings()
        if fotmob_standings:
            return {"standings": fotmob_standings, "count": len(fotmob_standings)}

        # Fallback to Sheets
        standings_raw = sheets_client.get_standings(limit=20)
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
                'isRealMadrid': 'Real Madrid' in team
            })

        return {"standings": standings, "count": len(standings)}
    except Exception as e:
        print(f"Standings error: {e}")
        return {"standings": [], "error": str(e)}


@app.get("/api/standings/debug")
async def debug_standings():
    """Debug FotMob standings parsing"""
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


@app.get("/api/ratings")
async def get_match_ratings():
    """Получить посты с оценками игроков из Telegram"""
    try:
        ratings = await get_telegram_ratings_async()
        return {"ratings": ratings[:5], "count": len(ratings[:5])}
    except Exception as e:
        print(f"Ratings error: {e}")
        return {"ratings": [], "error": str(e)}


@app.get("/api/players")
async def get_players():
    """Получить состав команды Real Madrid"""
    try:
        players = get_sofascore_player_stats()
        return {"players": players, "count": len(players)}
    except Exception as e:
        print(f"Players error: {e}")
        return {"players": [], "error": str(e)}


# ============ АВТО-РАСЧЁТ СТАВОК ============

from database import settle_all_for_match, get_pending_bets_for_match

_settled_matches = set()

def get_match_statistics(event_id: str) -> dict:
    """Получить статистику матча с SofaScore (угловые, карточки, голы)"""
    stats = {
        'total_goals': 0,
        'home_score': 0,
        'away_score': 0,
        'total_corners': 0,
        'home_corners': 0,
        'away_corners': 0,
        'total_yellow_cards': 0,
        'total_red_cards': 0,
        'both_scored': False,
        'outcome': 'draw'
    }

    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        # Получаем основную информацию о матче
        event_url = f"https://api.sofascore.com/api/v1/event/{event_id}"
        event_resp = requests.get(event_url, headers=headers, timeout=10)

        if event_resp.status_code == 200:
            event_data = event_resp.json().get('event', {})
            home_score = event_data.get('homeScore', {}).get('current', 0) or 0
            away_score = event_data.get('awayScore', {}).get('current', 0) or 0

            stats['home_score'] = int(home_score)
            stats['away_score'] = int(away_score)
            stats['total_goals'] = stats['home_score'] + stats['away_score']
            stats['both_scored'] = stats['home_score'] > 0 and stats['away_score'] > 0

            if stats['home_score'] > stats['away_score']:
                stats['outcome'] = 'home'
            elif stats['away_score'] > stats['home_score']:
                stats['outcome'] = 'away'
            else:
                stats['outcome'] = 'draw'

        # Получаем статистику (угловые, карточки)
        stats_url = f"https://api.sofascore.com/api/v1/event/{event_id}/statistics"
        stats_resp = requests.get(stats_url, headers=headers, timeout=10)

        if stats_resp.status_code == 200:
            stats_data = stats_resp.json().get('statistics', [])

            for group in stats_data:
                for item in group.get('groups', []):
                    for stat in item.get('statisticsItems', []):
                        name = stat.get('name', '')
                        home_val = int(stat.get('home', 0) or 0)
                        away_val = int(stat.get('away', 0) or 0)

                        if name == 'Corner kicks':
                            stats['home_corners'] = home_val
                            stats['away_corners'] = away_val
                            stats['total_corners'] = home_val + away_val

                        if name == 'Yellow cards':
                            stats['total_yellow_cards'] = home_val + away_val

                        if name == 'Red cards':
                            stats['total_red_cards'] = home_val + away_val

    except Exception as e:
        print(f"Error fetching match stats: {e}")

    return stats


def settle_bet_by_type(bet_type: str, stats: dict):
    """Проверить выиграла ли ставка. Returns: True=win, False=lose, 'push'=refund"""

    # Основной исход
    if bet_type in ['home', 'draw', 'away']:
        return bet_type == stats['outcome']

    # Точный счёт
    if bet_type.startswith('score_'):
        score = bet_type.replace('score_', '')
        return score == f"{stats['home_score']}-{stats['away_score']}"

    # Тотал голов (целые линии: ровно = возврат)
    if bet_type.startswith('total_over_'):
        line = float(bet_type.replace('total_over_', ''))
        total = stats['total_goals']
        if total == line and line == int(line):  # Целая линия, ровно = push
            return 'push'
        return total > line

    if bet_type.startswith('total_under_'):
        line = float(bet_type.replace('total_under_', ''))
        total = stats['total_goals']
        if total == line and line == int(line):  # Целая линия, ровно = push
            return 'push'
        return total < line

    # Обе забьют
    if bet_type == 'btts_yes':
        return stats['both_scored'] == True
    if bet_type == 'btts_no':
        return stats['both_scored'] == False

    # Двойной шанс
    if bet_type == 'dc_1x':
        return stats['outcome'] in ['home', 'draw']
    if bet_type == 'dc_x2':
        return stats['outcome'] in ['draw', 'away']
    if bet_type == 'dc_12':
        return stats['outcome'] in ['home', 'away']

    # Ничья — нет ставки (Draw No Bet)
    if bet_type == 'dnb_home':
        if stats['outcome'] == 'draw':
            return 'push'
        return stats['outcome'] == 'home'
    if bet_type == 'dnb_away':
        if stats['outcome'] == 'draw':
            return 'push'
        return stats['outcome'] == 'away'

    # Угловые (целые линии: ровно = возврат)
    if bet_type.startswith('corners_over_'):
        line = float(bet_type.replace('corners_over_', ''))
        total = stats.get('total_corners', 0)
        if total == line and line == int(line):
            return 'push'
        return total > line

    if bet_type.startswith('corners_under_'):
        line = float(bet_type.replace('corners_under_', ''))
        total = stats.get('total_corners', 0)
        if total == line and line == int(line):
            return 'push'
        return total < line

    # Индивидуальный тотал хозяев
    if bet_type.startswith('home_total_over_'):
        line = float(bet_type.replace('home_total_over_', ''))
        total = stats.get('home_score', 0)
        if total == line and line == int(line):
            return 'push'
        return total > line
    if bet_type.startswith('home_total_under_'):
        line = float(bet_type.replace('home_total_under_', ''))
        total = stats.get('home_score', 0)
        if total == line and line == int(line):
            return 'push'
        return total < line

    # Индивидуальный тотал гостей
    if bet_type.startswith('away_total_over_'):
        line = float(bet_type.replace('away_total_over_', ''))
        total = stats.get('away_score', 0)
        if total == line and line == int(line):
            return 'push'
        return total > line
    if bet_type.startswith('away_total_under_'):
        line = float(bet_type.replace('away_total_under_', ''))
        total = stats.get('away_score', 0)
        if total == line and line == int(line):
            return 'push'
        return total < line

    # Фора (handicap)
    if bet_type.startswith('handicap_home_'):
        line = float(bet_type.replace('handicap_home_', ''))
        diff = stats['home_score'] - stats['away_score'] + line
        if diff == 0:
            return 'push'
        return diff > 0
    if bet_type.startswith('handicap_away_'):
        line = float(bet_type.replace('handicap_away_', ''))
        diff = stats['away_score'] - stats['home_score'] + line
        if diff == 0:
            return 'push'
        return diff > 0

    # Первый гол
    if bet_type == 'first_goal_home':
        return stats.get('first_goal') == 'home'
    if bet_type == 'first_goal_away':
        return stats.get('first_goal') == 'away'
    if bet_type == 'first_goal_none':
        return stats['total_goals'] == 0

    return False


def settle_all_bets_advanced(match_id: str, stats: dict) -> dict:
    """Расчёт всех типов ставок с использованием статистики"""
    from database import _execute

    result = {'bets_settled': 0, 'predictions_settled': 0, 'bets_won': 0, 'bets_lost': 0, 'bets_pushed': 0}

    # Получаем все pending ставки на этот матч
    bets = _execute("""
        SELECT bet_id, user_id, bet_type, amount, odds
        FROM bets
        WHERE match_id = ? AND status = 'pending'
    """, (str(match_id),)) or []

    for bet in bets:
        bet_id = bet['bet_id']
        user_id = bet['user_id']
        bet_type = bet['bet_type']
        amount = bet['amount']
        odds = bet['odds']

        outcome = settle_bet_by_type(bet_type, stats)

        if outcome == 'push':
            # Возврат — ставка с целой линией, ровно на линии
            _execute("UPDATE bets SET status = 'returned' WHERE bet_id = ?", (bet_id,))
            _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            result['bets_pushed'] += 1
        elif outcome:
            # Выигрыш
            winnings = int(amount * odds)
            _execute("UPDATE bets SET status = 'won' WHERE bet_id = ?", (bet_id,))
            _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (winnings, user_id))
            result['bets_won'] += 1
        else:
            # Проигрыш
            _execute("UPDATE bets SET status = 'lost' WHERE bet_id = ?", (bet_id,))
            result['bets_lost'] += 1

        result['bets_settled'] += 1

    # Прогнозы (только основной исход)
    predictions = _execute("""
        SELECT prediction_id, user_id, prediction
        FROM predictions
        WHERE match_id = ? AND status = 'pending'
    """, (str(match_id),)) or []

    for pred in predictions:
        pred_id = pred['prediction_id']
        user_id = pred['user_id']
        prediction = pred['prediction']

        won = prediction == stats['outcome']

        if won:
            _execute("UPDATE predictions SET status = 'correct' WHERE prediction_id = ?", (pred_id,))
            _execute("UPDATE users SET balance = balance + 10, predictions_correct = predictions_correct + 1 WHERE user_id = ?", (user_id,))
        else:
            _execute("UPDATE predictions SET status = 'incorrect' WHERE prediction_id = ?", (pred_id,))
            _execute("UPDATE users SET predictions_incorrect = predictions_incorrect + 1 WHERE user_id = ?", (user_id,))

        result['predictions_settled'] += 1

    return result


@app.post("/api/admin/settle-check")
async def check_and_settle():
    """Проверить и рассчитать завершённые матчи с полной статистикой"""
    global _settled_matches

    try:
        results = get_sofascore_recent_matches()
        settled_info = []

        for result in results:
            match_id = str(result.get('matchId', ''))

            if not match_id or match_id in _settled_matches:
                continue

            # Получаем полную статистику матча
            stats = get_match_statistics(match_id)

            if stats['total_goals'] == 0 and stats['home_score'] == 0:
                # Возможно матч ещё не завершён
                continue

            # Рассчитываем все ставки
            st = settle_all_bets_advanced(match_id, stats)

            if st['bets_settled'] > 0 or st['predictions_settled'] > 0:
                _settled_matches.add(match_id)
                settled_info.append({
                    'match': f"{result['homeTeam']} vs {result['awayTeam']}",
                    'score': f"{stats['home_score']}:{stats['away_score']}",
                    'outcome': stats['outcome'],
                    'corners': stats['total_corners'],
                    'both_scored': stats['both_scored'],
                    'bets_settled': st['bets_settled'],
                    'bets_won': st.get('bets_won', 0),
                    'predictions_settled': st['predictions_settled']
                })
            else:
                _settled_matches.add(match_id)

        return {"settled": settled_info, "count": len(settled_info)}
    except Exception as e:
        print(f"Settle check error: {e}")
        return {"error": str(e)}


# ============ ФОНОВАЯ ЗАДАЧА ДЛЯ АВТО-РАСЧЁТА ============

import asyncio
from contextlib import asynccontextmanager

async def auto_settle_task():
    """Фоновая задача для авто-расчёта каждые 5 минут"""
    while True:
        try:
            await asyncio.sleep(300)  # 5 минут

            results = get_sofascore_recent_matches()

            for result in results:
                match_id = result.get('matchId', '')

                if not match_id or match_id in _settled_matches:
                    continue

                home_score = int(result.get('homeScore', 0))
                away_score = int(result.get('awayScore', 0))

                if home_score > away_score:
                    outcome = 'home'
                elif away_score > home_score:
                    outcome = 'away'
                else:
                    outcome = 'draw'

                exact_score = f"{home_score}-{away_score}"
                st = settle_all_for_match(match_id, outcome, exact_score)

                if st['bets_settled'] > 0 or st['predictions_settled'] > 0:
                    _settled_matches.add(match_id)
                    print(f"✅ Auto-settled {result['homeTeam']} vs {result['awayTeam']}: {st}")
        except Exception as e:
            print(f"Auto-settle error: {e}")


async def photo_cleanup_task():
    """Фоновая задача очистки старых фото каждые 5 минут"""
    while True:
        await asyncio.sleep(300)  # 5 минут
        try:
            await cleanup_old_photos()
        except Exception as e:
            print(f"Photo cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-fetch standings to populate team logo map
    try:
        standings = _get_fotmob_league_standings()
        print(f"🏆 Startup: {len(standings)} standings teams, {len(_team_logo_map)} logos cached")

        # Also pre-fetch RM team data for fixtures logos
        team_data = _get_fotmob_team(FOTMOB_RM_ID)
        if team_data:
            for f in team_data.get('overview', {}).get('overviewFixtures', []):
                _register_team(f.get('home', {}).get('name', ''), f.get('home', {}).get('id'))
                _register_team(f.get('away', {}).get('name', ''), f.get('away', {}).get('id'))
            print(f"⚽ Startup: fixtures logos cached, total {len(_team_logo_map)} teams")
    except Exception as e:
        print(f"Startup pre-fetch error: {e}")

    # Запускаем фоновые задачи
    settle_task = asyncio.create_task(auto_settle_task())
    cleanup_task = asyncio.create_task(photo_cleanup_task())
    print("🚀 Auto-settle task started")
    print("🧹 Photo cleanup task started")
    yield
    settle_task.cancel()
    cleanup_task.cancel()

# Обновляем app с lifespan
app.router.lifespan_context = lifespan


# Photo endpoint
from fastapi.responses import FileResponse

@app.get("/api/photo/{filename}")
async def get_photo(filename: str):
    """Отдать скачанное фото"""
    photo_path = f'/app/data/photos/{filename}'
    if os.path.exists(photo_path):
        return FileResponse(photo_path, media_type='image/jpeg')
    return {"error": "Photo not found"}


# Video endpoint
@app.get("/api/video/{filename}")
async def get_video(filename: str):
    """Отдать скачанное видео"""
    video_path = f'/app/data/videos/{filename}'
    if os.path.exists(video_path):
        return FileResponse(video_path, media_type='video/mp4')
    return {"error": "Video not found"}


# Stream proxy для обхода CORS
from fastapi.responses import StreamingResponse
from urllib.parse import urlparse

def get_referer_for_url(url: str) -> str:
    """Определяет правильный Referer для URL"""
    if 'mfvideo' in url or 'videomf' in url or 'myfootball' in url:
        return 'https://myfootball.pw/'
    elif 'liveball' in url or 'hayuhi' in url:
        return 'https://liveball4.info/'
    elif 'staypoor' in url or '58103793' in url or '77911050' in url:
        return 'https://myfootball.pw/'
    return ''

@app.get("/api/stream/proxy")
async def stream_proxy(url: str):
    """Проксирует m3u8 стрим для обхода CORS"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Origin': 'https://myfootball.pw',
        }

        referer = get_referer_for_url(url)
        if referer:
            headers['Referer'] = referer

        response = requests.get(url, timeout=30, stream=True, headers=headers)

        content = response.content
        content_type = response.headers.get('content-type', 'application/vnd.apple.mpegurl')

        # Если это m3u8 плейлист, нужно переписать относительные URL
        if b'#EXTM3U' in content or '.m3u8' in url:
            text = content.decode('utf-8', errors='ignore')

            # Получаем базовый URL
            base_url = url.rsplit('/', 1)[0]

            # Заменяем относительные пути на абсолютные
            lines = text.split('\n')
            new_lines = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Это URL сегмента
                    if not line.startswith('http'):
                        line = f"{base_url}/{line}"
                new_lines.append(line)

            content = '\n'.join(new_lines).encode('utf-8')
            content_type = 'application/vnd.apple.mpegurl'

        return StreamingResponse(
            iter([content]),
            media_type=content_type,
            headers={
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'no-cache'
            }
        )
    except Exception as e:
        print(f"Stream proxy error: {e}")
        return {"error": str(e)}


# Прокси для .ts сегментов
@app.get("/api/stream/segment")
async def stream_segment(url: str):
    """Проксирует .ts сегменты видео"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Origin': 'https://myfootball.pw',
        }

        referer = get_referer_for_url(url)
        if referer:
            headers['Referer'] = referer

        response = requests.get(url, timeout=30, stream=True, headers=headers)

        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                yield chunk

        return StreamingResponse(
            generate(),
            media_type='video/MP2T',
            headers={
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'no-cache'
            }
        )
    except Exception as e:
        print(f"Segment proxy error: {e}")
        return {"error": str(e)}


# ============ АДМИНКА ============

ADMIN_IDS = [1697882482]  # Список админов

class AdminAddBalanceRequest(BaseModel):
    username: str
    amount: int

@app.post("/api/admin/add-balance")
async def admin_add_balance(req: AdminAddBalanceRequest, user: dict = Depends(get_current_user)):
    """Пополнить баланс пользователя по username (только для админов)"""
    if user['user_id'] not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    username = req.username.replace('@', '').strip().lower()

    # Ищем пользователя по username
    from database import _execute
    result = _execute("SELECT user_id, balance, first_name FROM users WHERE LOWER(username) = ?", (username,))

    if not result:
        raise HTTPException(status_code=404, detail=f"Пользователь @{username} не найден")

    target_user = result[0]
    target_id = target_user['user_id']
    old_balance = target_user['balance']
    new_balance = old_balance + req.amount

    # Обновляем баланс
    _execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, target_id))

    return {
        "success": True,
        "username": username,
        "first_name": target_user.get('first_name'),
        "old_balance": old_balance,
        "new_balance": new_balance,
        "added": req.amount
    }


@app.get("/api/admin/users")
async def admin_get_users(user: dict = Depends(get_current_user), limit: int = 50):
    """Получить список пользователей (только для админов)"""
    if user['user_id'] not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    from database import _execute
    users = _execute(f"SELECT user_id, username, first_name, balance FROM users ORDER BY balance DESC LIMIT {limit}")

    return {"users": users or [], "count": len(users or [])}


@app.get("/api/admin/pending-bets")
async def admin_pending_bets(user: dict = Depends(get_current_user)):
    """Получить все pending ставки для проверки"""
    if user['user_id'] not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    from database import _execute
    bets = _execute("""
        SELECT b.*, u.username, u.first_name
        FROM bets b
        LEFT JOIN users u ON b.user_id = u.user_id
        WHERE b.status = 'pending'
        ORDER BY b.created_at DESC
    """)

    return {"bets": bets or [], "count": len(bets or [])}


@app.post("/api/admin/settle-manual")
async def admin_settle_manual(user: dict = Depends(get_current_user)):
    """Ручной запуск расчёта ставок"""
    if user['user_id'] not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    try:
        results = get_sofascore_recent_matches()
        settled_info = []

        for result in results:
            match_id = str(result.get('matchId', ''))

            # Получаем полную статистику
            stats = get_match_statistics(match_id)

            if stats['home_score'] == 0 and stats['away_score'] == 0:
                continue

            st = settle_all_bets_advanced(match_id, stats)

            if st['bets_settled'] > 0 or st['predictions_settled'] > 0:
                settled_info.append({
                    'match': f"{result['homeTeam']} vs {result['awayTeam']}",
                    'score': f"{stats['home_score']}:{stats['away_score']}",
                    'corners': stats['total_corners'],
                    'bets_settled': st['bets_settled'],
                    'bets_won': st.get('bets_won', 0)
                })

        return {"settled": settled_info, "count": len(settled_info)}
    except Exception as e:
        return {"error": str(e)}


# ============ PURCHASE SYSTEM ============

PURCHASES_FILE = '/app/data/purchases.json'
RECEIPTS_DIR = '/app/data/receipts'
PURCHASE_CONFIG = {
    'card_number': '2202 2032 1091 8506',   # <-- ОБНОВИТЬ номер карты!
    'card_bank': 'Сбербанк',
    'price_per_point': 2.5,
    'min_purchase': 100,
    'amounts': [100, 250, 500, 1000],
}


def _load_purchases():
    try:
        if os.path.exists(PURCHASES_FILE):
            with open(PURCHASES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return []


def _save_purchases(data):
    with open(PURCHASES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@app.get("/api/purchase/config")
async def purchase_config_endpoint():
    """Get purchase configuration (card number, prices, etc.)"""
    return PURCHASE_CONFIG


@app.post("/api/purchase")
async def create_purchase(request: Request, user: dict = Depends(get_current_user)):
    """Create a purchase request with receipt upload"""
    from fastapi import UploadFile
    from fastapi.responses import JSONResponse

    form = await request.form()
    amount_str = form.get('amount', '0')
    receipt_file = form.get('receipt')

    try:
        amount = int(amount_str)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Некорректная сумма"})

    min_purchase = PURCHASE_CONFIG.get('min_purchase', 100)
    if amount < min_purchase:
        return JSONResponse(status_code=400, content={"detail": f"Минимальная покупка: {min_purchase} очков"})

    # Generate purchase ID
    purchases = _load_purchases()
    max_id = max((p.get('id', 0) for p in purchases), default=10000)
    purchase_id = max_id + 1

    # Save receipt file
    receipt_filename = None
    receipt_path = None
    if receipt_file and hasattr(receipt_file, 'read'):
        os.makedirs(RECEIPTS_DIR, exist_ok=True)
        ext = 'jpg'
        if hasattr(receipt_file, 'filename') and receipt_file.filename and '.' in receipt_file.filename:
            ext = receipt_file.filename.rsplit('.', 1)[-1].lower()
        receipt_filename = f"{purchase_id}.{ext}"
        receipt_path = os.path.join(RECEIPTS_DIR, receipt_filename)
        content = await receipt_file.read()
        with open(receipt_path, 'wb') as f:
            f.write(content)

    # Save purchase record
    price_per_point = PURCHASE_CONFIG.get('price_per_point', 2.5)
    purchase = {
        'id': purchase_id,
        'user_id': user['user_id'],
        'username': user.get('username', ''),
        'first_name': user.get('first_name', ''),
        'amount': amount,
        'total_rub': round(amount * price_per_point),
        'receipt': receipt_filename,
        'status': 'pending',
        'created_at': datetime.now(MOSCOW_TZ).isoformat(),
    }
    purchases.append(purchase)
    _save_purchases(purchases)

    # Notify admin via Telegram
    try:
        import requests as req_lib
        username = user.get('username', '') or user.get('first_name', '') or str(user['user_id'])
        caption = (
            f"<b>💰 Заявка на покупку #{purchase_id}</b>\n\n"
            f"👤 @{username}\n"
            f"🔢 {amount} очков = {purchase['total_rub']}₽\n"
            f"📅 {datetime.now(MOSCOW_TZ).strftime('%d.%m %H:%M')}"
        )
        reply_markup = json.dumps({
            "inline_keyboard": [[
                {"text": "✅ Одобрить", "callback_data": f"approve_{purchase_id}"},
                {"text": "❌ Отклонить", "callback_data": f"reject_{purchase_id}"}
            ]]
        })
        for admin_id in ADMIN_IDS:
            try:
                if receipt_path and os.path.exists(receipt_path):
                    with open(receipt_path, 'rb') as f:
                        req_lib.post(
                            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                            data={'chat_id': admin_id, 'caption': caption, 'parse_mode': 'HTML', 'reply_markup': reply_markup},
                            files={'photo': f},
                            timeout=10
                        )
                else:
                    req_lib.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                        json={'chat_id': admin_id, 'text': caption, 'parse_mode': 'HTML', 'reply_markup': json.loads(reply_markup)},
                        timeout=5
                    )
            except Exception as e:
                print(f"Failed to notify admin {admin_id}: {e}")
    except Exception as e:
        print(f"Purchase notification error: {e}")

    return {"success": True, "id": purchase_id}




# ============ LIVE STREAM ============

STREAMS_FILE = '/app/data/streams.json'


def get_streams_data():
    """Получить данные стримов"""
    try:
        if os.path.exists(STREAMS_FILE):
            with open(STREAMS_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {"streams": [], "updated": "", "updated_by": ""}


@app.get("/api/streams")
async def get_streams():
    """Получить активные стримы"""
    data = get_streams_data()
    active = []
    for s in data.get("streams", []):
        if not s.get("active", True):
            continue
        entry = {"name": s.get("name", ""), "url": s.get("url", ""), "type": s.get("type", "hls")}
        if s.get("type") == "acestream" and s.get("ace_id"):
            entry["http_url"] = f"/ace/getstream?id={s['ace_id']}&.mp4"
        if s.get("type") == "iframe" and s.get("url"):
            entry["parse_url"] = f"/api/parse_stream?url={quote(s['url'], safe='')}"
        active.append(entry)
    return {"streams": active}


@app.get("/api/stream")
async def get_stream():
    """Обратная совместимость — первый активный стрим"""
    data = get_streams_data()
    for s in data.get("streams", []):
        if s.get("active", True) and s.get("url"):
            return {"url": s["url"], "title": s.get("name", "")}
    return {"url": "", "title": ""}



# ============ STREAM PARSER ============

_PARSE_CACHE = {}  # url -> {ts, result}
_PARSE_CACHE_TTL = 300  # 5 minutes

_BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}

_LANG_MAP = {
    'russia': 'RU', 'ukraine': 'UA', 'england': 'EN', 'spain': 'ES',
    'france': 'FR', 'germany': 'DE', 'italy': 'IT', 'portugal': 'PT',
    'brazil': 'BR', 'turkey': 'TR', 'arab': 'AR', 'china': 'CN',
}


def _unpack_all_packer(text: str) -> list:
    """Decode ALL p.a.c.k.e.r obfuscated blocks in text, return list of decoded strings"""
    results = []
    for match in re.finditer(
        r"eval\(function\(p,a,c,k,e,[dr]\)\{.*?\}\('(.*?)',\s*(\d+),\s*(\d+),\s*'([^']+)'\.split",
        text, re.DOTALL
    ):
        p_str = match.group(1)
        a_val = int(match.group(2))
        keywords = match.group(4).split('|')

        def _base_n_decode(word, base):
            chars = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
            result = 0
            for ch in word:
                idx = chars.index(ch) if ch in chars else -1
                if idx < 0 or idx >= base:
                    return -1
                result = result * base + idx
            return result

        def _make_replacer(kw, base):
            def _replacer(m):
                word = m.group(0)
                idx = _base_n_decode(word, base)
                if 0 <= idx < len(kw) and kw[idx]:
                    return kw[idx]
                return word
            return _replacer

        decoded = re.sub(r'\b\w+\b', _make_replacer(keywords, a_val), p_str)
        decoded = decoded.replace('\\/', '/')
        results.append(decoded)
    return results


def _find_m3u8_urls(text: str) -> list:
    """Find m3u8 URLs in text"""
    urls = re.findall(r'https?://[^\s\'"<>\\]+?\.m3u8[^\s\'"<>\\]*', text)
    seen = set()
    unique = []
    for u in urls:
        u = u.rstrip('"').rstrip("'").rstrip(')').rstrip(';').rstrip(',')
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def _parse_myfootball_channels(text: str) -> list:
    """Parse myfootball.pw channel structure: section tabs + content"""
    channels = []

    # Parse channel tabs for language info
    tab_langs = {}
    for m in re.finditer(r'href="#section-(\d+)"[^>]*>(\d+)\s*<span>.*?</span>\s*(?:<img[^>]*alt="[^"]*?(\w+)")?', text, re.DOTALL):
        section_num = m.group(1)
        lang_key = m.group(3) or ''
        lang_code = _LANG_MAP.get(lang_key.lower(), '')
        tab_langs[section_num] = lang_code

    # Parse each section for m3u8 and iframes
    for m in re.finditer(r'<section\s+id="section-(\d+)">(.*?)</section>', text, re.DOTALL | re.IGNORECASE):
        section_num = m.group(1)
        section_html = m.group(2)
        lang = tab_langs.get(section_num, '')
        label = f"Канал {section_num}" + (f" [{lang}]" if lang else '')

        # Direct m3u8 in section
        m3u8s = _find_m3u8_urls(section_html)
        for u in m3u8s:
            channels.append({'url': u, 'name': label, 'type': 'direct'})

        # iframe data-src in section
        iframes = re.findall(r'<iframe[^>]+data-src=["\']([^"\']+)["\']', section_html, re.IGNORECASE)
        for iframe_url in iframes:
            if iframe_url.startswith('//'):
                iframe_url = 'https:' + iframe_url
            channels.append({'url': iframe_url, 'name': label, 'type': 'iframe'})

    return channels


def _fetch_page(url: str, referer: str = None) -> str:
    """Fetch a URL with browser-like headers, return text or empty string"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        headers = dict(_BROWSER_HEADERS)
        headers['Referer'] = referer or (origin + '/')

        resp = requests.get(url, timeout=10, headers=headers)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        print(f"[parse_stream] Error fetching {url}: {e}")
    return ''


def _extract_m3u8_from_page(text: str, url: str) -> list:
    """Extract m3u8 URLs from page text using all methods"""
    streams = []
    seen = set()

    def add(u):
        if u not in seen:
            seen.add(u)
            streams.append(u)

    # 1. Direct m3u8 URLs
    for u in _find_m3u8_urls(text):
        add(u)

    # 2. Unpack ALL p.a.c.k.e.r blocks in full page
    for decoded in _unpack_all_packer(text):
        for u in _find_m3u8_urls(decoded):
            add(u)

    # 3. Individual script tags (for packed JS)
    script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', text, re.DOTALL | re.IGNORECASE)
    for script in script_blocks:
        if 'eval(function(p,a,c,k,e,' in script:
            for decoded in _unpack_all_packer(script):
                for u in _find_m3u8_urls(decoded):
                    add(u)

    # 4. Decode atob("base64") patterns (liveball.st style)
    import base64
    atob_matches = re.findall(r'atob\(["\']([A-Za-z0-9+/=]+)["\']\)', text)
    for b64 in atob_matches:
        try:
            decoded_url = base64.b64decode(b64).decode('utf-8', errors='replace')
            for u in _find_m3u8_urls(decoded_url):
                add(u)
        except Exception:
            pass

    # 5. Fetch external JS files that look like player scripts
    from urllib.parse import urljoin as _urljoin
    js_urls = re.findall(r'<script[^>]+src=["\']([^"\']+/pll/[^"\']+)["\']', text, re.IGNORECASE)
    js_urls += re.findall(r"\.src='(/pll/[^']+)'", text)
    js_urls += re.findall(r'\.src="(/pll/[^"]+)"', text)
    # Also dynamic script creation: s.src='/pll/...'
    js_urls += re.findall(r"s\.src='([^']+/pll/[^']+)'", text)
    for js_url in js_urls:
        if not js_url.startswith('http'):
            js_url = _urljoin(url, js_url)
        js_text = _fetch_page(js_url, referer=url)
        if js_text:
            for u in _find_m3u8_urls(js_text):
                add(u)
            for decoded in _unpack_all_packer(js_text):
                for u in _find_m3u8_urls(decoded):
                    add(u)

    return streams


def _parse_page_for_streams(url: str, depth: int = 0, visited: set = None, referer: str = None) -> list:
    """Recursively parse page to find m3u8 stream URLs with channel info"""
    if visited is None:
        visited = set()
    if depth > 3 or url in visited:
        return []
    visited.add(url)

    results = []  # list of {url, name}

    text = _fetch_page(url, referer=referer)
    if not text:
        return []

    # Check if this is a myfootball-style page with channel tabs
    is_myfootball = 'section-1' in text and 'канал' in text.lower()

    if is_myfootball and depth == 0:
        channels = _parse_myfootball_channels(text)
        for ch in channels:
            if ch['type'] == 'direct':
                results.append({'url': ch['url'], 'name': ch['name']})
            elif ch['type'] == 'iframe':
                # Recursively parse iframe embed
                sub = _parse_page_for_streams(ch['url'], depth + 1, visited, referer=url)
                if sub:
                    for s in sub:
                        # Use channel name if sub-result has generic name
                        if s.get('name', '').startswith('Поток'):
                            s['name'] = ch['name']
                        results.append(s)
                else:
                    # Could not extract m3u8 from iframe, store as iframe fallback
                    results.append({'url': ch['url'], 'name': ch['name'], 'fallback': True})
    else:
        # Generic page: extract all m3u8
        m3u8_list = _extract_m3u8_from_page(text, url)
        for i, u in enumerate(m3u8_list):
            results.append({'url': u, 'name': f"Поток {i+1}"})

        # Follow iframes
        from urllib.parse import urljoin as _urljoin
        iframe_urls = re.findall(r'<iframe[^>]+(?:src|data-src)=["\']([^"\']+)["\']', text, re.IGNORECASE)
        for iframe_url in iframe_urls:
            if iframe_url.startswith('//'):
                iframe_url = 'https:' + iframe_url
            elif not iframe_url.startswith('http'):
                iframe_url = _urljoin(url, iframe_url)
            if any(skip in iframe_url.lower() for skip in ['google', 'facebook', 'twitter', 'ads', 'analytics', 'oleronraid', 'lernody']):
                continue
            sub = _parse_page_for_streams(iframe_url, depth + 1, visited, referer=url)
            for s in sub:
                if s['url'] not in [r['url'] for r in results]:
                    results.append(s)

    return results


@app.get("/api/parse_stream")
def parse_stream(url: str):
    """Parse a page to find m3u8 stream URLs"""
    from fastapi.responses import JSONResponse

    now = time.time()
    cached = _PARSE_CACHE.get(url)
    if cached and now - cached['ts'] < _PARSE_CACHE_TTL:
        return JSONResponse(
            content=cached['result'],
            headers={'Access-Control-Allow-Origin': '*'}
        )

    streams = _parse_page_for_streams(url)

    # Filter out fallback entries for the success response
    real_streams = [s for s in streams if not s.get('fallback')]

    if real_streams:
        result = {"success": True, "streams": [{"url": s['url'], "name": s['name']} for s in real_streams]}
    else:
        result = {"success": False, "fallback_url": url}

    _PARSE_CACHE[url] = {'ts': now, 'result': result}

    return JSONResponse(
        content=result,
        headers={'Access-Control-Allow-Origin': '*'}
    )



# ============ HLS PROXY ============

_HLS_PROXY_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}


def _rewrite_m3u8(text: str, base_url: str) -> str:
    """Rewrite URLs in m3u8 playlist to go through proxy"""
    lines = text.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            # URL line (segment or sub-playlist)
            url = stripped
            if not url.startswith('http'):
                url = urljoin(base_url, url)
            line = '/api/proxy/hls?url=' + quote(url, safe='')
        elif 'URI="' in stripped:
            # Handle URI= attributes (#EXT-X-MAP, #EXT-X-KEY, etc.)
            def _replace_uri(match):
                uri = match.group(1)
                if not uri.startswith('http'):
                    uri = urljoin(base_url, uri)
                return 'URI="/api/proxy/hls?url=' + quote(uri, safe='') + '"'
            line = re.sub(r'URI="([^"]+)"', _replace_uri, line)
        result.append(line)
    return '\n'.join(result)


@app.get("/api/proxy/hls")
def proxy_hls(url: str):
    """HLS proxy to bypass CORS restrictions"""
    from fastapi.responses import Response

    # Security: only proxy HLS-related URLs
    url_lower = url.lower()
    if not any(ext in url_lower for ext in ['.m3u8', '.ts', '.m3u', '.aac', '.mp4', '.key']):
        raise HTTPException(status_code=400, detail="Only HLS URLs allowed")

    try:
        headers = dict(_HLS_PROXY_HEADERS)
        from urllib.parse import urlparse
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        # Use smart referer based on stream source
        smart_ref = get_referer_for_url(url)
        if smart_ref:
            headers['Referer'] = smart_ref
            headers['Origin'] = smart_ref.rstrip('/')
        else:
            headers['Referer'] = origin + '/'
            headers['Origin'] = origin

        resp = requests.get(url, timeout=10, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Upstream {resp.status_code}")

        body = resp.content
        is_m3u8 = '.m3u8' in url_lower or '.m3u' in url_lower

        if is_m3u8:
            text = body.decode('utf-8', errors='replace')
            text = _rewrite_m3u8(text, url)
            body = text.encode('utf-8')
            content_type = 'application/vnd.apple.mpegurl'
            cache_control = 'no-cache, no-store'
        elif '.ts' in url_lower:
            content_type = 'video/MP2T'
            cache_control = 'public, max-age=60'
        elif '.aac' in url_lower:
            content_type = 'audio/aac'
            cache_control = 'public, max-age=60'
        elif '.key' in url_lower:
            content_type = 'application/octet-stream'
            cache_control = 'public, max-age=300'
        else:
            content_type = resp.headers.get('Content-Type', 'application/octet-stream')
            cache_control = 'public, max-age=60'

        return Response(
            content=body,
            media_type=content_type,
            headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Access-Control-Allow-Headers': '*',
                'Cache-Control': cache_control,
            }
        )
    except HTTPException:
        raise
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Upstream timeout")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Proxy error: {str(e)}")


# ============ РЕФЕРАЛЬНАЯ СИСТЕМА ============

@app.get("/api/referral/info")
async def get_referral_info(user: dict = Depends(get_current_user)):
    """Получить реферальную информацию пользователя"""
    try:
        user_id = user['user_id']

        # Получаем количество рефералов
        referrals = _execute(
            "SELECT COUNT(*) as count FROM users WHERE referred_by = ?",
            (user_id,)
        )
        referral_count = referrals[0]['count'] if referrals else 0

        # Получаем заработок с рефералов (только за приглашение друзей, не за свою регистрацию)
        earnings = _execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE user_id = ? AND type = 'referral_bonus' AND description LIKE '%приглашение друга%'",
            (user_id,)
        )
        total_earnings = earnings[0]['total'] if earnings else 0

        # Генерируем реферальную ссылку
        bot_username = "Real_Madrid_football_bot"  # Замени на своего бота
        ref_link = f"https://t.me/{bot_username}?start=ref{user_id}"

        return {
            "ref_link": ref_link,
            "ref_code": f"ref{user_id}",
            "referral_count": referral_count,
            "total_earnings": total_earnings,
            "bonus_per_referral": 25  # Бонус за каждого реферала
        }
    except Exception as e:
        print(f"Referral info error: {e}")
        return {"ref_link": "", "referral_count": 0, "total_earnings": 0}


@app.post("/api/referral/apply")
async def apply_referral(ref_code: str, user: dict = Depends(get_current_user)):
    """Применить реферальный код (бонус начислится после первой ставки)"""
    try:
        user_id = user['user_id']

        # Проверяем что пользователь ещё не применял реферальный код
        current_user = _execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,))
        if current_user and current_user[0].get('referred_by'):
            raise HTTPException(status_code=400, detail="Вы уже использовали реферальный код")

        # Извлекаем ID реферера из кода
        if not ref_code.startswith('ref'):
            raise HTTPException(status_code=400, detail="Неверный реферальный код")

        try:
            referrer_id = int(ref_code.replace('ref', ''))
        except:
            raise HTTPException(status_code=400, detail="Неверный реферальный код")

        # Нельзя приглашать самого себя
        if referrer_id == user_id:
            raise HTTPException(status_code=400, detail="Нельзя использовать свой код")

        # Проверяем что реферер существует
        referrer = _execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,))
        if not referrer:
            raise HTTPException(status_code=400, detail="Пользователь не найден")

        # Записываем реферера (бонус начислится после первой ставки)
        _execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user_id))

        return {
            "success": True,
            "message": "Реферальный код применён! Вы и ваш друг получите по 25 очков после вашей первой ставки."
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Apply referral error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def process_referral_bonus(user_id: int):
    """Начислить реферальный бонус после первой ставки (вызывается из place_bet)"""
    try:
        # Проверяем есть ли реферер и не начислен ли уже бонус
        user_data = _execute(
            "SELECT referred_by FROM users WHERE user_id = ?",
            (user_id,)
        )
        if not user_data or not user_data[0].get('referred_by'):
            return

        referrer_id = user_data[0]['referred_by']

        # Проверяем не начисляли ли уже бонус этому пользователю
        existing_bonus = _execute(
            "SELECT transaction_id FROM transactions WHERE user_id = ? AND type = 'referral_bonus' AND reference_id = ?",
            (user_id, str(referrer_id))
        )
        if existing_bonus:
            return  # Бонус уже начислен

        bonus = 25

        # Бонус рефереру
        referrer = _execute("SELECT balance FROM users WHERE user_id = ?", (referrer_id,))
        if referrer:
            ref_balance = referrer[0]['balance']
            _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, referrer_id))
            _execute(
                """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                   VALUES (?, 'referral_bonus', ?, ?, ?, ?, ?)""",
                (referrer_id, bonus, ref_balance, ref_balance + bonus,
                 f"Бонус за приглашение друга (первая ставка)", str(user_id))
            )

        # Бонус новому пользователю
        user_balance = _execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        if user_balance:
            ub = user_balance[0]['balance']
            _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, user_id))
            _execute(
                """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                   VALUES (?, 'referral_bonus', ?, ?, ?, ?, ?)""",
                (user_id, bonus, ub, ub + bonus,
                 f"Бонус за регистрацию по приглашению (первая ставка)", str(referrer_id))
            )

        print(f"✅ Referral bonus: {referrer_id} <- {user_id}, +{bonus} each")

    except Exception as e:
        print(f"Referral bonus error: {e}")


# ============ ЗАПУСК ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
