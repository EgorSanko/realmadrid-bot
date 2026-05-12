"""src/routes/purchases.py — Points purchase + admin approval flow.

Эндпоинты:
- GET /api/purchase/config — реквизиты карты, цены, мин. покупка
- POST /api/purchase — создать заявку (multipart: amount + receipt photo)

Уведомление админу через TG идёт в background task — пользователь
получает 200 OK мгновенно (см. фикс 2026-05-04 30s вилка delay).
"""
import os
import json
import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["purchases"])


def init(get_current_user):
    @router.get("/purchase/config")
    async def purchase_config_endpoint():
        from api import PURCHASE_CONFIG
        return PURCHASE_CONFIG

    @router.post("/purchase")
    async def create_purchase(request: Request, user: dict = Depends(get_current_user)):
        from api import (
            PURCHASE_CONFIG, RECEIPTS_DIR, MOSCOW_TZ,
            _load_purchases, _save_purchases,
            ADMIN_IDS, BOT_TOKEN,
        )

        form = await request.form()
        amount_str = form.get('amount', '0')
        receipt_file = form.get('receipt')

        try:
            amount = int(amount_str)
        except (ValueError, TypeError):
            return JSONResponse(status_code=400, content={"detail": "Некорректная сумма"})

        min_purchase = PURCHASE_CONFIG.get('min_purchase', 100)
        if amount < min_purchase:
            return JSONResponse(status_code=400, content={"detail": f"Минимальная покупка: {min_purchase} очков"})

        purchases = _load_purchases()
        max_id = max((p.get('id', 0) for p in purchases), default=10000)
        purchase_id = max_id + 1

        receipt_filename = None
        receipt_path = None
        if receipt_file and hasattr(receipt_file, 'read'):
            os.makedirs(RECEIPTS_DIR, exist_ok=True)
            ext = 'jpg'
            if hasattr(receipt_file, 'filename') and receipt_file.filename and '.' in receipt_file.filename:
                ext = receipt_file.filename.rsplit('.', 1)[-1].lower()
            receipt_filename = f"{purchase_id}.{ext}"
            receipt_path = os.path.join(RECEIPTS_DIR, receipt_filename)
            content = await receipt_file.read()
            with open(receipt_path, 'wb') as f:
                f.write(content)

        price_per_point = PURCHASE_CONFIG.get('price_per_point', 2.5)
        purchase = {
            'id': purchase_id,
            'user_id': user['user_id'],
            'username': user.get('username', ''),
            'first_name': user.get('first_name', ''),
            'amount': amount,
            'total_rub': round(amount * price_per_point),
            'receipt': receipt_filename,
            'status': 'pending',
            'created_at': datetime.now(MOSCOW_TZ).isoformat(),
        }
        purchases.append(purchase)
        _save_purchases(purchases)

        # Background notify — request returns immediately
        def _notify_admins_blocking():
            try:
                import requests as req_lib
                username = user.get('username', '') or user.get('first_name', '') or str(user['user_id'])
                caption = (
                    f"<b>💰 Заявка на покупку #{purchase_id}</b>\n\n"
                    f"👤 @{username}\n"
                    f"🔢 {amount} очков = {purchase['total_rub']}₽\n"
                    f"📅 {datetime.now(MOSCOW_TZ).strftime('%d.%m %H:%M')}"
                )
                reply_markup = json.dumps({
                    "inline_keyboard": [[
                        {"text": "✅ Одобрить", "callback_data": f"approve_{purchase_id}"},
                        {"text": "❌ Отклонить", "callback_data": f"reject_{purchase_id}"},
                    ]]
                })
                for admin_id in ADMIN_IDS:
                    try:
                        if receipt_path and os.path.exists(receipt_path):
                            with open(receipt_path, 'rb') as f:
                                req_lib.post(
                                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                                    data={'chat_id': admin_id, 'caption': caption, 'parse_mode': 'HTML', 'reply_markup': reply_markup},
                                    files={'photo': f},
                                    timeout=10,
                                )
                        else:
                            req_lib.post(
                                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                json={'chat_id': admin_id, 'text': caption, 'parse_mode': 'HTML',
                                      'reply_markup': json.loads(reply_markup)},
                                timeout=5,
                            )
                    except Exception as e:
                        print(f"Notify admin {admin_id} failed: {e}", flush=True)
            except Exception as e:
                print(f"Purchase notification error: {e}", flush=True)

        asyncio.create_task(asyncio.to_thread(_notify_admins_blocking))
        return {"success": True, "id": purchase_id}
