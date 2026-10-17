import { useCallback, useEffect, useState } from 'react';
import { ApiError, getJson } from '../../lib/apiResource';
import type { ApiPlayer } from './playerData';

export type PlayerState =
  | { kind: 'loading' }
  | { kind: 'pending'; attempt: number }
  | { kind: 'ok'; player: ApiPlayer }
  | { kind: 'not_found' }
  | { kind: 'error'; unavailable: boolean };

const RETRY_MS = 3000;
// ~2 минуты ожидания: дальше честно показываем ошибку (сборщик не успел или источник молчит)
const MAX_PENDING = 40;

/** /api/player/{id}: pending → повтор через 3 с; 404 → «не найден»; 503 / сеть → ошибка с «Повторить». */
export function usePlayer(id: string): { state: PlayerState; reload: () => void } {
  const [state, setState] = useState<PlayerState>({ kind: 'loading' });
  const [run, setRun] = useState(0);

  useEffect(() => {
    let timer = 0;
    let attempt = 0;
    const ctl = new AbortController();
    setState({ kind: 'loading' });
    const load = () => {
      getJson<ApiPlayer>(`/api/player/${encodeURIComponent(id)}`, ctl.signal)
        .then((p) => {
          if (p.pending) {
            attempt += 1;
            if (attempt > MAX_PENDING) {
              setState({ kind: 'error', unavailable: true });
              return;
            }
            setState({ kind: 'pending', attempt });
            timer = window.setTimeout(load, RETRY_MS);
            return;
          }
          setState({ kind: 'ok', player: p });
        })
        .catch((e: Error) => {
          if (ctl.signal.aborted) return;
          if (e instanceof ApiError && e.status === 404) setState({ kind: 'not_found' });
          else setState({ kind: 'error', unavailable: e instanceof ApiError && e.status === 503 });
        });
    };
    load();
    return () => {
      ctl.abort();
      window.clearTimeout(timer);
    };
  }, [id, run]);

  const reload = useCallback(() => setRun((r) => r + 1), []);
  return { state, reload };
}
