import { useEffect, useLayoutEffect, useRef } from 'react';

/** Что считаем якорем: крупные блоки экрана матча. */
const ANCHORS = '.mt > section, .mt > nav, .mt-body > section, .mt-body > div > section, .mt-body > a';

function nativeAnchoring(): boolean {
  try {
    if (typeof CSS === 'undefined' || !CSS.supports('overflow-anchor', 'auto')) return false;
    const root = document.scrollingElement ?? document.documentElement;
    return getComputedStyle(root).overflowAnchor !== 'none' && getComputedStyle(document.body).overflowAnchor !== 'none';
  } catch {
    return false;
  }
}

function pickAnchor(): { el: Element; top: number } | null {
  for (const el of document.querySelectorAll(ANCHORS)) {
    const r = el.getBoundingClientRect();
    if (r.bottom > 0 && r.height > 0) return { el, top: r.top };
  }
  return null;
}

/**
 * Новые события в лайве не должны сдвигать то, что человек сейчас читает.
 * Chrome и Firefox делают это сами (CSS scroll anchoring); WebKit (Telegram на iOS) — нет.
 * Там, где нативного якоря нет, запоминаем верх первого видимого блока и после
 * обновления данных возвращаем его на место.
 */
export function useScrollAnchorFallback(dep: unknown): void {
  const anchor = useRef<{ el: Element; top: number } | null>(null);

  useEffect(() => {
    let raf = 0;
    const remember = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        anchor.current = window.scrollY > 0 ? pickAnchor() : null;
      });
    };
    remember();
    window.addEventListener('scroll', remember, { passive: true });
    window.addEventListener('resize', remember);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('scroll', remember);
      window.removeEventListener('resize', remember);
    };
  }, []);

  useLayoutEffect(() => {
    const a = anchor.current;
    if (!a || !a.el.isConnected || nativeAnchoring()) return;
    const delta = a.el.getBoundingClientRect().top - a.top;
    if (Math.abs(delta) >= 1) window.scrollBy(0, delta);
    anchor.current = { el: a.el, top: a.el.getBoundingClientRect().top };
  }, [dep]);
}
