import { useEffect, useRef } from 'react';
import ballSrc from '../assets/games/ball.webp';
import { refreshAll } from '../lib/refresh';
import { isTelegramShell } from '../lib/shell';
import { verticalSwipesOff } from '../telegram';
import '../styles/ptr.css';

/*
 * Потянуть вниз в самом верху экрана — обновить данные (lib/refresh.ts).
 * Мяч (тот же, что в игре «Пенальти») выезжает из-под верхнего края и крутится по мере натяжения;
 * отпустили за порогом — мяч встаёт и крутится, пока экран перечитывает данные, потом уходит.
 *
 * Где включено: только тач-устройства (pointer: coarse), раскладка телефона. В Telegram — только если
 * клиент дал отключить вертикальные свайпы (иначе тот же жест сворачивает мини-апп); в старых клиентах — нет.
 * Скролл — у окна (документа): тянем, только когда window.scrollY === 0; поверх открытых слоёв
 * (карточка игрока, новость, видео) и в горизонтальных лентах — не срабатывает.
 * Слушатели пассивные: прокрутку не блокируем (body уже overscroll-behavior-y: none — системного PTR нет).
 */

const MAX = 120; // предел хода мяча, px
const TRIGGER = 72; // порог: отпустил дальше — обновляем
const REST = 58; // где мяч крутится во время загрузки
const SIZE = 36;

const resist = (dy: number) => MAX * (1 - Math.exp(-dy / (MAX * 1.6)));

function enabled(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  if (!matchMedia('(pointer: coarse)').matches) return false;
  if (document.documentElement.classList.contains('desk')) return false;
  if (isTelegramShell() && !verticalSwipesOff) return false;
  return true;
}

export function PullToRefresh() {
  const wrap = useRef<HTMLDivElement>(null);
  const ball = useRef<HTMLImageElement>(null);

  useEffect(() => {
    if (!enabled()) return;
    const w = wrap.current!;
    const b = ball.current!;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    let x0 = 0;
    let y0 = 0;
    let tracking = false;
    let pulling = false;
    let busy = false;
    let d = 0;
    let raf = 0;

    const paint = () => {
      raf = 0;
      const k = Math.min(1, d / TRIGGER);
      w.style.transform = `translate3d(0, ${d - SIZE - 8}px, 0)`;
      w.style.opacity = String(Math.min(1, d / 28));
      b.style.transform = reduce ? '' : `rotate(${d * 4.2}deg) scale(${0.7 + 0.3 * k})`;
      w.classList.toggle('is-armed', d >= TRIGGER);
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(paint);
    };
    const settle = (to: number, ms: number) =>
      w.animate([{ transform: w.style.transform, opacity: w.style.opacity }, { transform: `translate3d(0, ${to - SIZE - 8}px, 0)`, opacity: to > 0 ? '1' : '0' }], {
        duration: reduce ? 1 : ms,
        easing: 'cubic-bezier(.3,1.3,.5,1)',
      }).finished;

    const onStart = (e: TouchEvent) => {
      if (busy || e.touches.length !== 1 || window.scrollY > 0) return;
      const t = e.target as Element | null;
      if (t?.closest?.('.pc, .nr, .vp, .gb, input, textarea, [data-no-ptr]')) return;
      if (document.body.style.overflow === 'hidden') return; // открыт слой поверх экрана
      x0 = e.touches[0].clientX;
      y0 = e.touches[0].clientY;
      tracking = true;
      pulling = false;
    };
    const onMove = (e: TouchEvent) => {
      if (!tracking) return;
      const dx = e.touches[0].clientX - x0;
      const dy = e.touches[0].clientY - y0;
      if (!pulling) {
        if (Math.abs(dx) > 10 && Math.abs(dx) > dy) return void (tracking = false); // горизонтальный жест
        if (dy < 6) {
          if (dy < -6) tracking = false;
          return;
        }
        if (window.scrollY > 0) return void (tracking = false);
        pulling = true;
        w.hidden = false;
      }
      d = dy > 0 ? resist(dy) : 0;
      schedule();
    };
    const onEnd = async () => {
      if (!tracking) return;
      tracking = false;
      if (!pulling) return;
      pulling = false;
      if (raf) cancelAnimationFrame(raf), paint();
      if (d < TRIGGER) {
        await settle(0, 260).catch(() => undefined);
        d = 0;
        paint();
        w.hidden = true;
        return;
      }
      busy = true;
      try {
        (navigator as Navigator & { vibrate?: (ms: number) => boolean }).vibrate?.(8);
      } catch {
        /* нет вибро */
      }
      await settle(REST, 320).catch(() => undefined);
      d = REST;
      paint();
      w.classList.remove('is-armed');
      w.classList.add('is-loading');
      const t0 = Date.now();
      await refreshAll();
      // крутимся хотя бы полоборота — иначе на быстром ответе мяч дёрнется и пропадёт
      const wait = 500 - (Date.now() - t0);
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
      w.classList.remove('is-loading');
      await w
        .animate([{ transform: w.style.transform, opacity: 1 }, { transform: `translate3d(0, ${REST - SIZE - 8}px, 0) scale(.4)`, opacity: 0 }], {
          duration: reduce ? 1 : 260,
          easing: 'cubic-bezier(.55,0,.75,.2)',
        })
        .finished.catch(() => undefined);
      d = 0;
      paint();
      w.hidden = true;
      busy = false;
    };

    window.addEventListener('touchstart', onStart, { passive: true });
    window.addEventListener('touchmove', onMove, { passive: true });
    window.addEventListener('touchend', onEnd, { passive: true });
    window.addEventListener('touchcancel', onEnd, { passive: true });
    return () => {
      window.removeEventListener('touchstart', onStart);
      window.removeEventListener('touchmove', onMove);
      window.removeEventListener('touchend', onEnd);
      window.removeEventListener('touchcancel', onEnd);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div ref={wrap} className="ptr" hidden aria-hidden="true">
      <span className="ptr__disc">
        <img ref={ball} className="ptr__ball" src={ballSrc} alt="" width={24} height={24} decoding="async" draggable={false} />
      </span>
    </div>
  );
}
