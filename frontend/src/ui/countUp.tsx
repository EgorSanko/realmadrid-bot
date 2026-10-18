import { useLayoutEffect, useRef } from 'react';

/*
 * Число, которое «отсчитывается» к новому значению (count-up). Пишет в textContent сам, без перерисовок
 * React на каждом кадре; ширину держит font-variant-numeric: tabular-nums родителя — вёрстка не прыгает.
 * fromZero — при появлении считает от нуля (один раз за монтирование); дальше — только при смене значения.
 * reduce motion — сразу итоговое число.
 */

const ease = (t: number) => 1 - Math.pow(1 - t, 4);

export interface CountUpProps {
  value: number;
  fromZero?: boolean;
  /** мс */
  duration?: number;
  className?: string;
  /** вызов, когда счёт дошёл до конца (для «отклика» плитки) */
  onDone?: () => void;
}

export function CountUp({ value, fromZero, duration = 750, className, onDone }: CountUpProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const shown = useRef<number | null>(fromZero ? 0 : null);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const from = shown.current;
    const reduce = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (from == null || from === value || reduce || !Number.isFinite(from)) {
      shown.current = value;
      el.textContent = String(value);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / duration);
      const v = Math.round(from + (value - from) * ease(k));
      el.textContent = String(v);
      shown.current = v;
      if (k < 1) raf = requestAnimationFrame(step);
      else doneRef.current?.();
    };
    el.textContent = String(from);
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);

  // текст ставит только эффект (до первой отрисовки): React не держит здесь своих текстовых узлов
  return <span ref={ref} className={className} />;
}
