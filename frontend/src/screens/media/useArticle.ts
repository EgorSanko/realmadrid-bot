import { useCallback, useEffect, useState } from 'react';
import { ApiError, getJson } from '../../lib/apiResource';
import type { ArticleData } from './mediaData';

export type ArticleState =
  | { kind: 'loading' }
  | { kind: 'pending'; data: ArticleData }
  | { kind: 'ok'; data: ArticleData }
  | { kind: 'not_found' }
  | { kind: 'error' };

const RETRY_MS = 2000;
// ~1 минута: дальше показываем то, что есть (лид и ссылку на источник), а не вечное «загружаем»
const MAX_PENDING = 30;

/** /api/news/{aid}: pending → повтор через 2 с; 404 → «не найдена»; сеть / 503 → ошибка с «Повторить». */
export function useArticle(aid: string): { state: ArticleState; reload: () => void } {
  const [state, setState] = useState<ArticleState>({ kind: 'loading' });
  const [run, setRun] = useState(0);

  useEffect(() => {
    let timer = 0;
    let attempt = 0;
    const ctl = new AbortController();
    setState({ kind: 'loading' });
    const load = () => {
      getJson<ArticleData>(`/api/news/${encodeURIComponent(aid)}`, ctl.signal)
        .then((d) => {
          if (d.pending) {
            attempt += 1;
            if (attempt > MAX_PENDING) {
              setState({ kind: 'ok', data: { ...d, pending: false, reason: 'unavailable' } });
              return;
            }
            setState({ kind: 'pending', data: d });
            timer = window.setTimeout(load, RETRY_MS);
            return;
          }
          setState({ kind: 'ok', data: d });
        })
        .catch((e: Error) => {
          if (ctl.signal.aborted) return;
          setState(e instanceof ApiError && e.status === 404 ? { kind: 'not_found' } : { kind: 'error' });
        });
    };
    load();
    return () => {
      ctl.abort();
      window.clearTimeout(timer);
    };
  }, [aid, run]);

  const reload = useCallback(() => setRun((r) => r + 1), []);
  return { state, reload };
}
