import { useEffect, useRef } from 'react';
import { celebrateGoal, noteLive, type GoalCelebration } from './celebrate';
import { createGoalWatcher, storedSeen, type FreshGoal, type GoalSide } from './goalWatch';

export interface GoalWatchInput {
  id: number | string;
  score: [number, number] | null | undefined;
  live: boolean;
  /** сторона Реала; Реала в матче нет — null (тогда праздников нет, только перелистывание счёта) */
  real: GoalSide | null;
}

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/**
 * Следит за счётом лайва и празднует гол Реала, которого человек ещё не видел — в том числе забитый,
 * пока приложение было закрыто (lib/goalWatch.ts — правила). Несколько пропущенных — плашка последнего.
 * Гол соперника — без праздника: счёт сам перелистнётся на табло.
 * details — подробности гола (автор, минута), если экран их знает.
 */
export function useGoalWatch(
  input: GoalWatchInput | null,
  details?: (g: FreshGoal) => Pick<GoalCelebration, 'minute' | 'scorer'>,
): void {
  const watch = useRef<ReturnType<typeof createGoalWatcher> | null>(null);
  const detailsRef = useRef(details);
  detailsRef.current = details;
  const id = input?.id;
  const h = input?.score?.[0];
  const a = input?.score?.[1];
  const live = !!input?.live;
  const real = input?.real ?? null;

  useEffect(() => {
    if (id == null) return;
    if (live && real) noteLive();
    watch.current ??= createGoalWatcher(storedSeen(storage()));
    const fresh = watch.current({ id, score: h != null && a != null ? [h, a] : null, live });
    const ours = fresh.filter((g) => g.side === real);
    const g = ours[ours.length - 1];
    if (!g) return;
    celebrateGoal({ matchId: id, side: g.side, n: g.n, ...detailsRef.current?.(g) });
  }, [id, h, a, live, real]);
}
