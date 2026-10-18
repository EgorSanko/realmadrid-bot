import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiFetchError, fetchApi } from './api';
import { onRefresh } from './refresh';

export interface PollState<T> {
  data: T | null;
  /** последняя ошибка; при уже полученных данных их не сбрасывает */
  error: ApiFetchError | null;
  /** первая загрузка ещё идёт */
  loading: boolean;
  /** когда пришёл последний удачный ответ (Date.now()) */
  receivedAt: number;
  /** загрузить сейчас (кнопка «Повторить», конец отсчёта) */
  reload: () => void;
}

/**
 * Опрос эндпоинта: интервал считается по последним данным (во время матча — чаще).
 * Пока вкладка скрыта — не опрашиваем; при возврате (visibilitychange) — сразу.
 */
export function usePoll<T>(path: string, intervalFor: (data: T | null) => number): PollState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiFetchError | null>(null);
  const [loading, setLoading] = useState(true);
  const [receivedAt, setReceivedAt] = useState(0);
  const intervalRef = useRef(intervalFor);
  intervalRef.current = intervalFor;
  const loadRef = useRef<() => void>(() => {});
  const hasData = useRef(false);
  hasData.current = data != null;

  useEffect(() => {
    let alive = true;
    let ctrl: AbortController | null = null;
    let timer = 0;
    let last: T | null = null;

    const schedule = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (document.visibilityState === 'visible') void load();
        else schedule();
      }, intervalRef.current(last));
    };

    const load = async () => {
      ctrl?.abort();
      const c = new AbortController();
      ctrl = c;
      try {
        const d = await fetchApi<T>(path, c.signal);
        if (!alive || c.signal.aborted) return;
        last = d;
        setData(d);
        setError(null);
        setReceivedAt(Date.now());
      } catch (e) {
        if (!alive || (e as Error).name === 'AbortError') return;
        setError(e instanceof ApiFetchError ? e : new ApiFetchError(0, null, String(e)));
      }
      if (!alive) return;
      setLoading(false);
      schedule();
    };

    loadRef.current = () => {
      window.clearTimeout(timer);
      void load();
    };

    const onVisible = () => {
      if (document.visibilityState === 'visible') loadRef.current();
    };

    void load();
    document.addEventListener('visibilitychange', onVisible);
    // pull-to-refresh: перечитать сейчас (опрос дальше идёт своим чередом)
    const off = onRefresh(() => {
      window.clearTimeout(timer);
      return load();
    });
    return () => {
      off();
      alive = false;
      window.clearTimeout(timer);
      ctrl?.abort();
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [path]);

  // стабильная ссылка: от неё зависят эффекты (конец отсчёта) — новая на каждый ответ зацикливала бы запросы
  const reload = useCallback(() => {
    setLoading((l) => l || !hasData.current);
    loadRef.current();
  }, []);

  return { data, error, loading, receivedAt, reload };
}
