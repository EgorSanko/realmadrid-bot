"""
Модуль для получения ссылки на трансляцию LiveBall

Примечание: liveball загружает контент через JavaScript,
поэтому парсить конкретный матч через requests невозможно.
Возвращаем ссылку на страницу команды Real Madrid - 
там все матчи и пользователь легко найдёт нужный.
"""

import re
import logging
import requests
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Кэш
_cached_mirror: Optional[str] = None
_mirror_cache_time: Optional[datetime] = None

MIRROR_CACHE_DURATION = timedelta(hours=6)

# Константы
LIVEBALL_MAIN = 'https://liveball.website/'
REAL_MADRID_TEAM_ID = '541'
LIVEBALL_TELEGRAM = 'https://t.me/liveballst'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
}


def get_liveball_mirror() -> Optional[str]:
    """Получить актуальное зеркало liveball"""
    global _cached_mirror, _mirror_cache_time
    
    if _cached_mirror and _mirror_cache_time:
        if datetime.now() - _mirror_cache_time < MIRROR_CACHE_DURATION:
            return _cached_mirror
    
    try:
        logger.info("🔄 Получаем зеркало liveball...")
        response = requests.get(LIVEBALL_MAIN, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        match = re.search(r'https://([a-z0-9]+)\.liveball\.([a-z]{2,})', response.text)
        
        if match:
            mirror = match.group(0)
            _cached_mirror = mirror
            _mirror_cache_time = datetime.now()
            logger.info(f"✅ Зеркало: {mirror}")
            return mirror
        
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return None


def get_real_madrid_stream_url(opponent: str = None) -> str:
    """
    Получить ссылку на страницу Real Madrid на liveball
    
    Там отображаются все матчи команды - 
    пользователь сам выберет нужный матч.
    """
    mirror = get_liveball_mirror()
    
    if mirror:
        url = f"{mirror}/team/{REAL_MADRID_TEAM_ID}"
        logger.info(f"📺 Ссылка: {url}")
        return url
    
    return LIVEBALL_TELEGRAM


def get_team_page_url() -> str:
    """Ссылка на страницу команды"""
    return get_real_madrid_stream_url()


def clear_cache():
    """Очистить кэш"""
    global _cached_mirror, _mirror_cache_time
    _cached_mirror = None
    _mirror_cache_time = None


# Тест
if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )
    
    print("\n" + "="*50)
    print("🔍 LIVEBALL - ССЫЛКА НА REAL MADRID")
    print("="*50 + "\n")
    
    url = get_real_madrid_stream_url()
    print(f"📺 Ссылка: {url}\n")
    
    print("На этой странице отображаются все матчи")
    print("Real Madrid - пользователь выберет нужный.\n")
    
    print("="*50 + "\n")
