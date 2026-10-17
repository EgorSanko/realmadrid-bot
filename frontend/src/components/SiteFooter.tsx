import { useSpaLink } from '../lib/spaLink';
import { SECTIONS } from '../sections';

const BOT_LINK = 'https://t.me/Real_Madrid_football_bot';

/** Подвал сайта на компьютере. В мини-аппе не рисуется. */
export function SiteFooter() {
  const link = useSpaLink();
  return (
    <footer className="sf">
      <div className="sf__in">
        <div className="sf__brand">
          <img
            className="sf__crest"
            src="/img/team/8633.png"
            width={40}
            height={40}
            alt=""
            loading="lazy"
            decoding="async"
            onError={(e) => {
              e.currentTarget.style.visibility = 'hidden';
            }}
          />
          <div>
            <div className="sf__word">МАДРИДИСТА</div>
            <div className="sf__sub">Real Madrid · фан-приложение</div>
          </div>
        </div>

        <nav className="sf__nav" aria-label="Разделы сайта">
          {SECTIONS.map((s) => (
            <a key={s.path} className="sf__link" {...link(s.path)}>
              {s.label}
            </a>
          ))}
          <a className="sf__link" {...link('/profile')}>
            Профиль
          </a>
        </nav>

        <a className="sf__tg" href={BOT_LINK} target="_blank" rel="noopener noreferrer">
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
            <path
              fill="currentColor"
              d="M21.4 3.6 2.9 10.7c-1.3.5-1.2 1.3-.2 1.6l4.7 1.5 1.8 5.6c.2.6.4.8.9.8.4 0 .6-.2.9-.5l2.3-2.2 4.8 3.5c.9.5 1.5.2 1.7-.8l3.1-14.6c.3-1.3-.5-1.9-1.5-1.5zM9.6 14.9l-.3 3.2-1.4-4.6 10.6-6.7z"
            />
          </svg>
          Открыть в Telegram
        </a>
      </div>
      <p className="sf__legal">
        Неофициальный фан-проект, не связан с Real Madrid CF. Данные: FotMob, SofaScore, ESPN; новости: Чемпионат,
        Спорт-Экспресс, Sports.ru.
      </p>
    </footer>
  );
}
