import { memo, useState, type CSSProperties } from 'react';
import { cx } from './format';

/*
 * Табло с перелистыванием (split-flap). Каждая буква — своя ячейка: когда она меняется, верхняя половина
 * старой цифры откидывается вниз, за ней на место падает нижняя половина новой (с лёгким отскоком).
 * Анимируются только transform (rotateX) и opacity; половинки режутся статичным clip-path.
 * При первой отрисовке и при тех же значениях ничего не происходит — листается только смена.
 * Ячейки ключуются с правого края: «9» → «10» добавляет цифру слева, а единицы листаются.
 * prefers-reduced-motion — слои листания не показываются, цифра просто меняется.
 */

interface FlipCharProps {
  ch: string;
  /** задержка листания, мс — чтобы соседние цифры падали не разом */
  delay: number;
}

const FlipChar = memo(function FlipChar({ ch, delay }: FlipCharProps) {
  const [st, setSt] = useState<{ cur: string; prev: string | null; n: number }>({ cur: ch, prev: null, n: 0 });
  // производное состояние: смена буквы запоминает прежнюю прямо в рендере (без лишнего кадра)
  if (st.cur !== ch) setSt({ cur: ch, prev: st.cur, n: st.n + 1 });
  const prev = st.cur !== ch ? st.cur : st.prev;
  const n = st.cur !== ch ? st.n + 1 : st.n;
  return (
    <span className={cx('ui-flip__c', prev != null && 'is-flip')}>
      <span className="ui-flip__b">{ch}</span>
      {prev != null && (
        <span
          key={n}
          className="ui-flip__fx"
          aria-hidden="true"
          style={delay ? ({ '--flip-d': `${delay}ms` } as CSSProperties) : undefined}
          onAnimationEnd={(e) => {
            if ((e.target as HTMLElement).classList.contains('ui-flip__fb')) setSt((s) => (s.n === n ? { ...s, prev: null } : s));
          }}
        >
          <span className="ui-flip__nt">{ch}</span>
          <span className="ui-flip__ob">{prev}</span>
          <span className="ui-flip__ft">{prev}</span>
          <span className="ui-flip__fb">{ch}</span>
        </span>
      )}
    </span>
  );
});

export interface FlipTextProps {
  value: string;
  className?: string;
  /** шаг задержки между ячейками справа налево, мс */
  stagger?: number;
}

/** Текст-табло: меняющиеся символы перелистываются. Пробелы не листаются. */
export function FlipText({ value, className, stagger = 0 }: FlipTextProps) {
  const chars = Array.from(value);
  const len = chars.length;
  return (
    <span className={cx('ui-flip', className)}>
      {chars.map((c, i) =>
        /\s/.test(c) ? (
          <span key={`s${len - i}`}>{c}</span>
        ) : (
          <FlipChar key={len - i} ch={c} delay={(len - 1 - i) * stagger} />
        ),
      )}
    </span>
  );
}

/** Счёт «2 : 1» как на табло: цифры каждой команды листаются отдельно. */
export function FlipScore({ score, className }: { score: [number, number]; className?: string }) {
  return (
    <span className={cx('ui-flip-score', className)}>
      <FlipText value={String(score[0])} />
      {' : '}
      <FlipText value={String(score[1])} />
    </span>
  );
}
