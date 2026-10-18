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

/** Слой праздника над всеми экранами (App). Пока гола нет — ничего не рисует и не грузит. */
export function GoalLayer() {
  const [cur, setCur] = useState<{ goal: GoalCelebration; n: number } | null>(null);
  const fsHost = useFullscreenHost();
  useEffect(() => onLive(() => void loadBurst().catch(() => undefined)), []);
  useEffect(() => onGoal((goal) => setCur((p) => ({ goal, n: (p?.n ?? 0) + 1 }))), []);
  if (!cur) return null;
  const n = cur.n;
  const layer = (
    <Suspense fallback={null}>
      <GoalBurst key={n} goal={cur.goal} onDone={() => setCur((p) => (p?.n === n ? null : p))} />
    </Suspense>
  );
  return fsHost ? createPortal(layer, fsHost) : layer;
}
