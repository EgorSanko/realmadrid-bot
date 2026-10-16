/**
 * Срок действия ссылки поставщика (Nimble Streamer).
 * Ссылка вида …/chunks.m3u8?nimblesessionid=…&token=<base64url(JSON)>.<подпись>,
 * в JSON есть поле exp (unix-время, секунды). Если разобрать не удалось — null.
 */
export function linkExpiry(url: string): Date | null {
  try {
    const token = new URL(url.trim()).searchParams.get('token');
    if (!token) return null;
    const head = token.split('.')[0];
    if (!head || !/^[A-Za-z0-9_-]+={0,2}$/.test(head)) return null;
    const b64 = head.replace(/-/g, '+').replace(/_/g, '/').replace(/=+$/, '');
    const bin = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
    const json = new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
    const payload: unknown = JSON.parse(json);
    if (!payload || typeof payload !== 'object') return null;
    const exp = (payload as { exp?: unknown }).exp;
    if (typeof exp !== 'number' || !Number.isFinite(exp) || exp <= 0) return null;
    const d = new Date(exp * 1000);
    return Number.isNaN(d.getTime()) ? null : d;
  } catch {
    return null;
  }
}

const MSK = 'Europe/Moscow';

function mskParts(d: Date) {
  const f = new Intl.DateTimeFormat('ru-RU', {
    timeZone: MSK,
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  });
  const p = Object.fromEntries(f.formatToParts(d).map((x) => [x.type, x.value]));
  return { day: `${p.day}.${p.month}`, time: `${p.hour}:${p.minute}` };
}

/** «HH:MM» по Москве; если не сегодня (по МСК) — «ДД.ММ HH:MM». */
export function formatMsk(d: Date, now: Date = new Date()): string {
  const a = mskParts(d);
  return a.day === mskParts(now).day ? a.time : `${a.day} ${a.time}`;
}

export type ExpiryLevel = 'ok' | 'soon' | 'expired';

export interface ExpiryInfo {
  at: Date;
  level: ExpiryLevel;
  minutesLeft: number;
  text: string;
}

/** Готовая подпись для админки или null, если срок не удалось узнать. */
export function describeExpiry(url: string, now: Date = new Date()): ExpiryInfo | null {
  const at = linkExpiry(url);
  if (!at) return null;
  const minutesLeft = Math.floor((at.getTime() - now.getTime()) / 60000);
  const until = `${formatMsk(at, now)} (МСК)`;
  if (at.getTime() <= now.getTime()) {
    return { at, level: 'expired', minutesLeft, text: `Срок действия ссылки истёк в ${until}` };
  }
  if (minutesLeft < 30) {
    return {
      at,
      level: 'soon',
      minutesLeft,
      text: `Ссылка действует до ${until} — осталось меньше 30 мин`,
    };
  }
  return { at, level: 'ok', minutesLeft, text: `Ссылка действует до ${until}` };
}
