"""
АВТОМАТИЧЕСКИЙ парсер статистики Real Madrid с сайта La Liga
Больше никаких ручных обновлений!
"""

import requests
import re
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Кэш
_stats_cache: Optional[List[Dict]] = None
_cache_time: Optional[datetime] = None
CACHE_DURATION = timedelta(hours=2)

LALIGA_STATS_URL = "https://www.laliga.com/en-GB/clubs/real-madrid/stats"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml',
}

POSITION_MAP = {
    'Goalkeeper': 'G', 'Defender': 'D', 'Midfielder': 'M', 'Forward': 'F'
}

PLAYER_IDS = {
    'Mbappé': 903140, 'Vini Jr.': 862620, 'Bellingham': 868886, 'Rodrygo': 847169,
    'Arda Güler': 1082846, 'Valverde': 815914, 'Tchouameni': 867678, 'Camavinga': 902377,
    'Courtois': 108390, 'E. Militão': 822519, 'Rüdiger': 88442, 'Carvajal': 44834,
    'Huijsen': 1176744, 'Á. Carreras': 1085081, 'Mastantuono': 1403559, 'Brahim': 826422,
    'D. Ceballos': 547838, 'Fran García': 973887, 'F. Mendy': 750518, 'Asencio': 1156645,
    'Trent': 795064, 'Gonzalo': 910536, 'Alaba': 59015, 'Lunin': 859025,
}


def parse_laliga_stats() -> List[Dict]:
    """Парсит статистику с сайта La Liga"""
    players = []
    
    try:
        logger.info("🔄 Загружаем статистику с laliga.com...")
        response = requests.get(LALIGA_STATS_URL, headers=HEADERS, timeout=15)
        
        if response.status_code != 200:
            logger.warning(f"⚠️ Статус: {response.status_code}")
            return []
        
        html = response.text
        
        # Парсим данные из таблицы
        # Ищем строки вида: | 10 | Forward | Mbappé | 1576 | 18 | ... | 18 |
        
        # Первая таблица (основная статистика)
        # DORSAL | POSITION | NAME | MIN | PLD | TIT | SUP | SUST | YC | RC | 2Y | GOALS
        main_pattern = r'\|\s*(\d+)\s*\|\s*(Goalkeeper|Defender|Midfielder|Forward)\s*\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|'
        
        main_matches = re.findall(main_pattern, html)
        
        player_dict = {}
        
        for match in main_matches:
            dorsal, position, name, minutes, played, tit, sup, sust, yc, rc, two_y, goals = match
            name = name.strip()
            played = int(played)
            
            if played > 0:
                player_dict[name] = {
                    'name': name,
                    'position': POSITION_MAP.get(position, 'M'),
                    'goals': int(goals),
                    'assists': 0,
                    'matches': played,
                    'minutes': int(minutes),
                }
        
        # Вторая таблица (атака) - ищем ассисты
        # SHOTS | SHOTS T | ASS | ...
        attack_pattern = r'\|\s*\d+\s*\|\s*(?:Goalkeeper|Defender|Midfielder|Forward)\s*\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|'
        
        attack_matches = re.findall(attack_pattern, html)
        
        for match in attack_matches:
            name, shots, shots_t, assists = match
            name = name.strip()
            
            if name in player_dict:
                player_dict[name]['assists'] = int(assists)
        
        players = list(player_dict.values())
        logger.info(f"✅ Спарсено {len(players)} игроков")
        
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга: {e}")
    
    return players


def get_backup_stats() -> List[Dict]:
    """Резервные данные (обновлены 2 января 2026 с laliga.com)"""
    return [
        {'name': 'Mbappé', 'position': 'F', 'goals': 18, 'assists': 4, 'matches': 18, 'minutes': 1576},
        {'name': 'Vini Jr.', 'position': 'F', 'goals': 5, 'assists': 5, 'matches': 18, 'minutes': 1331},
        {'name': 'Bellingham', 'position': 'M', 'goals': 4, 'assists': 3, 'matches': 14, 'minutes': 1011},
        {'name': 'Arda Güler', 'position': 'M', 'goals': 3, 'assists': 5, 'matches': 18, 'minutes': 1145},
        {'name': 'Rodrygo', 'position': 'F', 'goals': 1, 'assists': 1, 'matches': 16, 'minutes': 551},
        {'name': 'E. Militão', 'position': 'D', 'goals': 1, 'assists': 1, 'matches': 13, 'minutes': 1002},
        {'name': 'Camavinga', 'position': 'M', 'goals': 1, 'assists': 0, 'matches': 12, 'minutes': 510},
        {'name': 'Á. Carreras', 'position': 'D', 'goals': 1, 'assists': 1, 'matches': 16, 'minutes': 1341},
        {'name': 'Huijsen', 'position': 'D', 'goals': 1, 'assists': 1, 'matches': 13, 'minutes': 966},
        {'name': 'Mastantuono', 'position': 'F', 'goals': 1, 'assists': 0, 'matches': 10, 'minutes': 551},
        {'name': 'Valverde', 'position': 'M', 'goals': 0, 'assists': 4, 'matches': 17, 'minutes': 1384},
        {'name': 'Tchouameni', 'position': 'M', 'goals': 0, 'assists': 0, 'matches': 16, 'minutes': 1305},
        {'name': 'Courtois', 'position': 'G', 'goals': 0, 'assists': 0, 'matches': 18, 'minutes': 1620},
        {'name': 'Brahim', 'position': 'M', 'goals': 0, 'assists': 2, 'matches': 12, 'minutes': 312},
        {'name': 'Trent', 'position': 'D', 'goals': 0, 'assists': 1, 'matches': 8, 'minutes': 392},
    ]


def get_real_player_stats() -> List[Dict]:
    """ГЛАВНАЯ ФУНКЦИЯ - получить статистику игроков"""
    global _stats_cache, _cache_time
    
    if _stats_cache and _cache_time:
        if datetime.now() - _cache_time < CACHE_DURATION:
            logger.info("📊 Статистика из кэша")
            return _stats_cache
    
    logger.info("🔄 Загружаем актуальную статистику...")
    
    players = parse_laliga_stats()
    
    if len(players) < 5:
        logger.warning("⚠️ Парсинг не удался, используем резервные данные")
        players = get_backup_stats()
    
    players.sort(key=lambda x: (x.get('goals', 0) + x.get('assists', 0)), reverse=True)
    
    for i, p in enumerate(players):
        p['rank'] = i + 1
        player_id = PLAYER_IDS.get(p['name'], 0)
        p['photo'] = f"https://api.sofascore.app/api/v1/player/{player_id}/image" if player_id else ''
        p['id'] = player_id
        if 'assists' not in p: p['assists'] = 0
        if 'rating' not in p: p['rating'] = 0
    
    if players:
        _stats_cache = players
        _cache_time = datetime.now()
    
    logger.info(f"✅ Статистика готова: {len(players)} игроков")
    return players


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%H:%M:%S')
    
    print("\n" + "="*60)
    print("⚽ АВТОМАТИЧЕСКАЯ СТАТИСТИКА REAL MADRID La Liga 2025/26")
    print("="*60 + "\n")
    
    players = get_real_player_stats()
    
    print(f"{'#':<3} {'Игрок':<18} {'Поз':<4} {'⚽':<4} {'🎯':<4} {'📊':<4}")
    print("-" * 45)
    
    for p in players[:15]:
        print(f"{p['rank']:<3} {p['name'][:17]:<18} {p['position']:<4} {p['goals']:<4} {p.get('assists', 0):<4} {p['matches']:<4}")
    
    print("\n" + "="*60 + "\n")
