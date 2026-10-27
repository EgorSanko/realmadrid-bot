/**
 * Два языка интерфейса: русский (исходный) и английский.
 *
 * Ключ перевода — сам русский текст: t('Прогнозов пока нет'). Английский словарь (src/i18n/en/*.ts)
 * грузится до первой отрисовки, только когда язык английский (main.tsx); русским он не нужен.
 * Нет строки в словаре — показываем русский текст: недопереведённое видно, но ничего не ломается.
 *
 * Язык выбирается один раз на загрузку страницы: сохранённый выбор (переключатель RU / EN) →
 * ?lang= в адресе → язык Telegram → язык браузера. Русский — для ru и близких языков, остальным — английский.
 * Смена языка — перезагрузка страницы (setLang): так тексты в константах модулей тоже переводятся.
 */

export type Lang = 'ru' | 'en';

const KEY = 'rmLang';
/** языки, на которых человеку удобнее русский интерфейс; тот же список — у бота (backend/app/bot.py) */
const RU_LANGS = new Set(['ru', 'uk', 'be', 'kk', 'ky', 'uz', 'tg', 'hy', 'az', 'ka', 'tk', 'ro']);

export function langFromCode(code: string | null | undefined): Lang | null {
  const c = String(code || '').toLowerCase().split(/[-_]/)[0];
  if (!c) return null;
  return RU_LANGS.has(c) ? 'ru' : 'en';
}

function stored(): Lang | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'ru' || v === 'en' ? v : null;
  } catch {
    return null;
  }
}

/** Язык Telegram из initData мини-аппа (user.language_code). */
function telegramCode(initData: string | null): string | null {
  if (!initData) return null;
  try {
    const user = JSON.parse(new URLSearchParams(initData).get('user') || 'null') as { language_code?: string } | null;
    return user?.language_code ?? null;
  } catch {
    return null;
  }
}

export function detectLang(initData: string | null = null): Lang {
  const saved = stored();
  if (saved) return saved;
  if (typeof location !== 'undefined') {
    const q = new URLSearchParams(location.search).get('lang');
    if (q === 'ru' || q === 'en') return q;
  }
  const tg = langFromCode(telegramCode(initData));
  if (tg) return tg;
  if (typeof navigator !== 'undefined') {
    for (const l of navigator.languages ?? [navigator.language]) {
      const v = langFromCode(l);
      if (v) return v;
    }
  }
  return 'ru';
}

let current: Lang = 'ru';
let dict: Record<string, string> = {};

/** Текущий язык (на всю загрузку страницы). */
export function lang(): Lang {
  return current;
}

export const isEn = (): boolean => current === 'en';

/** Включить язык и словарь — main.tsx до импорта приложения; тесты — для проверки английского. */
export function applyLang(l: Lang, d: Record<string, string> = {}): void {
  current = l;
  dict = l === 'en' ? d : {};
  if (typeof document !== 'undefined') document.documentElement.lang = l;
}

/** Сменить язык: запомнить и перезагрузить страницу. */
export function setLang(l: Lang): void {
  try {
    localStorage.setItem(KEY, l);
  } catch {
    /* приватный режим — язык всё равно сменится на эту загрузку */
  }
  const u = new URL(location.href);
  u.searchParams.set('lang', l);
  location.replace(u.toString());
}

function fill(s: string, vars?: Record<string, string | number>): string {
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
}

/**
 * Перевод: t('Ты {place}-й из {total}', { place, total }).
 * Подстановки — {имя}; в английском словаре те же имена: 'You are #{place} of {total}'.
 */
export function t(ru: string, vars?: Record<string, string | number>): string {
  return fill(current === 'en' ? (dict[ru] ?? ru) : ru, vars);
}

/**
 * Формы для plural(): в словаре ключ 'матч|матча|матчей' → 'match|matches' (единственное|множественное).
 * Без строки в словаре — русские формы.
 */
export function pluralEn(n: number, forms: [string, string, string]): string | null {
  if (current !== 'en') return null;
  const en = dict[forms.join('|')];
  if (!en) return null;
  const [one, many = one] = en.split('|');
  return Math.abs(n) === 1 ? one : many;
}

/**
 * Адрес запроса к нашему API на текущем языке: по-английски — с lang=en (сервер переводит новости, видео,
 * викторину; остальным ручкам параметр безразличен). Отдельный адрес — отдельный кэш браузера на язык.
 */
export function withLang(path: string): string {
  if (current !== 'en' || !path.startsWith('/api/') || /[?&]lang=/.test(path)) return path;
  return path + (path.includes('?') ? '&' : '?') + 'lang=en';
}
