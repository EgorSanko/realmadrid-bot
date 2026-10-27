import { useLocation } from 'react-router';
import { t } from '../lib/i18n';
import { useSpaLink } from '../lib/spaLink';
import '../styles/gamesTabs.css';

/** Раздел «Игры»: «Прогнозы / Викторина / Пенальти». Ссылки, а не кнопки — у каждой вкладки свой адрес. */
export const GAME_TABS = [
  { path: '/predict', label: t('Прогнозы') },
  { path: '/games/quiz', label: t('Викторина') },
  { path: '/games/penalty', label: t('Пенальти') },
] as const;

export function GamesTabs() {
  const { pathname } = useLocation();
  const link = useSpaLink();
  return (
    <nav className="ui-tabs ui-tabs--segmented gtabs" aria-label={t('Игры')}>
      {GAME_TABS.map((tab) => {
        const on = pathname.startsWith(tab.path);
        return (
          <a key={tab.path} className={`ui-tabs__tab gtabs__tab${on ? ' is-on' : ''}`} aria-current={on ? 'page' : undefined} {...link(tab.path)}>
            {tab.label}
          </a>
        );
      })}
    </nav>
  );
}
