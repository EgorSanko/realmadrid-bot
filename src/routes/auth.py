"""src/routes/auth.py — Code-based login flow for public site.

Эндпоинты (3):
- POST /api/auth/code/request — выдаёт 6-символьный code и bot_username
- GET  /api/auth/code/check    — клиент опрашивает: pending / ok / expired
- POST /api/auth/code/confirm  — бот после /start <code> подтверждает (X-Internal-Secret)

Flow:
1. Сайт открывается → POST /auth/code/request → получает code
2. Сайт показывает ссылку https://t.me/<bot>?start=<code>
3. Юзер нажимает → бот вызывает /auth/code/confirm с user_id + secret
4. Сайт периодически опрашивает /auth/code/check → когда status=ok, забирает auth_qs (подписанный Login Widget querystring) и кладёт в localStorage

State + helpers (_login_codes dict, _gen_login_code, _sign_login_widget,
_gc_login_codes, LOGIN_CODE_TTL) живут в src/shared/tg_auth.py.
"""
import os
import hmac
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from src.shared.tg_auth import (
    _login_codes, _gen_login_code, _sign_login_widget, _gc_login_codes,
    LOGIN_CODE_TTL,
)
import time as _t

router = APIRouter(prefix="/api/auth", tags=["auth"])


class _CodeConfirmReq(BaseModel):
    code: str
    user_id: int
    first_name: str = ''
    last_name: str = ''
    username: str = ''
    photo_url: str = ''


def init():
    INTERNAL_API_SECRET = os.getenv('INTERNAL_API_SECRET', '')
    _INTERNAL_SECRET_OK = bool(INTERNAL_API_SECRET) and INTERNAL_API_SECRET != 'change-me-shared-secret'
    if not _INTERNAL_SECRET_OK:
        print("WARNING: INTERNAL_API_SECRET not set — /api/auth/code/confirm disabled", flush=True)

    @router.post('/code/request')
    async def auth_code_request():
        _gc_login_codes()
        code = _gen_login_code()
        _login_codes[code] = {'created': _t.time(), 'status': 'pending'}
        return {
            'code': code,
            'expires_in': LOGIN_CODE_TTL,
            'bot_username': os.getenv('BOT_USERNAME', 'Real_Madrid_football_bot'),
        }

    @router.get('/code/check')
    async def auth_code_check(code: str):
        _gc_login_codes()
        rec = _login_codes.get(code)
        if not rec:
            return {'status': 'expired'}
        if rec['status'] != 'ok':
            return {'status': 'pending'}
        out = {'status': 'ok', 'auth': rec.get('auth_qs', ''), 'user': rec.get('user', {})}
        _login_codes.pop(code, None)
        return out

    @router.post('/code/confirm')
    async def auth_code_confirm(req: _CodeConfirmReq, x_internal_secret: str = Header(None, alias='X-Internal-Secret')):
        if not _INTERNAL_SECRET_OK:
            raise HTTPException(status_code=503, detail='auth bridge disabled')
        if not x_internal_secret or not hmac.compare_digest(x_internal_secret, INTERNAL_API_SECRET):
            raise HTTPException(status_code=403, detail='forbidden')
        _gc_login_codes()
        rec = _login_codes.get(req.code)
        if not rec:
            raise HTTPException(status_code=404, detail='code not found or expired')
        qs = _sign_login_widget(req.user_id, req.first_name, req.last_name, req.username, req.photo_url)
        rec['status'] = 'ok'
        rec['auth_qs'] = qs
        rec['user'] = {
            'id': req.user_id,
            'first_name': req.first_name,
            'last_name': req.last_name,
            'username': req.username,
            'photo_url': req.photo_url,
        }
        try:
            from database import get_or_create_user
            get_or_create_user(
                user_id=req.user_id,
                username=req.username or None,
                first_name=req.first_name or None,
                last_name=req.last_name or None,
            )
        except Exception as e:
            print(f'auth confirm get_or_create_user err: {e}', flush=True)
        return {'ok': True}
