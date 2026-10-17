import { acceptSession, authFetch, type AuthResponse, type AuthUser } from './auth';

/**
 * Вход на сайте по коду через бота (backend/app/auth_api.py, app/bot.py).
 *
 * POST /api/auth/code → 6 цифр и deep link `t.me/<бот>?start=login_<токен>`. Секретный nonce сервер
 * кладёт в HttpOnly-cookie этого браузера — сюда он не попадает. Человек жмёт «Старт» в боте
 * (или присылает 6 цифр), а сайт раз в 1,5 с спрашивает GET /api/auth/code/status: подтверждено —
 * сервер выдаёт сессию этому же браузеру (cookie + token), как при обычном входе.
 */

export const POLL_MS = 1500;

export interface LoginCode {
  code: string;
  deepLink: string;
  bot: string;
  /** когда код истечёт — по часам браузера (сервер отдаёт срок в секундах, без расхождения часов) */
  expiresAt: number;
}

interface CodeResponse {
  code: string;
  deep_link: string;
  bot: string;
  ttl: number;
  expires_at: string;
}

type StatusResponse = { status: 'pending'; ttl: number } | { status: 'expired' | 'missing' } | (AuthResponse & { status: 'ok' });

export async function requestCode(now: () => number = Date.now): Promise<LoginCode> {
  const r = await authFetch<CodeResponse>('/api/auth/code', { method: 'POST' });
  return { code: r.code, deepLink: r.deep_link, bot: r.bot, expiresAt: now() + r.ttl * 1000 };
}

export type CodeCheck = { state: 'pending' } | { state: 'expired' } | { state: 'ok'; user: AuthUser | null };

/** Один опрос. Подтверждено — сессия принимается сразу (как signIn). */
export async function checkCode(signal?: AbortSignal): Promise<CodeCheck> {
  const r = await authFetch<StatusResponse>('/api/auth/code/status', { signal });
  if (r.status === 'pending') return { state: 'pending' };
  if (r.status === 'ok') {
    const st = acceptSession(r);
    return { state: 'ok', user: st.user };
  }
  return { state: 'expired' };
}
