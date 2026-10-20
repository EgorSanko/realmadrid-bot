/*
 * Счётчик посещений без входа (backend/app/visits.py): сколько новых людей приходит каждый день.
 *
 * На устройстве — случайный id (crypto.randomUUID) в localStorage, больше ничего. Раз в календарный день
 * (по местной дате — только чтобы не слать лишнего; день для статистики считает сервер, по МСК) уходит
 * POST /api/visit {device, platform}. Запрос «выстрелил и забыл»: отрисовку не держит, при ошибке не повторяем
 * (день не отмечен — попробуем при следующем открытии). Без localStorage — id на время вкладки, в памяти.
 *
 * Модуль без импортов — чистые функции проверяются тестами (tests/visit.test.ts).
 */

export type VisitPlatform = 'tg' | 'android' | 'web';

export const DEVICE_KEY = 'rm-device';
export const SENT_KEY = 'rm-visit-day';

/** Где открыто: мини-апп Telegram (есть initData), наше Android-приложение (UA MadridistaApp) или сайт. */
export function detectPlatform(hasInitData: boolean, nativeApp: boolean): VisitPlatform {
  if (hasInitData) return 'tg';
  if (nativeApp) return 'android';
  return 'web';
}

/** Местная дата 'YYYY-MM-DD'. */
export function localDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Слать ли сегодня: не слали — да; уже слали в этот день — нет. */
export function shouldSend(lastSent: string | null, today: string): boolean {
  return lastSent !== today;
}

const DEVICE_RE = /^[A-Za-z0-9-]{16,64}$/;

export function isDeviceId(v: unknown): v is string {
  return typeof v === 'string' && DEVICE_RE.test(v);
}

function randomId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  } catch {
    /* не безопасный контекст */
  }
  // запасной путь для старых WebView: 32 hex-символа
  const b = new Uint8Array(16);
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') crypto.getRandomValues(b);
  else for (let i = 0; i < b.length; i++) b[i] = Math.floor(Math.random() * 256);
  return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
}

/** Хранилище с интерфейсом localStorage (в тестах — подмена). */
export interface KV {
  getItem(k: string): string | null;
  setItem(k: string, v: string): void;
}

let memoryId: string | null = null;

/** id устройства: из хранилища или новый. Хранилище недоступно — id живёт до закрытия вкладки. */
export function deviceId(store: KV | null): string {
  try {
    if (store) {
      const old = store.getItem(DEVICE_KEY);
      if (isDeviceId(old)) return old;
      const id = randomId();
      store.setItem(DEVICE_KEY, id);
      return id;
    }
  } catch {
    /* приватный режим, запрет cookie и хранилища */
  }
  memoryId ??= randomId();
  return memoryId;
}

function storage(): KV | null {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null;
  } catch {
    return null;
  }
}

let sentThisSession = false;

/**
 * Отметить посещение (не чаще раза в день). Возвращает промис, который никогда не падает.
 * headers — заголовки входа (если человек вошёл, сервер свяжет устройство с аккаунтом).
 */
export async function reportVisit(
  platform: VisitPlatform,
  headers: Record<string, string> = {},
  opts: { store?: KV | null; now?: Date; fetchFn?: typeof fetch } = {},
): Promise<boolean> {
  if (sentThisSession) return false;
  const store = opts.store !== undefined ? opts.store : storage();
  const today = localDay(opts.now ?? new Date());
  let last: string | null = null;
  try {
    last = store ? store.getItem(SENT_KEY) : null;
  } catch {
    last = null;
  }
  if (!shouldSend(last, today)) return false;
  sentThisSession = true; // одна попытка за открытие — никаких повторов
  const device = deviceId(store);
  try {
    const r = await (opts.fetchFn ?? fetch)('/api/visit', {
      method: 'POST',
      cache: 'no-store',
      credentials: 'same-origin',
      keepalive: true,
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify({ device, platform }),
    });
    if (!r.ok) return false;
    try {
      store?.setItem(SENT_KEY, today);
    } catch {
      /* не запомнилось — завтрашняя отметка всё равно одна: сервер считает раз в день */
    }
    return true;
  } catch {
    return false;
  }
}

/** Для тестов: сбросить состояние модуля. */
export function _resetVisit(): void {
  sentThisSession = false;
  memoryId = null;
}
