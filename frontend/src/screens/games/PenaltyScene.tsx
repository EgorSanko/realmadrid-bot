import { forwardRef, useCallback, useImperativeHandle, useLayoutEffect, useMemo, useRef } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import ballSrc from '../../assets/games/ball.webp';
import diveSrc from '../../assets/games/courtois-dive.webp';
import idleSrc from '../../assets/games/courtois-idle.webp';
import { zoneFromSwipe } from '../../lib/games';
import {
  BALL_SIZE,
  DIVE,
  GOAL,
  GOAL_LINE,
  IDLE,
  POST_W,
  SPOT,
  WORLD,
  catchPoint,
  cell,
  divePoint,
  diveTransform,
  ease,
  goalPoint,
  keeperPose,
  lerp,
  parryPoint,
  reboundPoint,
  woodPoint,
  zonePoint,
} from '../../lib/penalty';
import type { PenaltyOutcome, Pt } from '../../lib/penalty';
import { reducedMotion } from './kit';

/*
 * Сцена пенальти — вид от бьющего. Фон (стадион, прожекторы, газон, ворота с сеткой) — SVG.
 * Куртуа и мяч — картинки из старой игры (penalty.html) в слое «мира» 400×320, который
 * масштабируется под ширину сцены. Всё движение — requestAnimationFrame и только transform/opacity
 * (слои на GPU, без перерисовки React): стойка с раскачкой → присед → прыжок → сейв или гол.
 */

const { w: W, h: H } = WORLD;
const R = BALL_SIZE / 2;

/** тайминги, мс (при prefers-reduced-motion — короче) */
const T = {
  prepMin: 150, // присед перед ударом, пока сервер решает
  flight: 520, // полёт мяча
  diveDelay: 80, // вратарь стартует чуть позже удара
  dive: 440,
  hold: 110, // сейв: вратарь на миг замирает в прыжке, потом падает
  parry: 560, // сейв: мяч отлетает от перчаток в поле, отскакивает от газона
  fall: 380, // приземление вратаря
  net: 150, // гол: мяч продавливает сетку
  drop: 430, // гол: мяч падает в сетке
  rebound: 470, // штанга: отскок
};

export interface ShotPlan {
  zone: number;
  keeper: number;
  outcome: PenaltyOutcome;
  /** момент касания: перчатки, сетка или каркас — для вибрации и надписи */
  onImpact?: () => void;
}

export interface SceneHandle {
  /** присед вратаря сразу по нажатию — пока сервер решает исход */
  prepare(): void;
  /** проиграть удар; промис — когда всё отыграло (вратарь приземлился, мяч упал) */
  play(plan: ShotPlan): Promise<void>;
  reset(): void;
}

export interface FpsSample {
  frames: number;
  ms: number;
  fps: number;
  worst_ms: number;
  outcome: PenaltyOutcome;
}

declare global {
  interface Window {
    /** замер плавности последнего удара (для проверок Playwright) */
    __rmShotFps?: FpsSample[];
    /** только для проверок: «стоп-кадр» удара на этой миллисекунде (кадры для скриншотов) */
    __rmPkAt?: number;
  }
}

/** Конфетти: детерминированный разброс (одинаковый на каждом рендере). */
function confettiPieces(n: number) {
  const colors = ['#F4D57A', '#D4AF37', '#FFFFFF', '#EEF0F5', '#B8962E'];
  let seed = 7;
  const rnd = () => {
    seed = (seed * 9301 + 49297) % 233280;
    return seed / 233280;
  };
  return Array.from({ length: n }, (_, i) => ({
    left: rnd() * 100,
    delay: rnd() * 0.25,
    dur: 1.3 + rnd() * 0.8,
    drift: (rnd() - 0.5) * 80,
    spin: 360 + rnd() * 540,
    w: 4 + rnd() * 4,
    round: rnd() > 0.55,
    color: colors[i % colors.length],
  }));
}

export const PenaltyScene = forwardRef<
  SceneHandle,
  {
    aim: number | null;
    disabled: boolean;
    onShoot: (zone: number) => void;
    onAim: (zone: number) => void;
  }
>(function PenaltyScene({ aim, disabled, onShoot, onAim }, ref) {
  const stage = useRef<HTMLDivElement>(null);
  const world = useRef<HTMLDivElement>(null);
  const idle = useRef<HTMLDivElement>(null);
  const dive = useRef<HTMLImageElement>(null);
  const ball = useRef<HTMLImageElement>(null);
  const shadow = useRef<HTMLDivElement>(null);
  const net = useRef<SVGGElement>(null);
  const frame = useRef<SVGGElement>(null);
  const dent = useRef<HTMLDivElement>(null);
  const spark = useRef<HTMLDivElement>(null);
  const confetti = useRef<HTMLDivElement>(null);
  const arrow = useRef<HTMLDivElement>(null);
  const raf = useRef(0);
  const prepAt = useRef(0);
  const swipe = useRef<{ x: number; y: number; id: number } | null>(null);
  const swiped = useRef(false);
  const pieces = useMemo(() => confettiPieces(36), []);

  // ---------- позиционирование слоёв ----------
  const setBall = (p: Pt, s: number, spin: number, o = 1) => {
    const el = ball.current;
    if (!el) return;
    el.style.transform = `translate(${(p.x - R).toFixed(2)}px, ${(p.y - R).toFixed(2)}px) scale(${s.toFixed(3)}) rotate(${spin.toFixed(1)}deg)`;
    el.style.opacity = String(o);
  };
  const setShadow = (x: number, y: number, s: number, o: number) => {
    const el = shadow.current;
    if (!el) return;
    el.style.transform = `translate(${(x - 16).toFixed(2)}px, ${(y - 4).toFixed(2)}px) scale(${s.toFixed(3)})`;
    el.style.opacity = o.toFixed(3);
  };
  const setIdle = (dy: number, sx: number, sy: number, o: number) => {
    const el = idle.current;
    if (!el) return;
    el.style.transform = `translate(${(IDLE.foot.x - IDLE.w / 2).toFixed(2)}px, ${(IDLE.foot.y - IDLE.h + dy).toFixed(2)}px) scale(${sx.toFixed(3)}, ${sy.toFixed(3)})`;
    el.style.opacity = o.toFixed(3);
  };
  const setDive = (hip: Pt, rot: number, flip: 1 | -1, s: number, o: number) => {
    const el = dive.current;
    if (!el) return;
    el.style.transform = diveTransform(hip, rot, flip, s);
    el.style.opacity = o.toFixed(3);
  };
  /** перезапуск CSS-анимации по классу */
  const kick = (el: Element | null, cls: string) => {
    if (!el) return;
    el.classList.remove(cls);
    void (el as HTMLElement).getBoundingClientRect();
    el.classList.add(cls);
  };

  const reset = useCallback(() => {
    cancelAnimationFrame(raf.current);
    setBall(SPOT, 1, 0);
    setShadow(SPOT.x, SPOT.y + R - 2, 1, 0.5);
    setIdle(0, 1, 1, 1);
    if (dive.current) dive.current.style.opacity = '0';
    idle.current?.classList.remove('is-ready', 'is-off');
    for (const [el, cls] of [
      [stage.current, 'is-shake'],
      [net.current, 'is-hit'],
      [frame.current, 'is-hit'],
      [dent.current, 'is-on'],
      [spark.current, 'is-on'],
      [confetti.current, 'is-on'],
    ] as const)
      el?.classList.remove(cls);
    stage.current?.classList.remove('is-flying');
  }, []);

  // масштаб мира под ширину сцены
  useLayoutEffect(() => {
    const el = stage.current;
    if (!el) return;
    const fit = () => world.current?.style.setProperty('--k', String(el.clientWidth / W));
    fit();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(fit) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, []);

  // до первой отрисовки: мяч на отметке, вратарь в воротах
  useLayoutEffect(() => {
    reset();
    return () => cancelAnimationFrame(raf.current);
  }, [reset]);

  useImperativeHandle(
    ref,
    () => ({
      reset,
      prepare() {
        prepAt.current = performance.now();
        idle.current?.classList.add('is-ready');
        stage.current?.classList.add('is-flying');
      },
      async play(plan) {
        cancelAnimationFrame(raf.current);
        const fast = reducedMotion();
        const k = fast ? 0.5 : 1;
        const waited = performance.now() - prepAt.current;
        if (!fast && prepAt.current && waited < T.prepMin) await new Promise((r) => window.setTimeout(r, T.prepMin - waited));
        prepAt.current = 0;
        stage.current?.classList.add('is-flying');

        const flight = T.flight * k;
        const diveDelay = T.diveDelay * k;
        const diveMs = T.dive * k;
        const hold = T.hold * k;
        const fallMs = T.fall * k;
        const netMs = T.net * k;
        const dropMs = T.drop * k;
        const reboundMs = T.rebound * k;
        const parryMs = T.parry * k;

        const { outcome } = plan;
        const pose = keeperPose(plan.keeper);
        const top = cell(plan.zone).row === 0;
        const side = cell(plan.zone).col === 0 ? -1 : cell(plan.zone).col === 2 ? 1 : 0;
        const target =
          outcome === 'save'
            ? catchPoint(pose)
            : outcome === 'goal'
              ? goalPoint(plan.zone, Math.random() * 2 - 1, Math.random() * 2 - 1)
              : woodPoint(plan.zone, outcome);
        const endScale = outcome === 'save' ? 0.62 : 0.52;
        const lift = outcome === 'bar' ? 52 : top ? 44 : 20;
        const spinDir = side < 0 ? -1 : 1;
        const rebound = outcome === 'post' || outcome === 'bar' ? reboundPoint(plan.zone, outcome) : null;

        // старт прыжка: корпус почти вертикально у центра ворот, перчатка вверх
        const flip = pose.kind === 'dive' ? pose.flip : 1;
        const hip0: Pt = { x: 200 + flip * 6, y: GOAL_LINE - 34 };
        const rot0 = flip * -62;
        const keeperRow = cell(plan.keeper).row;
        const land = { y: GOAL_LINE - (keeperRow === 0 ? 14 : 10), rot: flip * 8 };
        const caught = outcome === 'save';
        // вратарь падает: при сейве — после остановки с мячом, иначе — сразу, как долетел
        const fallAt = caught ? flight + hold : diveDelay + diveMs;


        let frames = 0;
        let worst = 0;
        let prev = 0;
        let impacted = false;
        let parry: { from: Pt; to: Pt } | null = null;
        const t0 = performance.now();
        const end =
          outcome === 'save'
            ? Math.max(flight + hold + fallMs + 140 * k, flight + parryMs + 40 * k)
            : outcome === 'goal'
              ? flight + netMs + dropMs + 80 * k
              : flight + reboundMs + 60 * k;

        const keeperAt = (t: number): { glove: Pt } => {
          const u = ease.out((t - diveDelay) / diveMs);
          const f = ease.in((t - fallAt) / fallMs);
          if (pose.kind === 'idle') {
            // по центру: вверх — прыжок, вниз — глубокий присед; потом обратно в стойку
            const back = ease.inOut((t - fallAt) / fallMs);
            const dy = pose.dy * (pose.dy < 0 ? Math.sin((Math.PI / 2) * u) : u) * (1 - back);
            const sy = lerp(1, pose.sy, u * (1 - back));
            const sx = pose.sy < 1 ? lerp(1, 1.1, u * (1 - back)) : 1;
            setIdle(dy, sx, sy, 1);
            // точка «поймал» от ступней: в позе — (catchAt − ступни − dy) / sy; сейчас — с текущими dy и sy
            const offY = (pose.catchAt.y - IDLE.foot.y - pose.dy) / pose.sy;
            return { glove: { x: pose.catchAt.x, y: IDLE.foot.y + dy + offY * sy } };
          }
          // прыжок: стойка гаснет, картинка прыжка разворачивается в позу
          const show = Math.min(1, Math.max(0, (t - diveDelay) / (60 * k)));
          setIdle(-6 * show, 1, 1, 1 - show);
          const arc = (keeperRow === 0 ? -16 : -6) * Math.sin(Math.PI * u);
          const hip = {
            x: lerp(hip0.x, pose.hip.x, u),
            y: lerp(hip0.y, pose.hip.y, u) + arc + (land.y - pose.hip.y) * Math.max(0, f) * (pose.hip.y < land.y ? 1 : 0),
          };
          const rot = lerp(rot0, pose.rot, u) + land.rot * f;
          const s = lerp(0.9, 1, u);
          setDive(hip, rot, pose.flip, s, show);
          return { glove: divePoint(DIVE.ball, hip, rot, pose.flip) };
        };

        const impact = () => {
          impacted = true;
          plan.onImpact?.();
          if (outcome === 'save') {
            if (!fast) kick(stage.current, 'is-shake');
            // вспышка у перчаток в момент отбития
            if (spark.current) {
              spark.current.style.transform = `translate(${target.x - 18}px, ${target.y - 18}px)`;
              kick(spark.current, 'is-on');
            }
          } else if (outcome === 'goal') {
            const n = net.current;
            if (n) n.style.transformOrigin = `${target.x}px ${target.y}px`;
            kick(n, 'is-hit');
            if (dent.current) {
              dent.current.style.transform = `translate(${target.x - 30}px, ${target.y - 30}px)`;
              kick(dent.current, 'is-on');
            }
            if (!fast) kick(confetti.current, 'is-on');
          } else {
            kick(frame.current, 'is-hit');
            if (spark.current) {
              spark.current.style.transform = `translate(${target.x - 18}px, ${target.y - 18}px)`;
              kick(spark.current, 'is-on');
            }
          }
        };

        return new Promise<void>((resolve) => {
          const tick = (now: number) => {
            if (prev) worst = Math.max(worst, now - prev);
            prev = now;
            frames += 1;
            const freeze = window.__rmPkAt;
            const t = freeze != null ? Math.min(now - t0, freeze) : now - t0;
            // присед держится до старта прыжка
            if (t >= diveDelay) idle.current?.classList.remove('is-ready');
            const gk = keeperAt(t);

            if (t <= flight) {
              // полёт: дуга, уменьшение (перспектива), вращение; тень скользит по газону к линии ворот
              const x = t / flight;
              const e = 1 - (1 - x) ** 2;
              const p = { x: lerp(SPOT.x, target.x, e), y: lerp(SPOT.y, target.y, e) - lift * Math.sin(Math.PI * e) };
              setBall(p, lerp(1, endScale, e), spinDir * 620 * e);
              const gy = lerp(SPOT.y + R - 2, GOAL_LINE + 1, e);
              setShadow(p.x, gy, lerp(1, 0.45, e), 0.5 * (1 - 0.75 * e));
            } else {
              if (!impacted) impact();
              const a = t - flight;
              if (outcome === 'save') {
                // отбил: мяч отлетает от перчаток к бьющему (растёт — летит к нам), бьётся о газон и
                // подпрыгивает ещё раз пониже; вращение меняет направление
                if (!parry) parry = { from: gk.glove, to: parryPoint(gk.glove) };
                const u = Math.min(1, a / parryMs);
                const f1 = 0.62; // доля до первого касания газона
                let p: Pt;
                let s: number;
                if (u <= f1) {
                  const e = u / f1;
                  p = {
                    x: lerp(parry.from.x, parry.to.x, ease.out(e)),
                    y: lerp(parry.from.y, parry.to.y, e * e) - 30 * Math.sin(Math.PI * e),
                  };
                  s = lerp(endScale, 0.86, e);
                } else {
                  const e = (u - f1) / (1 - f1);
                  p = { x: parry.to.x + (parry.to.x - parry.from.x) * 0.22 * e, y: parry.to.y - 12 * Math.sin(Math.PI * e) };
                  s = lerp(0.86, 0.9, e);
                }
                setBall(p, s, spinDir * (620 - 520 * ease.out(u)), 1 - Math.max(0, (u - 0.8) / 0.2));
                const gy = u <= f1 ? lerp(GOAL_LINE + 1, parry.to.y + 9, u / f1) : parry.to.y + 9;
                setShadow(p.x, gy, lerp(0.45, 0.85, Math.min(1, u / f1)), (0.12 + 0.3 * Math.min(1, u / f1)) * (1 - Math.max(0, (u - 0.8) / 0.2)));
              } else if (outcome === 'goal') {
                if (a <= netMs) {
                  // продавливает сетку
                  const u = ease.out(a / netMs);
                  setBall({ x: target.x + side * 3 * u, y: target.y + 3 * u }, endScale * lerp(1, 0.84, u), spinDir * (620 + 90 * u));
                } else {
                  // падает в сетке с отскоком
                  const u = Math.min(1, (a - netMs) / dropMs);
                  const floor = GOAL_LINE - 8;
                  const y0 = target.y + 3;
                  const fallU = Math.min(1, u / 0.72);
                  let y = lerp(y0, floor, ease.in(fallU));
                  if (u > 0.72) y = floor - 7 * Math.sin((Math.PI * (u - 0.72)) / 0.28);
                  setBall({ x: target.x + side * (3 + 6 * u), y }, endScale * 0.84, spinDir * (710 + 160 * u));
                  setShadow(target.x + side * (3 + 6 * u), GOAL_LINE - 6, 0.35, 0.3 * ease.in(u));
                }
              } else if (rebound) {
                // штанга/перекладина: отскок наружу и к бьющему
                const u = Math.min(1, a / reboundMs);
                const e = ease.out(u);
                const p = {
                  x: lerp(target.x, rebound.x, e),
                  y: lerp(target.y, rebound.y, e) - (outcome === 'bar' ? 34 : 18) * Math.sin(Math.PI * e),
                };
                setBall(p, lerp(endScale, 0.78, e), spinDir * (620 - 300 * e), 1 - Math.max(0, (u - 0.7) / 0.3));
                setShadow(p.x, lerp(GOAL_LINE + 1, rebound.y + 10, e), lerp(0.45, 0.7, e), 0.3 * (1 - u));
              }
            }

            if (t < end || freeze != null) raf.current = requestAnimationFrame(tick);
            else {
              const ms = now - t0;
              (window.__rmShotFps ??= []).push({
                frames,
                ms: Math.round(ms),
                fps: Math.round((frames / ms) * 1000 * 10) / 10,
                worst_ms: Math.round(worst * 10) / 10,
                outcome,
              });
              stage.current?.classList.remove('is-flying');
              resolve();
            }
          };
          raf.current = requestAnimationFrame(tick);
        });
      },
    }),
    [reset],
  );

  // ---------- свайп от мяча ----------
  const toWorld = (dx: number, dy: number) => {
    const w = stage.current?.clientWidth || W;
    return { dx: (dx * W) / w, dy: (dy * W) / w, w };
  };
  const showArrow = (dx: number, dy: number) => {
    const el = arrow.current;
    if (!el) return;
    const len = Math.min(150, Math.hypot(dx, dy));
    const ang = (Math.atan2(dy, dx) * 180) / Math.PI;
    el.style.transform = `translate(${SPOT.x}px, ${SPOT.y}px) rotate(${ang.toFixed(1)}deg) scaleX(${(len / 100).toFixed(3)})`;
    el.style.opacity = len > 12 ? '1' : '0';
  };
  const onDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (disabled) return;
    swipe.current = { x: e.clientX, y: e.clientY, id: e.pointerId };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const s = swipe.current;
    if (!s || s.id !== e.pointerId || disabled) return;
    const v = toWorld(e.clientX - s.x, e.clientY - s.y);
    showArrow(v.dx, v.dy);
    const z = zoneFromSwipe(e.clientX - s.x, e.clientY - s.y, v.w);
    if (z != null) onAim(z);
  };
  const endSwipe = () => {
    swipe.current = null;
    if (arrow.current) arrow.current.style.opacity = '0';
  };
  const onUp = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const s = swipe.current;
    endSwipe();
    if (!s || s.id !== e.pointerId || disabled) return;
    const w = stage.current?.clientWidth ?? 360;
    const z = zoneFromSwipe(e.clientX - s.x, e.clientY - s.y, w);
    swiped.current = z != null;
    if (z != null) onShoot(z);
  };

  const aimPt = aim != null ? zonePoint(aim) : null;

  return (
    <div className={`pk-stage${disabled ? ' is-busy' : ''}`} ref={stage}>
      <svg className="pk-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Стадион ночью: ворота, Куртуа и мяч на одиннадцатиметровой отметке">
        <defs>
          <linearGradient id="pk-sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#020308" />
            <stop offset="0.6" stopColor="#090C16" />
            <stop offset="1" stopColor="#0E1220" />
          </linearGradient>
          <radialGradient id="pk-flood" cx="0.5" cy="0" r="0.5">
            <stop offset="0" stopColor="#FFF4CF" stopOpacity="0.55" />
            <stop offset="0.35" stopColor="#F4D57A" stopOpacity="0.14" />
            <stop offset="1" stopColor="#F4D57A" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="pk-beam" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#FFF1C4" stopOpacity="0.16" />
            <stop offset="1" stopColor="#F4D57A" stopOpacity="0" />
          </linearGradient>
          <pattern id="pk-crowd" width="9" height="7" patternUnits="userSpaceOnUse">
            <circle cx="2.5" cy="2.5" r="1.5" fill="#262C3E" />
            <circle cx="7" cy="5.5" r="1.3" fill="#1B2030" />
          </pattern>
          <linearGradient id="pk-stand" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#06070B" stopOpacity="0.2" />
            <stop offset="1" stopColor="#06070B" stopOpacity="0.85" />
          </linearGradient>
          <linearGradient id="pk-board" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#1A1408" />
            <stop offset="0.5" stopColor="#2A2110" />
            <stop offset="1" stopColor="#1A1408" />
          </linearGradient>
          <linearGradient id="pk-grass" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#0C2318" />
            <stop offset="1" stopColor="#154029" />
          </linearGradient>
          <radialGradient id="pk-pitchlight" cx="0.5" cy="0.15" r="0.75">
            <stop offset="0" stopColor="#F4D57A" stopOpacity="0.10" />
            <stop offset="1" stopColor="#F4D57A" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="pk-mouth" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#141A2A" />
            <stop offset="1" stopColor="#0B101C" />
          </linearGradient>
          <pattern id="pk-mesh" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <path d="M0 0H9M0 0V9" stroke="#E8ECF5" strokeOpacity="0.2" strokeWidth="0.7" fill="none" />
          </pattern>
          <pattern id="pk-mesh-side" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <path d="M0 0H7M0 0V7" stroke="#E8ECF5" strokeOpacity="0.13" strokeWidth="0.6" fill="none" />
          </pattern>
          <linearGradient id="pk-post" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#FFFFFF" />
            <stop offset="0.6" stopColor="#E9ECF2" />
            <stop offset="1" stopColor="#A9B0BE" />
          </linearGradient>
          <linearGradient id="pk-bar" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#FFFFFF" />
            <stop offset="1" stopColor="#B4BAC8" />
          </linearGradient>
          <linearGradient id="pk-rim" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#D4AF37" stopOpacity="0" />
            <stop offset="0.5" stopColor="#F4D57A" stopOpacity="0.9" />
            <stop offset="1" stopColor="#D4AF37" stopOpacity="0" />
          </linearGradient>
          <radialGradient id="pk-vignette" cx="0.5" cy="0.55" r="0.75">
            <stop offset="0.6" stopColor="#000" stopOpacity="0" />
            <stop offset="1" stopColor="#000" stopOpacity="0.55" />
          </radialGradient>
        </defs>

        {/* небо, трибуны, рекламный борт */}
        <rect width={W} height={H} fill="url(#pk-sky)" />
        <path d="M0 34 L400 34 L400 160 L0 160 Z" fill="url(#pk-crowd)" />
        <path d="M0 34 L400 34 L400 160 L0 160 Z" fill="url(#pk-stand)" />
        <path d="M0 34 L400 34" stroke="url(#pk-rim)" strokeWidth="1.2" />
        <path d="M0 96 L400 96" stroke="#D4AF37" strokeOpacity="0.12" strokeWidth="4" />
        <rect x="0" y="160" width={W} height="14" fill="url(#pk-board)" />
        <path d="M0 160 H400 M0 174 H400" stroke="#D4AF37" strokeOpacity="0.35" strokeWidth="0.8" />
        {/* светодиодный борт: золотые полосы по краям (центр закрывают ворота) */}
        <g fill="#F4D57A">
          {[6, 22, 38, 352, 368, 384].map((x, i) => (
            <rect key={x} x={x - 5} y="164" width="10" height="6" rx="1" opacity={i % 3 === 1 ? 0.5 : 0.28} />
          ))}
        </g>

        {/* прожекторы: мачты, свечение, лучи */}
        <path d="M18 18 L-30 176 L60 176 Z" fill="url(#pk-beam)" />
        <path d="M382 18 L340 176 L430 176 Z" fill="url(#pk-beam)" />
        <ellipse cx="28" cy="16" rx="120" ry="90" fill="url(#pk-flood)" />
        <ellipse cx="372" cy="16" rx="120" ry="90" fill="url(#pk-flood)" />
        <g fill="#FFF7DD">
          <rect x="8" y="8" width="40" height="12" rx="2.5" opacity="0.18" />
          <rect x="352" y="8" width="40" height="12" rx="2.5" opacity="0.18" />
          {[0, 1, 2, 3].map((i) => (
            <g key={i}>
              <circle cx={13 + i * 10} cy="11" r="2.6" />
              <circle cx={13 + i * 10} cy="17" r="2.6" opacity="0.85" />
              <circle cx={357 + i * 10} cy="11" r="2.6" />
              <circle cx={357 + i * 10} cy="17" r="2.6" opacity="0.85" />
            </g>
          ))}
        </g>

        {/* газон: полосы стрижки шире к бьющему, свет прожекторов */}
        <path d={`M0 174 L400 174 L400 ${H} L0 ${H} Z`} fill="url(#pk-grass)" />
        <g fill="#FFFFFF" opacity="0.04">
          <path d="M0 182 H400 V192 H0 Z" />
          <path d="M0 204 H400 V220 H0 Z" />
          <path d="M0 238 H400 V260 H0 Z" />
          <path d="M0 286 H400 V320 H0 Z" />
        </g>
        <rect x="0" y="174" width={W} height={H - 174} fill="url(#pk-pitchlight)" />
        {/* разметка: линия ворот, вратарская, отметка */}
        <g stroke="#E8ECF5" strokeOpacity="0.55" strokeWidth="1.5" fill="none">
          <path d={`M0 ${GOAL_LINE} L400 ${GOAL_LINE}`} />
          <path d={`M30 ${GOAL_LINE} L12 226 L388 226 L370 ${GOAL_LINE}`} strokeOpacity="0.38" />
        </g>
        <ellipse cx={SPOT.x} cy={SPOT.y + R - 3} rx="5.5" ry="2" fill="#E8ECF5" opacity="0.6" />

        {/* ворота: задняя сетка, боковые, свод — прогибается при голе */}
        <g ref={net} className="pk-net">
          <rect x={GOAL.x} y={GOAL.y} width={GOAL.w} height={GOAL.h} fill="url(#pk-mouth)" />
          <path d={`M${GOAL.x} ${GOAL.y} L${GOAL.x + 16} ${GOAL.y + 12} L${GOAL.x + 16} ${GOAL_LINE - 2} L${GOAL.x} ${GOAL_LINE} Z`} fill="url(#pk-mesh-side)" />
          <path d={`M${GOAL.x + GOAL.w} ${GOAL.y} L${GOAL.x + GOAL.w - 16} ${GOAL.y + 12} L${GOAL.x + GOAL.w - 16} ${GOAL_LINE - 2} L${GOAL.x + GOAL.w} ${GOAL_LINE} Z`} fill="url(#pk-mesh-side)" />
          <rect x={GOAL.x + 16} y={GOAL.y + 12} width={GOAL.w - 32} height={GOAL.h - 14} fill="url(#pk-mesh)" />
          <path d={`M${GOAL.x} ${GOAL.y} L${GOAL.x + 16} ${GOAL.y + 12} H${GOAL.x + GOAL.w - 16} L${GOAL.x + GOAL.w} ${GOAL.y}`} fill="url(#pk-mesh-side)" />
          <path
            d={`M${GOAL.x + 16} ${GOAL.y + 12} H${GOAL.x + GOAL.w - 16} M${GOAL.x + 16} ${GOAL.y + 12} V${GOAL_LINE - 2} M${GOAL.x + GOAL.w - 16} ${GOAL.y + 12} V${GOAL_LINE - 2} M${GOAL.x + 16} ${GOAL_LINE - 2} H${GOAL.x + GOAL.w - 16}`}
            stroke="#E8ECF5"
            strokeOpacity="0.28"
            strokeWidth="0.9"
            fill="none"
          />
        </g>
        <ellipse cx={W / 2} cy={GOAL_LINE + 2} rx="152" ry="4.5" fill="#000" opacity="0.35" />
        {/* каркас: штанги и перекладина — дрожат при попадании */}
        <g ref={frame} className="pk-frame">
          <rect x={GOAL.x - POST_W} y={GOAL.y - POST_W} width={POST_W} height={GOAL.h + POST_W} rx="2" fill="url(#pk-post)" />
          <rect x={GOAL.x + GOAL.w} y={GOAL.y - POST_W} width={POST_W} height={GOAL.h + POST_W} rx="2" fill="url(#pk-post)" />
          <rect x={GOAL.x - POST_W} y={GOAL.y - POST_W} width={GOAL.w + POST_W * 2} height={POST_W} rx="2" fill="url(#pk-bar)" />
          <path d={`M${GOAL.x - POST_W + 1} ${GOAL.y - POST_W + 1.5} H${GOAL.x + GOAL.w + POST_W - 1}`} stroke="#FFFFFF" strokeOpacity="0.9" strokeWidth="1" />
        </g>
        <rect width={W} height={H} fill="url(#pk-vignette)" pointerEvents="none" />
      </svg>

      {/* слой «мира» 400×320: Куртуа, мяч, тень, прицел, эффекты */}
      <div className="pk-world" ref={world} aria-hidden="true">
        <div className="pk-dent" ref={dent} />
        <div className="pk-gk" ref={idle} style={{ width: IDLE.w, height: IDLE.h, transformOrigin: `${IDLE.w / 2}px ${IDLE.h}px` }}>
          <div className="pk-gk__pose">
            <div className="pk-gk__sway">
              <img src={idleSrc} alt="" width={IDLE.w} height={IDLE.h} draggable={false} decoding="async" />
            </div>
          </div>
        </div>
        <img className="pk-dive" ref={dive} src={diveSrc} alt="" width={DIVE.w} height={DIVE.h} draggable={false} decoding="async" />
        {aimPt && (
          <div className="pk-aim" style={{ transform: `translate(${aimPt.x - 15}px, ${aimPt.y - 15}px)` }}>
            <i />
          </div>
        )}
        <div className="pk-shadow" ref={shadow} />
        <div className="pk-swipe" ref={arrow} />
        <img className="pk-ball" ref={ball} src={ballSrc} alt="" width={BALL_SIZE} height={BALL_SIZE} draggable={false} decoding="async" />
        <div className="pk-spark" ref={spark} />
      </div>

      <div className="pk-confetti" ref={confetti} aria-hidden="true">
        {pieces.map((p, i) => (
          <i
            key={i}
            style={{
              left: `${p.left}%`,
              width: p.w,
              height: p.round ? p.w : p.w * 1.6,
              borderRadius: p.round ? '50%' : 1.5,
              background: p.color,
              animationDelay: `${p.delay}s`,
              animationDuration: `${p.dur}s`,
              ['--drift' as string]: `${p.drift}px`,
              ['--spin' as string]: `${p.spin}deg`,
            }}
          />
        ))}
      </div>

      {/* зоны ворот — кнопки поверх сцены (проценты = координаты ворот в мире) */}
      <div
        className="pk-zones"
        style={{
          left: `${(GOAL.x / W) * 100}%`,
          top: `${(GOAL.y / H) * 100}%`,
          width: `${(GOAL.w / W) * 100}%`,
          height: `${(GOAL.h / H) * 100}%`,
        }}
        role="group"
        aria-label="Куда бить: зоны ворот 1–6"
      >
        {[1, 2, 3, 4, 5, 6].map((z) => (
          <button
            key={z}
            type="button"
            className={`pk-zone${aim === z ? ' is-aim' : ''}`}
            disabled={disabled}
            aria-label={`Удар в зону ${z}: ${z <= 3 ? 'верх' : 'низ'}, ${['левый угол', 'по центру', 'правый угол'][(z - 1) % 3]}`}
            onPointerEnter={() => !disabled && onAim(z)}
            onFocus={() => onAim(z)}
            onClick={() => onShoot(z)}
          >
            <span>{z}</span>
          </button>
        ))}
      </div>

      {/* мяч: свайп в сторону ворот, тап — удар в выбранную зону */}
      <button
        type="button"
        className="pk-ballhit"
        style={{ left: `${(SPOT.x / W) * 100}%`, top: `${(SPOT.y / H) * 100}%` }}
        aria-label="Мяч: проведите пальцем к воротам или нажмите — удар в выбранную зону"
        disabled={disabled}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={endSwipe}
        onClick={() => {
          // после свайпа браузер всё равно шлёт click — удар уже сделан
          if (swiped.current) {
            swiped.current = false;
            return;
          }
          if (!disabled) onShoot(aim ?? 5);
        }}
      />
    </div>
  );
});
