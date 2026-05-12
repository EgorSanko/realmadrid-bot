"""src/routes/prizes.py — Prize catalog + claim flow.

Эндпоинты:
- GET /api/prizes — список призов + balance + can_claim
- POST /api/prize/claim — подать заявку на приз
"""
from fastapi import APIRouter, Depends, HTTPException
import requests as _requests

router = APIRouter(prefix="/api", tags=["prizes"])

# Prize catalog
PRIZES = {
    1: {"name": "Telegram Premium 3 мес", "cost": 1000, "icon": "⭐", "requires": "phone"},
    2: {"name": "Футболка Real Madrid", "cost": 1500, "icon": "👕", "requires": "size"},
    3: {"name": "PlayStation 5", "cost": 50000, "icon": "🎮", "requires": "address"},
}


def _prizes_list():
    return [{"id": pid, **info} for pid, info in PRIZES.items()]


# Lazy dependency injection — set by api.py at startup
_deps = {}


def init(get_current_user, ClaimPrizeRequest):
    """Wire FastAPI deps + pydantic model from api.py."""
    _deps['get_current_user'] = get_current_user
    _deps['ClaimPrizeRequest'] = ClaimPrizeRequest

    @router.get("/prizes")
    async def get_prizes(user: dict = Depends(get_current_user)):
        from api import can_claim_prize
        return {
            "prizes": _prizes_list(),
            "user_balance": user['balance'],
            "can_claim": can_claim_prize(user['user_id']),
        }

    @router.post("/prize/claim")
    async def claim_prize_endpoint(req: ClaimPrizeRequest, user: dict = Depends(get_current_user)):
        from api import claim_prize, ADMIN_IDS, BOT_TOKEN
        from database import _execute

        prize_info = PRIZES.get(req.prize_id)
        if not prize_info:
            raise HTTPException(status_code=400, detail="Приз не найден")

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

        try:
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
            print(f"Prize tx description update failed: {e}", flush=True)

        try:
            username = user.get('username', '') or user.get('first_name', '') or str(user['user_id'])
            text = (
                f"🏆 <b>Заявка на приз!</b>\n\n"
                f"👤 @{username}\n"
                f"{prize_info['icon']} {prize_info['name']}\n"
                f"💰 Стоимость: {prize_info['cost']} очков\n"
                f"📞 Контакт: {contact_info}"
            )
            for admin_id in ADMIN_IDS:
                _requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": admin_id, "text": text, "parse_mode": "HTML"},
                    timeout=5,
                )
        except Exception as e:
            print(f"Prize admin notify failed: {e}", flush=True)

        return {"success": True, "message": message}
