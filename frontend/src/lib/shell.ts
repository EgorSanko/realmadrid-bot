import { useSyncExternalStore } from 'react';

/*
 * Две оболочки над общими экранами.
 *  — TMA: внутри Telegram. Всё как было: нижнее меню, нативная «Назад», раскладка телефона на любой ширине.
 *  — Сайт: обычный браузер. До 1024 px — та же мобильная раскладка (с нижним меню),
 *    от 1024 px — десктоп: верхняя шапка, подвал, многоколоночные раскладки.
 *
 * На <html> ставится класс: .tma (его ставит telegram.ts) или .site, и .desk — только на сайте шире 1024 px.
 * Десктопные стили пишутся под html.desk, а не под @media: так в мини-аппе (даже в широком окне
 * Telegram Desktop) они не включатся никогда.
 *
 * Третья оболочка — Android-приложение из RuStore (android/, WebView на этот же сайт). Оно дописывает к
 * User-Agent « MadridistaApp/<версия> (Android; RuStore)». Раскладка та же, что у сайта на телефоне, плюс
 * класс .app-native на <html>. В приложении нет трансляции (ни блока, ни бейджа «В ЭФИРЕ», ни опроса
 * /api/stream, плеер не монтируется) и нет виджета входа Telegram (в WebView он не работает).
 */

/** Признак нашего Android-приложения в User-Agent. */
export const NATIVE_APP_UA = /\bMadridistaApp\/\d/;

/** Это User-Agent нашего приложения из RuStore? (отдельно — для тестов) */
export function isNativeAppUa(ua: string | null | undefined): boolean {
  return !!ua && NATIVE_APP_UA.test(ua);
}

const nativeApp = typeof navigator !== 'undefined' && isNativeAppUa(navigator.userAgent);

/** Мы внутри Android-приложения «Мадридиста» (RuStore)? */
export function isNativeApp(): boolean {
  return nativeApp;
}

export const DESKTOP_MIN_PX = 1024;
const QUERY = `(min-width: ${DESKTOP_MIN_PX}px)`;

let telegram = false;
let mql: MediaQueryList | null = null;
const listeners = new Set<() => void>();

function current(): boolean {
  if (telegram || typeof window === 'undefined' || !window.matchMedia) return false;
  mql ??= window.matchMedia(QUERY);
  return mql.matches;
}

function apply(): void {
  document.documentElement.classList.toggle('desk', current());
}

/** Вызывается один раз при старте, до первой отрисовки. */
export function initShell(inTelegram: boolean): void {
  telegram = inTelegram;
  const root = document.documentElement;
  if (!inTelegram) root.classList.add('site');
  if (!inTelegram && nativeApp) root.classList.add('app-native');
  apply();
  if (inTelegram || !window.matchMedia) return;
  mql ??= window.matchMedia(QUERY);
  mql.addEventListener('change', () => {
    apply();
    listeners.forEach((l) => l());
  });
}

/** Мы внутри Telegram (мини-апп)? */
export function isTelegramShell(): boolean {
  return telegram;
}

/** Сейчас десктопная раскладка сайта (не мини-апп, ширина ≥ 1024 px). */
export function isDesktop(): boolean {
  return current();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** То же, что isDesktop(), но перерисовывает компонент при пересечении 1024 px. */
export function useDesktop(): boolean {
  return useSyncExternalStore(subscribe, current, () => false);
}
