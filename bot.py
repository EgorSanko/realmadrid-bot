"""
Real Madrid Bot v5.3
- ÐÐ²Ñ‚Ð¾Ñ€Ð°ÑÑ‡Ñ‘Ñ‚ Ð¸Ð· Google Sheets (MatchStats)
- Ð—Ð°ÐºÑ€Ñ‹Ñ‚Ð¸Ðµ ÑÑ‚Ð°Ð²Ð¾Ðº Ð·Ð° 1 Ð¼Ð¸Ð½ÑƒÑ‚Ñƒ Ð´Ð¾ Ð¼Ð°Ñ‚Ñ‡Ð°
- Ð£Ð²ÐµÐ´Ð¾Ð¼Ð»ÐµÐ½Ð¸Ñ Ð·Ð° 5Ñ‡ Ð¸ 5Ð¼Ð¸Ð½
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import gspread
import requests
from google.oauth2.service_account import Credentials

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from config import Config
from database import (
    init_database, get_or_create_user, get_all_users, _execute
)

# ÐœÐ¾ÑÐºÐ¾Ð²ÑÐºÐ¸Ð¹ Ñ‡Ð°ÑÐ¾Ð²Ð¾Ð¹ Ð¿Ð¾ÑÑ UTC+3
MSK = timezone(timedelta(hours=3))

# ÐÐ°ÑÑ‚Ñ€Ð¾Ð¹ÐºÐ° Ð»Ð¾Ð³Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð¸Ñ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Ð­Ð¼Ð¾Ð´Ð·Ð¸
E = {'bell': 'ðŸ””', 'stadium': 'ðŸŸï¸', 'clock': 'ðŸ•', 'tv': 'ðŸ“º', 'goal': 'âš½', 'home': 'ðŸ ', 'away': 'âœˆï¸'}

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
            logger.info("âœ… Google Sheets Ð¿Ð¾Ð´ÐºÐ»ÑŽÑ‡ÐµÐ½")
        except Exception as e:
            logger.error(f"âŒ Sheets auth error: {e}")
    return _sheets_client


def get_upcoming_matches(force_refresh=False) -> List[Dict]:
    """ÐŸÐ¾Ð»ÑƒÑ‡Ð¸Ñ‚ÑŒ Ð¿Ñ€ÐµÐ´ÑÑ‚Ð¾ÑÑ‰Ð¸Ðµ Ð¼Ð°Ñ‚Ñ‡Ð¸ Ð¸Ð· Google Sheets"""
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
        logger.info(f"ðŸ“… Ð—Ð°Ð³Ñ€ÑƒÐ¶ÐµÐ½Ð¾ {len(matches)} Ð¼Ð°Ñ‚Ñ‡ÐµÐ¹")
        return matches
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        return _matches_cache['data'] or []


def get_finished_matches_from_sheets() -> List[Dict]:
    """ÐŸÐ¾Ð»ÑƒÑ‡Ð¸Ñ‚ÑŒ Ð·Ð°Ð²ÐµÑ€ÑˆÑ‘Ð½Ð½Ñ‹Ðµ Ð¼Ð°Ñ‚Ñ‡Ð¸ ÑÐ¾ ÑÑ‚Ð°Ñ‚Ð¸ÑÑ‚Ð¸ÐºÐ¾Ð¹ Ð¸Ð· Google Sheets (MatchStats)"""
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
                    'total_corners': int(row.get('totalCorners', 0) or 0),
                    'total_yellow': int(row.get('totalYellowCards', 0) or 0),
                    'total_red': int(row.get('totalRedCards', 0) or 0),
                    'both_scored': row.get('bothScored', 'no') == 'yes',
                    'outcome': row.get('outcome', 'draw'),
                    'has_penalty': row.get('hasPenalty', 'no') == 'yes',
                })
        
        _results_cache = {'data': matches, 'time': datetime.now()}
        logger.info(f"ðŸ“Š Ð—Ð°Ð³Ñ€ÑƒÐ¶ÐµÐ½Ð¾ {len(matches)} Ð·Ð°Ð²ÐµÑ€ÑˆÑ‘Ð½Ð½Ñ‹Ñ… Ð¼Ð°Ñ‚Ñ‡ÐµÐ¹ Ð¸Ð· MatchStats")
        return matches
    except Exception as e:
        logger.error(f"MatchStats error: {e}")
        return _results_cache['data'] or []


def _match_data_complete(match: dict) -> bool:
    """ÐŸÑ€Ð¾Ð²ÐµÑ€ÑÐµÐ¼ Ð¿Ð¾Ð»Ð½Ð¾Ñ‚Ñƒ Ð´Ð°Ð½Ð½Ñ‹Ñ… (Sheets Ð¾Ð±Ð½Ð¾Ð²Ð»ÑÐµÑ‚ÑÑ Ñ€Ð°Ð· Ð² Ñ‡Ð°Ñ)"""
    expected_goals = match.get('home_score', 0) + match.get('away_score', 0)
    actual_goals = match.get('total_goals', 0)
    if actual_goals != expected_goals and expected_goals > 0:
        return False
    if match.get('total_goals', 0) > 0 and match.get('total_corners', 0) == 0:
        return False
    if match.get('total_corners', 0) < 2:
        return False
    return True



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


# ============ Ð ÐÐ¡Ð§ÐÐ¢ Ð¡Ð¢ÐÐ’ÐžÐš ============

def check_bet_won(bet_type: str, stats: dict) -> bool:
    """ÐŸÑ€Ð¾Ð²ÐµÑ€Ð¸Ñ‚ÑŒ Ð²Ñ‹Ð¸Ð³Ñ€Ð°Ð»Ð° Ð»Ð¸ ÑÑ‚Ð°Ð²ÐºÐ°"""
    outcome = stats.get('outcome', 'draw')
    home_score = stats.get('home_score', 0)
    away_score = stats.get('away_score', 0)
    total = stats.get('total_goals', 0)
    
    # Ð£Ð±Ð¸Ñ€Ð°ÐµÐ¼ Ð¿Ñ€ÐµÑ„Ð¸ÐºÑ LIVE_ ÐµÑÐ»Ð¸ ÐµÑÑ‚ÑŒ
    if bet_type.startswith('LIVE_'):
        bet_type = bet_type.replace('LIVE_', '')
    
    # Ð˜ÑÑ…Ð¾Ð´ Ð¼Ð°Ñ‚Ñ‡Ð°
    if bet_type in ['home', 'draw', 'away']:
        return bet_type == outcome
    
    # Ð¢Ð¾Ñ‡Ð½Ñ‹Ð¹ ÑÑ‡Ñ‘Ñ‚
    if bet_type.startswith('score_'):
        score = bet_type.replace('score_', '')
        return score == f"{home_score}-{away_score}"
    
    # Ð¢Ð¾Ñ‚Ð°Ð»Ñ‹ Ð³Ð¾Ð»Ð¾Ð²
    if bet_type.startswith('total_over_'):
        line = float(bet_type.replace('total_over_', ''))
        return total > line
    if bet_type.startswith('total_under_'):
        line = float(bet_type.replace('total_under_', ''))
        return total < line
    
    # ÐžÐ±Ðµ Ð·Ð°Ð±ÑŒÑŽÑ‚
    if bet_type == 'btts_yes':
        return stats.get('both_scored', False)
    if bet_type == 'btts_no':
        return not stats.get('both_scored', False)
    
    # Ð£Ð³Ð»Ð¾Ð²Ñ‹Ðµ
    corners = stats.get('total_corners', 0)
    if bet_type.startswith('corners_over_'):
        line = float(bet_type.replace('corners_over_', ''))
        return corners > line
    if bet_type.startswith('corners_under_'):
        line = float(bet_type.replace('corners_under_', ''))
        return corners < line
    
    # ÐšÐ°Ñ€Ñ‚Ð¾Ñ‡ÐºÐ¸
    cards = stats.get('total_yellow', 0)
    if bet_type.startswith('cards_over_'):
        line = float(bet_type.replace('cards_over_', ''))
        return cards > line
    if bet_type.startswith('cards_under_'):
        line = float(bet_type.replace('cards_under_', ''))
        return cards < line
    
    # Ð˜Ð½Ð´Ð¸Ð²Ð¸Ð´ÑƒÐ°Ð»ÑŒÐ½Ñ‹Ð¹ Ñ‚Ð¾Ñ‚Ð°Ð» Ñ…Ð¾Ð·ÑÐµÐ²
    if bet_type.startswith('home_over_'):
        line = float(bet_type.replace('home_over_', ''))
        return home_score > line
    if bet_type.startswith('home_under_'):
        line = float(bet_type.replace('home_under_', ''))
        return home_score < line
    
    # Ð˜Ð½Ð´Ð¸Ð²Ð¸Ð´ÑƒÐ°Ð»ÑŒÐ½Ñ‹Ð¹ Ñ‚Ð¾Ñ‚Ð°Ð» Ð³Ð¾ÑÑ‚ÐµÐ¹
    if bet_type.startswith('away_over_'):
        line = float(bet_type.replace('away_over_', ''))
        return away_score > line
    if bet_type.startswith('away_under_'):
        line = float(bet_type.replace('away_under_', ''))
        return away_score < line
    
    # ÐŸÐµÐ½Ð°Ð»ÑŒÑ‚Ð¸
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
    if bet_type == 'first_goal_home':
        return first_goal == 'home'
    if bet_type == 'first_goal_away':
        return first_goal == 'away'
    if bet_type == 'first_goal_none':
        return first_goal == 'none' or (home_score == 0 and away_score == 0)
    
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
    """Ð—Ð°Ð¿Ð¸ÑÐ°Ñ‚ÑŒ Ñ‚Ñ€Ð°Ð½Ð·Ð°ÐºÑ†Ð¸ÑŽ Ð² Ð¸ÑÑ‚Ð¾Ñ€Ð¸ÑŽ"""
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
    """Ð Ð°ÑÑÑ‡Ð¸Ñ‚Ð°Ñ‚ÑŒ Ð²ÑÐµ ÑÑ‚Ð°Ð²ÐºÐ¸ Ð½Ð° Ð¼Ð°Ñ‚Ñ‡"""
    result = {
        'bets_settled': 0, 'bets_won': 0, 'bets_lost': 0,
        'predictions_settled': 0, 'predictions_correct': 0
    }
    
    # ÐŸÐ¾Ð»ÑƒÑ‡Ð°ÐµÐ¼ pending ÑÑ‚Ð°Ð²ÐºÐ¸
    bets = _execute(
        "SELECT bet_id, user_id, bet_type, amount, odds FROM bets WHERE match_id = ? AND status = 'pending'",
        (str(match_id),)
    ) or []
    
    for bet in bets:
        won = check_bet_won(bet['bet_type'], stats)
        
        if won:
            winnings = int(bet['amount'] * bet['odds'])
            # Ð¡Ð½Ð°Ñ‡Ð°Ð»Ð° Ð¿Ð¾Ð»ÑƒÑ‡Ð°ÐµÐ¼ Ñ‚ÐµÐºÑƒÑ‰Ð¸Ð¹ Ð±Ð°Ð»Ð°Ð½Ñ
            user = _execute("SELECT balance FROM users WHERE user_id = ?", (bet['user_id'],))
            balance_before = user[0]['balance'] if user else 0
            balance_after = balance_before + winnings
            # ÐžÐ±Ð½Ð¾Ð²Ð»ÑÐµÐ¼ Ð±Ð°Ð»Ð°Ð½Ñ
            _execute("UPDATE bets SET status = 'won', payout = ? WHERE bet_id = ?", (winnings, bet['bet_id']))
            _execute("UPDATE users SET balance = ?, bets_won = bets_won + 1 WHERE user_id = ?", (balance_after, bet['user_id']))
            # Ð—Ð°Ð¿Ð¸ÑÑ‹Ð²Ð°ÐµÐ¼ Ñ‚Ñ€Ð°Ð½Ð·Ð°ÐºÑ†Ð¸ÑŽ Ñ Ð¿Ñ€Ð°Ð²Ð¸Ð»ÑŒÐ½Ñ‹Ð¼Ð¸ Ð·Ð½Ð°Ñ‡ÐµÐ½Ð¸ÑÐ¼Ð¸
            _execute(
                """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                   VALUES (?, 'bet_win', ?, ?, ?, ?, ?)""",
                (bet['user_id'], winnings, balance_before, balance_after, f"Ð’Ñ‹Ð¸Ð³Ñ€Ñ‹Ñˆ ÑÑ‚Ð°Ð²ÐºÐ¸ #{bet['bet_id']}", str(bet['bet_id']))
            )
            result['bets_won'] += 1
        else:
            # Ð”Ð»Ñ Ð¿Ñ€Ð¾Ð¸Ð³Ñ€Ñ‹ÑˆÐ° Ð±Ð°Ð»Ð°Ð½Ñ Ð½Ðµ Ð¼ÐµÐ½ÑÐµÑ‚ÑÑ
            user = _execute("SELECT balance FROM users WHERE user_id = ?", (bet['user_id'],))
            balance = user[0]['balance'] if user else 0
            _execute("UPDATE bets SET status = 'lost' WHERE bet_id = ?", (bet['bet_id'],))
            _execute("UPDATE users SET bets_lost = bets_lost + 1 WHERE user_id = ?", (bet['user_id'],))
            _execute(
                """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                   VALUES (?, 'bet_lose', 0, ?, ?, ?, ?)""",
                (bet['user_id'], balance, balance, f"ÐŸÑ€Ð¾Ð¸Ð³Ñ€Ñ‹Ñˆ ÑÑ‚Ð°Ð²ÐºÐ¸ #{bet['bet_id']}", str(bet['bet_id']))
            )
            result['bets_lost'] += 1
        
        result['bets_settled'] += 1
    
    # ÐŸÑ€Ð¾Ð³Ð½Ð¾Ð·Ñ‹
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
                (pred['user_id'], balance_before, balance_after, f"ÐŸÑ€Ð°Ð²Ð¸Ð»ÑŒÐ½Ñ‹Ð¹ Ð¿Ñ€Ð¾Ð³Ð½Ð¾Ð· #{pred['prediction_id']}", str(pred['prediction_id']))
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
                (pred['user_id'], balance_before, balance_after, f"ÐÐµÐ¿Ñ€Ð°Ð²Ð¸Ð»ÑŒÐ½Ñ‹Ð¹ Ð¿Ñ€Ð¾Ð³Ð½Ð¾Ð· #{pred['prediction_id']}", str(pred['prediction_id']))
            )
        
        result['predictions_settled'] += 1
    
    return result


# ============ ÐšÐžÐœÐÐÐ”Ð« ============

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # ÐŸÑ€Ð¾Ð²ÐµÑ€ÑÐµÐ¼ ÐµÑÑ‚ÑŒ Ð»Ð¸ Ñ€ÐµÑ„ÐµÑ€Ð°Ð»ÑŒÐ½Ñ‹Ð¹ ÐºÐ¾Ð´
    ref_code = None
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith('ref'):
            ref_code = arg
    
    # ÐŸÑ€Ð¾Ð²ÐµÑ€ÑÐµÐ¼ ÑÑƒÑ‰ÐµÑÑ‚Ð²ÑƒÐµÑ‚ Ð»Ð¸ Ð¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÐµÐ»ÑŒ
    existing_user = _execute("SELECT user_id, referred_by FROM users WHERE user_id = ?", (user.id,))
    is_new_user = not existing_user
    
    # Ð¡Ð¾Ð·Ð´Ð°Ñ‘Ð¼/Ð¿Ð¾Ð»ÑƒÑ‡Ð°ÐµÐ¼ Ð¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÐµÐ»Ñ
    get_or_create_user(user.id, user.username, user.first_name)
    
    # ÐžÐ±Ñ€Ð°Ð±Ð°Ñ‚Ñ‹Ð²Ð°ÐµÐ¼ Ñ€ÐµÑ„ÐµÑ€Ð°Ð»ÑŒÐ½Ñ‹Ð¹ ÐºÐ¾Ð´ Ð´Ð»Ñ Ð½Ð¾Ð²Ñ‹Ñ… Ð¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÐµÐ»ÐµÐ¹
    ref_bonus_msg = ""
    if ref_code:
        try:
            referrer_id = int(ref_code.replace('ref', ''))
            
            # ÐŸÑ€Ð¾Ð²ÐµÑ€ÑÐµÐ¼ Ñ‡Ñ‚Ð¾ Ñ€ÐµÑ„ÐµÑ€ÐµÑ€ ÑÑƒÑ‰ÐµÑÑ‚Ð²ÑƒÐµÑ‚ Ð¸ ÑÑ‚Ð¾ Ð½Ðµ ÑÐ°Ð¼ Ð¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÐµÐ»ÑŒ
            if referrer_id != user.id:
                referrer = _execute("SELECT user_id, balance FROM users WHERE user_id = ?", (referrer_id,))
                if referrer:
                    # ÐŸÑ€Ð¾Ð²ÐµÑ€ÑÐµÐ¼ Ñ‡Ñ‚Ð¾ Ð¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÐµÐ»ÑŒ ÐµÑ‰Ñ‘ Ð½Ðµ Ð¸Ð¼ÐµÐµÑ‚ Ñ€ÐµÑ„ÐµÑ€ÐµÑ€Ð°
                    current = _execute("SELECT referred_by FROM users WHERE user_id = ?", (user.id,))
                    if current and not current[0].get('referred_by'):
                        bonus = 25
                        
                        # Ð—Ð°Ð¿Ð¸ÑÑ‹Ð²Ð°ÐµÐ¼ Ñ€ÐµÑ„ÐµÑ€ÐµÑ€Ð°
                        _execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user.id))
                        
                        # Ð‘Ð¾Ð½ÑƒÑ Ñ€ÐµÑ„ÐµÑ€ÐµÑ€Ñƒ
                        _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, referrer_id))
                        _execute(
                            """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                               VALUES (?, 'referral_bonus', ?, ?, ?, ?, ?)""",
                            (referrer_id, bonus, referrer[0]['balance'], referrer[0]['balance'] + bonus, 
                             f"Ð‘Ð¾Ð½ÑƒÑ Ð·Ð° Ð¿Ñ€Ð¸Ð³Ð»Ð°ÑˆÐµÐ½Ð¸Ðµ Ð´Ñ€ÑƒÐ³Ð° @{user.username or user.first_name}", str(user.id))
                        )
                        
                        # Ð‘Ð¾Ð½ÑƒÑ Ð½Ð¾Ð²Ð¾Ð¼Ñƒ Ð¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÐµÐ»ÑŽ
                        user_data = _execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
                        user_balance = user_data[0]['balance'] if user_data else 0
                        
                        _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, user.id))
                        _execute(
                            """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                               VALUES (?, 'referral_bonus', ?, ?, ?, ?, ?)""",
                            (user.id, bonus, user_balance, user_balance + bonus,
                             f"Ð‘Ð¾Ð½ÑƒÑ Ð·Ð° Ñ€ÐµÐ³Ð¸ÑÑ‚Ñ€Ð°Ñ†Ð¸ÑŽ Ð¿Ð¾ Ð¿Ñ€Ð¸Ð³Ð»Ð°ÑˆÐµÐ½Ð¸ÑŽ", str(referrer_id))
                        )
                        
                        ref_bonus_msg = f"\n\nðŸŽ <b>+{bonus} Ð¾Ñ‡ÐºÐ¾Ð²</b> Ð·Ð° Ñ€ÐµÐ³Ð¸ÑÑ‚Ñ€Ð°Ñ†Ð¸ÑŽ Ð¿Ð¾ Ð¿Ñ€Ð¸Ð³Ð»Ð°ÑˆÐµÐ½Ð¸ÑŽ!"
                        logger.info(f"Referral bonus: {user.id} invited by {referrer_id}, +{bonus} each")
        except Exception as e:
            logger.error(f"Referral error: {e}")
    
    keyboard = [[InlineKeyboardButton("âš½ ÐžÑ‚ÐºÑ€Ñ‹Ñ‚ÑŒ Ð¿Ñ€Ð¸Ð»Ð¾Ð¶ÐµÐ½Ð¸Ðµ", web_app={"url": Config.WEBAPP_URL})]]
    
    await update.message.reply_text(
        f"ðŸ‘‹ ÐŸÑ€Ð¸Ð²ÐµÑ‚, <b>{user.first_name}</b>!\n\n"
        f"Ð”Ð¾Ð±Ñ€Ð¾ Ð¿Ð¾Ð¶Ð°Ð»Ð¾Ð²Ð°Ñ‚ÑŒ Ð² <b>Real Madrid Fan Bot</b>!\n\n"
        f"ðŸŽ° Ð”ÐµÐ»Ð°Ð¹ ÑÑ‚Ð°Ð²ÐºÐ¸ â€¢ ðŸŽ¯ ÐŸÑ€Ð¾Ð³Ð½Ð¾Ð·Ñ‹ â€¢ ðŸ† Ð ÐµÐ¹Ñ‚Ð¸Ð½Ð³ â€¢ ðŸŽ ÐŸÑ€Ð¸Ð·Ñ‹{ref_bonus_msg}\n\n"
        f"ÐÐ°Ð¶Ð¼Ð¸ ÐºÐ½Ð¾Ð¿ÐºÑƒ ðŸ‘‡",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.ADMIN_IDS:
        return
    
    users = get_all_users(limit=10000)
    pending = _execute("SELECT COUNT(*) as cnt FROM bets WHERE status = 'pending'") or [{'cnt': 0}]
    
    await update.message.reply_text(
        f"ðŸ‘‘ <b>ÐÐ´Ð¼Ð¸Ð½</b>\n\n"
        f"ðŸ‘¥ {len(users)} ÑŽÐ·ÐµÑ€Ð¾Ð²\n"
        f"ðŸ’° {sum(u.get('balance', 0) for u in users)} Ð¾Ñ‡ÐºÐ¾Ð²\n"
        f"â³ {pending[0]['cnt']} pending ÑÑ‚Ð°Ð²Ð¾Ðº\n\n"
        f"/settle - Ñ€Ð°ÑÑ‡Ñ‘Ñ‚\n"
        f"/addbal @user 100 - Ð±Ð°Ð»Ð°Ð½Ñ",
        parse_mode=ParseMode.HTML
    )


async def settle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ð ÑƒÑ‡Ð½Ð¾Ð¹ Ñ€Ð°ÑÑ‡Ñ‘Ñ‚ ÑÑ‚Ð°Ð²Ð¾Ðº"""
    global _results_cache
    
    if update.effective_user.id not in Config.ADMIN_IDS:
        return
    
    await update.message.reply_text("â³ Ð Ð°ÑÑ‡Ñ‘Ñ‚ Ð¸Ð· Google Sheets...")
    
    # Ð¡Ð±Ñ€Ð°ÑÑ‹Ð²Ð°ÐµÐ¼ ÐºÑÑˆ Ñ‡Ñ‚Ð¾Ð±Ñ‹ Ð¿Ð¾Ð»ÑƒÑ‡Ð¸Ñ‚ÑŒ ÑÐ²ÐµÐ¶Ð¸Ðµ Ð´Ð°Ð½Ð½Ñ‹Ðµ
    _results_cache = {'data': [], 'time': None}
    
    matches = get_finished_matches_from_sheets()
    settled_any = False
    
    for match in matches:
        mid = match['matchId']
        
        # Ð˜Ñ‰ÐµÐ¼ orphan ÑÑ‚Ð°Ð²ÐºÐ¸ Ð³Ð´Ðµ ÑÐ¾Ð²Ð¿Ð°Ð´Ð°ÑŽÑ‚ ÐžÐ‘Ð• ÐºÐ¾Ð¼Ð°Ð½Ð´Ñ‹
        home = match.get('homeTeam', '')
        away = match.get('awayTeam', '')
        if home and away:
            try:
                orphan_bets = _execute(
                    """SELECT DISTINCT match_id FROM bets 
                       WHERE status = 'pending' AND match_id != ?
                       AND ((home_team LIKE ? AND away_team LIKE ?)
                         OR (home_team LIKE ? AND away_team LIKE ?))""",
                    (str(mid), f'%{home}%', f'%{away}%', f'%{away}%', f'%{home}%')
                )
                if orphan_bets:
                    for ob in orphan_bets:
                        _execute("UPDATE bets SET match_id = ? WHERE match_id = ? AND status = 'pending'", (str(mid), str(ob['match_id'])))
                        _execute("UPDATE predictions SET match_id = ? WHERE match_id = ? AND status = 'pending'", (str(mid), str(ob['match_id'])))
            except Exception:
                pass
        
        # ÐŸÑ€Ð¾Ð²ÐµÑ€ÑÐµÐ¼ Ð¿Ð¾Ð»Ð½Ð¾Ñ‚Ñƒ Ð´Ð°Ð½Ð½Ñ‹Ñ…
        if not _match_data_complete(match):
            await update.message.reply_text(
                f"\u26a0\ufe0f <b>{match['homeTeam']} vs {match['awayTeam']}</b>\n"
                f"Ð”Ð°Ð½Ð½Ñ‹Ðµ Ð½ÐµÐ¿Ð¾Ð»Ð½Ñ‹Ðµ (\U0001f6a9{match.get('total_corners',0)} \U0001f7e8{match.get('total_yellow',0)}) - Ð¿Ñ€Ð¾Ð¿ÑƒÑÐº.\n"
                f"Ð”Ð¾Ð¶Ð´Ð¸ÑÑŒ Ð¾Ð±Ð½Ð¾Ð²Ð»ÐµÐ½Ð¸Ñ Sheets Ð¸ /settle",
                parse_mode=ParseMode.HTML
            )
            continue
        
        stats = {
            'home_score': match['home_score'],
            'away_score': match['away_score'],
            'total_goals': match['total_goals'],
            'total_corners': match['total_corners'],
            'total_yellow': match['total_yellow'],
            'both_scored': match['both_scored'],
            'outcome': match['outcome'],
            'has_penalty': match.get('has_penalty', False),
        }
        
        st = settle_all_bets(mid, stats)
        
        if st['bets_settled'] > 0 or st['predictions_settled'] > 0:
            settled_any = True
            await update.message.reply_text(
                f"âœ… <b>{match['homeTeam']} vs {match['awayTeam']}</b>\n"
                f"{home_score}:{away_score} | ðŸš©{stats['total_corners']} | ðŸŸ¨{stats['total_yellow']}\n"
                f"ðŸŽ° {st['bets_settled']} (âœ…{st['bets_won']} âŒ{st['bets_lost']})",
                parse_mode=ParseMode.HTML
            )
    
    if not settled_any:
        await update.message.reply_text("â„¹ï¸ ÐÐµÑ‚ ÑÑ‚Ð°Ð²Ð¾Ðº Ð´Ð»Ñ Ñ€Ð°ÑÑ‡Ñ‘Ñ‚Ð°")


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
        await update.message.reply_text(f"âŒ @{username} Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½")
        return
    
    new_bal = result[0]['balance'] + amount
    _execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_bal, result[0]['user_id']))
    await update.message.reply_text(f"âœ… @{username}: {result[0]['balance']} â†’ {new_bal}")




async def fixbets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ÐŸÐ¾Ð¸ÑÐº Ð¸ Ñ„Ð¸ÐºÑ orphan ÑÑ‚Ð°Ð²Ð¾Ðº"""
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
            await update.message.reply_text(f"\u2705 {cnt} ÑÑ‚Ð°Ð²Ð¾Ðº: {old_id} \u2192 {new_id}\nÐ¢ÐµÐ¿ÐµÑ€ÑŒ /settle")
        else:
            await update.message.reply_text(f"\u274c ÐÐµÑ‚ pending ÑÑ‚Ð°Ð²Ð¾Ðº Ñ match_id={old_id}")
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
        await update.message.reply_text("\u2705 ÐÐµÑ‚ pending ÑÑ‚Ð°Ð²Ð¾Ðº")
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
        text += "<b>Finished Ð² Sheets:</b>\n"
        for m in finished[-5:]:
            text += f"<code>{m['matchId']}</code> {m['homeTeam']} {m.get('home_score',0)}:{m.get('away_score',0)} {m['awayTeam']}\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ============ Ð£Ð’Ð•Ð”ÐžÐœÐ›Ð•ÐÐ˜Ð¯ ============

_notified_5h = set()
_notified_5m = set()


async def check_notifications(context: ContextTypes.DEFAULT_TYPE):
    """ÐŸÑ€Ð¾Ð²ÐµÑ€ÐºÐ° ÑƒÐ²ÐµÐ´Ð¾Ð¼Ð»ÐµÐ½Ð¸Ð¹"""
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
            loc = "Ð´Ð¾Ð¼Ð°" if is_home else "Ð² Ð³Ð¾ÑÑ‚ÑÑ…"
            
            # 5 Ñ‡Ð°ÑÐ¾Ð²
            if 290 <= diff <= 310 and key not in _notified_5h:
                _notified_5h.add(key)
                text = f"{E['bell']} <b>ÐœÐ°Ñ‚Ñ‡ Ñ‡ÐµÑ€ÐµÐ· 5 Ñ‡Ð°ÑÐ¾Ð²!</b>\n\n{E['stadium']} <b>{home}</b> vs <b>{away}</b>\n{E['clock']} {m['date']} {m['time']}\n{icon} Real Madrid {loc}\n\n{E['goal']} Ð¡Ð´ÐµÐ»Ð°Ð¹ ÑÑ‚Ð°Ð²ÐºÑƒ!"
                for u in get_all_users(limit=10000):
                    if u.get('notifications_enabled', 1):
                        try:
                            await context.bot.send_message(u['user_id'], text, parse_mode=ParseMode.HTML)
                        except:
                            pass
            
            # 5 Ð¼Ð¸Ð½ÑƒÑ‚
            if 4 <= diff <= 6 and key not in _notified_5m:
                _notified_5m.add(key)
                stream_url = get_liveball_url()
                text = f"{E['bell']} <b>ÐœÐ°Ñ‚Ñ‡ Ñ‡ÐµÑ€ÐµÐ· 5 Ð¼Ð¸Ð½ÑƒÑ‚!</b>\n\n{E['stadium']} <b>{home}</b> vs <b>{away}</b>\n\n{E['tv']} <a href=\"{stream_url}\">Ð¡Ð¼Ð¾Ñ‚Ñ€ÐµÑ‚ÑŒ</a>\n\nâ° ÐŸÐ¾ÑÐ»ÐµÐ´Ð½Ð¸Ð¹ ÑˆÐ°Ð½Ñ ÑÐ´ÐµÐ»Ð°Ñ‚ÑŒ ÑÑ‚Ð°Ð²ÐºÑƒ!"
                for u in get_all_users(limit=10000):
                    if u.get('notifications_enabled', 1):
                        try:
                            await context.bot.send_message(u['user_id'], text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                        except:
                            pass
    except Exception as e:
        logger.error(f"Notif error: {e}")


# ============ ÐÐ’Ð¢Ðž-Ð ÐÐ¡Ð§ÐÐ¢ ============

_settled = set()


async def auto_settle(context: ContextTypes.DEFAULT_TYPE):
    """ÐÐ²Ñ‚Ð¾Ð¼Ð°Ñ‚Ð¸Ñ‡ÐµÑÐºÐ¸Ð¹ Ñ€Ð°ÑÑ‡Ñ‘Ñ‚ Ð¸Ð· Google Sheets"""
    global _settled
    
    try:
        matches = get_finished_matches_from_sheets()
        logger.info(f"ðŸ” ÐÐ²Ñ‚Ð¾Ñ€Ð°ÑÑ‡Ñ‘Ñ‚: {len(matches)} Ð·Ð°Ð²ÐµÑ€ÑˆÑ‘Ð½Ð½Ñ‹Ñ… Ð¼Ð°Ñ‚Ñ‡ÐµÐ¹ Ð² MatchStats")
        
        for match in matches:
            mid = match['matchId']
            
            if mid in _settled:
                continue
            
            # ÐŸÑ€Ð¾Ð²ÐµÑ€ÑÐµÐ¼ ÐµÑÑ‚ÑŒ Ð»Ð¸ pending ÑÑ‚Ð°Ð²ÐºÐ¸ Ð½Ð° ÑÑ‚Ð¾Ñ‚ Ð¼Ð°Ñ‚Ñ‡
            pending = _execute(
                "SELECT COUNT(*) as cnt FROM bets WHERE match_id = ? AND status = 'pending'",
                (str(mid),)
            )
            
            pending_count = pending[0]['cnt'] if pending else 0
            
            # Ð˜Ñ‰ÐµÐ¼ orphan ÑÑ‚Ð°Ð²ÐºÐ¸ (ÐžÐ‘Ð• ÐºÐ¾Ð¼Ð°Ð½Ð´Ñ‹ Ð´Ð¾Ð»Ð¶Ð½Ñ‹ ÑÐ¾Ð²Ð¿Ð°ÑÑ‚ÑŒ)
            if pending_count == 0:
                home = match.get('homeTeam', '')
                away = match.get('awayTeam', '')
                if home and away:
                    try:
                        orphan_bets = _execute(
                            """SELECT DISTINCT match_id FROM bets 
                               WHERE status = 'pending' AND match_id != ?
                               AND ((home_team LIKE ? AND away_team LIKE ?)
                                 OR (home_team LIKE ? AND away_team LIKE ?))""",
                            (str(mid), f'%{home}%', f'%{away}%', f'%{away}%', f'%{home}%')
                        )
                        if orphan_bets:
                            for ob in orphan_bets:
                                _execute("UPDATE bets SET match_id = ? WHERE match_id = ? AND status = 'pending'", (str(mid), str(ob['match_id'])))
                            pending = _execute("SELECT COUNT(*) as cnt FROM bets WHERE match_id = ? AND status = 'pending'", (str(mid),))
                            pending_count = pending[0]['cnt'] if pending else 0
                    except Exception:
                        pass
            
            if pending_count == 0:
                _settled.add(mid)
                continue
            
            # ÐŸÑ€Ð¾Ð²ÐµÑ€ÑÐµÐ¼ Ð¿Ð¾Ð»Ð½Ð¾Ñ‚Ñƒ Ð´Ð°Ð½Ð½Ñ‹Ñ…
            if not _match_data_complete(match):
                logger.warning(f"  Ð”Ð°Ð½Ð½Ñ‹Ðµ Ð½ÐµÐ¿Ð¾Ð»Ð½Ñ‹Ðµ: {match['homeTeam']} vs {match['awayTeam']} corners={match.get('total_corners',0)}")
                continue
            
            stats = {
                'home_score': match['home_score'],
                'away_score': match['away_score'],
                'total_goals': match['total_goals'],
                'total_corners': match['total_corners'],
                'total_yellow': match['total_yellow'],
                'both_scored': match['both_scored'],
                'outcome': match['outcome'],
                'has_penalty': match.get('has_penalty', False),
            }
            
            logger.info(f"  ðŸ“Œ Ð Ð°ÑÑ‡Ñ‘Ñ‚: {match['homeTeam']} {home_score}:{away_score} {match['awayTeam']}")
            
            st = settle_all_bets(mid, stats)
            
            if st['bets_settled'] > 0 or st['predictions_settled'] > 0:
                _settled.add(mid)
                
                # Ð”ÐµÑ‚Ð°Ð»Ð¸ ÑÑ‚Ð°Ð²Ð¾Ðº Ð´Ð»Ñ Ð°Ð´Ð¼Ð¸Ð½Ð°
                settled_bets = _execute("""
                    SELECT b.user_id, b.bet_type, b.amount, b.odds, b.status, b.payout, u.username, u.first_name
                    FROM bets b
                    LEFT JOIN users u ON b.user_id = u.user_id
                    WHERE b.match_id = ? AND b.status IN ('won', 'lost')
                    ORDER BY b.created_at DESC
                """, (str(mid),)) or []
                
                bets_detail = ""
                if settled_bets:
                    bets_detail = "\n\nðŸ“‹ <b>Ð¡Ñ‚Ð°Ð²ÐºÐ¸:</b>\n"
                    for bet in settled_bets[:15]:
                        name = bet.get('username') or bet.get('first_name') or str(bet.get('user_id'))
                        icon = "âœ…" if bet['status'] == 'won' else "âŒ"
                        result = f"+{bet['payout']}" if bet['status'] == 'won' else f"-{bet['amount']}"
                        bets_detail += f"{icon} @{name}: {bet['bet_type']} ({bet['amount']}ðŸ’°) â†’ {result}\n"
                
                # Ð£Ð²ÐµÐ´Ð¾Ð¼Ð»ÐµÐ½Ð¸Ðµ Ð°Ð´Ð¼Ð¸Ð½Ñƒ
                for admin_id in Config.ADMIN_IDS:
                    try:
                        await context.bot.send_message(
                            admin_id,
                            f"âœ… <b>ÐÐ²Ñ‚Ð¾-Ñ€Ð°ÑÑ‡Ñ‘Ñ‚</b>\n\n"
                            f"âš½ {match['homeTeam']} {home_score}:{away_score} {match['awayTeam']}\n"
                            f"ðŸš© Ð£Ð³Ð»Ð¾Ð²Ñ‹Ðµ: {stats['total_corners']} | ðŸŸ¨ ÐšÐ°Ñ€Ñ‚Ð¾Ñ‡ÐºÐ¸: {stats['total_yellow']}\n"
                            f"âš½ ÐžÐ±Ðµ Ð·Ð°Ð±Ð¸Ð»Ð¸: {'Ð”Ð°' if stats['both_scored'] else 'ÐÐµÑ‚'} | âš ï¸ ÐŸÐµÐ½Ð°Ð»ÑŒÑ‚Ð¸: {'Ð”Ð°' if stats.get('has_penalty') else 'ÐÐµÑ‚'}\n\n"
                            f"ðŸ“Š <b>Ð˜Ñ‚Ð¾Ð³Ð¾:</b> {st['bets_settled']} ÑÑ‚Ð°Ð²Ð¾Ðº\n"
                            f"âœ… Ð’Ñ‹Ð¸Ð³Ñ€Ð°Ð»Ð¸: {st['bets_won']} | âŒ ÐŸÑ€Ð¾Ð¸Ð³Ñ€Ð°Ð»Ð¸: {st['bets_lost']}"
                            f"{bets_detail}",
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"ÐžÑˆÐ¸Ð±ÐºÐ° Ð¾Ñ‚Ð¿Ñ€Ð°Ð²ÐºÐ¸ Ð°Ð´Ð¼Ð¸Ð½Ñƒ: {e}")
            else:
                _settled.add(mid)
                
    except Exception as e:
        logger.error(f"Auto-settle error: {e}")


# ============ MAIN ============

def main():
    init_database()
    
    app = Application.builder().token(Config.TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("settle", settle_cmd))
    app.add_handler(CommandHandler("addbal", addbal_cmd))
    app.add_handler(CommandHandler("fixbets", fixbets_cmd))
    
    job_queue = app.job_queue
    job_queue.run_repeating(check_notifications, interval=60, first=10)
    job_queue.run_repeating(auto_settle, interval=300, first=60)
    
    logger.info("ðŸš€ Bot v5.3 Ð·Ð°Ð¿ÑƒÑ‰ÐµÐ½!")
    logger.info("   - ÐÐ²Ñ‚Ð¾Ñ€Ð°ÑÑ‡Ñ‘Ñ‚ Ð¸Ð· Google Sheets")
    logger.info("   - Ð£Ð²ÐµÐ´Ð¾Ð¼Ð»ÐµÐ½Ð¸Ñ Ð·Ð° 5Ñ‡ Ð¸ 5Ð¼Ð¸Ð½")
    app.run_polling()


if __name__ == '__main__':
    main()
