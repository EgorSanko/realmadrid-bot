import { useState } from 'react';
import type { MouseEvent } from 'react';
import { useAuth } from '../lib/auth';
import { t } from '../lib/i18n';
import '../styles/auth.css';

/** Силуэт: без входа или пока аватар не скачан — свой SVG, никаких внешних картинок. */
function Silhouette({ size }: { size: number }) {
  return (
    <svg className="uav__sil" width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="15.5" r="7" />
      <path d="M6.5 35.5c1.6-7.4 7-11.5 13.5-11.5s11.9 4.1 13.5 11.5" />
    </svg>
  );
}

/** Аватар пользователя с золотым кольцом. src — только наш /img/avatar/…; ошибка загрузки — силуэт. */
export function UserAvatar({ src, size = 40, className }: { src: string | null | undefined; size?: number; className?: string }) {
  const [broken, setBroken] = useState<string | null>(null);
  const show = !!src && broken !== src;
  return (
    <span className={`uav${className ? ` ${className}` : ''}`} style={{ width: size, height: size }}>
      {show ? (
        <img src={src!} alt="" width={size} height={size} decoding="async" draggable={false} onError={() => setBroken(src!)} />
      ) : (
        <Silhouette size={size} />
      )}
    </span>
  );
}

/** Кнопка-аватар в шапке главной → /profile. Без входа — силуэт. */
export function AvatarButton({ onClick }: { onClick?: (e: MouseEvent<HTMLAnchorElement>) => void }) {
  const auth = useAuth();
  const label = auth.user ? t('Профиль: {name}', { name: auth.user.name }) : t('Профиль и вход');
  return (
    <a className="avatar-btn" href="/profile" aria-label={label} title={label} onClick={onClick}>
      <UserAvatar src={auth.user?.avatar} size={38} />
    </a>
  );
}
