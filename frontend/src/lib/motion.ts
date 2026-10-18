/**
 * Маленькие помощники моушена на Web Animations: только transform и opacity.
 * Всё уважает prefers-reduced-motion и молча ничего не делает там, где нет element.animate.
 */

export function reducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

const canAnimate = (el: Element | null | undefined): el is HTMLElement =>
  !!el && typeof (el as HTMLElement).animate === 'function' && !reducedMotion();

export const EASE_OUT = 'cubic-bezier(.22,1,.36,1)';
export const EASE_SPRING = 'cubic-bezier(.34,1.56,.64,1)';

/** «Штамп»: карточка вдавливается и пружинит обратно, по контуру расходится золотое кольцо. */
export function stamp(el: HTMLElement | null | undefined): void {
  if (!canAnimate(el)) return;
  el.animate(
    [
      { transform: 'none' },
      { transform: 'scale(.965)', offset: 0.22 },
      { transform: 'scale(1.012)', offset: 0.6 },
      { transform: 'none' },
    ],
    { duration: 520, easing: 'cubic-bezier(.3,.7,.4,1)' },
  );
  const r = el.getBoundingClientRect();
  const ring = document.createElement('i');
  ring.className = 'mo-ring';
  const cs = getComputedStyle(el);
  Object.assign(ring.style, {
    left: `${r.left}px`,
    top: `${r.top}px`,
    width: `${r.width}px`,
    height: `${r.height}px`,
    borderRadius: cs.borderRadius,
  });
  document.body.appendChild(ring);
  ring
    .animate(
      [
        { transform: 'scale(.99)', opacity: 0.95 },
        { transform: `scale(${1 + 28 / Math.max(r.width, 1)}, ${1 + 28 / Math.max(r.height, 1)})`, opacity: 0 },
      ],
      { duration: 620, delay: 90, easing: EASE_OUT, fill: 'both' },
    )
    .finished.finally(() => ring.remove())
    .catch(() => undefined);
}

/** Пульс-отклик цели (плитка очков, место): короткая пружина. */
export function pop(el: Element | null | undefined, scale = 1.08): void {
  if (!canAnimate(el)) return;
  el.animate([{ transform: 'none' }, { transform: `scale(${scale})`, offset: 0.4 }, { transform: 'none' }], {
    duration: 460,
    easing: EASE_SPRING,
  });
}

/**
 * Искра: золотая точка с хвостом летит по дуге от from к to (X и Y — разные кривые, отсюда дуга).
 * Возвращает промис прилёта.
 */
export function spark(from: Element | DOMRect | null | undefined, to: Element | null | undefined): Promise<void> {
  if (!from || !canAnimate(to)) return Promise.resolve();
  const a = from instanceof Element ? from.getBoundingClientRect() : from;
  const b = to.getBoundingClientRect();
  const x0 = a.left + a.width / 2;
  const y0 = a.top + a.height / 2;
  const dx = b.left + b.width / 2 - x0;
  const dy = b.top + b.height / 2 - y0;
  const dur = Math.min(720, Math.max(420, Math.hypot(dx, dy) * 0.9));
  const done: Promise<unknown>[] = [];
  [0, 1, 2, 3].forEach((i) => {
    const ox = document.createElement('i');
    const dot = document.createElement('i');
    ox.className = 'mo-spark';
    dot.className = i === 0 ? 'mo-spark__dot' : 'mo-spark__dot mo-spark__dot--tail';
    ox.style.left = `${x0}px`;
    ox.style.top = `${y0}px`;
    ox.appendChild(dot);
    document.body.appendChild(ox);
    const t = { duration: dur, delay: i * 26, fill: 'both' as const };
    const s = 1 - i * 0.22;
    done.push(
      ox.animate([{ transform: 'translateX(0)' }, { transform: `translateX(${dx}px)` }], { ...t, easing: 'cubic-bezier(.45,0,.75,.6)' }).finished,
      dot
        .animate(
          [
            { transform: `translateY(0) scale(${0.4 * s})`, opacity: 0 },
            { transform: `translateY(${dy * 0.25}px) scale(${s})`, opacity: 1, offset: 0.18 },
            { transform: `translateY(${dy}px) scale(${0.55 * s})`, opacity: i ? 0 : 1 },
          ],
          { ...t, easing: 'cubic-bezier(.15,.65,.35,1)' },
        )
        .finished.finally(() => ox.remove()),
    );
  });
  return Promise.all(done.map((p) => p.catch(() => undefined))).then(() => undefined);
}
