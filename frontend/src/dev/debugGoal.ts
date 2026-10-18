/**
 * Только для dev-сервера (import.meta.env.DEV): симуляция гола в лайве.
 *   /match/<id>?debugGoal=1    — матч становится «идёт, 67′», через 2,5 с Реал забивает
 *   /match/<id>?debugGoal=opp  — то же, но забивает соперник (сдержанно: только табло)
 *   /?debugGoal=1              — то же на главной (ближайший матч становится лайвом 0:0 → 1:0)
 * В прод-сборку не попадает: вызовы стоят под `if (import.meta.env.DEV)` и вырезаются вместе с модулем.
 */
import type { ApiGoal, ApiMatch } from '../api/match';
import type { ApiHome } from '../lib/api';

const REAL_ID = 8633;
export const DEBUG_GOAL_DELAY = 2500;

let t0 = 0;

export function debugGoalMode(): 'real' | 'opp' | null {
  if (typeof location === 'undefined') return null;
  const v = new URLSearchParams(location.search).get('debugGoal');
  if (!v) return null;
  if (!t0) t0 = Date.now();
  return v === 'opp' ? 'opp' : 'real';
}

const scored = () => Date.now() - t0 >= DEBUG_GOAL_DELAY;

export function debugGoalMatch(m: ApiMatch): ApiMatch {
  const mode = debugGoalMode();
  if (!mode) return m;
  const realSide = m.away.id === REAL_ID ? 'away' : 'home';
  const side = mode === 'real' ? realSide : realSide === 'home' ? 'away' : 'home';
  const base: [number, number] = [m.home.score ?? 0, m.away.score ?? 0];
  const out: ApiMatch = {
    ...m,
    pending: false,
    status: { state: 'live', live: true, finished: false, minute: 67, added: null, label: null },
    home: { ...m.home, score: base[0] },
    away: { ...m.away, score: base[1] },
  };
  if (!scored()) return out;
  const sc: [number, number] = side === 'home' ? [base[0] + 1, base[1]] : [base[0], base[1] + 1];
  // автор — кто-то из стартового состава этой стороны (с фото), иначе прошлый автор гола
  const starters = m.lineups?.[side]?.starters ?? [];
  const fw = [...starters].reverse().find((p) => p.id != null) ?? null;
  const prev = m.events.find((e): e is ApiGoal => e.type === 'goal' && e.side === side && !!e.player);
  const player = fw ? { id: fw.id, name: fw.name, photo: fw.photo } : (prev?.player ?? null);
  const goal: ApiGoal = {
    type: 'goal', minute: 68, added: null, side, player, assist: null,
    own_goal: false, penalty: false, shootout: false, score: sc,
  };
  return { ...out, home: { ...out.home, score: sc[0] }, away: { ...out.away, score: sc[1] }, events: [...m.events, goal] };
}

export function debugGoalHome(h: ApiHome | null): ApiHome | null {
  const mode = debugGoalMode();
  if (!mode || !h?.next) return h;
  const n = h.next;
  const realHome = n.home.id === REAL_ID;
  const homeScores = mode === 'real' ? realHome : !realHome;
  const goal = scored() ? 1 : 0;
  return {
    ...h,
    next: {
      ...n,
      status: { state: 'live', live: true, finished: false, minute: 67 + goal, added: null, label: null },
      home: { ...n.home, score: homeScores ? goal : 0 },
      away: { ...n.away, score: homeScores ? 0 : goal },
    },
  };
}
