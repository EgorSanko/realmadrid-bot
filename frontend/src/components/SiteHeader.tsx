import { useEffect, useRef, useState } from 'react';
import { NavLink, useLocation } from 'react-router';
import { useAuth } from '../lib/auth';
import { useSpaLink } from '../lib/spaLink';
import { useStream } from '../lib/stream';
import { SECTIONS } from '../sections';
import { LoginButton } from './LoginButton';
import { UserAvatar } from './UserAvatar';

/** Верхняя шапка сайта на компьютере: эмблема и «МАДРИДИСТА» · разделы · «В ЭФИРЕ» и вход / аватар. */
export function SiteHeader() {
  const auth = useAuth();
  const stream = useStream();
  const link = useSpaLink();
  const { pathname } = useLocation();
  // разделы, вложенные в «Матчи» / «Медиа» / «Команду», подсвечивают свой пункт меню
  const activeOf = (path: string) => {
    if (path === '/') return pathname === '/';
    if (path === '/matches') return pathname.startsWith('/matches') || pathname.startsWith('/match/');
    if (path === '/media') return pathname.startsWith('/media') || pathname.startsWith('/news/') || pathname.startsWith('/video/');
    if (path === '/team') return pathname.startsWith('/team') || pathname.startsWith('/player/');
    return pathname.startsWith(path);
  };

  return (
    <header className="sh">
      <div className="sh__in">
        <a className="sh__brand" aria-label="Мадридиста — на главную" {...link('/')}>
          <img
            className="sh__crest"
            src="/img/team/8633.png"
            width={36}
            height={36}
            alt=""
            decoding="async"
            onError={(e) => {
              e.currentTarget.style.visibility = 'hidden';
            }}
          />
          <span className="sh__word">МАДРИДИСТА</span>
        </a>

        <nav className="sh__nav" aria-label="Разделы">
          {SECTIONS.map((s) => (
            <NavLink key={s.path} to={s.path} className={() => (activeOf(s.path) ? 'sh__link on' : 'sh__link')} aria-current={activeOf(s.path) ? 'page' : undefined}>
              {s.label}
            </NavLink>
          ))}
        </nav>

        <div className="sh__right">
          {stream?.live && (
            <a className="badge-live sh__live" {...link('/')} aria-label="Идёт эфир — смотреть на главной">
              <span className="live-dot" />В ЭФИРЕ
            </a>
          )}
          {auth.status === 'user' && auth.user ? (
            <a className="sh__user" title={`Профиль: ${auth.user.name}`} aria-label={`Профиль: ${auth.user.name}`} {...link('/profile')}>
              <UserAvatar src={auth.user.avatar} size={34} />
              <span className="sh__uname">{auth.user.name}</span>
            </a>
          ) : auth.status === 'loading' ? (
            <span className="sh__user-skel" aria-hidden="true" />
          ) : (
            <HeaderLogin />
          )}
        </div>
      </div>
    </header>
  );
}

const TG_ICON = (
  <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
    <path
      fill="currentColor"
      d="M21.4 3.6 2.9 10.7c-1.3.5-1.2 1.3-.2 1.6l4.7 1.5 1.8 5.6c.2.6.4.8.9.8.4 0 .6-.2.9-.5l2.3-2.2 4.8 3.5c.9.5 1.5.2 1.7-.8l3.1-14.6c.3-1.3-.5-1.9-1.5-1.5zM9.6 14.9l-.3 3.2-1.4-4.6 10.6-6.7z"
    />
  </svg>
);

/**
 * «Войти через Telegram» в шапке. Виджет Telegram со своими состояниями (загрузка, ошибка, запасной путь)
 * не помещается в строку меню — он открывается в панели под кнопкой. Скрипт виджета грузится только по нажатию.
 */
function HeaderLogin() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    const onDown = (e: PointerEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('pointerdown', onDown);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('pointerdown', onDown);
    };
  }, [open]);

  return (
    <div className="sh-login" ref={box}>
      <button type="button" className="sh-login__btn" aria-expanded={open} aria-controls="sh-login-panel" onClick={() => setOpen((v) => !v)}>
        {TG_ICON}
        Войти через Telegram
      </button>
      {open && (
        <div className="sh-login__panel" id="sh-login-panel" role="dialog" aria-label="Вход через Telegram">
          <p className="sh-login__text">Прогнозы, рейтинг и лиги с друзьями — после входа через Telegram. Пароль не нужен.</p>
          <LoginButton autoStart />
        </div>
      )}
    </div>
  );
}
