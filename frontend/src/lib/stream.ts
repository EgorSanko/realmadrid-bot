import { useEffect, useState } from 'react';

export interface StreamState {
  live: boolean;
  url: string | null;
  title: string | null;
  started_at: string | null;
}

export interface AdminStreamState extends StreamState {
  stopped_at: string | null;
  expires_at: string | null;
}

export const POLL_MS = 20_000;

export async function fetchStream(signal?: AbortSignal): Promise<StreamState> {
  const r = await fetch('/api/stream', { cache: 'no-store', signal });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as StreamState;
}

/*
 * Состояние эфира: опрос раз в 20 с и сразу при возврате на вкладку. Пока вкладка скрыта — не опрашиваем.
 * Ошибка сети не сбрасывает последнее известное состояние.
 * Один опрос на всё приложение: главная и шапка сайта («В ЭФИРЕ») читают одно и то же состояние.
 * Опрос идёт, пока смонтирован хотя бы один подписчик.
 */
let shared: StreamState | null = null;
let lastKey = '';
const subs = new Set<(s: StreamState | null) => void>();
let stopPoll: (() => void) | null = null;

function startPoll(): () => void {
  let ctrl: AbortController | null = null;
  let timer = 0;
  const publish = (s: StreamState) => {
    shared = s;
    subs.forEach((f) => f(s));
  };

  const load = async () => {
    ctrl?.abort();
    ctrl = new AbortController();
    try {
      const s = await fetchStream(ctrl.signal);
      const key = `${s.live}|${s.url}|${s.title}`;
      if (key !== lastKey) {
        lastKey = key;
        publish(s);
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      // нет сети / сервер недоступен: оставляем, что было (а при первом запуске — «нет эфира»)
      if (!lastKey) {
        lastKey = 'offline';
        publish({ live: false, url: null, title: null, started_at: null });
      }
    }
  };

  const schedule = () => {
    window.clearInterval(timer);
    timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load();
    }, POLL_MS);
  };

  const onVisible = () => {
    if (document.visibilityState === 'visible') {
      void load();
      schedule();
    }
  };

  void load();
  schedule();
  document.addEventListener('visibilitychange', onVisible);
  return () => {
    window.clearInterval(timer);
    ctrl?.abort();
    document.removeEventListener('visibilitychange', onVisible);
  };
}

export function useStream(): StreamState | null {
  const [state, setState] = useState<StreamState | null>(shared);

  useEffect(() => {
    subs.add(setState);
    setState(shared);
    if (!stopPoll) stopPoll = startPoll();
    return () => {
      subs.delete(setState);
      if (subs.size === 0 && stopPoll) {
        stopPoll();
        stopPoll = null;
      }
    };
  }, []);

  return state;
}

// ---------- админка ----------

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function adminRequest<T>(
  method: 'GET' | 'POST',
  path: string,
  auth: Record<string, string>,
  body?: unknown,
): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, {
      method,
      cache: 'no-store',
      headers: {
        ...auth,
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, 'Сервер недоступен. Проверьте интернет и попробуйте ещё раз');
  }
  if (r.ok) return (await r.json()) as T;
  let detail = '';
  try {
    const j = (await r.json()) as { detail?: unknown };
    if (typeof j.detail === 'string') detail = j.detail;
  } catch {
    /* не JSON */
  }
  if (r.status === 401 || r.status === 403) {
    if (detail === 'Админка отключена') throw new ApiError(r.status, 'Админка отключена на сервере');
    const why = detail && detail !== 'Нет доступа' ? `: ${detail[0].toLowerCase()}${detail.slice(1)}` : '';
    throw new ApiError(r.status, `Нет доступа${why}`);
  }
  if (r.status === 422) throw new ApiError(422, detail || 'Проверьте ссылку');
  throw new ApiError(r.status, `Ошибка сервера (${r.status})`);
}
