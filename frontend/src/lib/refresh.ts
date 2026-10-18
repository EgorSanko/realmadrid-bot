import { useCallback, useEffect, useRef } from 'react';

/**
 * Шина «обновить экран» для pull-to-refresh: хуки данных (usePoll, useMatch, useApiResource,
 * useAuthedGet) подписываются, жест вызывает refreshAll() и ждёт, пока все перечитают (не дольше 5 с).
 * Никаких новых запросов сверх обычного «Повторить»: каждый хук просто делает свою загрузку ещё раз.
 */

type Refresher = () => Promise<unknown> | void;
const subs = new Set<Refresher>();

export function onRefresh(fn: Refresher): () => void {
  subs.add(fn);
  return () => {
    subs.delete(fn);
  };
}

export const REFRESH_TIMEOUT_MS = 5000;

export async function refreshAll(): Promise<void> {
  const all = Promise.allSettled([...subs].map((f) => Promise.resolve().then(f)));
  await Promise.race([all, new Promise((r) => setTimeout(r, REFRESH_TIMEOUT_MS))]);
}

/**
 * Для хуков вида «счётчик попыток»: при обновлении экрана дёргает bump() и ждёт settle() —
 * его хук зовёт, когда загрузка закончилась (успехом или ошибкой).
 */
export function useRefreshBump(bump: () => void): () => void {
  const waiters = useRef<Array<() => void>>([]);
  useEffect(
    () =>
      onRefresh(
        () =>
          new Promise<void>((res) => {
            waiters.current.push(res);
            bump();
          }),
      ),
    [bump],
  );
  return useCallback(() => {
    const w = waiters.current;
    waiters.current = [];
    w.forEach((f) => f());
  }, []);
}
