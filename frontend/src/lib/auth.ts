import { useSyncExternalStore } from 'react';
import { retrieveRawInitData } from '@tma.js/sdk-react';

/**
 * Вход через Telegram (backend/app/auth_api.py).
 *
 * Мини-апп: при старте тихо POST /api/auth/telegram {initData} — без кнопок.
 * Сайт: GET /api/auth/me по cookie rm_session; вход — по коду через бота (lib/codeLogin.ts),
 * запасной путь — Telegram Login Widget (lib/telegramWidget.ts).
 * Сессию сервер кладёт в HttpOnly-cookie и дублирует в ответе — значение держим только в памяти
 * и шлём заголовком `Authorization: Session …` (на случай, если cookie не работают, например
 * в Telegram Web внутри iframe). Без сессии в мини-аппе — заголовок `tma <initData>`.
 */

export interface AuthUser {
  id: number;
  name: string;
  first_name: string;
  last_name: string | null;
  username: string | null;
  /** наш файл /img/avatar/{id}.jpg?v=… или null — тогда силуэт */
  avatar: string | null;
}

export interface AuthState {
  /** loading — ещё не знаем; anon — не вошёл; user — вошёл */
  status: 'loading' | 'anon' | 'user';
  user: AuthUser | null;
  isAdmin: boolean;
  /** start_param из подписанного initData (мини-апп) */
  startParam: string | null;
}

export interface AuthResponse {
  user: AuthUser | null;
  is_admin: boolean;
  token?: string;
  start_param?: string | null;
}

export const BOT_USERNAME = 'Real_Madrid_football_bot';
export const BOT_PROFILE_LINK = `https://t.me/${BOT_USERNAME}?startapp=profile`;

let state: AuthState = { status: 'loading', user: null, isAdmin: false, startParam: null };
let token: string | null = null;
const listeners = new Set<() => void>();
let ready: Promise<AuthState> | null = null;

function set(next: Partial<AuthState>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

export function getAuth(): AuthState {
  return state;
}

export function useAuth(): AuthState {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
    () => state,
  );
}

/** Внутри мини-аппа (initTelegram пометил <html class="tma">). */
export function inMiniApp(): boolean {
  return typeof document !== 'undefined' && document.documentElement.classList.contains('tma');
}

export function telegramInitData(): string | null {
  if (!inMiniApp()) return null;
  try {
    return retrieveRawInitData() || null;
  } catch {
    return null;
  }
}

/** Заголовки входа для запросов к нашему API. Cookie браузер добавит сам (тот же сайт). */
export function authHeaders(): Record<string, string> {
  if (token) return { Authorization: `Session ${token}` };
  const init = telegramInitData();
  if (init) return { Authorization: `tma ${init}` };
  return {};
}

export class AuthFetchError extends Error {
  status: number;
  code: string | null;
  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = 'AuthFetchError';
    this.status = status;
    this.code = code;
  }
}

/** Запрос к нашему API с входом. Ошибка — AuthFetchError с русским сообщением сервера. */
export async function authFetch<T>(
  path: string,
  init: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, {
      method: init.method ?? 'GET',
      cache: 'no-store',
      credentials: 'same-origin',
      signal: init.signal,
      headers: {
        Accept: 'application/json',
        ...authHeaders(),
        ...(init.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new AuthFetchError(0, null, 'Нет соединения');
  }
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    /* не JSON */
  }
  if (!r.ok) {
    const b = (body ?? {}) as { error?: unknown; message?: unknown; detail?: unknown };
    const msg = typeof b.message === 'string' ? b.message : typeof b.detail === 'string' ? b.detail : `Ошибка сервера (${r.status})`;
    throw new AuthFetchError(r.status, typeof b.error === 'string' ? b.error : null, msg);
  }
  return body as T;
}

let avatarRetries = 0;

function apply(r: AuthResponse) {
  if (r.token) token = r.token;
  set({
    status: r.user ? 'user' : 'anon',
    user: r.user,
    isAdmin: !!r.user && !!r.is_admin,
    startParam: r.start_param ?? state.startParam,
  });
  // при первом входе аватар ещё не скачан (сборщик качает его через туннель) — дважды перечитываем
  if (r.user && !r.user.avatar && avatarRetries < 2) {
    const delay = avatarRetries === 0 ? 5000 : 15000;
    avatarRetries += 1;
    window.setTimeout(() => void refreshMe(), delay);
  }
}

/** Принять сессию, выданную сервером (вход по коду). */
export function acceptSession(r: AuthResponse): AuthState {
  apply(r);
  return state;
}

/** Отправить данные входа (initData или Login Widget). */
export async function signIn(payload: Record<string, unknown>): Promise<AuthState> {
  const r = await authFetch<AuthResponse>('/api/auth/telegram', { method: 'POST', body: payload });
  apply(r);
  return state;
}

/**
 * Узнать, кто мы, при старте приложения. В мини-аппе — тихий вход по initData;
 * на сайте — /api/auth/me по cookie. Ошибки не показываем: просто «не вошёл».
 */
export function bootstrapAuth(): Promise<AuthState> {
  if (ready) return ready;
  ready = (async () => {
    const init = telegramInitData();
    if (init) {
      try {
        return await signIn({ initData: init });
      } catch (e) {
        // сервер недоступен — запросы пойдут с tma-заголовком, вход повторится при следующем запуске
        console.warn('[auth] вход по initData не удался', (e as Error).message);
      }
    }
    try {
      apply(await authFetch<AuthResponse>('/api/auth/me'));
    } catch {
      set({ status: 'anon', user: null, isAdmin: false });
    }
    return state;
  })();
  return ready;
}

/** Обновить данные пользователя (например, аватар уже скачан). */
export async function refreshMe(): Promise<void> {
  try {
    apply(await authFetch<AuthResponse>('/api/auth/me'));
  } catch {
    /* оставляем, что было */
  }
}

export async function signOut(): Promise<void> {
  try {
    await authFetch('/api/auth/logout', { method: 'POST' });
  } catch {
    /* cookie сотрётся при следующем /me; локально выходим в любом случае */
  }
  token = null;
  avatarRetries = 0;
  set({ status: 'anon', user: null, isAdmin: false });
}

/** Для тестов. */
export function _resetAuth() {
  state = { status: 'loading', user: null, isAdmin: false, startParam: null };
  token = null;
  ready = null;
}
