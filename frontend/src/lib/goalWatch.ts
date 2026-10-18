/**
 * Новые голы во время лайва: что праздновать, а что уже показано.
 *
 * Гол определяется по счёту: «матч 123, хозяева, 2-й гол» → ключ `123:home:2`. Так один и тот же гол
 * узнаётся и на главной (там есть только счёт), и на экране матча (счёт + события), и в другой вкладке
 * той же сессии. Показанные ключи — в sessionStorage (rmGoalsSeen).
 *
 * Правила:
 *  — первый взгляд на матч (открыли экран, а голы уже забиты) — всё помечаем показанным, без анимации;
 *  — праздник только пока матч идёт; после свистка новые цифры просто помечаем;
 *  — счёт уменьшился (VAR отменил гол) — снимаем пометку с «лишних» ключей: перебитый гол отпразднуем;
 *  — пришло сразу больше двух голов (вкладка спала) — не празднуем, это уже не новость.
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
const MAX_FRESH = 2;

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

/** Множество показанных голов поверх sessionStorage; без хранилища — просто в памяти. */
export function sessionSeen(storage: Pick<Storage, 'getItem' | 'setItem'> | null): SeenStore {
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
 * Один шаг наблюдения. first — первый взгляд на этот матч в этом экране.
 * Возвращает голы, которые надо отпраздновать (по порядку), и сам обновляет seen.
 */
export function observeScore(snap: ScoreSnapshot, seen: SeenStore, first: boolean): FreshGoal[] {
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
  if (first || !snap.live || fresh.length === 0 || fresh.length > MAX_FRESH) return [];
  return fresh;
}

/** Прогон наблюдателя для одного экрана: помнит, видел ли он уже этот матч. */
export function createGoalWatcher(seen: SeenStore) {
  const looked = new Set<string>();
  return (snap: ScoreSnapshot): FreshGoal[] => {
    const id = String(snap.id);
    const first = !looked.has(id);
    if (snap.score) looked.add(id);
    return observeScore(snap, seen, first);
  };
}
