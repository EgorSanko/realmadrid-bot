import { useSpaLink } from '../lib/spaLink';
import { t } from '../lib/i18n';
import { AvatarButton } from './UserAvatar';

/** Шапка раздела, как .topbar в макете. На главной — логотип-надпись и справа кнопка-аватар (профиль). */
export function ScreenHeader({
  title,
  brand = false,
  live = false,
}: {
  title: string;
  brand?: boolean;
  /** идёт эфир — бейдж «В ЭФИРЕ», как в a-live.html */
  live?: boolean;
}) {
  if (brand) {
    return (
      <header className="brandbar">
        <h1 className="brand" aria-label={t('Мадридиста — {title}', { title })}>
          {/* настоящая эмблема клуба из нашего кэша /img; не загрузилась — просто прячется */}
          <img
            className="brand__crest"
            src="/img/team/8633.png"
            width={34}
            height={34}
            alt=""
            decoding="async"
            onError={(e) => {
              e.currentTarget.style.visibility = 'hidden';
            }}
          />
          <span className="brand__word">
            {t('МАДРИДИСТА')}
            <span className="brand__sub">{t('Real Madrid · фан-приложение')}</span>
          </span>
        </h1>
        <div className="brandbar__right">
          {live && (
            <span className="badge-live">
              <span className="live-dot" />
              {t('В ЭФИРЕ')}
            </span>
          )}
          <ProfileLink />
        </div>
      </header>
    );
  }
  return (
    <header className="topbar">
      <h1 className="topbar__title">{title}</h1>
    </header>
  );
}

function ProfileLink() {
  const link = useSpaLink();
  return <AvatarButton onClick={link('/profile').onClick} />;
}
