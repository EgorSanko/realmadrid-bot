import { fetchMatch } from '../api/match';
import type { GoalCelebration } from '../lib/celebrate';
import { orderBatch } from '../lib/goalWatch';
import { goals } from '../screens/match/view';

/**
 * Несколько пропущенных голов: одна лёгкая выборка матча (не дольше 1,5 с) — и голы по ходу матча.
 * Отдельный ленивый модуль: экран матча и его разбор не попадают в основной чанк.
 */
export async function orderGoals(batch: GoalCelebration[]): Promise<GoalCelebration[]> {
  const ctrl = new AbortController();
  const t = window.setTimeout(() => ctrl.abort(), 1500);
  try {
    const r = await fetchMatch(batch[0].matchId, ctrl.signal);
    return orderBatch(batch, r.kind === 'ok' ? goals(r.match) : null);
  } catch {
    return orderBatch(batch, null);
  } finally {
    window.clearTimeout(t);
  }
}
