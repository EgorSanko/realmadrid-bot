"""src/routes/user.py — User profile endpoints.

Эндпоинты:
- GET /api/user/me — данные пользователя + статистика (bets, predictions counts)
- GET /api/user/bets — список ставок
- GET /api/user/predictions — список прогнозов
- GET /api/user/transactions — журнал транзакций с русскими лейблами

Все требуют auth (Telegram initData или Login Widget signed qs).
"""
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/api/user", tags=["user"])

TX_TYPE_INFO = {
    'bet':              {'icon': '🎰',   'name': 'Ставка'},
    'bet_place':        {'icon': '🎰',   'name': 'Ставка'},
    'bet_win':          {'icon': '🎰✅', 'name': 'Выигрыш ставки'},
    'bet_lose':         {'icon': '🎰❌', 'name': 'Проигрыш ставки'},
    'bet_sell':         {'icon': '💰',   'name': 'Продажа ставки'},
    'prediction_win':   {'icon': '🔮✅', 'name': 'Правильный прогноз'},
    'prediction_lose':  {'icon': '🔮❌', 'name': 'Неправильный прогноз'},
    'bonus':            {'icon': '🎁',   'name': 'Бонус'},
    'deposit':          {'icon': '💳',   'name': 'Пополнение'},
    'admin_add':        {'icon': '👑➕', 'name': 'Начисление от админа'},
    'admin_remove':     {'icon': '👑➖', 'name': 'Списание от админа'},
    'win':              {'icon': '🎰✅', 'name': 'Выигрыш ставки'},
    'refund':           {'icon': '↩️',  'name': 'Возврат ставки'},
    'loss':             {'icon': '🎰❌', 'name': 'Проигрыш ставки'},
    'referral_bonus':   {'icon': '👥',   'name': 'Реферальный бонус'},
    'prize':            {'icon': '🏆',   'name': 'Приз'},
}


def init(get_current_user):
    @router.get("/me")
    async def get_me(user: dict = Depends(get_current_user)):
        from database import get_user_bets, get_user_predictions

        bets = get_user_bets(user['user_id'], limit=1000)
        predictions = get_user_predictions(user['user_id'], limit=1000)

        total_won = user.get('total_won', 0)
        if not total_won or total_won == -0:
            total_won = 0

        return {
            "user_id": user['user_id'],
            "username": user.get('username'),
            "first_name": user.get('first_name'),
            "balance": user['balance'],
            "total_wagered": user.get('total_wagered', 0),
            "total_won": total_won,
            "bets_count": len(bets),
            "bets_won": len([b for b in bets if b.get('status') == 'won']),
            "predictions_total": len(predictions),
            "predictions_correct": len([p for p in predictions if p.get('status') in ('correct', 'won')]),
            "predictions_incorrect": len([p for p in predictions if p.get('status') in ('incorrect', 'lost')]),
            "created_at": user.get('created_at'),
        }

    @router.get("/bets")
    async def get_my_bets(user: dict = Depends(get_current_user), limit: int = 20):
        from database import get_user_bets
        return {"bets": get_user_bets(user['user_id'], limit=limit)}

    @router.get("/predictions")
    async def get_my_predictions(user: dict = Depends(get_current_user), limit: int = 20):
        from database import get_user_predictions
        return {"predictions": get_user_predictions(user['user_id'], limit=limit)}

    @router.get("/transactions")
    async def get_user_transactions(user: dict = Depends(get_current_user), limit: int = 50):
        from database import _execute
        try:
            transactions = _execute(
                """SELECT transaction_id, type, amount, balance_before, balance_after,
                          description, reference_id, created_at
                   FROM transactions
                   WHERE user_id = ?
                   ORDER BY created_at DESC, transaction_id DESC
                   LIMIT ?""",
                (user['user_id'], limit),
            ) or []

            result = []
            for tx in transactions:
                tx_type = tx['type']
                info = TX_TYPE_INFO.get(tx_type, {'icon': '💫', 'name': tx_type})
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
                    'created_at': tx['created_at'],
                })
            return {"transactions": result}
        except Exception as e:
            print(f"Transactions error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return {"transactions": [], "error": str(e)}
