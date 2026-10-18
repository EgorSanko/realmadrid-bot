/**
 * «Общий элемент» между экранами своими силами (FLIP): экран-источник запоминает, где стояли картинки,
 * экран-приёмник, когда его элементы появились, проигрывает их полёт из старых мест в новые.
 * View Transitions API здесь не подходит: экран матча — ленивый чанк и рисует шапку только после ответа
 * /api/match, а снимок «после» View Transition делает сразу — общего элемента в нём ещё нет.
 */

const store = new Map<string, { rects: DOMRect[]; at: number }>();

export function rememberRects(key: string, rects: DOMRect[]): void {
  store.clear(); // помним только последний переход
  store.set(key, { rects, at: Date.now() });
}

/** Забрать прямоугольники (один раз), если переход был недавно. */
export function takeRects(key: string, maxAgeMs = 2500): DOMRect[] | null {
  const v = store.get(key);
  store.delete(key);
  return v && Date.now() - v.at <= maxAgeMs ? v.rects : null;
}

/** Полёт элемента из прямоугольника from на его текущее место (translate + scale). */
export function flyFrom(el: HTMLElement, from: DOMRect, duration = 480, delay = 0): Animation | null {
  if (typeof el.animate !== 'function') return null;
  const to = el.getBoundingClientRect();
  if (!to.width || !from.width) return null;
  const dx = from.left + from.width / 2 - (to.left + to.width / 2);
  const dy = from.top + from.height / 2 - (to.top + to.height / 2);
  const s = from.width / to.width;
  return el.animate([{ transform: `translate(${dx}px, ${dy}px) scale(${s})` }, { transform: 'none' }], {
    duration,
    delay,
    easing: 'cubic-bezier(.3,1.15,.45,1)',
    fill: 'backwards',
  });
}
