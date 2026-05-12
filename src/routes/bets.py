"""src/routes/bets.py — Bets + Predictions endpoints (money flow).

Эндпоинты (4):
- POST /api/bet/place — prematch ставка с Leon odds verification + anti-вилка
- POST /api/bet/sell — продать за 50%
- POST /api/bet/live — live ставка (odds с фронта + verify)
- POST /api/prediction/make — прогноз 1X2 + anti-вилка

КРИТИЧНО: anti-вилка check'и проверяют existing bets AND predictions
(см. 2026-05-04 30s вилка delay инцидент).
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["bets"])


class LiveBetRequest(BaseModel):
    match_id: str
    bet_type: str
    amount: int
    odds: float  # передаётся с фронта (live меняются)


def init(get_current_user, BetRequest, PredictionRequest, SellBetRequest, MOSCOW_TZ):
    @router.post("/bet/place")
    async def place_bet_endpoint(bet: BetRequest, user: dict = Depends(get_current_user)):
        from api import (
            _is_arb_against_existing, _get_leon_cached, _leon_cache_dict,
            sheets_client, process_referral_bonus,
        )
        from database import get_user_bets, get_user_predictions, place_bet

        print(f"Place bet: match_id={bet.match_id}, type={bet.bet_type}, amount={bet.amount}", flush=True)
        if bet.amount <= 0:
            raise HTTPException(status_code=400, detail="Сумма должна быть больше 0")
        if bet.amount > user['balance']:
            raise HTTPException(status_code=400, detail="Недостаточно очков")

        # Anti-вилка early check
        try:
            if bet.match_id is not None:
                mid = str(bet.match_id)
                existing_bets = get_user_bets(user['user_id'], status='pending', limit=200)
                existing_preds = get_user_predictions(user['user_id'], status='pending', limit=200)
                types = [b['bet_type'] for b in existing_bets if str(b.get('match_id','')) == mid]
                types += [p['prediction'] for p in existing_preds if str(p.get('match_id','')) == mid]
                if _is_arb_against_existing(bet.bet_type, types):
                    raise HTTPException(status_code=400, detail='🔒 Нельзя ставить на противоположный исход (вилка)')
        except HTTPException:
            raise
        except Exception as e:
            print(f'early arb check warn: {e}', flush=True)

        matches = sheets_client.get_matches(limit=1) if sheets_client else []
        leon_live_check = _get_leon_cached()
        is_live_now = bool(leon_live_check and leon_live_check.get('is_live'))

        if not matches and not is_live_now:
            raise HTTPException(status_code=404, detail="Матч не найден")

        if matches:
            match = matches[0]
        else:
            match = {
                'id': bet.match_id or f"live:{leon_live_check.get('leon_id','')}",
                'opponent': leon_live_check.get('away_team', '') if 'real madrid' in (leon_live_check.get('home_team','').lower())
                            else leon_live_check.get('home_team', ''),
                'is_home': 'real madrid' in (leon_live_check.get('home_team','').lower()),
                'date': datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y'),
                'time': datetime.now(MOSCOW_TZ).strftime('%H:%M'),
                'tournament': leon_live_check.get('stage', 'Live'),
            }

        if not is_live_now:
            try:
                mt = datetime.strptime(f"{match.get('date')} {match.get('time')}", '%d.%m.%Y %H:%M')
                mt = mt.replace(tzinfo=MOSCOW_TZ)
                if datetime.now(MOSCOW_TZ) >= mt - timedelta(minutes=5):
                    raise HTTPException(status_code=400, detail="Ставки закрыты (до матча менее 5 минут)")
            except ValueError:
                pass

        # Late arb check
        if bet.match_id is None:
            try:
                mid = str(match.get('id', ''))
                if mid:
                    existing_bets = get_user_bets(user['user_id'], status='pending', limit=200)
                    existing_preds = get_user_predictions(user['user_id'], status='pending', limit=200)
                    types = [b['bet_type'] for b in existing_bets if str(b.get('match_id','')) == mid]
                    types += [p['prediction'] for p in existing_preds if str(p.get('match_id','')) == mid]
                    if _is_arb_against_existing(bet.bet_type, types):
                        raise HTTPException(status_code=400, detail='🔒 Нельзя ставить на противоположный исход (вилка)')
            except HTTPException:
                raise
            except Exception as e:
                print(f'late arb check warn: {e}', flush=True)

        opponent = match.get('opponent', '')
        leon_data = _get_leon_cached(target_opponent=opponent)
        leon_odds = leon_data.get('live_odds', {}) if leon_data else {}
        if not leon_odds:
            leon_data = _get_leon_cached()
            leon_odds = leon_data.get('live_odds', {}) if leon_data else {}

        if leon_data and leon_data.get('bets_suspended'):
            raise HTTPException(status_code=400, detail="Ставки приостановлены (пересчёт коэффициентов)")

        if bet.bet_type.startswith('score_'):
            odds = 30.0
        elif bet.bet_type in leon_odds and leon_odds[bet.bet_type]:
            odds = leon_odds[bet.bet_type]
        else:
            normalized_key = bet.bet_type.replace(',', '.')
            alt_key = bet.bet_type.replace('.', ',')
            if normalized_key in leon_odds and leon_odds[normalized_key]:
                odds = leon_odds[normalized_key]
            elif alt_key in leon_odds and leon_odds[alt_key]:
                odds = leon_odds[alt_key]
            else:
                _leon_cache_dict.pop(opponent or '__live__', None)
                _leon_cache_dict.pop('__live__', None)
                leon_data = _get_leon_cached(target_opponent=opponent)
                fresh = leon_data.get('live_odds', {}) if leon_data else {}
                if not fresh:
                    leon_data = _get_leon_cached()
                    fresh = leon_data.get('live_odds', {}) if leon_data else {}
                if leon_data and leon_data.get('bets_suspended'):
                    raise HTTPException(status_code=400, detail="Ставки приостановлены (пересчёт коэффициентов)")
                if bet.bet_type in fresh and fresh[bet.bet_type]:
                    odds = fresh[bet.bet_type]
                elif normalized_key in fresh and fresh[normalized_key]:
                    odds = fresh[normalized_key]
                elif alt_key in fresh and fresh[alt_key]:
                    odds = fresh[alt_key]
                else:
                    print(f"Bet type '{bet.bet_type}' not found after refresh", flush=True)
                    raise HTTPException(status_code=400, detail="Этот рынок закрылся. Обновите страницу.")

        home_team = "Real Madrid" if match.get('is_home') else match.get('opponent')
        away_team = match.get('opponent') if match.get('is_home') else "Real Madrid"
        match_date = f"{match.get('date')} {match.get('time')}"

        final_match_id = bet.match_id if bet.match_id is not None else match.get('id', '')
        bet_id = place_bet(
            user_id=user['user_id'], match_id=final_match_id, bet_type=bet.bet_type,
            amount=bet.amount, odds=odds, home_team=home_team, away_team=away_team,
            match_date=match_date,
        )

        if not bet_id:
            raise HTTPException(status_code=500, detail="Ошибка создания ставки")

        try:
            user_bets = get_user_bets(user['user_id'])
            if len(user_bets) == 1:
                process_referral_bonus(user['user_id'])
        except Exception as e:
            print(f"Referral check error: {e}", flush=True)

        return {
            "success": True, "bet_id": bet_id, "amount": bet.amount,
            "odds": odds, "potential_win": int(bet.amount * odds),
        }

    @router.post("/bet/sell")
    async def sell_bet_endpoint(req: SellBetRequest, user: dict = Depends(get_current_user)):
        from database import get_user_bets, sell_bet

        bets = get_user_bets(user['user_id'])
        bet = next((b for b in bets if b['bet_id'] == req.bet_id and b['status'] == 'pending'), None)
        if not bet:
            raise HTTPException(status_code=404, detail="Ставка не найдена")

        try:
            mt = datetime.strptime(bet['match_date'], '%d.%m.%Y %H:%M')
            mt = mt.replace(tzinfo=MOSCOW_TZ)
            if datetime.now(MOSCOW_TZ) >= mt - timedelta(minutes=1):
                raise HTTPException(status_code=400, detail="Нельзя продать - матч скоро начнётся или уже идёт")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="Ошибка проверки времени матча")

        sell_price = max(1, bet['amount'] // 2)
        if sell_bet(req.bet_id, user['user_id'], sell_price):
            return {"success": True, "sell_price": sell_price,
                    "message": f"Ставка продана за {sell_price} очков"}
        raise HTTPException(status_code=500, detail="Ошибка продажи")

    @router.post("/bet/live")
    async def place_live_bet(bet: LiveBetRequest, user: dict = Depends(get_current_user)):
        from api import _get_leon_cached, get_sofascore_live_match
        from database import place_bet

        if bet.amount <= 0:
            raise HTTPException(status_code=400, detail="Сумма должна быть больше 0")
        if bet.amount > user['balance']:
            raise HTTPException(status_code=400, detail="Недостаточно очков")

        live_match = get_sofascore_live_match()
        leon_data = _get_leon_cached()
        leon_is_live = leon_data and leon_data.get('is_live')
        if (not live_match or not live_match.get('is_live')) and not leon_is_live:
            raise HTTPException(status_code=400, detail="Нет live матча")

        if leon_data and leon_data.get('bets_suspended'):
            raise HTTPException(status_code=400, detail="Ставки временно приостановлены")

        if leon_data and leon_data.get('live_odds'):
            current = leon_data.get('live_odds', {}).get(bet.bet_type)
            if current and current != bet.odds:
                bet.odds = current

        home_team = (live_match or {}).get('home_team', '') or (leon_data or {}).get('home_team', '')
        away_team = (live_match or {}).get('away_team', '') or (leon_data or {}).get('away_team', '')
        minute = (live_match or {}).get('minute', '') or (leon_data or {}).get('minute', '')
        score = leon_data.get('score', '0:0') if leon_data and leon_data.get('score') else \
                f"{(live_match or {}).get('home_score', 0)}:{(live_match or {}).get('away_score', 0)}"

        bet_id = place_bet(
            user_id=user['user_id'], match_id=bet.match_id,
            bet_type=f"LIVE_{bet.bet_type}", amount=bet.amount, odds=bet.odds,
            home_team=home_team, away_team=away_team, match_date=f"LIVE {minute} ({score})",
        )
        if not bet_id:
            raise HTTPException(status_code=500, detail="Ошибка создания ставки")

        return {
            "success": True, "bet_id": bet_id, "amount": bet.amount, "odds": bet.odds,
            "potential_win": int(bet.amount * bet.odds),
            "is_live": True, "minute": minute, "score": score,
        }

    @router.post("/prediction/make")
    async def make_prediction_endpoint(req: PredictionRequest, user: dict = Depends(get_current_user)):
        from api import _is_arb_against_existing, _get_leon_cached, sheets_client
        from database import get_user_bets, get_user_predictions, make_prediction

        if req.prediction not in ['home', 'draw', 'away']:
            raise HTTPException(status_code=400, detail="Неверный тип прогноза")

        try:
            if req.match_id is not None:
                mid = str(req.match_id)
                existing_bets = get_user_bets(user['user_id'], status='pending', limit=200)
                existing_preds = get_user_predictions(user['user_id'], status='pending', limit=200)
                types = [b['bet_type'] for b in existing_bets if str(b.get('match_id','')) == mid]
                types += [p['prediction'] for p in existing_preds if str(p.get('match_id','')) == mid]
                if _is_arb_against_existing(req.prediction, types):
                    raise HTTPException(status_code=400, detail='🔒 Нельзя прогнозировать противоположный исход (вилка)')
        except HTTPException:
            raise
        except Exception as e:
            print(f'pred arb check warn: {e}', flush=True)

        matches = sheets_client.get_matches(limit=1) if sheets_client else []
        leon_live_check = _get_leon_cached()
        is_live_now = bool(leon_live_check and leon_live_check.get('is_live'))

        if not matches and not is_live_now:
            raise HTTPException(status_code=404, detail="Матч не найден")

        if matches:
            match = matches[0]
        else:
            match = {
                'id': req.match_id or f"live:{leon_live_check.get('leon_id','')}",
                'opponent': leon_live_check.get('away_team', '') if 'real madrid' in (leon_live_check.get('home_team','').lower())
                            else leon_live_check.get('home_team', ''),
                'is_home': 'real madrid' in (leon_live_check.get('home_team','').lower()),
                'date': datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y'),
                'time': datetime.now(MOSCOW_TZ).strftime('%H:%M'),
            }

        if not is_live_now:
            try:
                mt = datetime.strptime(f"{match.get('date')} {match.get('time')}", '%d.%m.%Y %H:%M')
                mt = mt.replace(tzinfo=MOSCOW_TZ)
                if datetime.now(MOSCOW_TZ) >= mt - timedelta(minutes=5):
                    raise HTTPException(status_code=400, detail="Прогнозы закрыты (до матча менее 5 минут)")
            except ValueError:
                pass

        home_team = "Real Madrid" if match.get('is_home') else match.get('opponent')
        away_team = match.get('opponent') if match.get('is_home') else "Real Madrid"
        match_date = f"{match.get('date')} {match.get('time')}"

        final_match_id = req.match_id if req.match_id is not None else match.get('id', '')
        prediction_id = make_prediction(
            user_id=user['user_id'], match_id=str(final_match_id), prediction=req.prediction,
            home_team=home_team, away_team=away_team, match_date=match_date,
        )

        if not prediction_id:
            raise HTTPException(status_code=400, detail="Прогноз на этот матч уже сделан!")

        return {"success": True, "prediction_id": prediction_id, "message": "Прогноз принят!"}
