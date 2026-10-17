/*
 * Мост к Android-приложению из RuStore (android/…/NativeBridge.kt): объект `window.MadridistaNative`.
 * На сайте и в мини-аппе его нет — функции возвращают false, и работает обычный путь.
 */

interface MadridistaNative {
  version(): string;
  share(text: string | null, url: string | null): void;
  addToCalendar(title: string, startMs: number, endMs: number, location: string | null, description: string | null): void;
}

function bridge(): MadridistaNative | null {
  if (typeof window === 'undefined') return null;
  const b = (window as unknown as { MadridistaNative?: MadridistaNative }).MadridistaNative;
  return b && typeof b.share === 'function' ? b : null;
}

/** Системное меню «Поделиться» Android. true — меню открыто. */
export function nativeShare(url: string, text: string): boolean {
  const b = bridge();
  if (!b) return false;
  try {
    b.share(text, url);
    return true;
  } catch {
    return false;
  }
}

/** Можно ли добавить событие в календарь устройства (только в приложении). */
export function canAddToCalendar(): boolean {
  const b = bridge();
  return !!b && typeof b.addToCalendar === 'function';
}

/** Матч → экран нового события календаря Android (сохраняет человек сам). Длительность — 2 часа. */
export function addMatchToCalendar(title: string, kickoffIso: string, location: string | null, description: string): boolean {
  const b = bridge();
  const start = Date.parse(kickoffIso);
  if (!b || typeof b.addToCalendar !== 'function' || !Number.isFinite(start)) return false;
  try {
    b.addToCalendar(title, start, start + 2 * 60 * 60 * 1000, location, description);
    return true;
  } catch {
    return false;
  }
}
