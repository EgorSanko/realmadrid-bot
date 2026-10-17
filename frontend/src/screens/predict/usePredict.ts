import { useCallback, useEffect, useRef, useState } from 'react';
import { AuthFetchError, authFetch, useAuth } from '../../lib/auth';
import type { MatchesResponse, PredictionView } from '../../lib/predict';

export type Load<T> =
  | { kind: 'loading' }
  | { kind: 'ok'; data: T }
  | { kind: 'error'; status: number; code: string | null; message: string };

const LIVE_POLL_MS = 45_000;

/**
 * GET с входом (заголовки — lib/auth). Ждёт, пока станет ясно, вошёл ли пользователь, и перечитывает
 * при входе/выходе. Повторная загрузка не сбрасывает уже показанные данные.
 */
export function useAuthedGet<T>(path: string | null, deps: unknown[] = []): [Load<T>, () => void, (f: (d: T) => T) => void] {
  const auth = useAuth();
  const [state, setState] = useState<Load<T>>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const who = auth.status === 'user' ? auth.user?.id ?? 0 : auth.status;
  useEffect(() => {
    if (auth.status === 'loading' || path == null) return;
    const ctl = new AbortController();
    authFetch<T>(path, { signal: ctl.signal })
      .then((data) => setState({ kind: 'ok', data }))
      .catch((e: Error) => {
        if (ctl.signal.aborted) return;
        const fe = e instanceof AuthFetchError ? e : null;
        setState((s) =>
          s.kind === 'ok' && fe?.status === 0 ? s : { kind: 'error', status: fe?.status ?? 0, code: fe?.code ?? null, message: e.message },
        );
      });
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, who, attempt, ...deps]);
  const reload = useCallback(() => setAttempt((a) => a + 1), []);
  const patch = useCallback((f: (d: T) => T) => setState((s) => (s.kind === 'ok' ? { kind: 'ok', data: f(s.data) } : s)), []);
  return [state, reload, patch];
}

/** /api/predict/matches: ближайший матч и последние сыгранные; пока матч идёт — перечитываем раз в 45 с. */
export function usePredictMatches() {
  const [state, reload, patch] = useAuthedGet<MatchesResponse>('/api/predict/matches');
  const live = state.kind === 'ok' && state.data.next?.status === 'live';
  const reloadRef = useRef(reload);
  reloadRef.current = reload;
  useEffect(() => {
    if (!live) return;
    const t = window.setInterval(() => reloadRef.current(), LIVE_POLL_MS);
    return () => window.clearInterval(t);
  }, [live]);
  const setMyPrediction = useCallback(
    (p: PredictionView) => patch((d) => (d.next ? { ...d, next: { ...d.next, my_prediction: p } } : d)),
    [patch],
  );
  return { state, reload, setMyPrediction };
}
