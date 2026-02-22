"""
Real Madrid Bot v5.3
- Авторасчёт из Google Sheets (MatchStats)
- Закрытие ставок за 1 минуту до матча
- Уведомления за 5ч и 5мин
"""

import logging
import re
import os
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import gspread
import requests
from google.oauth2.service_account import Credentials

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

from config import Config
from database import (
    init_database, get_or_create_user, get_all_users, _execute
)

# Московский часовой пояс UTC+3
MSK = timezone(timedelta(hours=3))

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Эмодзи
E = {'bell': '🔔', 'stadium': '🏟️', 'clock': '🕐', 'tv': '📺', 'goal': '⚽', 'home': '🏠', 'away': '✈️'}

REAL_MADRID_TEAM_ID = 2829

# ============ GOOGLE SHEETS ============

_sheets_client = None
_matches_cache = {'data': [], 'time': None}
_results_cache = {'data': [], 'time': None}
CACHE_TTL = timedelta(minutes=5)


def get_sheets_client():
    global _sheets_client
    if _sheets_client is None:
        try:
            creds = Credentials.from_service_account_file(
                Config.CREDENTIALS_FILE,
                scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
            _sheets_client = gspread.authorize(creds)
            logger.info("✅ Google Sheets подключен")
        except Exception as e:
            logger.error(f"❌ Sheets auth error: {e}")
    return _sheets_client


def get_upcoming_matches(force_refresh=False) -> List[Dict]:
    """Получить предстоящие матчи из Google Sheets"""
    global _matches_cache

    if not force_refresh and _matches_cache['time']:
        if datetime.now() - _matches_cache['time'] < CACHE_TTL:
            return _matches_cache['data']

    try:
        client = get_sheets_client()
        if not client:
            return _matches_cache['data'] or []

        sheet = client.open_by_key(Config.SPREADSHEET_ID).worksheet('Matches')
        data = sheet.get_all_records()

        matches = [{
            'id': str(row.get('matchId', '')),
            'date': row.get('date', ''),
            'time': row.get('time', ''),
            'home_team': row.get('homeTeam', ''),
            'away_team': row.get('awayTeam', ''),
            'tournament': row.get('tournament', '')
        } for row in data if row.get('matchId')]

        _matches_cache = {'data': matches, 'time': datetime.now()}
        logger.info(f"📅 Загружено {len(matches)} матчей")
        return matches
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        return _matches_cache['data'] or []


def get_finished_matches_from_sheets() -> List[Dict]:
    """Получить завершённые матчи со статистикой из Google Sheets (MatchStats)"""
    global _results_cache

    if _results_cache['time']:
        if datetime.now() - _results_cache['time'] < CACHE_TTL:
            return _results_cache['data']

    try:
        client = get_sheets_client()
        if not client:
            return _results_cache['data'] or []

        sheet = client.open_by_key(Config.SPREADSHEET_ID).worksheet('MatchStats')
        data = sheet.get_all_records()

        matches = []
        for row in data:
            if row.get('status') == 'FINISHED' and row.get('matchId'):
                matches.append({
                    'matchId': str(row.get('matchId', '')),
                    'homeTeam': row.get('homeTeam', ''),
                    'awayTeam': row.get('awayTeam', ''),
                    'home_score': int(row.get('homeScore', 0) or 0),
                    'away_score': int(row.get('awayScore', 0) or 0),
                    'total_goals': int(row.get('totalGoals', 0) or 0),
                    'home_corners': int(row.get('homeCorners', 0) or 0),
                    'away_corners': int(row.get('awayCorners', 0) or 0),
                    'total_corners': int(row.get('homeCorners', 0) or 0) + int(row.get('awayCorners', 0) or 0),
                    'home_yellow': int(row.get('homeYellowCards', 0) or 0),
                    'away_yellow': int(row.get('awayYellowCards', 0) or 0),
                    'total_yellow': int(row.get('homeYellowCards', 0) or 0) + int(row.get('awayYellowCards', 0) or 0),
                    'total_red': int(row.get('totalRedCards', 0) or 0),
                    'both_scored': row.get('bothScored', 'no') == 'yes',
                    'outcome': row.get('outcome', 'draw'),
                    'has_penalty': row.get('hasPenalty', 'no') == 'yes',
                    'date': row.get('date', ''),
                })

        _results_cache = {'data': matches, 'time': datetime.now()}
        logger.info(f"📊 Загружено {len(matches)} завершённых матчей из MatchStats")
        return matches
    except Exception as e:
        logger.error(f"MatchStats error: {e}")
        return _results_cache['data'] or []


def _match_data_complete(match: dict) -> bool:
    """Проверяем полноту данных (Sheets обновляется раз в час)"""
    expected_goals = match.get('home_score', 0) + match.get('away_score', 0)
    actual_goals = match.get('total_goals', 0)
    if actual_goals != expected_goals and expected_goals > 0:
        return False
    if match.get('total_goals', 0) > 0 and match.get('total_corners', 0) == 0:
        return False
    if match.get('total_corners', 0) < 2:
        return False
    return True




# ============ ESPN: ПЕРВЫЙ ГОЛ ============

ESPN_API = "http://site.api.espn.com/apis/site/v2/sports/soccer"
_ESPN_LEAGUES = ['esp.1', 'uefa.champions', 'uefa.europa', 'eng.1', 'ger.1', 'ita.1', 'fra.1', 'uefa.europa.conf']


def _normalize_team(name: str) -> str:
    n = name.lower().strip()
    for rem in ['fc ', 'cf ', 'rcd ', 'ud ', 'rc ', 'sd ', 'sc ', 'sl ']:
        n = n.replace(rem, '')
    return n.strip()


def _teams_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    wa, wb = set(a.split()), set(b.split())
    return any(len(w) > 3 for w in wa & wb)


def get_first_goal_team(date_str: str, home_team: str, away_team: str, home_score: int, away_score: int) -> str:
    """Определить кто забил первый гол.
    Возвращает: 'home', 'away', 'none', '' (не удалось определить)
    """
    # Быстрые случаи без API
    if home_score == 0 and away_score == 0:
        return 'none'
    if home_score > 0 and away_score == 0:
        return 'home'
    if away_score > 0 and home_score == 0:
        return 'away'

    # Оба забили — нужен ESPN для определения первого гола
    try:
        date_part = date_str.split()[0] if ' ' in date_str else date_str
        parts = date_part.split('.')
        if len(parts) == 3:
            ds = parts[2] + parts[1] + parts[0]
        else:
            logger.warning(f"first_goal: bad date format {date_str}")
            return ''

        h_norm = _normalize_team(home_team)
        a_norm = _normalize_team(away_team)

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
                    espn_home, espn_away, home_id = '', '', ''
                    for c in competitors:
                        tn = c.get('team', {}).get('displayName', '')
                        if c.get('homeAway') == 'home':
                            espn_home = tn
                            home_id = str(c.get('id', ''))
                        else:
                            espn_away = tn
                    if not _teams_match(h_norm, _normalize_team(espn_home)):
                        continue
                    if not _teams_match(a_norm, _normalize_team(espn_away)):
                        continue

                    # Нашли матч — получаем summary
                    espn_id = str(ev.get('id', ''))
                    for lg2 in [league]:
                        try:
                            sum_url = f"{ESPN_API}/{lg2}/summary?event={espn_id}"
                            sr = requests.get(sum_url, timeout=15)
                            if sr.status_code != 200:
                                continue
                            summary = sr.json()
                            if not summary.get('header'):
                                continue
                            goals = []
                            for ke in summary.get('keyEvents', []):
                                ev_type = (ke.get('type', {}).get('type', '') or '').lower()
                                if ev_type == 'goal' or ('penalty' in ev_type and 'scored' in ev_type):
                                    sort_val = ke.get('clock', {}).get('value', 0) or 0
                                    team_id = str(ke.get('team', {}).get('id', ''))
                                    is_home = (team_id == home_id)
                                    goals.append((sort_val, is_home))
                            if goals:
                                goals.sort(key=lambda x: x[0])
                                result = 'home' if goals[0][1] else 'away'
                                logger.info(f"  ESPN first_goal: {home_team} vs {away_team} -> {result}")
                                return result
                            logger.warning(f"  ESPN: no goals in keyEvents for {espn_id}")
                            return ''
                        except:
                            continue
                    return ''
            except Exception as e:
                logger.debug(f"ESPN league {league}: {e}")
                continue

        logger.warning(f"  ESPN: match not found for {home_team} vs {away_team}")
        return ''
    except Exception as e:
        logger.error(f"first_goal ESPN error: {e}")
        return ''


# ============ LIVEBALL ============

_liveball_cache = {'url': None, 'time': None}


def get_liveball_url() -> str:
    global _liveball_cache

    if _liveball_cache['url'] and _liveball_cache['time']:
        if datetime.now() - _liveball_cache['time'] < timedelta(hours=1):
            return _liveball_cache['url']

    try:
        resp = requests.get('https://liveball.website/', headers={'User-Agent': 'Mozilla/5.0'}, timeout=10, allow_redirects=True)
        if resp.url and 'liveball' in resp.url:
            url = f"{resp.url.rstrip('/')}/team/541"
            _liveball_cache = {'url': url, 'time': datetime.now()}
            return url
    except:
        pass

    return 'https://liveball.website/'


# ============ STREAMS ============

STREAMS_FILE = '/app/data/streams.json'


def get_streams():
    try:
        if os.path.exists(STREAMS_FILE):
            with open(STREAMS_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {"streams": [], "updated": "", "updated_by": ""}


def save_streams(data):
    try:
        os.makedirs(os.path.dirname(STREAMS_FILE), exist_ok=True)
        with open(STREAMS_FILE, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Save streams error: {e}")
        return False


def get_active_streams():
    data = get_streams()
    return [s for s in data.get('streams', []) if s.get('active', True)]


def _parse_stream_url(url, name=None, index=0):
    """Parse URL and create stream entry with type detection"""
    url = url.strip()
    if url.startswith('acestream://'):
        ace_id = url.replace('acestream://', '').strip()
        return {
            "name": name or f"Acestream {index+1}",
            "url": url,
            "type": "acestream",
            "ace_id": ace_id,
            "active": True
        }
    if url.startswith('iframe:'):
        real_url = url.replace('iframe:', '', 1).strip()
        return {
            "name": name or f"Stream {index+1}",
            "url": real_url,
            "type": "iframe",
            "active": True
        }
    if url.startswith('http'):
        # Check if it's m3u8/HLS or a webpage (iframe)
        url_lower = url.lower()
        if '.m3u8' in url_lower or '.m3u' in url_lower or '.ts' in url_lower:
            return {
                "name": name or f"Stream {index+1}",
                "url": url,
                "type": "hls",
                "active": True
            }
        # Default: treat as iframe (webpage with embedded player)
        return {
            "name": name or f"Stream {index+1}",
            "url": url,
            "type": "iframe",
            "active": True
        }
    return None


# ============ РАСЧЁТ СТАВОК ============

def check_bet_won(bet_type: str, stats: dict) -> bool:
    """Проверить выиграла ли ставка"""
    outcome = stats.get('outcome', 'draw')
    home_score = stats.get('home_score', 0)
    away_score = stats.get('away_score', 0)
    total = stats.get('total_goals', 0)

    # Убираем префикс LIVE_ если есть
    if bet_type.startswith('LIVE_'):
        bet_type = bet_type.replace('LIVE_', '')

    # Исход матча
    if bet_type in ['home', 'draw', 'away']:
        return bet_type == outcome

    # Точный счёт
    if bet_type.startswith('score_'):
        score = bet_type.replace('score_', '')
        return score == f"{home_score}-{away_score}"

    # Тоталы голов
    if bet_type.startswith('total_over_'):
        line = float(bet_type.replace('total_over_', ''))
        return total > line
    if bet_type.startswith('total_under_'):
        line = float(bet_type.replace('total_under_', ''))
        return total < line

    # Обе забьют
    if bet_type == 'btts_yes':
        return stats.get('both_scored', False)
    if bet_type == 'btts_no':
        return not stats.get('both_scored', False)

    # Чёт/Нечёт тотал голов
    if bet_type == 'total_even':
        return total % 2 == 0
    if bet_type == 'total_odd':
        return total % 2 == 1

    # Угловые
    corners = stats.get('total_corners', 0)
    if bet_type.startswith('corners_over_'):
        line = float(bet_type.replace('corners_over_', ''))
        return corners > line
    if bet_type.startswith('corners_under_'):
        line = float(bet_type.replace('corners_under_', ''))
        return corners < line

    # Карточки
    cards = stats.get('total_yellow', 0)
    if bet_type.startswith('cards_over_'):
        line = float(bet_type.replace('cards_over_', ''))
        return cards > line
    if bet_type.startswith('cards_under_'):
        line = float(bet_type.replace('cards_under_', ''))
        return cards < line

    # Индивидуальный тотал хозяев
    if bet_type.startswith('home_over_'):
        line = float(bet_type.replace('home_over_', ''))
        return home_score > line
    if bet_type.startswith('home_under_'):
        line = float(bet_type.replace('home_under_', ''))
        return home_score < line

    # Индивидуальный тотал гостей
    if bet_type.startswith('away_over_'):
        line = float(bet_type.replace('away_over_', ''))
        return away_score > line
    if bet_type.startswith('away_under_'):
        line = float(bet_type.replace('away_under_', ''))
        return away_score < line

    # Пенальти
    has_penalty = stats.get('has_penalty', False)
    if bet_type == 'penalty_yes':
        return has_penalty
    if bet_type == 'penalty_no':
        return not has_penalty

    # Двойной шанс
    if bet_type == 'dc_1x':
        return outcome in ('home', 'draw')
    if bet_type == 'dc_x2':
        return outcome in ('draw', 'away')
    if bet_type == 'dc_12':
        return outcome in ('home', 'away')

    # Результат без ничьей (Draw No Bet)
    if bet_type == 'dnb_home':
        return outcome == 'home'
    if bet_type == 'dnb_away':
        return outcome == 'away'

    # Кто забьёт первый гол
    first_goal = stats.get('first_goal', '')
    if bet_type.startswith('first_goal_'):
        if not first_goal:
            return None  # Не удалось определить — оставляем pending
        if bet_type == 'first_goal_home':
            return first_goal == 'home'
        if bet_type == 'first_goal_away':
            return first_goal == 'away'
        if bet_type == 'first_goal_none':
            return first_goal == 'none'

    # Фора (гандикап)
    if bet_type.startswith('handicap_home_'):
        line = float(bet_type.replace('handicap_home_', ''))
        return (home_score - away_score + line) > 0
    if bet_type.startswith('handicap_away_'):
        line = float(bet_type.replace('handicap_away_', ''))
        return (away_score - home_score + line) > 0

    # Азиатская фора
    if bet_type.startswith('asian_home_'):
        line = float(bet_type.replace('asian_home_', ''))
        return (home_score - away_score + line) > 0
    if bet_type.startswith('asian_away_'):
        line = float(bet_type.replace('asian_away_', ''))
        return (away_score - home_score + line) > 0

    # ИТ угловых хозяев/гостей
    home_corners = stats.get('home_corners', 0)
    away_corners = stats.get('away_corners', 0)
    if bet_type.startswith('corners_home_over_'):
        return home_corners > float(bet_type.replace('corners_home_over_', ''))
    if bet_type.startswith('corners_home_under_'):
        return home_corners < float(bet_type.replace('corners_home_under_', ''))
    if bet_type.startswith('corners_away_over_'):
        return away_corners > float(bet_type.replace('corners_away_over_', ''))
    if bet_type.startswith('corners_away_under_'):
        return away_corners < float(bet_type.replace('corners_away_under_', ''))

    # ИТ карточек хозяев/гостей
    home_cards = stats.get('home_yellow', 0)
    away_cards = stats.get('away_yellow', 0)
    if bet_type.startswith('cards_home_over_'):
        return home_cards > float(bet_type.replace('cards_home_over_', ''))
    if bet_type.startswith('cards_home_under_'):
        return home_cards < float(bet_type.replace('cards_home_under_', ''))
    if bet_type.startswith('cards_away_over_'):
        return away_cards > float(bet_type.replace('cards_away_over_', ''))
    if bet_type.startswith('cards_away_under_'):
        return away_cards < float(bet_type.replace('cards_away_under_', ''))

    return False


def log_transaction(user_id: int, tx_type: str, amount: int, description: str, reference_id: str = None):
    """Записать транзакцию в историю"""
    try:
        user = _execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance_before = user[0]['balance'] if user else 0
        balance_after = balance_before + amount

        _execute(
            """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, tx_type, amount, balance_before, balance_after, description, reference_id)
        )
    except Exception as e:
        logger.error(f"Transaction log error: {e}")


def settle_all_bets(match_id: str, stats: dict) -> dict:
    """Рассчитать все ставки на матч"""
    result = {
        'bets_settled': 0, 'bets_won': 0, 'bets_lost': 0,
        'predictions_settled': 0, 'predictions_correct': 0
    }

    # Получаем pending ставки
    bets = _execute(
        "SELECT bet_id, user_id, bet_type, amount, odds FROM bets WHERE match_id = ? AND status = 'pending'",
        (str(match_id),)
    ) or []

    for bet in bets:
        won = check_bet_won(bet['bet_type'], stats)

        # None = не удалось определить (например first_goal), оставляем pending
        if won is None:
            continue

        if won:
            winnings = int(bet['amount'] * bet['odds'])
            # Сначала получаем текущий баланс
            user = _execute("SELECT balance FROM users WHERE user_id = ?", (bet['user_id'],))
            balance_before = user[0]['balance'] if user else 0
            balance_after = balance_before + winnings
            # Обновляем баланс
            _execute("UPDATE bets SET status = 'won', payout = ? WHERE bet_id = ?", (winnings, bet['bet_id']))
            _execute("UPDATE users SET balance = ?, bets_won = bets_won + 1 WHERE user_id = ?", (balance_after, bet['user_id']))
            # Записываем транзакцию с правильными значениями
            _execute(
                """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                   VALUES (?, 'bet_win', ?, ?, ?, ?, ?)""",
                (bet['user_id'], winnings, balance_before, balance_after, f"Выигрыш ставки #{bet['bet_id']}", str(bet['bet_id']))
            )
            result['bets_won'] += 1
        else:
            # Для проигрыша баланс не меняется
            user = _execute("SELECT balance FROM users WHERE user_id = ?", (bet['user_id'],))
            balance = user[0]['balance'] if user else 0
            _execute("UPDATE bets SET status = 'lost' WHERE bet_id = ?", (bet['bet_id'],))
            _execute("UPDATE users SET bets_lost = bets_lost + 1 WHERE user_id = ?", (bet['user_id'],))
            _execute(
                """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                   VALUES (?, 'bet_lose', 0, ?, ?, ?, ?)""",
                (bet['user_id'], balance, balance, f"Проигрыш ставки #{bet['bet_id']}", str(bet['bet_id']))
            )
            result['bets_lost'] += 1

        result['bets_settled'] += 1

    # Прогнозы
    preds = _execute(
        "SELECT prediction_id, user_id, prediction FROM predictions WHERE match_id = ? AND status = 'pending'",
        (str(match_id),)
    ) or []

    for pred in preds:
        won = pred['prediction'] == stats.get('outcome')

        if won:
            user = _execute("SELECT balance FROM users WHERE user_id = ?", (pred['user_id'],))
            balance_before = user[0]['balance'] if user else 0
            balance_after = balance_before + 5
            _execute("UPDATE predictions SET status = 'correct', points_change = 5 WHERE prediction_id = ?", (pred['prediction_id'],))
            _execute("UPDATE users SET balance = ?, predictions_won = predictions_won + 1 WHERE user_id = ?", (balance_after, pred['user_id']))
            _execute(
                """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                   VALUES (?, 'prediction_win', 5, ?, ?, ?, ?)""",
                (pred['user_id'], balance_before, balance_after, f"Правильный прогноз #{pred['prediction_id']}", str(pred['prediction_id']))
            )
            result['predictions_correct'] += 1
        else:
            user = _execute("SELECT balance FROM users WHERE user_id = ?", (pred['user_id'],))
            balance_before = user[0]['balance'] if user else 0
            balance_after = balance_before - 10
            _execute("UPDATE predictions SET status = 'incorrect', points_change = -10 WHERE prediction_id = ?", (pred['prediction_id'],))
            _execute("UPDATE users SET balance = ?, predictions_lost = predictions_lost + 1 WHERE user_id = ?", (balance_after, pred['user_id']))
            _execute(
                """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                   VALUES (?, 'prediction_lose', -10, ?, ?, ?, ?)""",
                (pred['user_id'], balance_before, balance_after, f"Неправильный прогноз #{pred['prediction_id']}", str(pred['prediction_id']))
            )

        result['predictions_settled'] += 1

    return result


# ============ КОМАНДЫ ============

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Проверяем есть ли реферальный код
    ref_code = None
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith('ref'):
            ref_code = arg

    # Проверяем существует ли пользователь
    existing_user = _execute("SELECT user_id, referred_by FROM users WHERE user_id = ?", (user.id,))
    is_new_user = not existing_user

    # Создаём/получаем пользователя
    get_or_create_user(user.id, user.username, user.first_name)

    # Обрабатываем реферальный код для новых пользователей
    ref_bonus_msg = ""
    if ref_code:
        try:
            referrer_id = int(ref_code.replace('ref', ''))

            # Проверяем что реферер существует и это не сам пользователь
            if referrer_id != user.id:
                referrer = _execute("SELECT user_id, balance FROM users WHERE user_id = ?", (referrer_id,))
                if referrer:
                    # Проверяем что пользователь ещё не имеет реферера
                    current = _execute("SELECT referred_by FROM users WHERE user_id = ?", (user.id,))
                    if current and not current[0].get('referred_by'):
                        bonus = 25

                        # Записываем реферера
                        _execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user.id))

                        # Бонус рефереру
                        _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, referrer_id))
                        _execute(
                            """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                               VALUES (?, 'referral_bonus', ?, ?, ?, ?, ?)""",
                            (referrer_id, bonus, referrer[0]['balance'], referrer[0]['balance'] + bonus,
                             f"Бонус за приглашение друга @{user.username or user.first_name}", str(user.id))
                        )

                        # Бонус новому пользователю
                        user_data = _execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
                        user_balance = user_data[0]['balance'] if user_data else 0

                        _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, user.id))
                        _execute(
                            """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                               VALUES (?, 'referral_bonus', ?, ?, ?, ?, ?)""",
                            (user.id, bonus, user_balance, user_balance + bonus,
                             f"Бонус за регистрацию по приглашению", str(referrer_id))
                        )

                        ref_bonus_msg = f"\n\n🎁 <b>+{bonus} очков</b> за регистрацию по приглашению!"
                        logger.info(f"Referral bonus: {user.id} invited by {referrer_id}, +{bonus} each")
        except Exception as e:
            logger.error(f"Referral error: {e}")

    keyboard = [[InlineKeyboardButton("⚽ Открыть приложение", web_app={"url": Config.WEBAPP_URL})]]

    await update.message.reply_text(
        f"👋 Привет, <b>{user.first_name}</b>!\n\n"
        f"Добро пожаловать в <b>Real Madrid Fan Bot</b>!\n\n"
        f"🎰 Делай ставки • 🎯 Прогнозы • 🏆 Рейтинг • 🎁 Призы{ref_bonus_msg}\n\n"
        f"Нажми кнопку 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.ADMIN_IDS:
        return

    users = get_all_users(limit=10000)
    pending = _execute("SELECT COUNT(*) as cnt FROM bets WHERE status = 'pending'") or [{'cnt': 0}]

    await update.message.reply_text(
        f"👑 <b>Админ</b>\n\n"
        f"👥 {len(users)} юзеров\n"
        f"💰 {sum(u.get('balance', 0) for u in users)} очков\n"
        f"⏳ {pending[0]['cnt']} pending ставок\n\n"
        f"/settle - расчёт\n"
        f"/addbal @user 100 - баланс",
        parse_mode=ParseMode.HTML
    )


async def settle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной расчёт ставок"""
    global _results_cache

    if update.effective_user.id not in Config.ADMIN_IDS:
        return

    await update.message.reply_text("⏳ Расчёт из Google Sheets...")

    # Сбрасываем кэш чтобы получить свежие данные
    _results_cache = {'data': [], 'time': None}

    matches = get_finished_matches_from_sheets()
    settled_any = False

    for match in matches:
        mid = match['matchId']


        # Проверяем полноту данных
        if not _match_data_complete(match):
            await update.message.reply_text(
                f"\u26a0\ufe0f <b>{match['homeTeam']} vs {match['awayTeam']}</b>\n"
                f"Данные неполные (\U0001f6a9{match.get('total_corners',0)} \U0001f7e8{match.get('total_yellow',0)}) - пропуск.\n"
                f"Дождись обновления Sheets и /settle",
                parse_mode=ParseMode.HTML
            )
            continue

        # Определяем кто забил первый гол
        first_goal = get_first_goal_team(
            match.get('date', ''), match['homeTeam'], match['awayTeam'],
            match['home_score'], match['away_score']
        )

        stats = {
            'home_score': match['home_score'],
            'away_score': match['away_score'],
            'total_goals': match['total_goals'],
            'home_corners': match['home_corners'],
            'away_corners': match['away_corners'],
            'total_corners': match['home_corners'] + match['away_corners'],
            'home_yellow': match.get('home_yellow', 0),
            'away_yellow': match.get('away_yellow', 0),
            'total_yellow': match.get('home_yellow', 0) + match.get('away_yellow', 0),
            'both_scored': match['both_scored'],
            'outcome': match['outcome'],
            'has_penalty': match.get('has_penalty', False),
            'first_goal': first_goal,
        }

        st = settle_all_bets(mid, stats)

        if st['bets_settled'] > 0 or st['predictions_settled'] > 0:
            settled_any = True
            await update.message.reply_text(
                f"✅ <b>{match['homeTeam']} vs {match['awayTeam']}</b>\n"
                f"{stats['home_score']}:{stats['away_score']} | 🚩{stats['total_corners']} | 🟨{stats['total_yellow']}\n"
                f"🎰 {st['bets_settled']} (✅{st['bets_won']} ❌{st['bets_lost']})",
                parse_mode=ParseMode.HTML
            )

    if not settled_any:
        await update.message.reply_text("ℹ️ Нет ставок для расчёта")


async def addbal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.ADMIN_IDS:
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("/addbal @user 100")
        return

    username = args[0].replace('@', '').lower()
    try:
        amount = int(args[1])
    except:
        return

    result = _execute("SELECT user_id, balance FROM users WHERE LOWER(username) = ?", (username,))
    if not result:
        await update.message.reply_text(f"❌ @{username} не найден")
        return

    new_bal = result[0]['balance'] + amount
    _execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_bal, result[0]['user_id']))
    await update.message.reply_text(f"✅ @{username}: {result[0]['balance']} → {new_bal}")




async def fixbets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск и фикс orphan ставок"""
    if update.effective_user.id not in Config.ADMIN_IDS:
        return

    args = context.args

    if args and len(args) == 2:
        old_id, new_id = args
        count = _execute("SELECT COUNT(*) as cnt FROM bets WHERE match_id = ? AND status = 'pending'", (old_id,))
        cnt = count[0]['cnt'] if count else 0
        if cnt > 0:
            _execute("UPDATE bets SET match_id = ? WHERE match_id = ? AND status = 'pending'", (new_id, old_id))
            _execute("UPDATE predictions SET match_id = ? WHERE match_id = ? AND status = 'pending'", (new_id, old_id))
            await update.message.reply_text(f"\u2705 {cnt} ставок: {old_id} \u2192 {new_id}\nТеперь /settle")
        else:
            await update.message.reply_text(f"\u274c Нет pending ставок с match_id={old_id}")
        return

    try:
        pending = _execute("""
            SELECT b.match_id, b.bet_type, b.amount, b.odds, b.home_team, b.away_team, u.username
            FROM bets b LEFT JOIN users u ON b.user_id = u.user_id
            WHERE b.status = 'pending' ORDER BY b.created_at DESC LIMIT 30
        """) or []
    except Exception:
        pending = _execute("""
            SELECT b.match_id, b.bet_type, b.amount, b.odds, u.username
            FROM bets b LEFT JOIN users u ON b.user_id = u.user_id
            WHERE b.status = 'pending' ORDER BY b.created_at DESC LIMIT 30
        """) or []

    if not pending:
        await update.message.reply_text("\u2705 Нет pending ставок")
        return

    by_match = {}
    for b in pending:
        mid = b['match_id']
        if mid not in by_match:
            by_match[mid] = []
        by_match[mid].append(b)

    finished = get_finished_matches_from_sheets()
    sheets_ids = {m['matchId'] for m in finished}

    text = f"\U0001f4cb <b>Pending:</b> {len(pending)}\n\n"
    for mid, bets in by_match.items():
        icon = "\u26a0\ufe0f" if mid not in sheets_ids else "\u2705"
        teams = f" ({bets[0].get('home_team', '?')} vs {bets[0].get('away_team', '?')})" if bets[0].get('home_team') else ""
        text += f"{icon} <code>{mid}</code>{teams}\n"
        for b in bets[:5]:
            text += f"  \u2022 @{b.get('username','?')}: {b['bet_type']} {b['amount']}x{b['odds']}\n"
        if mid not in sheets_ids:
            text += f"  \u27a1\ufe0f /fixbets {mid} [sheets_id]\n"
        text += "\n"

    if finished:
        text += "<b>Finished в Sheets:</b>\n"
        for m in finished[-5:]:
            text += f"<code>{m['matchId']}</code> {m['homeTeam']} {m.get('home_score',0)}:{m.get('away_score',0)} {m['awayTeam']}\n"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ============ УВЕДОМЛЕНИЯ ============

_notified_5h = set()
_notified_5m = set()
_NOTIF_FILE = '/app/data/notified.json'

def _load_notified():
    global _notified_5h, _notified_5m
    try:
        import json as _j
        if os.path.exists(_NOTIF_FILE):
            with open(_NOTIF_FILE, 'r') as f:
                d = _j.load(f)
                _notified_5h = set(d.get('5h', []))
                _notified_5m = set(d.get('5m', []))
    except:
        pass

def _save_notified():
    try:
        import json as _j
        os.makedirs(os.path.dirname(_NOTIF_FILE), exist_ok=True)
        with open(_NOTIF_FILE, 'w') as f:
            _j.dump({'5h': list(_notified_5h), '5m': list(_notified_5m)}, f)
    except:
        pass

_load_notified()


async def check_notifications(context: ContextTypes.DEFAULT_TYPE):
    global _notified_5h, _notified_5m

    try:
        matches = get_upcoming_matches()
        now = datetime.now(MSK)

        for m in matches:
            key = f"{m['id']}_{m['date']}_{m['time']}"

            try:
                mt = datetime.strptime(f"{m['date']} {m['time']}", '%d.%m.%Y %H:%M')
                mt = mt.replace(tzinfo=MSK)
            except:
                continue

            diff = (mt - now).total_seconds() / 60

            home, away = m['home_team'], m['away_team']
            is_home = 'Real Madrid' in home
            icon = E['home'] if is_home else E['away']
            loc = "дома" if is_home else "в гостях"

            # 5 hours (window 270-360 min)
            if 270 <= diff <= 360 and key not in _notified_5h:
                _notified_5h.add(key)
                _save_notified()
                logger.info(f"5h notif: {home} vs {away}, diff={diff:.0f}m")
                text = f"{E['bell']} <b>Матч через 5 часов!</b>\n\n{E['stadium']} <b>{home}</b> vs <b>{away}</b>\n{E['clock']} {m['date']} {m['time']}\n{icon} Real Madrid {loc}\n\n{E['goal']} Сделай ставку!"
                for u in get_all_users(limit=10000):
                    if u.get('notifications_enabled', 1):
                        try:
                            await context.bot.send_message(u['user_id'], text, parse_mode=ParseMode.HTML)
                        except:
                            pass

            # 5 min (window 1-10 min)
            if 1 <= diff <= 10 and key not in _notified_5m:
                _notified_5m.add(key)
                _save_notified()
                logger.info(f"5m notif: {home} vs {away}, diff={diff:.0f}m")
                stream_url = get_liveball_url()
                # Добавляем стримы если есть
                stream_text = ""
                active = get_active_streams()
                if active:
                    stream_lines = '\n'.join(f"  • {s['name']}" for s in active)
                    stream_text = f"\n\n📺 Трансляция:\n{stream_lines}"
                text = f"{E['bell']} <b>Матч через 5 минут!</b>\n\n{E['stadium']} <b>{home}</b> vs <b>{away}</b>\n\n{E['tv']} <a href=\"{stream_url}\">Смотреть</a>{stream_text}\n\n⏰ Последний шанс сделать ставку!"
                for u in get_all_users(limit=10000):
                    if u.get('notifications_enabled', 1):
                        try:
                            await context.bot.send_message(u['user_id'], text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                        except:
                            pass
    except Exception as e:
        logger.error(f"Notif error: {e}")


# ============ АВТО-РАСЧЁТ ============

_settled = set()


async def auto_settle(context: ContextTypes.DEFAULT_TYPE):
    """Автоматический расчёт из Google Sheets"""
    global _settled

    try:
        matches = get_finished_matches_from_sheets()
        logger.info(f"🔍 Авторасчёт: {len(matches)} завершённых матчей в MatchStats")

        for match in matches:
            mid = match['matchId']

            if mid in _settled:
                continue

            # Проверяем есть ли pending ставки на этот матч
            pending = _execute(
                "SELECT COUNT(*) as cnt FROM bets WHERE match_id = ? AND status = 'pending'",
                (str(mid),)
            )

            pending_count = pending[0]['cnt'] if pending else 0


            if pending_count == 0:
                _settled.add(mid)
                continue

            # Проверяем полноту данных
            if not _match_data_complete(match):
                logger.warning(f"  Данные неполные: {match['homeTeam']} vs {match['awayTeam']} corners={match.get('total_corners',0)}")
                continue

            # Запоминаем pending ставки ДО расчёта
            pending_bets_before = _execute(
                "SELECT bet_id FROM bets WHERE match_id = ? AND status = 'pending'",
                (str(mid),)
            ) or []
            pending_ids = [b['bet_id'] for b in pending_bets_before]

            # Определяем кто забил первый гол
            first_goal = get_first_goal_team(
                match.get('date', ''), match['homeTeam'], match['awayTeam'],
                match['home_score'], match['away_score']
            )

            stats = {
                'home_score': match['home_score'],
                'away_score': match['away_score'],
                'total_goals': match['total_goals'],
                'home_corners': match['home_corners'],
                'away_corners': match['away_corners'],
                'total_corners': match['home_corners'] + match['away_corners'],
                'home_yellow': match.get('home_yellow', 0),
                'away_yellow': match.get('away_yellow', 0),
                'total_yellow': match.get('home_yellow', 0) + match.get('away_yellow', 0),
                'both_scored': match['both_scored'],
                'outcome': match['outcome'],
                'has_penalty': match.get('has_penalty', False),
                'first_goal': first_goal,
            }

            logger.info(f"  📌 Расчёт: {match['homeTeam']} {stats['home_score']}:{stats['away_score']} {match['awayTeam']}")

            st = settle_all_bets(mid, stats)

            if st['bets_settled'] > 0 or st['predictions_settled'] > 0:
                _settled.add(mid)

                # Детали ставок для админа
                settled_bets = []
                if pending_ids:
                    placeholders = ','.join(['?' for _ in pending_ids])
                    settled_bets = _execute(f"""
                        SELECT b.user_id, b.bet_type, b.amount, b.odds, b.status, b.payout, u.username, u.first_name
                        FROM bets b
                        LEFT JOIN users u ON b.user_id = u.user_id
                        WHERE b.bet_id IN ({placeholders})
                        ORDER BY b.created_at DESC
                    """, pending_ids) or []

                bets_detail = ""
                if settled_bets:
                    bets_detail = "\n\n📋 <b>Ставки:</b>\n"
                    for bet in settled_bets:
                        name = bet.get('username') or bet.get('first_name') or str(bet['user_id'])
                        if bet['status'] == 'won':
                            icon = "✅"
                            result = f"+{int(bet['payout'])}"
                        elif bet['status'] == 'returned':
                            icon = "↩️"
                            result = f"возврат {int(bet['amount'])}"
                        else:
                            icon = "❌"
                            result = f"-{int(bet['amount'])}"
                        bets_detail += f"{icon} @{name}: {bet['bet_type']} ({bet['amount']}💰) → {result}\n"

                # Уведомление админу
                for admin_id in Config.ADMIN_IDS:
                    try:
                        await context.bot.send_message(
                            admin_id,
                            f"✅ <b>Авто-расчёт</b>\n\n"
                            f"⚽ {match['homeTeam']} {stats['home_score']}:{stats['away_score']} {match['awayTeam']}\n"
                            f"🚩 Угловые: {stats['total_corners']} | 🟨 Карточки: {stats['total_yellow']}\n"
                            f"⚽ Обе забили: {'Да' if stats['both_scored'] else 'Нет'} | ⚠️ Пенальти: {'Да' if stats.get('has_penalty') else 'Нет'}\n\n"
                            f"📊 <b>Итого:</b> {st['bets_settled']} ставок\n"
                            f"✅ Выиграли: {st['bets_won']} | ❌ Проиграли: {st['bets_lost']}"
                            f"{bets_detail}",
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"Admin notify error: {e}")

                _settled.add(mid)

    except Exception as e:
        logger.error(f"Auto-settle error: {e}")


# ============ СТРИМЫ (АДМИН) ============

async def setstream_cmd(update, context):
    if update.effective_user.id not in Config.ADMIN_IDS:
        return
    text = update.message.text.replace('/setstream', '').strip()
    if not text:
        await update.message.reply_text(
            "Формат:\n"
            "/setstream URL1 URL2 ...\n\n"
            "Или с названиями:\n"
            "/setstream beIN Sports 1|https://url.m3u8\n"
            "SKY LaLiga|https://url2.m3u8\n\n"
            "Acestream:\n"
            "/setstream acestream://HASH\n"
            "LaLiga HD|acestream://HASH\n\n"
            "Iframe (сайт с плеером):\n"
            "/setstream Match|iframe:https://site.com/match.html\n"
            "/setstream Match|https://site.com/match.html\n"
            "(http ссылки без .m3u8 = iframe автоматически)\n\n"
            "📖 Где брать ссылки:\n"
            "1. https://iptv-org.github.io/iptv/categories/sports.m3u\n"
            "2. https://iptv-org.github.io/iptv/countries/es.m3u\n"
            "3. https://github.com/manikiptv/freecatv.github.io",
            disable_web_page_preview=True
        )
        return

    streams = []
    # Split by newlines first, then by spaces for URLs
    parts = [p.strip() for p in text.replace('\n', '\n').split('\n') if p.strip()]
    if len(parts) == 1:
        # Single line — split by spaces (all URLs)
        tokens = parts[0].split()
        for t in tokens:
            if '|' in t:
                name, url = t.rsplit('|', 1)
                entry = _parse_stream_url(url, name.strip(), len(streams))
                if entry: streams.append(entry)
            elif t.startswith('http') or t.startswith('acestream://') or t.startswith('iframe:'):
                entry = _parse_stream_url(t, None, len(streams))
                if entry: streams.append(entry)
    else:
        # Multiple lines — each can be "Name|URL" or just URL
        for p in parts:
            if '|' in p:
                name, url = p.rsplit('|', 1)
                entry = _parse_stream_url(url, name.strip(), len(streams))
                if entry: streams.append(entry)
            elif p.startswith('http') or p.startswith('acestream://') or p.startswith('iframe:'):
                entry = _parse_stream_url(p, None, len(streams))
                if entry: streams.append(entry)
            else:
                # Maybe "Name URL" format
                tokens = p.split()
                if len(tokens) >= 2 and (tokens[-1].startswith('http') or tokens[-1].startswith('acestream://') or tokens[-1].startswith('iframe:')):
                    url = tokens[-1]
                    name = ' '.join(tokens[:-1])
                    entry = _parse_stream_url(url, name, len(streams))
                    if entry: streams.append(entry)

    if not streams:
        await update.message.reply_text("❌ Не найдено ни одной ссылки")
        return

    streams = streams[:5]  # max 5

    data = {
        "streams": streams,
        "updated": datetime.now(MSK).strftime('%Y-%m-%d %H:%M'),
        "updated_by": update.effective_user.first_name or "admin"
    }

    if save_streams(data):
        type_tags = {'acestream': '[ACE] ', 'iframe': '[WEB] ', 'hls': '[HLS] '}
        lines = [f"{i+1}. {type_tags.get(s.get('type',''), '')}{s['name']} — {s['url'][:50]}..." for i, s in enumerate(streams)]
        await update.message.reply_text(
            f"✅ Установлено {len(streams)} трансляци{'я' if len(streams)==1 else 'и' if len(streams)<5 else 'й'}:\n"
            + '\n'.join(lines) +
            "\n\n📖 Где брать ссылки:\n"
            "1. iptv-org спорт: https://iptv-org.github.io/iptv/categories/sports.m3u\n"
            "2. iptv-org Испания: https://iptv-org.github.io/iptv/countries/es.m3u\n"
            "3. freecatv: https://github.com/manikiptv/freecatv.github.io\n"
            "Ищи: beIN Sports, SKY Sports LaLiga, TNT Sports, Movistar LaLiga",
            disable_web_page_preview=True
        )
    else:
        await update.message.reply_text("❌ Ошибка сохранения")


async def streams_cmd(update, context):
    if update.effective_user.id not in Config.ADMIN_IDS:
        return
    data = get_streams()
    streams = data.get('streams', [])
    if not streams:
        await update.message.reply_text("📺 Нет установленных трансляций\n\n/setstream — установить ссылки")
        return

    lines = []
    for i, s in enumerate(streams):
        status = "✅" if s.get('active', True) else "❌"
        type_tags = {'acestream': '[ACE] ', 'iframe': '[WEB] ', 'hls': '[HLS] '}
        type_tag = type_tags.get(s.get('type', ''), '')
        lines.append(f"{i+1}. {status} {type_tag}{s['name']} — {s['url'][:50]}...")

    await update.message.reply_text(
        "📺 Текущие трансляции:\n" + '\n'.join(lines) +
        "\n\n/setstream — обновить ссылки\n"
        "/delstream — очистить все\n"
        "/streamoff N — выключить\n"
        "/streamon N — включить",
        disable_web_page_preview=True
    )


async def delstream_cmd(update, context):
    if update.effective_user.id not in Config.ADMIN_IDS:
        return
    save_streams({"streams": [], "updated": "", "updated_by": ""})
    await update.message.reply_text("✅ Все трансляции удалены")


async def streamoff_cmd(update, context):
    if update.effective_user.id not in Config.ADMIN_IDS:
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Формат: /streamoff N (номер стрима)")
        return
    n = int(args[0]) - 1
    data = get_streams()
    streams = data.get('streams', [])
    if 0 <= n < len(streams):
        streams[n]['active'] = False
        data['streams'] = streams
        save_streams(data)
        await update.message.reply_text(f"❌ Стрим {n+1} ({streams[n]['name']}) выключен")
    else:
        await update.message.reply_text(f"❌ Стрим {n+1} не найден")


async def streamon_cmd(update, context):
    if update.effective_user.id not in Config.ADMIN_IDS:
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Формат: /streamon N (номер стрима)")
        return
    n = int(args[0]) - 1
    data = get_streams()
    streams = data.get('streams', [])
    if 0 <= n < len(streams):
        streams[n]['active'] = True
        data['streams'] = streams
        save_streams(data)
        await update.message.reply_text(f"✅ Стрим {n+1} ({streams[n]['name']}) включен")
    else:
        await update.message.reply_text(f"❌ Стрим {n+1} не найден")



# ============ PURCHASES ============

PURCHASES_FILE = '/app/data/purchases.json'

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


async def approve_cmd(update, context):
    """Одобрить покупку и начислить очки"""
    if update.effective_user.id not in Config.ADMIN_IDS:
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Формат: /approve ID")
        return

    purchase_id = int(args[0])
    purchases = _load_purchases()

    found = None
    for p in purchases:
        if p.get('id') == purchase_id:
            found = p
            break

    if not found:
        await update.message.reply_text(f"Покупка #{purchase_id} не найдена")
        return

    if found.get('status') != 'pending':
        await update.message.reply_text(f"Покупка #{purchase_id} уже обработана ({found['status']})")
        return

    # Credit balance
    _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?",
             (found['amount'], found['user_id']))

    # Update purchase status
    found['status'] = 'approved'
    found['approved_at'] = datetime.now(MSK).isoformat()
    found['approved_by'] = update.effective_user.id
    _save_purchases(purchases)

    # Notify user
    try:
        await context.bot.send_message(
            chat_id=found['user_id'],
            text=(
                f"\u2705 <b>Покупка одобрена!</b>\n\n"
                f"\U0001f4b0 +{found['amount']} очков начислено на баланс.\n"
                f"Спасибо за покупку!"
            ),
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Failed to notify user {found['user_id']}: {e}")

    await update.message.reply_text(
        f"\u2705 Покупка #{purchase_id} одобрена!\n"
        f"\U0001f464 {found.get('first_name', '')} (@{found.get('username', '')})\n"
        f"\U0001f4b0 +{found['amount']} очков начислено"
    )


async def reject_cmd(update, context):
    """Отклонить покупку"""
    if update.effective_user.id not in Config.ADMIN_IDS:
        return

    text = update.message.text.replace('/reject', '').strip()
    parts = text.split(None, 1)

    if not parts or not parts[0].isdigit():
        await update.message.reply_text("Формат: /reject ID [причина]")
        return

    purchase_id = int(parts[0])
    reason = parts[1] if len(parts) > 1 else 'Без указания причины'

    purchases = _load_purchases()

    found = None
    for p in purchases:
        if p.get('id') == purchase_id:
            found = p
            break

    if not found:
        await update.message.reply_text(f"Покупка #{purchase_id} не найдена")
        return

    if found.get('status') != 'pending':
        await update.message.reply_text(f"Покупка #{purchase_id} уже обработана ({found['status']})")
        return

    found['status'] = 'rejected'
    found['rejected_at'] = datetime.now(MSK).isoformat()
    found['reject_reason'] = reason
    _save_purchases(purchases)

    # Notify user
    try:
        await context.bot.send_message(
            chat_id=found['user_id'],
            text=(
                f"\u274c <b>Заявка на покупку отклонена</b>\n\n"
                f"Причина: {reason}\n"
                f"Если считаете это ошибкой, напишите @papito007"
            ),
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Failed to notify user {found['user_id']}: {e}")

    await update.message.reply_text(
        f"\u274c Покупка #{purchase_id} отклонена.\n"
        f"Причина: {reason}"
    )


async def purchases_cmd(update, context):
    """Список заявок на покупку"""
    if update.effective_user.id not in Config.ADMIN_IDS:
        return

    purchases = _load_purchases()
    pending = [p for p in purchases if p.get('status') == 'pending']

    if not pending:
        await update.message.reply_text("Нет заявок на покупку")
        return

    lines = []
    for p in pending:
        lines.append(
            f"#{p['id']} — {p.get('first_name', '')} (@{p.get('username', '')})\n"
            f"   {p['amount']} очков = {p.get('total_rub', '')}₽\n"
            f"   /approve {p['id']} | /reject {p['id']}"
        )

    await update.message.reply_text(
        f"\U0001f4cb Заявки на покупку ({len(pending)}):\n\n" + "\n\n".join(lines)
    )





async def purchase_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses for purchase approve/reject"""
    query = update.callback_query
    if not query or not query.from_user:
        return
    if query.from_user.id not in Config.ADMIN_IDS:
        await query.answer("Нет доступа")
        return

    await query.answer()

    data = query.data  # "approve_10001" or "reject_10001"
    parts = data.split("_", 1)
    if len(parts) != 2:
        return

    action = parts[0]
    try:
        purchase_id = int(parts[1])
    except ValueError:
        return

    purchases = _load_purchases()
    found = None
    for p in purchases:
        if p.get('id') == purchase_id:
            found = p
            break

    if not found:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer("Покупка не найдена", show_alert=True)
        return

    if found.get('status') != 'pending':
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer(f"Уже обработана: {found['status']}", show_alert=True)
        return

    old_caption = query.message.caption or query.message.text or ""

    if action == "approve":
        _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?",
                 (found['amount'], found['user_id']))
        found['status'] = 'approved'
        found['approved_at'] = datetime.now(MSK).isoformat()
        found['approved_by'] = query.from_user.id
        _save_purchases(purchases)

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=found['user_id'],
                text=(
                    f"\u2705 <b>Покупка одобрена!</b>\n\n"
                    f"\U0001f4b0 +{found['amount']} очков начислено на баланс.\n"
                    f"Спасибо за покупку!"
                ),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Notify user error: {e}")

        # Update admin message
        try:
            if query.message.caption is not None:
                await query.edit_message_caption(
                    caption=old_caption + "\n\n\u2705 ОДОБРЕНО",
                    parse_mode='HTML',
                    reply_markup=None
                )
            else:
                await query.edit_message_text(
                    text=old_caption + "\n\n\u2705 ОДОБРЕНО",
                    parse_mode='HTML',
                    reply_markup=None
                )
        except Exception:
            pass

    elif action == "reject":
        found['status'] = 'rejected'
        found['rejected_at'] = datetime.now(MSK).isoformat()
        found['reject_reason'] = 'Отклонено админом'
        _save_purchases(purchases)

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=found['user_id'],
                text=(
                    f"\u274c <b>Заявка на покупку отклонена</b>\n\n"
                    f"Если считаете это ошибкой, напишите @papito007"
                ),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Notify user error: {e}")

        # Update admin message
        try:
            if query.message.caption is not None:
                await query.edit_message_caption(
                    caption=old_caption + "\n\n\u274c ОТКЛОНЕНО",
                    parse_mode='HTML',
                    reply_markup=None
                )
            else:
                await query.edit_message_text(
                    text=old_caption + "\n\n\u274c ОТКЛОНЕНО",
                    parse_mode='HTML',
                    reply_markup=None
                )
        except Exception:
            pass


# ============ MAIN ============

def main():
    init_database()

    app = Application.builder().token(Config.TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("settle", settle_cmd))
    app.add_handler(CommandHandler("addbal", addbal_cmd))
    app.add_handler(CommandHandler("fixbets", fixbets_cmd))
    app.add_handler(CommandHandler("setstream", setstream_cmd))
    app.add_handler(CommandHandler("streams", streams_cmd))
    app.add_handler(CommandHandler("delstream", delstream_cmd))
    app.add_handler(CommandHandler("streamoff", streamoff_cmd))
    app.add_handler(CommandHandler("streamon", streamon_cmd))
    app.add_handler(CommandHandler("approve", approve_cmd))
    app.add_handler(CommandHandler("reject", reject_cmd))
    app.add_handler(CommandHandler("purchases", purchases_cmd))
    app.add_handler(CallbackQueryHandler(purchase_callback, pattern="^(approve|reject)_"))

    job_queue = app.job_queue
    job_queue.run_repeating(check_notifications, interval=60, first=10)
    job_queue.run_repeating(auto_settle, interval=300, first=60)

    logger.info("🚀 Bot v5.5 запущен — стримы!")
    logger.info("   - Авторасчёт из Google Sheets")
    logger.info("   - Уведомления за 5ч и 5мин")
    app.run_polling()


if __name__ == '__main__':
    main()
