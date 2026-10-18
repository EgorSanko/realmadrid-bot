/**
 * Новые голы во время лайва: что праздновать, а что уже показано.
 *
 * Гол определяется по счёту: «матч 123, хозяева, 2-й гол» → ключ `123:home:2`. Так один и тот же гол
 * узнаётся и на главной (там есть только счёт), и на экране матча (счёт + события), и при следующем
 * открытии приложения. Показанные ключи — в localStorage (rmGoalsSeen): переживают закрытие мини-аппа.
 *
 * Правила:
 *  — гол, которого человек ещё не видел, празднуем, пока матч идёт — даже если он забит, пока приложение
 *    было закрыто (смотрел при 0:0, открыл снова после гола; или впервые открыл на 35-й минуте);
 *    экран празднует только последний непоказанный гол — одна плашка, не очередь;
 *  — после свистка новые цифры просто помечаем показанными;
 *  — счёт уменьшился (VAR отменил гол) — снимаем пометку с «лишних» ключей: перебитый гол отпразднуем.
 *
 * Модуль без рантайм-импортов — его напрямую гоняет `node --test`.
 */

export type GoalSide = 'home' | 'away';

export interface ScoreSnapshot {
  id: number | string;
  score: [number, number] | null | undefined;
  live: boolean;
}

export interface FreshGoal {
  key: string;
  side: GoalSide;
  /** какой по счёту гол этой стороны (1, 2, …) */
  n: number;
}

export const SEEN_KEY = 'rmGoalsSeen';
const SEEN_CAP = 200;

export function goalKeyOf(id: number | string, side: GoalSide, n: number): string {
  return `${id}:${side}:${n}`;
}

/** Все ключи голов для счёта. */
export function scoreKeys(id: number | string, score: [number, number]): FreshGoal[] {
  const out: FreshGoal[] = [];
  (['home', 'away'] as const).forEach((side, i) => {
    for (let n = 1; n <= Math.max(0, score[i] | 0); n++) out.push({ key: goalKeyOf(id, side, n), side, n });
  });
  return out;
}

export interface SeenStore {
  has(key: string): boolean;
  add(keys: string[]): void;
  remove(keys: string[]): void;
}

/** Множество показанных голов поверх хранилища (localStorage); без хранилища — просто в памяти. */
export function storedSeen(storage: Pick<Storage, 'getItem' | 'setItem'> | null): SeenStore {
  let mem: string[] = [];
  const read = (): string[] => {
    if (!storage) return mem;
    try {
      const v = JSON.parse(storage.getItem(SEEN_KEY) || '[]');
      return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : [];
    } catch {
      return [];
    }
  };
  const write = (list: string[]) => {
    mem = list.slice(-SEEN_CAP);
    if (!storage) return;
    try {
      storage.setItem(SEEN_KEY, JSON.stringify(mem));
    } catch {
      /* приватный режим — живём в памяти */
    }
  };
  return {
    has: (k) => read().includes(k),
    add: (keys) => {
      const cur = read();
      const next = cur.concat(keys.filter((k) => !cur.includes(k)));
      if (next.length !== cur.length) write(next);
    },
    remove: (keys) => {
      const cur = read();
      const next = cur.filter((k) => !keys.includes(k));
      if (next.length !== cur.length) write(next);
    },
  };
}

/**
 * Один шаг наблюдения. Возвращает непоказанные голы (по порядку), если матч идёт, и сам обновляет seen.
 */
export function observeScore(snap: ScoreSnapshot, seen: SeenStore): FreshGoal[] {
  if (!snap.score) return [];
  const keys = scoreKeys(snap.id, snap.score);
  // VAR: счёт стал меньше — ключи выше текущего счёта больше не «показаны»
  const stale: string[] = [];
  (['home', 'away'] as const).forEach((side, i) => {
    for (let n = snap.score![i] + 1; n <= snap.score![i] + 3; n++) stale.push(goalKeyOf(snap.id, side, n));
  });
  seen.remove(stale);
  const fresh = keys.filter((k) => !seen.has(k.key));
  seen.add(fresh.map((k) => k.key));
  return snap.live ? fresh : [];
}

/** Наблюдатель для экрана: тот же observeScore поверх общего хранилища показанных голов. */
export function createGoalWatcher(seen: SeenStore) {
  return (snap: ScoreSnapshot): FreshGoal[] => observeScore(snap, seen);
}

/** Гол на ленте матча: сторона в порядке событий (screens/match/view.ts goals()). */
export interface TimelineGoal {
  side: GoalSide;
}

/**
 * Пачка пропущенных голов → порядок показа: по ходу матча (n-й гол стороны — его место на ленте),
 * не больше max последних. Ленты нет или гол на ней не найден — порядок прихода, такие — в конце.
 */
export function orderBatch<T extends { side: GoalSide; n: number }>(batch: T[], timeline: TimelineGoal[] | null, max = 3): T[] {
  const pos = (g: T): number => {
    if (!timeline) return Infinity;
    let k = 0;
    for (let i = 0; i < timeline.length; i++) if (timeline[i].side === g.side && ++k === g.n) return i;
    return Infinity;
  };
  return batch
    .map((g, i) => ({ g, i, p: pos(g) }))
    .sort((a, b) => a.p - b.p || a.i - b.i)
    .map((x) => x.g)
    .slice(-max);
}
