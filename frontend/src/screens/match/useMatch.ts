import { useCallback, useEffect, useRef, useState } from 'react';
import { LIVE_POLL_MS, fetchMatch, matchFingerprint, shouldPoll, type ApiMatch, type MatchResult } from '../../api/match';
import { DEBUG_GOAL_DELAY, debugGoalMatch, debugGoalMode } from '../../dev/debugGoal';
import { onRefresh } from '../../lib/refresh';

export type MatchLoad =
  | { kind: 'loading' }
  | { kind: 'ok'; match: ApiMatch }
  | { kind: 'not_found' }
  | { kind: 'unavailable' }
  | { kind: 'error'; message: string };

/** 503 (сборщик ещё пуст) — сервер скоро оживёт, пробуем сами реже, чем в лайве */
const UNAVAILABLE_RETRY_MS = 15_000;

/**
 * Данные матча. Пока матч идёт (или ответ pending) — опрос раз в 10 с и сразу при возврате на вкладку;
 * пока вкладка скрыта — не опрашиваем. Вне лайва — один запрос.
 * Ошибка сети во время опроса не стирает уже показанные данные.
 */
export function useMatch(id: string): { state: MatchLoad; reload: () => void } {
  const [state, setState] = useState<MatchLoad>({ kind: 'loading' });
  const last = useRef<{ fp: string; match: ApiMatch } | null>(null);
  const ctrl = useRef<AbortController | null>(null);
  const timer = useRef(0);
  const loadRef = useRef<() => void>(() => {});

  useEffect(() => {
    let alive = true;
    last.current = null;
    setState({ kind: 'loading' });

    const schedule = (ms: number) => {
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        // скрытая вкладка: ждём visibilitychange
        if (document.visibilityState === 'visible') void load();
      }, ms);
    };

    const apply = (r: MatchResult) => {
      if (r.kind === 'ok') {
        const fp = matchFingerprint(r.match);
        if (fp !== last.current?.fp) {
          last.current = { fp, match: r.match };
          setState({ kind: 'ok', match: r.match });
        }
        if (shouldPoll(r.match)) schedule(LIVE_POLL_MS);
        return;
      }
      // уже есть данные — ошибку опроса не показываем, просто пробуем снова
      if (last.current) {
        if (shouldPoll(last.current.match)) schedule(LIVE_POLL_MS);
        return;
      }
      setState(r);
      if (r.kind === 'unavailable') schedule(UNAVAILABLE_RETRY_MS);
    };

    const load = async () => {
      ctrl.current?.abort();
      const c = new AbortController();
      ctrl.current = c;
      try {
        let r = await fetchMatch(id, c.signal);
        // dev: ?debugGoal=1 — симуляция гола (в прод-сборку не попадает)
        if (import.meta.env.DEV && r.kind === 'ok') r = { kind: 'ok', match: debugGoalMatch(r.match) };
        if (alive && !c.signal.aborted) apply(r);
      } catch (e) {
        if ((e as Error).name !== 'AbortError' && alive) apply({ kind: 'error', message: String(e) });
      }
    };
    loadRef.current = () => {
      if (!last.current) setState({ kind: 'loading' });
      void load();
    };

    const onVisible = () => {
      if (document.visibilityState !== 'visible') return;
      const m = last.current?.match ?? null;
      // лайв — сразу свежие данные; первая загрузка не удалась — пробуем снова
      if (shouldPoll(m) || !m) void load();
    };

    void load();
    document.addEventListener('visibilitychange', onVisible);
    const off = onRefresh(() => load());
    let dbg = 0;
    if (import.meta.env.DEV && debugGoalMode()) dbg = window.setTimeout(() => alive && void load(), DEBUG_GOAL_DELAY + 100);
    return () => {
      alive = false;
      off();
      window.clearTimeout(dbg);
      window.clearTimeout(timer.current);
      ctrl.current?.abort();
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [id]);

  const reload = useCallback(() => loadRef.current(), []);
  return { state, reload };
}
