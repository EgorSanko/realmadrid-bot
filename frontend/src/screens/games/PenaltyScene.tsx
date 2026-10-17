import { forwardRef, useCallback, useImperativeHandle, useLayoutEffect, useRef } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { ballFrame, easeOut, zoneCell, zoneFromSwipe } from '../../lib/games';
import { reducedMotion } from './kit';

/*
 * Сцена пенальти — вид от бьющего: тёмный стадион, прожекторы, ворота с сеткой, газон в перспективе.
 * Всё — SVG и CSS, без картинок. Вратарь — силуэт. Полёт мяча и прыжок — requestAnimationFrame,
 * только transform (мяч, вратарь) и opacity — 60 кадров/с без перерисовки React.
 */

const W = 400;
const H = 320;
const GOAL = { x: 60, y: 80, w: 280, h: 112 };
const SPOT = { x: 200, y: 284 };
const KEEPER = { x: 200, y: GOAL.y + GOAL.h }; // ступни вратаря на линии ворот
const HIP = 36; // высота таза над ступнями — центр поворота в прыжке

const FLIGHT_MS = 560;
const DIVE_DELAY_MS = 70;
const DIVE_MS = 520;
const DEFLECT_MS = 380;

export interface ShotPlan {
  zone: number;
  keeper: number;
  goal: boolean;
}

export interface SceneHandle {
  /** проиграть удар; промис — когда мяч долетел (и отскочил при сейве) */
  play(plan: ShotPlan): Promise<void>;
  reset(): void;
}

export interface FpsSample {
  frames: number;
  ms: number;
  fps: number;
  worst_ms: number;
}

declare global {
  interface Window {
    /** замер плавности последнего удара (для проверок Playwright) */
    __rmShotFps?: FpsSample[];
  }
}

function zonePoint(zone: number, jitter: number): { x: number; y: number } {
  const { col, row } = zoneCell(zone);
  return {
    x: GOAL.x + (GOAL.w * (col + 0.5)) / 3 + jitter * 14,
    y: GOAL.y + GOAL.h * (row === 0 ? 0.27 : 0.73),
  };
}

/** Поза вратаря в прыжке к зоне: смещение ступней и наклон корпуса. */
function divePose(zone: number): { dx: number; dy: number; rot: number } {
  const { col, row } = zoneCell(zone);
  if (col === 1) return row === 0 ? { dx: 0, dy: -30, rot: 0 } : { dx: 0, dy: 4, rot: 0 };
  const side = col === 0 ? -1 : 1;
  return row === 0 ? { dx: side * 82, dy: -36, rot: side * 72 } : { dx: side * 86, dy: -8, rot: side * 88 };
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
  const ball = useRef<SVGGElement>(null);
  const ballShadow = useRef<SVGEllipseElement>(null);
  const keeper = useRef<SVGGElement>(null);
  const net = useRef<SVGGElement>(null);
  const raf = useRef(0);
  const swipe = useRef<{ x: number; y: number; id: number } | null>(null);
  const swiped = useRef(false);
  const stage = useRef<HTMLDivElement>(null);

  const setBall = (x: number, y: number, s: number, spin: number, o = 1) => {
    if (ball.current) {
      ball.current.style.transform = `translate(${x}px, ${y}px) scale(${s}) rotate(${spin}deg)`;
      ball.current.style.opacity = String(o);
    }
  };
  const setShadow = (x: number, s: number, o: number) => {
    if (ballShadow.current) {
      ballShadow.current.style.transform = `translate(${x}px, ${SPOT.y + 12}px) scale(${s})`;
      ballShadow.current.style.opacity = String(o);
    }
  };
  const setKeeper = (dx: number, dy: number, rot: number) => {
    if (keeper.current)
      keeper.current.style.transform = `translate(${KEEPER.x + dx}px, ${KEEPER.y + dy}px) translate(0px, ${-HIP}px) rotate(${rot}deg) translate(0px, ${HIP}px)`;
  };

  const reset = useCallback(() => {
    cancelAnimationFrame(raf.current);
    setBall(SPOT.x, SPOT.y, 1, 0);
    setShadow(SPOT.x, 1, 0.55);
    setKeeper(0, 0, 0);
    keeper.current?.classList.remove('is-diving');
    net.current?.classList.remove('is-hit');
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
      play(plan) {
        cancelAnimationFrame(raf.current);
        const fast = reducedMotion();
        const k = fast ? 0.45 : 1;
        const jitter = Math.random() * 2 - 1;
        const target = zonePoint(plan.zone, jitter);
        const pose = divePose(plan.keeper);
        const flight = FLIGHT_MS * k;
        const diveDelay = DIVE_DELAY_MS * k;
        const dive = DIVE_MS * k;
        const deflect = DEFLECT_MS * k;
        const lift = plan.zone <= 3 ? 46 : 22;
        const away = { x: target.x + (target.x < 200 ? -70 : 70), y: target.y - 60 };
        keeper.current?.classList.add('is-diving');

        // замер плавности: интервалы между кадрами
        let frames = 0;
        let worst = 0;
        let prev = 0;
        const t0 = performance.now();

        return new Promise<void>((resolve) => {
          const tick = (now: number) => {
            if (prev) worst = Math.max(worst, now - prev);
            prev = now;
            frames += 1;
            const t = now - t0;
            // мяч
            if (t <= flight) {
              const f = ballFrame(t / flight, SPOT, target, lift);
              setBall(f.x, f.y, f.scale, f.spin);
              setShadow(f.x, 1 - 0.6 * easeOut(t / flight), 0.55 * (1 - t / flight));
            } else if (!plan.goal && t <= flight + deflect) {
              // сейв: мяч отскакивает от перчаток в сторону и гаснет
              const u = easeOut((t - flight) / deflect);
              setBall(target.x + (away.x - target.x) * u, target.y + (away.y - target.y) * u - 20 * Math.sin(Math.PI * u), 0.45, 540 + 360 * u, 1 - u);
            } else if (plan.goal) {
              setBall(target.x, target.y + 4, 0.42, 560);
              net.current?.classList.add('is-hit');
            }
            // вратарь
            const d = Math.min(1, Math.max(0, (t - diveDelay) / dive));
            const e = easeOut(d);
            setKeeper(pose.dx * e, pose.dy * Math.sin((Math.PI / 2) * e), pose.rot * e);

            const end = flight + (plan.goal ? 60 : deflect);
            if (t < Math.max(end, diveDelay + dive)) raf.current = requestAnimationFrame(tick);
            else {
              const ms = now - t0;
              const sample = { frames, ms: Math.round(ms), fps: Math.round((frames / ms) * 1000 * 10) / 10, worst_ms: Math.round(worst * 10) / 10 };
              (window.__rmShotFps ??= []).push(sample);
              resolve();
            }
          };
          raf.current = requestAnimationFrame(tick);
        });
      },
    }),
    [reset],
  );

  const onDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (disabled) return;
    swipe.current = { x: e.clientX, y: e.clientY, id: e.pointerId };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onUp = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const s = swipe.current;
    swipe.current = null;
    if (!s || s.id !== e.pointerId || disabled) return;
    const w = stage.current?.clientWidth ?? 360;
    const z = zoneFromSwipe(e.clientX - s.x, e.clientY - s.y, w);
    swiped.current = z != null;
    if (z != null) onShoot(z);
  };

  return (
    <div className={`pk-stage${disabled ? ' is-busy' : ''}`} ref={stage}>
      <svg className="pk-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Ворота, вратарь и мяч на одиннадцатиметровой отметке">
        <defs>
          <linearGradient id="pk-sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#020308" />
            <stop offset="0.55" stopColor="#0A0D17" />
            <stop offset="1" stopColor="#0E1220" />
          </linearGradient>
          <radialGradient id="pk-flood-l" cx="0.08" cy="0.02" r="0.55">
            <stop offset="0" stopColor="#FFF4CF" stopOpacity="0.42" />
            <stop offset="0.25" stopColor="#F4D57A" stopOpacity="0.12" />
            <stop offset="1" stopColor="#F4D57A" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="pk-flood-r" cx="0.92" cy="0.02" r="0.55">
            <stop offset="0" stopColor="#FFF4CF" stopOpacity="0.42" />
            <stop offset="0.25" stopColor="#F4D57A" stopOpacity="0.12" />
            <stop offset="1" stopColor="#F4D57A" stopOpacity="0" />
          </radialGradient>
          <pattern id="pk-crowd" width="9" height="7" patternUnits="userSpaceOnUse">
            <circle cx="2.5" cy="2.5" r="1.5" fill="#262C3E" />
            <circle cx="7" cy="5.5" r="1.3" fill="#1B2030" />
          </pattern>
          <linearGradient id="pk-grass" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#0B2016" />
            <stop offset="1" stopColor="#133524" />
          </linearGradient>
          <linearGradient id="pk-mouth" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#151B2B" />
            <stop offset="1" stopColor="#0D1220" />
          </linearGradient>
          <pattern id="pk-mesh" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <path d="M0 0H10M0 0V10" stroke="#E8ECF5" strokeOpacity="0.16" strokeWidth="0.8" fill="none" />
          </pattern>
          <linearGradient id="pk-post" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#FFFFFF" />
            <stop offset="1" stopColor="#B9BFCC" />
          </linearGradient>
          <linearGradient id="pk-bar" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#FFFFFF" />
            <stop offset="1" stopColor="#B9BFCC" />
          </linearGradient>
          <radialGradient id="pk-ball" cx="0.38" cy="0.32" r="0.75">
            <stop offset="0" stopColor="#FFFFFF" />
            <stop offset="0.7" stopColor="#E3E6EE" />
            <stop offset="1" stopColor="#9EA4B3" />
          </radialGradient>
          <linearGradient id="pk-rim" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#D4AF37" stopOpacity="0" />
            <stop offset="0.5" stopColor="#F4D57A" stopOpacity="0.9" />
            <stop offset="1" stopColor="#D4AF37" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* небо и трибуны */}
        <rect width={W} height={H} fill="url(#pk-sky)" />
        <path d="M0 40 L400 40 L400 176 L0 176 Z" fill="url(#pk-crowd)" opacity="0.9" />
        <path d="M0 40 L400 40" stroke="url(#pk-rim)" strokeWidth="1.2" />
        <path d="M0 118 L400 118" stroke="#D4AF37" strokeOpacity="0.18" strokeWidth="6" />
        <rect width={W} height={H} fill="url(#pk-flood-l)" />
        <rect width={W} height={H} fill="url(#pk-flood-r)" />
        {/* мачты прожекторов */}
        <g fill="#FFF7DD" opacity="0.9">
          <rect x="14" y="10" width="26" height="6" rx="2" />
          <rect x="360" y="10" width="26" height="6" rx="2" />
        </g>

        {/* газон в перспективе */}
        <path d="M0 176 L400 176 L400 320 L0 320 Z" fill="url(#pk-grass)" />
        <g fill="#FFFFFF" opacity="0.035">
          <path d="M0 196 L400 196 L400 214 L0 214 Z" />
          <path d="M0 236 L400 236 L400 260 L0 260 Z" />
          <path d="M0 288 L400 288 L400 320 L0 320 Z" />
        </g>
        {/* разметка: линия ворот, вратарская, отметка */}
        <g stroke="#E8ECF5" strokeOpacity="0.5" strokeWidth="1.6" fill="none">
          <path d="M0 192 L400 192" />
          <path d="M34 192 L18 222 L382 222 L366 192" strokeOpacity="0.35" />
        </g>
        <ellipse cx={SPOT.x} cy={SPOT.y + 10} rx="5" ry="2" fill="#E8ECF5" opacity="0.6" />

        {/* ворота: сетка, штанги, перекладина */}
        <g ref={net} className="pk-net">
          <rect x={GOAL.x} y={GOAL.y} width={GOAL.w} height={GOAL.h} fill="url(#pk-mouth)" />
          <rect x={GOAL.x} y={GOAL.y} width={GOAL.w} height={GOAL.h} fill="url(#pk-mesh)" />
          <path d={`M${GOAL.x + 8} ${GOAL.y + 8} H${GOAL.x + GOAL.w - 8} M${GOAL.x + 8} ${GOAL.y + 8} L${GOAL.x} ${GOAL.y + GOAL.h} M${GOAL.x + GOAL.w - 8} ${GOAL.y + 8} L${GOAL.x + GOAL.w} ${GOAL.y + GOAL.h}`} stroke="#E8ECF5" strokeOpacity="0.22" strokeWidth="1" />
        </g>
        <rect x={GOAL.x - 7} y={GOAL.y - 7} width="7" height={GOAL.h + 7} rx="2" fill="url(#pk-post)" />
        <rect x={GOAL.x + GOAL.w} y={GOAL.y - 7} width="7" height={GOAL.h + 7} rx="2" fill="url(#pk-post)" />
        <rect x={GOAL.x - 7} y={GOAL.y - 7} width={GOAL.w + 14} height="7" rx="2" fill="url(#pk-bar)" />
        <ellipse cx={W / 2} cy={GOAL.y + GOAL.h + 2} rx="150" ry="4" fill="#000" opacity="0.35" />

        {/* вратарь — силуэт (ступни в 0,0) */}
        <g ref={keeper} className="pk-keeper">
          <g className="pk-keeper__idle">
            <ellipse cx="0" cy="2" rx="20" ry="3.5" fill="#000" opacity="0.4" />
            <g fill="#04050A" stroke="#04050A" strokeLinecap="round" strokeLinejoin="round">
              <path d="M-9 -34 L-15 -1" strokeWidth="9" fill="none" />
              <path d="M9 -34 L15 -1" strokeWidth="9" fill="none" />
              <path d="M-14 -61 Q0 -66 14 -61 L11 -33 Q0 -29 -11 -33 Z" strokeWidth="2" />
              <path d="M-13 -58 L-29 -45 L-35 -36" strokeWidth="7" fill="none" />
              <path d="M13 -58 L29 -45 L35 -36" strokeWidth="7" fill="none" />
              <circle cx="-36" cy="-34" r="5.2" />
              <circle cx="36" cy="-34" r="5.2" />
              <circle cx="0" cy="-72" r="7.5" />
            </g>
            {/* контровой свет прожекторов по краю силуэта */}
            <g fill="none" stroke="#F4D57A" strokeOpacity="0.38" strokeWidth="1" strokeLinecap="round">
              <path d="M-6.5 -77.5 A7.5 7.5 0 0 1 6.5 -77.5" />
              <path d="M-14 -61 Q0 -66 14 -61" />
              <path d="M13.5 -60 L30 -47" />
              <path d="M-13.5 -60 L-30 -47" />
            </g>
          </g>
        </g>

        {/* мяч */}
        <ellipse ref={ballShadow} cx="0" cy="0" rx="13" ry="3.6" fill="#000" opacity="0.55" className="pk-shadow" />
        <g ref={ball} className="pk-ball">
          <circle r="13" fill="url(#pk-ball)" />
          <g fill="#1A1E2A">
            <path d="M0 -4.6 L4.4 -1.4 L2.7 3.7 L-2.7 3.7 L-4.4 -1.4 Z" />
            <path d="M-1 -13 L3.4 -12.2 L2 -8.6 L-2.3 -9 Z" opacity="0.85" />
            <path d="M11.6 -5 L12.8 1 L9.4 0.2 L8.8 -3.8 Z" opacity="0.85" />
            <path d="M-12.4 -3.4 L-9.2 -3 L-9.6 1.6 L-12.8 2.2 Z" opacity="0.85" />
            <path d="M-6.4 10.8 L-2.8 8.4 L1 11 L-2 12.8 Z" opacity="0.8" />
            <path d="M6 9.6 L8.8 6.6 L10.8 8.2 L8.2 11 Z" opacity="0.8" />
          </g>
        </g>
      </svg>

      {/* зоны ворот — кнопки поверх сцены (проценты = координаты ворот в viewBox) */}
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
        onPointerUp={onUp}
        onPointerCancel={() => (swipe.current = null)}
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
