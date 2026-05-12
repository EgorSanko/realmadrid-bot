// src/lib/auth.js — авторизация: одна логика, две стратегии.
//
// WebApp:   получаем initData из window.Telegram.WebApp, шлём как Authorization header.
// Site:     code-based login (POST /auth/code/request → ссылка на бота → юзер жмёт
//           → бот POST /auth/code/confirm → клиент опрашивает /auth/code/check →
//           получает подписанный querystring и кладёт в localStorage).
//
// AUTH_MODE = 'tg-initdata' | 'login-widget' определяется build-time через .env.<mode>.

import { AUTH_MODE, API_BASE, BOT_USERNAME } from '@/config/features.js';

const SITE_AUTH_KEY = 'rm_auth_v1';

// ─── WebApp: Telegram WebApp initData ────────────────────────────────────────

function getTgInitData() {
  if (typeof window === 'undefined') return null;
  return window.Telegram?.WebApp?.initData || null;
}

// ─── Site: Login Widget code flow ────────────────────────────────────────────

function getSiteAuth() {
  try {
    const raw = localStorage.getItem(SITE_AUTH_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    // Должен содержать { qs, user }; qs — подписанная Login Widget строка.
    return parsed?.qs ? parsed : null;
  } catch {
    return null;
  }
}

function setSiteAuth(auth) {
  localStorage.setItem(SITE_AUTH_KEY, JSON.stringify(auth));
}

export function clearSiteAuth() {
  localStorage.removeItem(SITE_AUTH_KEY);
}

// ─── Унифицированный API ─────────────────────────────────────────────────────

/** Заголовок Authorization для текущего пользователя (null если не залогинен). */
export function authHeader() {
  if (AUTH_MODE === 'tg-initdata') {
    const initData = getTgInitData();
    return initData ? { Authorization: initData } : null;
  }
  // site
  const auth = getSiteAuth();
  return auth?.qs ? { Authorization: auth.qs } : null;
}

/** Залогинен ли. */
export function isAuthenticated() {
  return !!authHeader();
}

/** Текущий пользователь (для site — из localStorage, для webapp — из initData). */
export function currentUser() {
  if (AUTH_MODE === 'tg-initdata') {
    return window.Telegram?.WebApp?.initDataUnsafe?.user || null;
  }
  return getSiteAuth()?.user || null;
}

// ─── Site: code-based login flow ─────────────────────────────────────────────

export async function requestLoginCode() {
  const r = await fetch(`${API_BASE}/auth/code/request`, { method: 'POST' });
  if (!r.ok) throw new Error(`code/request ${r.status}`);
  return r.json();  // { code, expires_in, bot_username }
}

export async function pollLoginCode(code, { intervalMs = 1500, timeoutMs = 600000 } = {}) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const r = await fetch(`${API_BASE}/auth/code/check?code=${encodeURIComponent(code)}`);
    if (r.ok) {
      const j = await r.json();
      if (j.status === 'ok') {
        setSiteAuth({ qs: j.auth, user: j.user });
        return j.user;
      }
      if (j.status === 'expired') throw new Error('Код истёк, запросите новый');
    }
    await new Promise((res) => setTimeout(res, intervalMs));
  }
  throw new Error('Timeout: код не подтверждён');
}

export function botStartLink(code) {
  const username = BOT_USERNAME || 'Real_Madrid_football_bot';
  return `https://t.me/${username}?start=${encodeURIComponent(code)}`;
}
