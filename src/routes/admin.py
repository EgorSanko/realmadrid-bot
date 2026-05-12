"""src/routes/admin.py — Admin-only endpoints (ADMIN_IDS guard).

Эндпоинты:
- POST /api/admin/add-balance — пополнить баланс юзера по username
- GET /api/admin/users — список юзеров (топ-N по балансу)
- GET /api/admin/pending-bets — все pending ставки
- POST /api/admin/settle-manual — ручной запуск расчёта
- POST /api/admin/settle-check — проверка + расчёт завершённых матчей

Все защищены `user_id in ADMIN_IDS` (HTTP 403 если нет).
"""
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/api/admin", tags=["admin"])


def init(get_current_user, AdminAddBalanceRequest):
    @router.post("/add-balance")
    async def admin_add_balance(req: AdminAddBalanceRequest, user: dict = Depends(get_current_user)):
        from api import ADMIN_IDS
        from database import _execute

        if user['user_id'] not in ADMIN_IDS:
            raise HTTPException(status_code=403, detail="Доступ запрещён")

        username = req.username.replace('@', '').strip().lower()
        result = _execute("SELECT user_id, balance, first_name FROM users WHERE LOWER(username) = ?", (username,))
        if not result:
            raise HTTPException(status_code=404, detail=f"Пользователь @{username} не найден")

        target = result[0]
        old_balance = target['balance']
        new_balance = old_balance + req.amount
        _execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, target['user_id']))

        return {
            "success": True,
            "username": username,
            "first_name": target.get('first_name'),
            "old_balance": old_balance,
            "new_balance": new_balance,
            "added": req.amount,
        }

    @router.get("/users")
    async def admin_get_users(user: dict = Depends(get_current_user), limit: int = 50):
        from api import ADMIN_IDS
        from database import _execute

        if user['user_id'] not in ADMIN_IDS:
            raise HTTPException(status_code=403, detail="Доступ запрещён")
        users = _execute(f"SELECT user_id, username, first_name, balance FROM users ORDER BY balance DESC LIMIT {limit}")
        return {"users": users or [], "count": len(users or [])}

    @router.get("/pending-bets")
    async def admin_pending_bets(user: dict = Depends(get_current_user)):
        from api import ADMIN_IDS
        from database import _execute

        if user['user_id'] not in ADMIN_IDS:
            raise HTTPException(status_code=403, detail="Доступ запрещён")
        bets = _execute("""
            SELECT b.*, u.username, u.first_name
            FROM bets b
            LEFT JOIN users u ON b.user_id = u.user_id
            WHERE b.status = 'pending'
            ORDER BY b.created_at DESC
        """)
        return {"bets": bets or [], "count": len(bets or [])}

    @router.post("/settle-manual")
    async def admin_settle_manual(user: dict = Depends(get_current_user)):
        from api import ADMIN_IDS, get_sofascore_recent_matches, get_match_statistics, settle_all_bets_advanced

        if user['user_id'] not in ADMIN_IDS:
            raise HTTPException(status_code=403, detail="Доступ запрещён")

        try:
            results = get_sofascore_recent_matches()
            settled_info = []
            for result in results:
                match_id = str(result.get('matchId', ''))
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
                        'bets_won': st.get('bets_won', 0),
                    })
            return {"settled": settled_info, "count": len(settled_info)}
        except Exception as e:
            return {"error": str(e)}

    @router.post("/settle-check")
    async def check_and_settle():
        """Public settle-check (no admin guard — used by cron/curl)."""
        from api import get_sofascore_recent_matches, get_match_statistics, settle_all_bets_advanced, _settled_matches
        try:
            results = get_sofascore_recent_matches()
            settled_info = []
            for result in results:
                match_id = str(result.get('matchId', ''))
                if not match_id or match_id in _settled_matches:
                    continue
                stats = get_match_statistics(match_id)
                if stats['total_goals'] == 0 and stats['home_score'] == 0:
                    continue
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
                        'predictions_settled': st['predictions_settled'],
                    })
                else:
                    _settled_matches.add(match_id)
            return {"settled": settled_info, "count": len(settled_info)}
        except Exception as e:
            print(f"Settle check error: {e}", flush=True)
            return {"error": str(e)}
