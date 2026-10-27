/** Время и тексты для интерфейса. Всё время показываем по Москве; язык — lib/i18n (RU / EN). */

import { isEn, pluralEn } from '../lib/i18n';

export type DateInput = Date | string | number;

export const MSK_TZ = 'Europe/Moscow';

export function toMs(d: DateInput): number {
  return d instanceof Date ? d.getTime() : typeof d === 'number' ? d : Date.parse(d);
}

const MONTH_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const MONTH_LONG = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
];
const WEEKDAY = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
const MONTH_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH_LONG_EN = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];
const monthShort = (m: number) => (isEn() ? MONTH_EN : MONTH_SHORT)[m];
const monthLong = (m: number) => (isEn() ? MONTH_LONG_EN : MONTH_LONG)[m];
const weekday = (w: number) => (isEn() ? WD_EN : WEEKDAY)[w];

interface MskParts {
  year: number;
  month: number; // 0..11
  day: number;
  weekday: number; // 0 = вс
  hh: string;
  mm: string;
}

// Москва живёт в UTC+3 без перехода на летнее время с 2014 года,
// но берём смещение из Intl, чтобы не зашивать его.
const partsFmt = new Intl.DateTimeFormat('en-GB', {
  timeZone: MSK_TZ,
  year: 'numeric',
  month: 'numeric',
  day: 'numeric',
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});
const WD_EN = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export function mskParts(d: DateInput): MskParts {
  const p: Record<string, string> = {};
  for (const x of partsFmt.formatToParts(new Date(toMs(d)))) p[x.type] = x.value;
  return {
    year: +p.year,
    month: +p.month - 1,
    day: +p.day,
    weekday: WD_EN.indexOf(p.weekday),
    hh: p.hour === '24' ? '00' : p.hour,
    mm: p.minute,
  };
}

/** «22:00» */
export function formatTime(d: DateInput): string {
  const p = mskParts(d);
  return `${p.hh}:${p.mm}`;
}

/** «14 окт» · «14 Oct» */
export function formatDayShort(d: DateInput): string {
  const p = mskParts(d);
  return `${p.day} ${monthShort(p.month)}`;
}

/** «Вс, 18 окт» · «Sun, 18 Oct» */
export function formatWeekdayShort(d: DateInput): string {
  const p = mskParts(d);
  return `${weekday(p.weekday)}, ${p.day} ${monthShort(p.month)}`;
}

/** «Вс, 18 октября · 22:00 МСК» · «Sun, 18 October · 22:00 MSK» */
export function formatKickoff(d: DateInput): string {
  const p = mskParts(d);
  return `${weekday(p.weekday)}, ${p.day} ${monthLong(p.month)} · ${p.hh}:${p.mm} ${isEn() ? 'MSK' : 'МСК'}`;
}

/** Название месяца: «октября» / «October» (для дат в тексте). */
export function monthName(m: number): string {
  return monthLong(m);
}

/** plural(5, ['день', 'дня', 'дней']) → «дней»; по-английски — из словаря: 'день|дня|дней' → 'day|days' */
export function plural(n: number, forms: [string, string, string]): string {
  const en = pluralEn(n, forms);
  if (en != null) return en;
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b > 1 && b < 5) return forms[1];
  if (b === 1) return forms[0];
  return forms[2];
}

/** «25′», «90+3′» */
export function formatMinute(minute: number, added?: number): string {
  return added ? `${minute}+${added}′` : `${minute}′`;
}

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}
