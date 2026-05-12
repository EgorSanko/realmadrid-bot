"""src/shared/tg_auth.py — Telegram authentication.

Содержит:
- verify_telegram_webapp() — HMAC-SHA256 проверка initData из Telegram WebApp
- verify_telegram_login_widget() — проверка Login Widget на сайте
- _gen_login_code(), _sign_login_widget(), _gc_login_codes() — для code-based login flow

Состояние:
- _login_codes — in-memory словарь code → {created, status, ...} с TTL 10 минут

См. Obsidian/Real Madrid/01 - Frontend/WebApp (Telegram).md, Public site.md
"""
import os
import hmac
import hashlib
import secrets
import string
import time as _t
from urllib.parse import parse_qs, urlencode

BOT_TOKEN = os.getenv('TELEGRAM_TOKEN', '')
LOGIN_CODE_TTL = 600  # 10 min
LOGIN_WIDGET_AUTH_DATE_MAX_AGE = 30 * 86400  # 30 days (см. RM audit 2026-04-09)

_login_codes = {}  # code -> {created, status, auth_qs?, user?}


def verify_telegram_webapp(init_data: str) -> dict:
    """Проверка подписи Telegram Web App initData.
    Возвращает данные пользователя если подпись валидна, иначе None.
    """
    try:
        parsed = dict(parse_qs(init_data))
        received_hash = parsed.get('hash', [''])[0]

        data_check = []
        for key, value in sorted(parsed.items()):
            if key != 'hash':
                data_check.append(f"{key}={value[0]}")
        data_check_string = '\n'.join(data_check)

        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        user_data = parsed.get('user', ['{}'])[0]
        import json
        user = json.loads(user_data)
        return user
    except Exception as e:
        print(f"verify_telegram_webapp error: {e}", flush=True)
        return None


def verify_telegram_login_widget(init_data: str) -> dict:
    """Проверка подписи Telegram Login Widget (для публичного сайта).
    Принимает querystring как из ?id=...&hash=...
    """
    try:
        parsed = dict(parse_qs(init_data))
        received_hash = parsed.get('hash', [''])[0]
        if not received_hash:
            return None

        data_check = []
        for key in sorted(parsed.keys()):
            if key != 'hash':
                data_check.append(f"{key}={parsed[key][0]}")
        data_check_string = '\n'.join(data_check)

        # Login Widget использует sha256(BOT_TOKEN) как secret (не "WebAppData")
        secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        # Проверка возраста подписи (anti-replay)
        try:
            auth_date = int(parsed.get('auth_date', ['0'])[0])
            if _t.time() - auth_date > LOGIN_WIDGET_AUTH_DATE_MAX_AGE:
                return None
        except (ValueError, TypeError):
            return None

        return {
            'id': int(parsed.get('id', ['0'])[0]),
            'first_name': parsed.get('first_name', [''])[0],
            'last_name': parsed.get('last_name', [''])[0],
            'username': parsed.get('username', [''])[0],
            'photo_url': parsed.get('photo_url', [''])[0],
            'auth_date': auth_date,
        }
    except Exception as e:
        print(f"verify_telegram_login_widget error: {e}", flush=True)
        return None


def _gen_login_code() -> str:
    """Сгенерировать уникальный 6-символьный код для login flow."""
    while True:
        c = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        if c not in _login_codes:
            return c


def _sign_login_widget(user_id: int, first_name: str = '', last_name: str = '',
                       username: str = '', photo_url: str = '') -> str:
    """Подписать данные юзера как будто Login Widget. Используется для code-confirm flow."""
    fields = {
        'id': str(user_id),
        'auth_date': str(int(_t.time())),
    }
    if first_name:
        fields['first_name'] = first_name
    if last_name:
        fields['last_name'] = last_name
    if username:
        fields['username'] = username
    if photo_url:
        fields['photo_url'] = photo_url
    data_check = '\n'.join(f"{k}={fields[k]}" for k in sorted(fields.keys()))
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    sig = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    fields['hash'] = sig
    return urlencode(fields)


def _gc_login_codes():
    """Удалить expired login codes (TTL 10 минут)."""
    now = _t.time()
    expired = [c for c, v in _login_codes.items() if now - v['created'] > LOGIN_CODE_TTL]
    for c in expired:
        _login_codes.pop(c, None)
