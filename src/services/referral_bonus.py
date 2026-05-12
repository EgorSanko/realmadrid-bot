"""src/services/referral_bonus.py — Reward both referrer + referee on first bet.

Called from routes/bets.py.place_bet after a successful bet, only fires once
per user (idempotent via existing transaction check).
"""
from database import _execute


def process_referral_bonus(user_id: int):
    """Начислить реферальный бонус после первой ставки (вызывается из place_bet)"""
    try:
        # Проверяем есть ли реферер и не начислен ли уже бонус
        user_data = _execute(
            "SELECT referred_by FROM users WHERE user_id = ?",
            (user_id,)
        )
        if not user_data or not user_data[0].get('referred_by'):
            return

        referrer_id = user_data[0]['referred_by']

        # Проверяем не начисляли ли уже бонус этому пользователю
        existing_bonus = _execute(
            "SELECT transaction_id FROM transactions WHERE user_id = ? AND type = 'referral_bonus' AND reference_id = ?",
            (user_id, str(referrer_id))
        )
        if existing_bonus:
            return  # Бонус уже начислен

        bonus = 25

        # Бонус рефереру
        referrer = _execute("SELECT balance FROM users WHERE user_id = ?", (referrer_id,))
        if referrer:
            ref_balance = referrer[0]['balance']
            _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, referrer_id))
            _execute(
                """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                   VALUES (?, 'referral_bonus', ?, ?, ?, ?, ?)""",
                (referrer_id, bonus, ref_balance, ref_balance + bonus,
                 f"Бонус за приглашение друга (первая ставка)", str(user_id))
            )

        # Бонус новому пользователю
        user_balance = _execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        if user_balance:
            ub = user_balance[0]['balance']
            _execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, user_id))
            _execute(
                """INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, description, reference_id)
                   VALUES (?, 'referral_bonus', ?, ?, ?, ?, ?)""",
                (user_id, bonus, ub, ub + bonus,
                 f"Бонус за регистрацию по приглашению (первая ставка)", str(referrer_id))
            )

        print(f"✅ Referral bonus: {referrer_id} <- {user_id}, +{bonus} each")

    except Exception as e:
        print(f"Referral bonus error: {e}")
