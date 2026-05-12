"""src/services/settlement.py — Auto-settle engine.

Resolves pending bets/predictions after a match finishes:
1. Watches `_settled_matches` set
2. For each new finished match: fetch FotMob/SofaScore stats
3. Resolve each pending bet by type (1X2, totals, BTTS, score, corners, cards, etc.)
4. Update DB + notify user via TG + notify admins with summary

Async loop: `auto_settle_task()` runs every 60s via lifespan.

Lazy-imports from api.py to avoid circular import with bot integrations.
"""
import asyncio
import requests
import time as _time
import os
import sys
from datetime import datetime
from typing import Dict, List

# Helper for bot notifications (BOT_TOKEN from env or api.py)
BOT_TOKEN = os.getenv('TELEGRAM_TOKEN', '')



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
        'home_yellow_cards': 0,
        'away_yellow_cards': 0,
        'total_red_cards': 0,
        'home_red_cards': 0,
        'away_red_cards': 0,
        'total_cards': 0,
        'home_cards': 0,
        'away_cards': 0,
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
                            stats['home_yellow_cards'] = home_val
                            stats['away_yellow_cards'] = away_val
                            stats['total_yellow_cards'] = home_val + away_val

                        if name == 'Red cards':
                            stats['home_red_cards'] = home_val
                            stats['away_red_cards'] = away_val
                            stats['total_red_cards'] = home_val + away_val

        # Derived: combined yellow+red per side and total
        stats['home_cards'] = stats['home_yellow_cards'] + stats['home_red_cards']
        stats['away_cards'] = stats['away_yellow_cards'] + stats['away_red_cards']
        stats['total_cards'] = stats['home_cards'] + stats['away_cards']

    except Exception as e:
        print(f"Error fetching match stats: {e}")

    return stats


def _ou_check(total, line: float, over: bool):
    """Стандартная проверка over/under. На целой линии при равенстве — push.
    Если total=None (статы недоступны) — push (refund)."""
    if total is None:
        return 'push'  # stats unavailable → refund (см. инцидент 2026-05-11 settle)
    if total == line and line == int(line):
        return 'push'
    return total > line if over else total < line


def settle_bet_by_type(bet_type: str, stats: dict):
    """Проверить выиграла ли ставка.
    Returns: True=win, False=lose, 'push'=refund.
    Для неизвестных типов возвращает 'push' (возврат), чтобы не съесть деньги игрока."""
    # Live-ставки сохраняются с префиксом 'LIVE_' — снимаем его
    if bet_type.startswith('LIVE_'):
        bet_type = bet_type[5:]
    outcome = stats.get('outcome', 'draw')
    home_score = stats.get('home_score', 0)
    away_score = stats.get('away_score', 0)
    total_goals = stats.get('total_goals', 0)

    # 1X2
    if bet_type in ('home', 'draw', 'away'):
        return bet_type == outcome

    # Точный счёт
    if bet_type.startswith('score_'):
        return bet_type[6:] == f"{home_score}-{away_score}"

    # Тотал голов
    if bet_type.startswith('total_over_'):
        try: line = float(bet_type[11:])
        except ValueError: return 'push'
        return _ou_check(total_goals, line, True)
    if bet_type.startswith('total_under_'):
        try: line = float(bet_type[12:])
        except ValueError: return 'push'
        return _ou_check(total_goals, line, False)

    # Чёт/нечёт
    if bet_type == 'total_even':
        return total_goals % 2 == 0
    if bet_type == 'total_odd':
        return total_goals % 2 == 1

    # Обе забьют
    if bet_type == 'btts_yes':
        return bool(stats.get('both_scored'))
    if bet_type == 'btts_no':
        return not stats.get('both_scored')

    # Двойной шанс
    if bet_type == 'dc_1x':
        return outcome in ('home', 'draw')
    if bet_type == 'dc_x2':
        return outcome in ('draw', 'away')
    if bet_type == 'dc_12':
        return outcome in ('home', 'away')

    # Draw-No-Bet
    if bet_type == 'dnb_home':
        return 'push' if outcome == 'draw' else outcome == 'home'
    if bet_type == 'dnb_away':
        return 'push' if outcome == 'draw' else outcome == 'away'

    # Индивидуальные тоталы голов — реальные ключи парсера: home_over_X / away_over_X
    # Также поддерживаем legacy home_total_over_X на случай старых записей в БД.
    _ind_totals = [
        ('home_over_', 'home_score', True),
        ('home_under_', 'home_score', False),
        ('away_over_', 'away_score', True),
        ('away_under_', 'away_score', False),
        ('home_total_over_', 'home_score', True),
        ('home_total_under_', 'home_score', False),
        ('away_total_over_', 'away_score', True),
        ('away_total_under_', 'away_score', False),
    ]
    for prefix, key, over in _ind_totals:
        if bet_type.startswith(prefix):
            try: line = float(bet_type[len(prefix):])
            except ValueError: return 'push'
            return _ou_check(stats.get(key, 0), line, over)

    # Угловые (общий + по командам)
    _corners = [
        ('corners_over_', 'total_corners', True),
        ('corners_under_', 'total_corners', False),
        ('corners_home_over_', 'home_corners', True),
        ('corners_home_under_', 'home_corners', False),
        ('corners_away_over_', 'away_corners', True),
        ('corners_away_under_', 'away_corners', False),
    ]
    for prefix, key, over in _corners:
        if bet_type.startswith(prefix):
            try: line = float(bet_type[len(prefix):])
            except ValueError: return 'push'
            return _ou_check(stats.get(key, 0), line, over)

    # Карточки (жёлтые + красные)
    _cards = [
        ('cards_over_', 'total_cards', True),
        ('cards_under_', 'total_cards', False),
        ('cards_home_over_', 'home_cards', True),
        ('cards_home_under_', 'home_cards', False),
        ('cards_away_over_', 'away_cards', True),
        ('cards_away_under_', 'away_cards', False),
    ]
    for prefix, key, over in _cards:
        if bet_type.startswith(prefix):
            try: line = float(bet_type[len(prefix):])
            except ValueError: return 'push'
            return _ou_check(stats.get(key, 0), line, over)

    # Фора
    if bet_type.startswith('handicap_home_'):
        try: line = float(bet_type[14:])
        except ValueError: return 'push'
        diff = home_score - away_score + line
        if diff == 0: return 'push'
        return diff > 0
    if bet_type.startswith('handicap_away_'):
        try: line = float(bet_type[14:])
        except ValueError: return 'push'
        diff = away_score - home_score + line
        if diff == 0: return 'push'
        return diff > 0

    # Первый гол (если fetched)
    if bet_type == 'first_goal_home':
        return stats.get('first_goal') == 'home'
    if bet_type == 'first_goal_away':
        return stats.get('first_goal') == 'away'
    if bet_type == 'first_goal_none':
        return total_goals == 0

    # Пенальти: нет данных в get_match_statistics — возврат
    if bet_type in ('penalty_yes', 'penalty_no'):
        return 'push'

    # Неизвестный тип — push, чтобы не съесть ставку игрока из-за нашего бага
    try:
        print(f"settle_bet_by_type: unknown bet_type='{bet_type}' -> push", flush=True)
    except Exception:
        pass
    return 'push'




def _notify_settled_bet(user_id: int, bet_info: dict, match_info: dict):
    """Send Telegram notification to user about settled bet."""
    try:
        status = bet_info.get('status')
        bt = bet_info.get('bet_type', '')
        amount = bet_info.get('amount', 0)
        odds = bet_info.get('odds', 0)
        home = match_info.get('home_team', '?')
        away = match_info.get('away_team', '?')
        score = f"{match_info.get('home_score',0)}:{match_info.get('away_score',0)}"
        if status == 'won':
            winnings = int(amount * odds)
            text = (f"✅ <b>Ставка выиграла!</b>\n\n⚽ {home} {score} {away}\n"
                    f"🎯 {bt}\n💰 {amount} × {odds} = <b>+{winnings}</b>")
        elif status == 'returned':
            text = (f"↩️ <b>Возврат ставки</b>\n\n⚽ {home} {score} {away}\n"
                    f"🎯 {bt}\n💰 Возвращено: <b>{amount}</b>")
        else:
            text = (f"❌ <b>Ставка проиграла</b>\n\n⚽ {home} {score} {away}\n"
                    f"🎯 {bt}\n💰 Списано: <b>{amount}</b>")
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={'chat_id': user_id, 'text': text, 'parse_mode': 'HTML'},
            timeout=5
        )
    except Exception as _e:
        print(f'notify bet err user={user_id}: {_e}', flush=True)


def _notify_admins_settle(match_info: dict, summary: dict, bet_details: list):
    """Send Telegram notification to admins with settle summary + per-bet list."""
    try:
        home = match_info.get('home_team', '?')
        away = match_info.get('away_team', '?')
        score = f"{match_info.get('home_score',0)}:{match_info.get('away_score',0)}"
        corners = match_info.get('total_corners', 0)
        cards = match_info.get('total_cards', 0)
        header = (
            f"✅ <b>Авто-расчёт ставок</b>\n\n⚽ {home} {score} {away}\n"
            f"🚩 Угл: {corners} | 🟨 Карточки: {cards} | "
            f"Обе забили: {'Да' if match_info.get('both_scored') else 'Нет'}\n\n"
            f"📊 Всего: {summary.get('bets_settled',0)} | ✅ {summary.get('bets_won',0)} | "
            f"❌ {summary.get('bets_lost',0)} | ↩️ {summary.get('bets_pushed',0)}"
        )
        detail = ''
        if bet_details:
            detail = '\n\n📋 <b>Ставки:</b>'
            for b in bet_details[:20]:
                uname = b.get('username') or b.get('first_name') or str(b.get('user_id'))
                st = b.get('status')
                if st == 'won':
                    winnings = int(b.get('amount', 0) * b.get('odds', 0))
                    detail += f"\n✅ @{uname}: {b.get('bet_type','')} ({b.get('amount',0)}💰) → +{winnings}"
                elif st == 'returned':
                    detail += f"\n↩️ @{uname}: {b.get('bet_type','')} ({b.get('amount',0)}💰) → возврат"
                else:
                    detail += f"\n❌ @{uname}: {b.get('bet_type','')} ({b.get('amount',0)}💰) → -{b.get('amount',0)}"
        full = header + detail
        for admin_id in ADMIN_IDS:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={'chat_id': admin_id, 'text': full, 'parse_mode': 'HTML'},
                    timeout=5
                )
            except Exception as _ea:
                print(f'admin notify err {admin_id}: {_ea}', flush=True)
    except Exception as _e:
        print(f'admin notify outer err: {_e}', flush=True)


def get_match_statistics_fotmob(match_id) -> dict:
    """Pull match stats from FotMob (works when SofaScore is blocked).
    Falls back to team overview score when /api/v4/matchDetails 404 (после конца матча
    FotMob иногда снимает детальные данные, но score остаётся в overview).
    """
    try:
        d = _get_fotmob_match(match_id) or {}
        if not d:
            # FALLBACK: matchDetails 404'd. Try team overview for score-only.
            try:
                _team = _get_fotmob_team(FOTMOB_RM_ID) or {}
                _fixtures = (_team.get('overview') or {}).get('overviewFixtures', []) or []
                for _f in _fixtures:
                    if str(_f.get('id', '')) != str(match_id):
                        continue
                    _st = _f.get('status') or {}
                    if not _st.get('finished'):
                        continue
                    _home = _f.get('home') or {}
                    _away = _f.get('away') or {}
                    _hsc = int(_home.get('score') or 0)
                    _asc = int(_away.get('score') or 0)
                    _outcome = 'home' if _hsc > _asc else ('away' if _asc > _hsc else 'draw')
                    print(f'⚠️ FotMob matchDetails {match_id} 404, fallback to overview: {_hsc}:{_asc}', flush=True)
                    return {
                        'home_team': _home.get('name', ''),
                        'away_team': _away.get('name', ''),
                        'home_score': _hsc,
                        'away_score': _asc,
                        'total_goals': _hsc + _asc,
                        'both_scored': _hsc > 0 and _asc > 0,
                        'outcome': _outcome,
                        'finished': True,
                        # Detailed stats unavailable — None triggers push in _ou_check
                        'total_corners': None,
                        'home_corners': None,
                        'away_corners': None,
                        'total_cards': None,
                        'home_cards': None,
                        'away_cards': None,
                        'home_yellow_cards': None,
                        'away_yellow_cards': None,
                        'total_yellow_cards': None,
                        'home_red_cards': None,
                        'away_red_cards': None,
                        'total_red_cards': None,
                        'stats_partial': True,
                    }
            except Exception as _fe:
                print(f'overview fallback err for {match_id}: {_fe}', flush=True)
            return {}
        # Header has the score
        hdr = d.get('header', {}) or {}
        teams = hdr.get('teams', []) or []
        home_name = (teams[0].get('name') if len(teams) > 0 else '') or ''
        away_name = (teams[1].get('name') if len(teams) > 1 else '') or ''
        home_score = (teams[0].get('score') if len(teams) > 0 else 0) or 0
        away_score = (teams[1].get('score') if len(teams) > 1 else 0) or 0
        # status / finished?
        gen = d.get('general', {}) or {}
        status = (hdr.get('status', {}) or {})
        finished = bool(status.get('finished') or status.get('ended'))
        # corners / cards via stats list — use last-seen-wins to avoid double-count
        # (FotMob: 'Top stats' и 'Discipline' дублируют Yellow cards)
        _stat_values = {}  # normalized_title → [home, away]
        try:
            content = d.get('content', {}) or {}
            stats_root = content.get('stats', {}) or {}
            stats_data = stats_root.get('stats', stats_root) or {}
            periods = stats_data.get('Periods') if isinstance(stats_data, dict) else None
            all_stats = []
            if periods and isinstance(periods, dict):
                grp = periods.get('All') or {}
                all_stats = grp.get('stats') or grp.get('groups') or []
            for grp in (all_stats or []):
                items = grp.get('stats') if isinstance(grp, dict) else None
                if not items: continue
                for s in items:
                    title = (s.get('title') or '').lower().strip()
                    vals = s.get('stats') or []
                    if len(vals) >= 2:
                        # Coerce to int (FotMob sometimes returns strings like "484 (92%)" or None)
                        def _i(v):
                            if v is None: return 0
                            if isinstance(v, (int, float)): return int(v)
                            s = str(v).split(' ')[0]
                            try: return int(float(s))
                            except: return 0
                        _stat_values[title] = [_i(vals[0]), _i(vals[1])]
        except Exception:
            pass

        # Extract specific stats
        home_corners = _stat_values.get('corners', [0, 0])[0]
        away_corners = _stat_values.get('corners', [0, 0])[1]
        total_corners = home_corners + away_corners

        home_yellow = _stat_values.get('yellow cards', [0, 0])[0]
        away_yellow = _stat_values.get('yellow cards', [0, 0])[1]
        home_red = _stat_values.get('red cards', [0, 0])[0]
        away_red = _stat_values.get('red cards', [0, 0])[1]
        home_cards = home_yellow + home_red
        away_cards = away_yellow + away_red
        total_cards = home_cards + away_cards
        total_yellow_cards = home_yellow + away_yellow
        total_red_cards = home_red + away_red

        outcome = 'home' if home_score > away_score else ('away' if away_score > home_score else 'draw')
        return {
            'home_team': home_name, 'away_team': away_name,
            'home_score': int(home_score or 0), 'away_score': int(away_score or 0),
            'total_goals': int((home_score or 0) + (away_score or 0)),
            'both_scored': bool((home_score or 0) > 0 and (away_score or 0) > 0),
            'total_corners': total_corners,
            'home_corners': home_corners,
            'away_corners': away_corners,
            'total_cards': total_cards,
            'home_cards': home_cards,
            'away_cards': away_cards,
            'total_yellow_cards': total_yellow_cards,
            'home_yellow_cards': home_yellow,
            'away_yellow_cards': away_yellow,
            'total_red_cards': total_red_cards,
            'home_red_cards': home_red,
            'away_red_cards': away_red,
            'outcome': outcome,
            'finished': finished,
        }
    except Exception as _e:
        print(f'get_match_statistics_fotmob err {match_id}: {_e}', flush=True)
        return {}


# Block D (get_fotmob_recent_matches) moved to src/parsers/fotmob.py


def _resolve_leon_bet_to_fotmob(leon_match_id: str, fotmob_recent: list, bet_created_at: str = '') -> str:
    """Map a Leon/legacy match_id to a FotMob match_id by closest finished date to bet_created_at."""
    import datetime as _dtr
    if not fotmob_recent:
        return ''
    # If only one — pick it
    if not bet_created_at:
        return str(fotmob_recent[0].get('matchId', ''))
    try:
        bet_dt = _dtr.datetime.strptime(str(bet_created_at)[:19], '%Y-%m-%d %H:%M:%S')
    except Exception:
        try:
            bet_dt = _dtr.datetime.strptime(str(bet_created_at)[:10], '%Y-%m-%d')
        except Exception:
            return str(fotmob_recent[0].get('matchId', ''))
    candidates = []
    for m in fotmob_recent:
        ut = m.get('utcTime', '')
        try:
            m_dt = _dtr.datetime.strptime(str(ut)[:19], '%Y-%m-%dT%H:%M:%S')
        except Exception:
            continue
        delta = (m_dt - bet_dt).total_seconds()
        # Match must be from -4h before bet to +48h after (typical betting window)
        if -4 * 3600 <= delta <= 48 * 3600:
            candidates.append((abs(delta), m))
    if not candidates:
        return ''
    candidates.sort(key=lambda x: x[0])
    return str(candidates[0][1].get('matchId') or '')


# === end restored helpers ===

def settle_all_bets_advanced(match_id: str, stats: dict) -> dict:
    """Расчёт всех типов ставок + уведомления юзерам/админам."""
    from database import _execute

    result = {'bets_settled': 0, 'predictions_settled': 0, 'bets_won': 0, 'bets_lost': 0, 'bets_pushed': 0}

    bets = _execute("""
        SELECT bet_id, user_id, bet_type, amount, odds
        FROM bets
        WHERE match_id = ? AND status = 'pending'
    """, (str(match_id),)) or []

    _match_info = {
        'home_team': stats.get('home_team', ''),
        'away_team': stats.get('away_team', ''),
        'home_score': stats.get('home_score', 0),
        'away_score': stats.get('away_score', 0),
        'total_corners': stats.get('total_corners', 0),
        'total_cards': stats.get('total_cards', 0),
        'both_scored': stats.get('both_scored', False),
    }
    _settled_details = []

    for bet in bets:
        bet_id = bet['bet_id']
        user_id = bet['user_id']
        bet_type = bet['bet_type']
        amount = bet['amount']
        odds = bet['odds']

        outcome = settle_bet_by_type(bet_type, stats)

        # Helper: insert transaction for settle event
        _match_desc = f"{stats.get('home_team','?')} vs {stats.get('away_team','?')} — {bet_type}"
        # Read balance_before for proper chart-friendly tx record
        _bal_row = _execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        _bal_before = (_bal_row[0]['balance'] if _bal_row else 0)

        if outcome == 'push':
            _bal_after = _bal_before + amount
            _execute("UPDATE bets SET status = 'returned', payout = ?, settled_at=CURRENT_TIMESTAMP WHERE bet_id = ?", (amount, bet_id))
            _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            _execute(
                "INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id, created_at) "
                "VALUES (?, 'refund', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (user_id, amount, _bal_before, _bal_after, f"Возврат ставки: {_match_desc}", str(bet_id))
            )
            result['bets_pushed'] += 1
            _bet_status = 'returned'
        elif outcome:
            winnings = int(amount * odds)
            _bal_after = _bal_before + winnings
            _execute("UPDATE bets SET status = 'won', payout = ?, settled_at=CURRENT_TIMESTAMP WHERE bet_id = ?", (winnings, bet_id))
            _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (winnings, user_id))
            _execute(
                "INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id, created_at) "
                "VALUES (?, 'win', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (user_id, winnings, _bal_before, _bal_after, f"Выигрыш по ставке: {_match_desc}", str(bet_id))
            )
            result['bets_won'] += 1
            _bet_status = 'won'
        else:
            _execute("UPDATE bets SET status = 'lost', payout = 0, settled_at=CURRENT_TIMESTAMP WHERE bet_id = ?", (bet_id,))
            _execute(
                "INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id, created_at) "
                "VALUES (?, 'loss', 0, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (user_id, _bal_before, _bal_before, f"Проигранная ставка: {_match_desc}", str(bet_id))
            )
            result['bets_lost'] += 1
            _bet_status = 'lost'

        result['bets_settled'] += 1

        _bet_row = dict(bet)
        _bet_row['status'] = _bet_status
        try:
            _notify_settled_bet(user_id, _bet_row, _match_info)
        except Exception as _ne:
            print(f'notify err bet={bet_id}: {_ne}', flush=True)

        _u = _execute('SELECT username, first_name FROM users WHERE user_id=?', (user_id,))
        _uname, _fname = '', ''
        if _u:
            _uname = _u[0].get('username', '') or ''
            _fname = _u[0].get('first_name', '') or ''
        _settled_details.append({
            'user_id': user_id, 'username': _uname, 'first_name': _fname,
            'bet_type': bet_type, 'amount': amount, 'odds': odds,
            'status': _bet_status,
        })

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

    if result['bets_settled'] > 0 or result.get('predictions_settled', 0) > 0:
        try:
            _notify_admins_settle(_match_info, result, _settled_details)
        except Exception as _ae:
            print(f'admin summary err: {_ae}', flush=True)

    return result


# /api/admin/settle-check moved to src/routes/admin.py


# ============ ФОНОВАЯ ЗАДАЧА ДЛЯ АВТО-РАСЧЁТА ============

import asyncio
from contextlib import asynccontextmanager

async def auto_settle_task():
    """Auto-settle every 5 min. FotMob primary (HTML fallback survives CF), SofaScore fallback.
    Also resolves legacy Leon-id pending bets to FotMob match ids by closest date."""
    while True:
        try:
            await asyncio.sleep(300)

            fotmob_results = get_fotmob_recent_matches()
            sofa_results = []
            try:
                sofa_results = get_sofascore_recent_matches()
            except Exception:
                pass

            seen = set()
            combined = []
            for r in (fotmob_results + sofa_results):
                mid = str(r.get('matchId', ''))
                if mid and mid not in seen:
                    seen.add(mid)
                    combined.append(r)

            for result in combined:
                match_id = str(result.get('matchId', ''))
                if not match_id or match_id in _settled_matches:
                    continue
                stats = {}
                try:
                    stats = get_match_statistics_fotmob(match_id)
                except Exception:
                    stats = {}
                if not stats or (stats.get('home_score', 0) == 0 and stats.get('away_score', 0) == 0 and stats.get('total_goals', 0) == 0):
                    try:
                        stats = get_match_statistics(match_id)
                    except Exception:
                        stats = {}
                if not stats or (stats.get('home_score', 0) == 0 and stats.get('away_score', 0) == 0 and stats.get('total_goals', 0) == 0):
                    continue
                stats['home_team'] = result.get('homeTeam', '')
                stats['away_team'] = result.get('awayTeam', '')
                st = settle_all_bets_advanced(match_id, stats)
                if st.get('bets_settled', 0) > 0 or st.get('predictions_settled', 0) > 0:
                    _settled_matches.add(match_id)
                    print(f"✅ Auto-settled [{match_id}] {result.get('homeTeam','?')} vs {result.get('awayTeam','?')}: {st}", flush=True)
                else:
                    _settled_matches.add(match_id)

            # Legacy resolve loop — Leon match_ids (8+ digits) → FotMob ids by date proximity
            try:
                from database import _execute
                stale = _execute("""
                    SELECT match_id, MIN(created_at) as created_at FROM bets
                    WHERE status='pending' AND (match_id LIKE 'live:%' OR match_id GLOB '[0-9]*')
                      AND length(match_id) >= 8
                    GROUP BY match_id
                """) or []
                for row in stale:
                    legacy_id = row.get('match_id') if isinstance(row, dict) else row[0]
                    created_at = row.get('created_at') if isinstance(row, dict) else (row[1] if len(row) > 1 else '')
                    if not legacy_id:
                        continue
                    target = _resolve_leon_bet_to_fotmob(str(legacy_id), fotmob_results, created_at or '')
                    if not target:
                        continue
                    stats = get_match_statistics_fotmob(target)
                    if not stats or (stats.get('home_score', 0) + stats.get('away_score', 0) + stats.get('total_goals', 0) == 0):
                        continue
                    _t = next((r for r in fotmob_results if str(r.get('matchId')) == str(target)), {})
                    stats['home_team'] = _t.get('homeTeam', '') or stats.get('home_team', '')
                    stats['away_team'] = _t.get('awayTeam', '') or stats.get('away_team', '')
                    _execute("UPDATE bets SET match_id=? WHERE match_id=? AND status='pending'", (target, str(legacy_id)))
                    st = settle_all_bets_advanced(target, stats)
                    if st.get('bets_settled', 0) > 0:
                        print(f"✅ Legacy resolved {legacy_id} → {target}: {st}", flush=True)
                        _settled_matches.add(target)
            except Exception as _le:
                print(f'legacy resolve err: {_le}', flush=True)
        except Exception as e:
            print(f"Auto-settle error: {e}", flush=True)
