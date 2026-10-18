import { useCallback, useMemo } from 'react';
import type { MouseEvent } from 'react';
import { useLocation, useNavigate, type Location } from 'react-router';

export const playerHref = (id: number) => `/player/${id}`;

/** Состояние истории для карточки поверх экрана: что лежит под ней и кого открыли (имя — для шапки, пока грузится). */
export interface PlayerNavState {
  backgroundLocation?: Location;
  player?: { id: number; name: string };
}

export function backgroundOf(location: Location): Location | undefined {
  return (location.state as PlayerNavState | null)?.backgroundLocation;
}

/* Откуда открыли карточку: кружок с фото игрока (для раскрытия карточки «из кружка»). */
let origin: { id: number; rect: DOMRect; at: number } | null = null;

/** Забрать прямоугольник кружка, из которого только что открыли карточку этого игрока (один раз). */
export function takePlayerOrigin(id: number): DOMRect | null {
  const o = origin;
  origin = null;
  return o && o.id === id && Date.now() - o.at < 1500 ? o.rect : null;
}

/**
 * Пропсы для компонентов набора: `playerHref` + `onPlayerClick`.
 * Простой клик открывает карточку поверх текущего экрана (он остаётся смонтированным, со своей прокруткой);
 * клик с модификаторами — как у обычной ссылки.
 */
export function usePlayerLinks() {
  const navigate = useNavigate();
  const location = useLocation();
  const onPlayerClick = useCallback(
    (p: { id: number; name: string }, e: MouseEvent<HTMLElement>) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      const ph = (e.currentTarget as HTMLElement).querySelector?.('.ui-photo');
      origin = ph ? { id: p.id, rect: ph.getBoundingClientRect(), at: Date.now() } : null;
      const bg = backgroundOf(location) ?? location;
      const state: PlayerNavState = { backgroundLocation: bg, player: p };
      navigate(playerHref(p.id), { state });
    },
    [navigate, location],
  );
  return useMemo(() => ({ playerHref, onPlayerClick }), [onPlayerClick]);
}
