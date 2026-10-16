import { useCallback } from 'react';
import type { MouseEvent } from 'react';
import { useNavigate } from 'react-router';

/**
 * Компоненты набора рисуют обычные <a href>. Чтобы переход не перезагружал мини-приложение,
 * перехватываем простой клик и ведём через роутер; клик с модификаторами — как у браузера.
 */
export function useSpaLink() {
  const navigate = useNavigate();
  return useCallback(
    (to: string) => ({
      href: to,
      onClick: (e?: MouseEvent<HTMLElement>) => {
        if (!e || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        navigate(to);
      },
    }),
    [navigate],
  );
}
