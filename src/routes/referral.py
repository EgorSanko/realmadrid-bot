"""src/routes/referral.py — Referral system endpoints.

Эндпоинты:
- GET /api/referral/info — ссылка, статистика рефералов
- POST /api/referral/apply — применить реферальный код

Service-функция `process_referral_bonus` остаётся в api.py пока — её вызывает
place_bet endpoint. Перенос в services/referral.py запланирован в Block 2.5.
"""
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/api", tags=["referral"])

BOT_USERNAME = "Real_Madrid_football_bot"
BONUS_PER_REFERRAL = 25


def init(get_current_user):
    @router.get("/referral/info")
    async def get_referral_info(user: dict = Depends(get_current_user)):
        from database import _execute
        try:
            user_id = user['user_id']

            referrals = _execute(
                "SELECT COUNT(*) as count FROM users WHERE referred_by = ?",
                (user_id,)
            )
            referral_count = referrals[0]['count'] if referrals else 0

            earnings = _execute(
                "SELECT COALESCE(SUM(amount), 0) as total FROM transactions "
                "WHERE user_id = ? AND type = 'referral_bonus' "
                "AND description LIKE '%приглашение друга%'",
                (user_id,)
            )
            total_earnings = earnings[0]['total'] if earnings else 0

            return {
                "ref_link": f"https://t.me/{BOT_USERNAME}?start=ref{user_id}",
                "ref_code": f"ref{user_id}",
                "referral_count": referral_count,
                "total_earnings": total_earnings,
                "bonus_per_referral": BONUS_PER_REFERRAL,
            }
        except Exception as e:
            print(f"Referral info error: {e}", flush=True)
            return {"ref_link": "", "referral_count": 0, "total_earnings": 0}

    @router.post("/referral/apply")
    async def apply_referral(ref_code: str, user: dict = Depends(get_current_user)):
        from database import _execute
        try:
            user_id = user['user_id']

            current = _execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,))
            if current and current[0].get('referred_by'):
                raise HTTPException(status_code=400, detail="Вы уже использовали реферальный код")

            if not ref_code.startswith('ref'):
                raise HTTPException(status_code=400, detail="Неверный реферальный код")

            try:
                referrer_id = int(ref_code.replace('ref', ''))
            except ValueError:
                raise HTTPException(status_code=400, detail="Неверный реферальный код")

            if referrer_id == user_id:
                raise HTTPException(status_code=400, detail="Нельзя использовать свой код")

            referrer = _execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,))
            if not referrer:
                raise HTTPException(status_code=400, detail="Пользователь не найден")

            _execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user_id))

            return {
                "success": True,
                "message": f"Реферальный код применён! Вы и ваш друг получите по {BONUS_PER_REFERRAL} очков после вашей первой ставки.",
            }
        except HTTPException:
            raise
        except Exception as e:
            print(f"Apply referral error: {e}", flush=True)
            raise HTTPException(status_code=500, detail=str(e))
