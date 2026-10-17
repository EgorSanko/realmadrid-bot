import { hapticFeedback } from '@tma.js/sdk-react';
import { useCallback, useEffect, useState } from 'react';
import { AuthFetchError, authFetch, inMiniApp, useAuth } from '../../lib/auth';
import { LOCAL_KEY, gameError, mergeLocalBest, parseLocalBest } from '../../lib/games';
import type { GameId, GamesMe, LocalBest } from '../../lib/games';

/** Запрос к /api/games/*: с входом, если он есть (без входа игра тоже работает). body — POST, иначе GET. */
export async function gamesFetch<T>(path: string, body?: unknown): Promise<T> {
  try {
    return await authFetch<T>(`/api/games${path}`, body === undefined ? {} : { method: 'POST', body });
  } catch (e) {
    if (e instanceof AuthFetchError) throw new AuthFetchError(e.status, e.code, gameError(e.status, e.message));
    throw e;
  }
}

/* ---------- рекорды на устройстве ---------- */

function readLocal(): LocalBest {
  try {
    return parseLocalBest(localStorage.getItem(LOCAL_KEY));
  } catch {
    return {};
  }
}

/** Рекорды на этом устройстве (для игры без входа; со входом — в дополнение к серверным). */
export function useLocalBest(): [LocalBest, (game: GameId, level: string, score: number) => boolean] {
  const [store, setStore] = useState<LocalBest>(readLocal);
  const save = useCallback((game: GameId, level: string, score: number) => {
    const { store: next, record } = mergeLocalBest(readLocal(), game, level, score);
    if (next !== store) {
      try {
        localStorage.setItem(LOCAL_KEY, JSON.stringify(next));
      } catch {
        /* приватный режим — рекорд останется до перезагрузки */
      }
    }
    setStore(next);
    return record;
  }, [store]);
  return [store, save];
}

/** Мои рекорды на сервере (только со входом). */
export function useGamesMe(ver: number): GamesMe | null {
  const auth = useAuth();
  const [me, setMe] = useState<GamesMe | null>(null);
  useEffect(() => {
    if (auth.status !== 'user') {
      setMe(null);
      return;
    }
    let alive = true;
    authFetch<GamesMe>('/api/games/me')
      .then((r) => alive && setMe(r))
      .catch(() => alive && setMe(null));
    return () => {
      alive = false;
    };
  }, [auth.status, ver]);
  return me;
}

/* ---------- вибрация в Telegram ---------- */

type Impact = 'light' | 'medium' | 'heavy' | 'rigid' | 'soft';

export const haptic = {
  impact(style: Impact = 'light') {
    if (!inMiniApp()) return;
    try {
      hapticFeedback.impactOccurred.ifAvailable(style);
    } catch {
      /* старый клиент Telegram */
    }
  },
  notify(type: 'success' | 'error' | 'warning') {
    if (!inMiniApp()) return;
    try {
      hapticFeedback.notificationOccurred.ifAvailable(type);
    } catch {
      /* старый клиент Telegram */
    }
  },
};

/** Пользователь просит меньше движения — анимации короче и без тряски. */
export function reducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}
