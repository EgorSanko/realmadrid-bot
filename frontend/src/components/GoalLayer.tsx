import { Suspense, lazy, useEffect, useState } from 'react';
import { onGoal, onLive, type GoalCelebration } from '../lib/celebrate';

// сама анимация гола — свой ленивый чанк: грузится только в момент первого гола
const loadBurst = () => import('./GoalBurst');
const GoalBurst = lazy(loadBurst);

/** Слой праздника над всеми экранами (App). Пока гола нет — ничего не рисует и не грузит. */
export function GoalLayer() {
  const [cur, setCur] = useState<{ goal: GoalCelebration; n: number } | null>(null);
  useEffect(() => onLive(() => void loadBurst().catch(() => undefined)), []);
  useEffect(() => onGoal((goal) => setCur((p) => ({ goal, n: (p?.n ?? 0) + 1 }))), []);
  if (!cur) return null;
  const n = cur.n;
  return (
    <Suspense fallback={null}>
      <GoalBurst key={n} goal={cur.goal} onDone={() => setCur((p) => (p?.n === n ? null : p))} />
    </Suspense>
  );
}
