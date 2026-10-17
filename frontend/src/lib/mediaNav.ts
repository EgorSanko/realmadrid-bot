import { useCallback, useMemo } from 'react';
import type { MouseEvent } from 'react';
import { useLocation, useNavigate, type Location } from 'react-router';
import { backgroundOf } from './playerNav';

/*
 * Новость и видео открываются внутри приложения: /news/:aid и /video/:id — полноэкранный слой
 * поверх экрана, с которого их открыли (как карточка игрока). Экран под слоем остаётся смонтированным —
 * «Назад» возвращает к той же прокрутке и вкладке. Прямой заход по ссылке — слой рисуется один.
 */

export const newsHref = (aid: string) => `/news/${aid}`;
export const videoHref = (id: string) => `/video/${id}`;

/** Что знаем о материале до загрузки — для шапки, пока грузится. */
export interface NewsPreview {
  aid: string;
  title: string;
  source: string;
  image: string | null;
  published: string | null;
}
export interface VideoPreview {
  id: string;
  title: string;
  short: boolean;
  published: string | null;
}

export interface MediaNavState {
  backgroundLocation?: Location;
  news?: NewsPreview;
  video?: VideoPreview;
}

const YT_ID = /^[A-Za-z0-9_-]{11}$/;
export const isVideoId = (id: string) => YT_ID.test(id);

/** Клик с модификаторами и средней кнопкой — как у обычной ссылки (новая вкладка браузера). */
export function plainClick(e: MouseEvent<HTMLElement>): boolean {
  return !(e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey);
}

export function useMediaNav() {
  const navigate = useNavigate();
  const location = useLocation();
  const bg = (): Location => backgroundOf(location) ?? location;
  const openNews = useCallback(
    (n: NewsPreview, e?: MouseEvent<HTMLElement>) => {
      if (e) {
        if (!plainClick(e)) return;
        e.preventDefault();
      }
      const state: MediaNavState = { backgroundLocation: bg(), news: n };
      navigate(newsHref(n.aid), { state });
    },
    [navigate, location],
  );
  const openVideo = useCallback(
    (v: VideoPreview, e?: MouseEvent<HTMLElement>) => {
      if (e) {
        if (!plainClick(e)) return;
        e.preventDefault();
      }
      const state: MediaNavState = { backgroundLocation: bg(), video: v };
      navigate(videoHref(v.id), { state });
    },
    [navigate, location],
  );
  return useMemo(() => ({ openNews, openVideo }), [openNews, openVideo]);
}

/**
 * «Назад» со слоя: открыт из приложения — шаг назад по истории; прямой заход (под слоем ничего) —
 * в «Медиа», а не из приложения.
 */
export function useOverlayBack(fallback: string) {
  const navigate = useNavigate();
  const location = useLocation();
  const overlay = backgroundOf(location) != null;
  return useCallback(() => {
    const idx = (window.history.state as { idx?: number } | null)?.idx;
    if (overlay && idx) navigate(-1);
    else navigate(fallback, { replace: true });
  }, [navigate, overlay, fallback]);
}
