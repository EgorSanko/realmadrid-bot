/**
 * Золотое конфетти без библиотек: геометрия (полоски, прямоугольники, точки, ромбы) на Web Animations.
 * Каждая частица — два слоя: X (снос, ease-out — «сопротивление воздуха») и сама частица: Y + поворот
 * (взлёт ease-out, падение ease-in — парабола, в конце почти ровное падение и растворение).
 * Только transform и opacity → всё считается на compositor, главный поток свободен.
 * Слои убираются сами по окончании. prefers-reduced-motion — вызывающий просто не зовёт burst.
 */

export interface BurstOptions {
  /** число частиц */
  count?: number;
  /** разлёт: угол «вверх» ± spread (градусы) */
  spread?: number;
  /** скорость, px/с: [мин, макс] */
  speed?: [number, number];
  /** длительность полёта, мс: [мин, макс] */
  duration?: [number, number];
  /** ускорение свободного падения, px/с² */
  gravity?: number;
  /** задержка старта, мс */
  delay?: number;
  /** начальный разброс точки вылета по X, px */
  jitter?: number;
}

const COLORS = ['#F4D57A', '#D4AF37', '#FFF3C4', '#B8922A', '#E9C75A'];
const SHAPES = ['strip', 'rect', 'dot', 'diamond', 'strip', 'rect'];

const rnd = (a: number, b: number) => a + Math.random() * (b - a);

/** Запускает залп из точки (0, 0) контейнера (контейнер — position:absolute/fixed, overflow visible). */
export function burst(host: HTMLElement, o: BurstOptions = {}): Promise<void> {
  const {
    count = 30,
    spread = 75,
    speed = [380, 720],
    duration = [1050, 1450],
    gravity = 1150,
    delay = 0,
    jitter = 24,
  } = o;
  if (typeof host.animate !== 'function') return Promise.resolve();
  const frag = document.createDocumentFragment();
  const anims: Animation[] = [];
  const nodes: HTMLElement[] = [];
  for (let i = 0; i < count; i++) {
    const T = rnd(duration[0], duration[1]);
    const t = T / 1000;
    const ang = ((-90 + rnd(-spread, spread)) * Math.PI) / 180;
    const v = rnd(speed[0], speed[1]);
    const vx = Math.cos(ang) * v;
    const vy = Math.sin(ang) * v; // < 0 — вверх
    const x0 = rnd(-jitter, jitter);
    const tPeak = Math.min(Math.max(-vy / gravity, 0.05 * t), 0.8 * t);
    const yPeak = vy * tPeak + 0.5 * gravity * tPeak * tPeak;
    const yEnd = vy * t + 0.5 * gravity * t * t;
    const xEnd = x0 + vx * t * 0.55; // воздух гасит снос
    const r0 = rnd(0, 360);
    const r1 = r0 + rnd(240, 720) * (Math.random() < 0.5 ? -1 : 1);
    const shape = SHAPES[i % SHAPES.length];
    const d = delay + rnd(0, 90);

    const ox = document.createElement('i');
    const p = document.createElement('i');
    ox.className = 'cf-x';
    p.className = `cf-p cf-p--${shape}`;
    p.style.background = COLORS[i % COLORS.length];
    ox.appendChild(p);
    frag.appendChild(ox);
    nodes.push(ox);

    const ax = { duration: T, delay: d, fill: 'both' as const };
    anims.push(
      ox.animate([{ transform: `translateX(${x0}px)` }, { transform: `translateX(${xEnd}px)` }], {
        ...ax,
        easing: 'cubic-bezier(.2,.75,.35,1)',
      }),
    );
    // взлёт (ease-out) → вершина → падение (ease-in) → растворение; поворот и «кувырок» — тут же
    const tumble = shape === 'strip' || shape === 'rect' ? r1 * 1.4 : 0;
    const fp = tPeak / t;
    const fo = Math.max(fp + 0.05, 0.72);
    const tf = (f: number, y: number) =>
      `translateY(${y}px) rotate(${r0 + (r1 - r0) * f}deg) rotate3d(1, .35, 0, ${tumble * f}deg) scale(${f === 0 ? 0.3 : 1})`;
    const yAt = (f: number) => vy * f * t + 0.5 * gravity * (f * t) ** 2;
    anims.push(
      p.animate(
        [
          { offset: 0, transform: tf(0, 0), opacity: 1, easing: 'cubic-bezier(.25,.7,.45,1)' },
          { offset: fp, transform: tf(fp, yPeak), opacity: 1, easing: 'cubic-bezier(.45,0,.8,.55)' },
          { offset: fo, transform: tf(fo, yAt(fo)), opacity: 1, easing: 'cubic-bezier(.3,.2,.6,.9)' },
          { offset: 1, transform: tf(1, yEnd), opacity: 0 },
        ],
        ax,
      ),
    );
  }
  host.appendChild(frag);
  return Promise.all(anims.map((a) => a.finished.catch(() => undefined))).then(() => {
    nodes.forEach((n) => n.remove());
  });
}
