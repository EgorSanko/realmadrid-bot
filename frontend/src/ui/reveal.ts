import { useCallback, useEffect, useRef, useState, type RefCallback } from 'react';

/**
 * Один раз «в кадре»: false, пока элемент не показался на экране хотя бы на долю threshold, потом true
 * навсегда (повторные прокрутки и перерисовки опроса анимацию не перезапускают).
 * Нет IntersectionObserver — сразу true.
 */
export function useInViewOnce<T extends Element>(threshold = 0.25): [RefCallback<T>, boolean] {
  const [seen, setSeen] = useState(false);
  const io = useRef<IntersectionObserver | null>(null);
  const ref = useCallback(
    (el: T | null) => {
      io.current?.disconnect();
      io.current = null;
      if (!el || seen) return;
      if (typeof IntersectionObserver !== 'function') return setSeen(true);
      io.current = new IntersectionObserver(
        (es) => {
          if (es.some((e) => e.isIntersecting)) {
            io.current?.disconnect();
            setSeen(true);
          }
        },
        { threshold },
      );
      io.current.observe(el);
    },
    [seen, threshold],
  );
  useEffect(() => () => io.current?.disconnect(), []);
  return [ref, seen];
}
