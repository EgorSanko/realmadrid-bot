import { useLocation } from 'react-router';
import { useSpaLink } from '../lib/spaLink';
import '../styles/gamesTabs.css';

/** Раздел «Игры»: «Прогнозы / Викторина / Пенальти». Ссылки, а не кнопки — у каждой вкладки свой адрес. */
export const GAME_TABS = [
  { path: '/predict', label: 'Прогнозы' },
  { path: '/games/quiz', label: 'Викторина' },
  { path: '/games/penalty', label: 'Пенальти' },
] as const;

export function GamesTabs() {
  const { pathname } = useLocation();
  const link = useSpaLink();
  return (
    <nav className="ui-tabs ui-tabs--segmented gtabs" aria-label="Игры">
      {GAME_TABS.map((t) => {
        const on = pathname.startsWith(t.path);
        return (
          <a key={t.path} className={`ui-tabs__tab gtabs__tab${on ? ' is-on' : ''}`} aria-current={on ? 'page' : undefined} {...link(t.path)}>
            {t.label}
          </a>
        );
      })}
    </nav>
  );
}
