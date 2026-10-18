import { Suspense, lazy, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { onGoal, onLive, type GoalCelebration } from '../lib/celebrate';

// сама анимация гола — свой ленивый чанк: грузится только в момент первого гола
const loadBurst = () => import('./GoalBurst');
const GoalBurst = lazy(loadBurst);

/** Куда рисовать плашку: трансляция во весь экран (Fullscreen API) показывает только свой элемент —
 *  плашка должна быть внутри него, иначе гол во время просмотра не виден. */
function useFullscreenHost(): Element | null {
  const [host, setHost] = useState<Element | null>(() => (typeof document !== 'undefined' ? document.fullscreenElement : null));
  useEffect(() => {
    const on = () => setHost(document.fullscreenElement);
    document.addEventListener('fullscreenchange', on);
    document.addEventListener('webkitfullscreenchange', on);
    return () => {
      document.removeEventListener('fullscreenchange', on);
      document.removeEventListener('webkitfullscreenchange', on);
    };
  }, []);
  return host;
}

let seq = 0;

/** Слой праздника над всеми экранами (App). Пока гола нет — ничего не рисует и не грузит.
 *  Голы — очередью: пропустил «забили и пропустили» — обе плашки по ходу матча, одна за другой. */
export function GoalLayer() {
  const [queue, setQueue] = useState<Array<{ goal: GoalCelebration; n: number }>>([]);
  const fsHost = useFullscreenHost();
  useEffect(() => onLive(() => void loadBurst().catch(() => undefined)), []);
  useEffect(
    () =>
      onGoal((batch) => {
        const push = (list: GoalCelebration[]) => setQueue((q) => [...q, ...list.map((goal) => ({ goal, n: ++seq }))]);
        if (batch.length === 1) push(batch);
        else
          void import('./goalOrder')
            .then(({ orderGoals }) => orderGoals(batch))
            .then(push, () => push(batch.slice(-3)));
      }),
    [],
  );
  const cur = queue[0];
  if (!cur) return null;
  const n = cur.n;
  const layer = (
    <Suspense fallback={null}>
      <GoalBurst key={n} goal={cur.goal} onDone={() => setQueue((q) => (q[0]?.n === n ? q.slice(1) : q))} />
    </Suspense>
  );
  return fsHost ? createPortal(layer, fsHost) : layer;
}
