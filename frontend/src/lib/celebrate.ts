/**
 * Шина праздников: экран сообщает «гол Реала», слой GoalLayer (App) лениво грузит анимацию и показывает её.
 * Экраны не знают про анимацию, анимация не знает про экраны.
 */

export interface GoalScorer {
  id?: number;
  name: string;
}

export interface GoalCelebration {
  matchId: number | string;
  side: 'home' | 'away';
  /** какой по счёту гол этой стороны */
  n: number;
  /** «67′», если известна */
  minute?: string;
  /** автор, если уже известен; нет — слой сам спросит /api/match/{id} */
  scorer?: GoalScorer | null;
  /** пропустили: гол соперника — плашка сдержанная, без конфетти */
  against?: boolean;
  /** команда, забившая гол против Реала (эмблема на плашке) */
  rival?: { id?: number; name: string };
}

/** Пачка голов одного матча: слой сам расставит их по ходу матча и покажет по очереди. */
type Listener = (goals: GoalCelebration[]) => void;
const listeners = new Set<Listener>();

export function celebrateGoal(c: GoalCelebration): void {
  celebrateGoals([c]);
}

export function celebrateGoals(goals: GoalCelebration[]): void {
  if (goals.length) listeners.forEach((l) => l(goals));
}

export function onGoal(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

/* Идёт лайв — слой заранее подгружает чанк анимации, чтобы гол показался без задержки. */
const liveListeners = new Set<() => void>();
let liveSeen = false;

export function noteLive(): void {
  if (liveSeen) return;
  liveSeen = true;
  liveListeners.forEach((l) => l());
}

export function onLive(l: () => void): () => void {
  if (liveSeen) l();
  liveListeners.add(l);
  return () => liveListeners.delete(l);
}
