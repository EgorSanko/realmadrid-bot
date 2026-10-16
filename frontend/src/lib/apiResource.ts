import { useCallback, useEffect, useState } from 'react';

/**
 * Чтение снимка нашего API (/api/*). Клиент ходит только на свой сервер, по относительным путям.
 * 503 `no_data` — сборщик ещё не получил данные: показываем как ошибку с понятным текстом.
 */
export class ApiError extends Error {
  status: number;
  noData: boolean;
  constructor(status: number, noData: boolean, message: string) {
    super(message);
    this.status = status;
    this.noData = noData;
  }
}

export interface SnapshotMeta {
  source: string | null;
  updated_at: string | null;
  age_s: number | null;
  stale: boolean;
  available: string[];
}

export async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(url, { signal, headers: { Accept: 'application/json' } });
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    /* не JSON — ниже ошибка по статусу */
  }
  if (!r.ok) {
    const err = (body as { error?: string } | null)?.error;
    throw new ApiError(r.status, err === 'no_data', err ?? `HTTP ${r.status}`);
  }
  return body as T;
}

export interface Resource<T> {
  data: T | null;
  error: ApiError | Error | null;
  loading: boolean;
  reload: () => void;
}

/** Загрузить один раз при монтировании; reload — повторить (кнопка в ErrorState). */
export function useApiResource<T>(url: string): Resource<T> {
  const [state, setState] = useState<{ data: T | null; error: Error | null; loading: boolean }>({
    data: null,
    error: null,
    loading: true,
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctl = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    getJson<T>(url, ctl.signal)
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error: Error) => {
        if (ctl.signal.aborted) return;
        setState((s) => ({ data: s.data, error, loading: false }));
      });
    return () => ctl.abort();
  }, [url, attempt]);

  const reload = useCallback(() => setAttempt((a) => a + 1), []);
  return { ...state, reload };
}

/** Текст ошибки для ErrorState. */
export function errorText(e: Error | null): string {
  if (e instanceof ApiError && e.noData) return 'Данные ещё собираются — загляни через пару минут';
  return 'Проверь соединение и попробуй ещё раз';
}
