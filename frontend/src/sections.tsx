import type { ReactNode } from 'react';

/** Пять разделов нижнего меню. Иконки — ровно те, что в макете a-home.html («Игры» — кубок прогнозов). */
export interface Section {
  path: string;
  label: string;
  stage: number;
  /** что появится в разделе — описание продукта, не данные */
  about: string;
  /** другие адреса, на которых пункт меню тоже подсвечен */
  also?: string[];
  icon: ReactNode;
}

export const SECTIONS: Section[] = [
  {
    path: '/',
    label: 'Главная',
    stage: 2,
    about: 'Ближайший матч, обратный отсчёт и главное за день.',
    icon: <path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z" />,
  },
  {
    path: '/matches',
    label: 'Матчи',
    stage: 7,
    about: 'Календарь, результаты и онлайн матчей.',
    icon: (
      <>
        <rect x="4" y="5" width="16" height="15" rx="2" />
        <path d="M4 10h16M9 3v4M15 3v4" />
      </>
    ),
  },
  {
    path: '/team',
    label: 'Команда',
    stage: 8,
    about: 'Состав и статистика игроков.',
    icon: <path d="M8 4l-4 3 2 4 2-1v10h8V10l2 1 2-4-4-3c-1 1.5-2.5 2-4 2s-3-.5-4-2z" />,
  },
  {
    path: '/media',
    label: 'Медиа',
    stage: 9,
    about: 'Видео и новости клуба.',
    icon: (
      <>
        <rect x="3" y="6" width="18" height="13" rx="2" />
        <path d="M10 10v5l4-2.5z" />
      </>
    ),
  },
  {
    // «Игры»: внутри вкладки «Прогнозы / Викторина / Пенальти» (components/GamesTabs.tsx).
    // Пункт ведёт на прогнозы — главную игру раздела, викторина и пенальти — /games/*.
    path: '/predict',
    label: 'Игры',
    stage: 10,
    about: 'Прогнозы на матчи, викторина и пенальти.',
    also: ['/games'],
    icon: <path d="M7 4h10v4a5 5 0 01-10 0zM5 5H3v1a4 4 0 004 4M19 5h2v1a4 4 0 01-4 4M12 13v4M8 20h8" />,
  },
];

export function Icon({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {children}
    </svg>
  );
}

/** Пункт меню подсвечен: свой адрес или один из `also`. */
export function sectionActive(s: Section, pathname: string): boolean {
  if (s.path === '/') return pathname === '/';
  return [s.path, ...(s.also ?? [])].some((p) => pathname === p || pathname.startsWith(p + '/'));
}
