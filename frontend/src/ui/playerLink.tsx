import type { MouseEvent, ReactNode } from 'react';
import { cx } from './format';
import { PlayerPhoto } from './images';

/**
 * Нажимаемый игрок. Компоненты набора не знают про роутер: экран передаёт
 * `playerHref` (адрес карточки) и, по желанию, `onPlayerClick` (переход без перезагрузки).
 * Нет id или нет `playerHref` — обычный текст, ничего не нажимается.
 */
export interface PlayerRefLite {
  id?: number;
  name: string;
}

export interface PlayerLinkProps {
  playerHref?: (id: number) => string;
  onPlayerClick?: (player: { id: number; name: string }, e: MouseEvent<HTMLElement>) => void;
}

export interface PlayerTapProps extends PlayerLinkProps {
  player: PlayerRefLite;
  children: ReactNode;
  className?: string;
  /** подпись для экранного диктора; по умолчанию «Имя — карточка игрока» */
  label?: string;
}

export function PlayerTap({ player, playerHref, onPlayerClick, children, className, label }: PlayerTapProps) {
  const id = player.id;
  if (id == null || !playerHref) return <span className={className}>{children}</span>;
  return (
    <a
      className={cx('ui-ptap', 'ui-press-soft', className)}
      href={playerHref(id)}
      aria-label={label ?? `${player.name} — карточка игрока`}
      onClick={onPlayerClick ? (e) => onPlayerClick({ id, name: player.name }, e) : undefined}
    >
      {children}
    </a>
  );
}

/**
 * Фото + имя одной строкой (хронология, «Не играли», лучшие игроки).
 * Фото — только если есть id FotMob: без id картинки нет (не силуэт-заглушка рядом с текстом).
 */
export function PlayerInline({
  player,
  size = 24,
  className,
  reverse,
  ...link
}: PlayerLinkProps & { player: PlayerRefLite; size?: number; className?: string; reverse?: boolean }) {
  const photo = player.id != null ? <PlayerPhoto id={player.id} name="" size={size} className="ui-pin__photo" /> : null;
  return (
    <PlayerTap player={player} {...link} className={cx('ui-pin', reverse && 'ui-pin--rev', className)}>
      {!reverse && photo}
      <span className="ui-pin__name">{player.name}</span>
      {reverse && photo}
    </PlayerTap>
  );
}
