import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { hapticFeedback } from '@tma.js/sdk-react';
import { fetchMatch } from '../api/match';
import type { GoalCelebration, GoalScorer } from '../lib/celebrate';
import { burst } from '../lib/confetti';
import { REAL_ID, goals, minuteText, shortName } from '../screens/match/view';
import { PlayerPhoto, TeamCrest, imageUrl } from '../ui';
import './goalBurst.css';

/*
 * Гол Реала: сверху падает плашка «ГОЛ!» с фото автора и минутой, кольцо-вспышка вокруг фото,
 * буквы «ГОЛ!» впечатываются по очереди, по плашке проходит блик, из неё бьёт золотое конфетти,
 * счёт на экране «подпрыгивает». Всё ≈1,5 с, плашка держится ~3,2 с и уезжает вверх (тап — сразу).
 * Плашка не мешает: нажимается только она сама, остальной экран живёт как обычно.
 */

const HOLD_MS = 3200;
const EXIT_MS = 320;
const DETAILS_TIMEOUT = 1500;
const PHOTO_TIMEOUT = 250;

const reduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Автор гола, если экран его не передал: спрашиваем матч (одна лёгкая выборка, не дольше 1,5 с). */
async function lookupScorer(g: GoalCelebration): Promise<{ scorer: GoalScorer | null; minute?: string }> {
  const ctrl = new AbortController();
  const t = window.setTimeout(() => ctrl.abort(), DETAILS_TIMEOUT);
  try {
    const r = await fetchMatch(g.matchId, ctrl.signal);
    if (r.kind !== 'ok') return { scorer: null };
    const ev = goals(r.match).filter((x) => x.side === g.side)[g.n - 1]?.ev;
    if (!ev?.player?.name) return { scorer: null };
    const pid = Number(ev.player.id);
    return {
      scorer: { id: Number.isFinite(pid) && pid > 0 ? pid : undefined, name: shortName(ev.player.name) },
      minute: minuteText(ev.minute, ev.added) || undefined,
    };
  } catch {
    return { scorer: null };
  } finally {
    window.clearTimeout(t);
  }
}

function preload(src: string): Promise<void> {
  return new Promise((res) => {
    const img = new Image();
    const done = () => res();
    img.onload = () => (img.decode ? img.decode().then(done, done) : done());
    img.onerror = done;
    img.src = src;
    window.setTimeout(done, PHOTO_TIMEOUT);
  });
}

export default function GoalBurst({ goal, onDone }: { goal: GoalCelebration; onDone: () => void }) {
  const [info, setInfo] = useState<{ scorer: GoalScorer | null; minute?: string } | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const conf = useRef<HTMLDivElement>(null);
  const leaving = useRef(false);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  // 1. подробности и фото — до начала, чтобы плашка вылетела сразу целой
  useEffect(() => {
    let alive = true;
    void (async () => {
      const d = goal.scorer !== undefined ? { scorer: goal.scorer, minute: goal.minute } : await lookupScorer(goal);
      const photo = d.scorer?.id != null ? imageUrl.player(d.scorer.id) : imageUrl.team(REAL_ID);
      await preload(photo);
      if (alive) setInfo({ scorer: d.scorer, minute: d.minute ?? goal.minute });
    })();
    return () => {
      alive = false;
    };
  }, [goal]);

  const leave = () => {
    if (leaving.current) return;
    leaving.current = true;
    const el = card.current;
    if (!el || typeof el.animate !== 'function') return doneRef.current();
    const a = el.animate(
      reduced()
        ? [{ opacity: 1 }, { opacity: 0 }]
        : [
            { transform: 'none', opacity: 1 },
            { transform: 'translateY(-130%) scale(.96)', opacity: 0 },
          ],
      { duration: EXIT_MS, easing: 'cubic-bezier(.55,0,.75,.2)', fill: 'forwards' },
    );
    a.finished.then(() => doneRef.current(), () => doneRef.current());
  };

  // 2. запуск: конфетти и «подскок» табло — из JS (случайные траектории), остальное — CSS
  useLayoutEffect(() => {
    if (!info) return;
    // табло в верхней части экрана — плашка встаёт сразу под ним: перелистывание счёта остаётся на виду.
    // Трансляция во весь экран — табло не видно, плашка сверху поверх видео
    const fullscreen = !!document.fullscreenElement || !!document.querySelector('.player--css-fs');
    const board = fullscreen ? undefined : Array.from(document.querySelectorAll<HTMLElement>('.ui-flip-score'))
      .map((s) => s.closest<HTMLElement>('.ui-score-head, .ui-mc') ?? s)
      .map((el) => el.getBoundingClientRect())
      .find((r) => r.height > 0 && r.top >= 0 && r.bottom < window.innerHeight * 0.55);
    if (board && root.current) root.current.style.setProperty('--gb-top', `${Math.round(board.bottom + 8)}px`);
    const rm = reduced();
    const timers: number[] = [];
    if (!rm) {
      try {
        hapticFeedback.notificationOccurred.ifAvailable('success');
      } catch {
        /* не в Telegram */
      }
      // частицы создаём отдельными задачами, а не в кадре появления плашки: тот кадр и так тяжёлый
      timers.push(
        window.setTimeout(() => conf.current && void burst(conf.current, { count: 24, delay: 40, spread: 70, speed: [420, 780] }), 220),
        window.setTimeout(
          () => conf.current && void burst(conf.current, { count: 18, delay: 40, spread: 105, speed: [260, 540], duration: [1150, 1500] }),
          340,
        ),
      );
      document.querySelectorAll<HTMLElement>('.ui-flip-score').forEach((s) => {
        s.animate?.(
          [
            { transform: 'none' },
            { transform: 'scale(1.16)', offset: 0.35 },
            { transform: 'none' },
          ],
          { duration: 620, delay: 120, easing: 'cubic-bezier(.34,1.56,.64,1)' },
        );
      });
    }
    timers.push(window.setTimeout(leave, HOLD_MS));
    return () => timers.forEach((t) => window.clearTimeout(t));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [info]);

  if (!info) return null;
  const who = info.scorer?.name ?? 'Реал Мадрид';
  const label = `Гол! ${who}${info.minute ? `, ${info.minute}` : ''}`;
  return (
    <div ref={root} className="gb" role="status" aria-live="polite" aria-label={label}>
      <div className="gb__flash" aria-hidden="true" />
      <div ref={card} className="gb__card" onClick={leave} aria-hidden="true">
        <span className="gb__ph">
          <span className="gb__ring" />
          {info.scorer?.id != null ? (
            <PlayerPhoto id={info.scorer.id} name={who} size={60} className="gb__photo" />
          ) : (
            <span className="gb__crest-only">
              <TeamCrest id={REAL_ID} name="" size={52} />
            </span>
          )}
        </span>
        <span className="gb__txt">
          <span className="gb__goal">
            {['Г', 'О', 'Л', '!'].map((c, i) => (
              <span key={i} style={{ animationDelay: `${170 + i * 55}ms` }}>
                {c}
              </span>
            ))}
          </span>
          <span className="gb__who">
            <b>{who}</b>
            {info.minute && <em>{info.minute}</em>}
          </span>
        </span>
        {info.scorer?.id != null && <TeamCrest id={REAL_ID} name="" size={36} className="gb__club" />}
        <span className="gb__gloss">
          <span className="gb__shine" />
        </span>
        <div ref={conf} className="gb__conf" />
      </div>
    </div>
  );
}
