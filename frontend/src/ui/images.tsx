import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { cx } from './format';

/**
 * Картинки отдаёт наш сервер. Никаких самодельных эмблем: если картинка
 * не загрузилась или пришла пустая (1×1) — элемент становится невидимым,
 * но держит размер, чтобы вёрстка не прыгала.
 */
export const imageUrl = {
  team: (id: number | string) => `/img/team/${id}.png`,
  player: (id: number | string) => `/img/player/${id}.png`,
  league: (id: number | string) => `/img/league/${id}.png`,
  flag: (iso2: string) => `/img/flag/${iso2.toLowerCase()}.svg`,
};

interface SafeImgProps {
  src: string;
  alt: string;
  width: number;
  height: number;
  className?: string;
  style?: CSSProperties;
  /** что показать вместо сломанной картинки; не задано — картинка просто прячется */
  fallback?: ReactNode;
  /** картинка пришла и не пустая */
  onReady?: () => void;
}

function isEmptyImage(img: HTMLImageElement) {
  return img.naturalWidth <= 1 && img.naturalHeight <= 1;
}

export function SafeImg({ src, alt, width, height, className, style, fallback, onReady }: SafeImgProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const ref = useRef<HTMLImageElement>(null);
  const failed = failedSrc === src;

  // картинка могла уже загрузиться (или сломаться) до того, как React повесил обработчики
  useEffect(() => {
    const img = ref.current;
    if (!img || !img.complete) return;
    if (isEmptyImage(img)) setFailedSrc(src);
    else onReady?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src]);

  if (failed && fallback !== undefined) return <>{fallback}</>;
  return (
    <img
      ref={ref}
      src={src}
      alt={alt}
      width={width}
      height={height}
      loading="lazy"
      decoding="async"
      draggable={false}
      className={cx('ui-img', failed && 'is-failed', className)}
      style={{ width, height, ...style }}
      aria-hidden={failed || undefined}
      onError={() => setFailedSrc(src)}
      onLoad={(e) => {
        if (isEmptyImage(e.currentTarget)) setFailedSrc(src);
        else onReady?.();
      }}
    />
  );
}

export type CrestSize = 16 | 20 | 24 | 28 | 36 | 52 | 56 | 68;

export interface TeamCrestProps {
  /** id команды (FotMob) */
  id: number;
  /** название команды — идёт в alt */
  name: string;
  size?: CrestSize;
  className?: string;
}

/** Эмблема клуба, 192 px с прозрачным фоном, вписывается в квадрат size×size. */
export function TeamCrest({ id, name, size = 36, className }: TeamCrestProps) {
  return <SafeImg src={imageUrl.team(id)} alt={name} width={size} height={size} className={cx('ui-crest', className)} />;
}

export interface LeagueLogoProps {
  id: number;
  name: string;
  size?: number;
  className?: string;
}

/** Логотип турнира (версия для тёмного фона). */
export function LeagueLogo({ id, name, size = 20, className }: LeagueLogoProps) {
  return <SafeImg src={imageUrl.league(id)} alt={name} width={size} height={size} className={cx('ui-league', className)} />;
}

export interface FlagProps {
  /** ISO 3166-1 alpha-2: es, fr, br… */
  iso2: string;
  /** название страны — в alt */
  name: string;
  /** ширина; высота = 3/4 ширины */
  width?: number;
  className?: string;
}

export function Flag({ iso2, name, width = 20, className }: FlagProps) {
  return (
    <SafeImg
      src={imageUrl.flag(iso2)}
      alt={name}
      width={width}
      height={Math.round((width * 3) / 4)}
      className={cx('ui-flag', className)}
    />
  );
}

export interface PlayerPhotoProps {
  /** id игрока (FotMob); нет id — сразу нейтральный силуэт */
  id?: number;
  name: string;
  size?: number;
  className?: string;
}

/** Нейтральный силуэт — тот же смысл, что и заглушка сервера, когда фото нет. */
function Silhouette() {
  return (
    <svg className="ui-photo__sil" viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="15.5" r="7" />
      <path d="M6 40c1.2-8.4 6.8-13 14-13s12.8 4.6 14 13z" />
    </svg>
  );
}

/**
 * Фото игрока в круглой обрезке. Пока фото грузится и при ошибке — силуэт, а не пустой тёмный круг
 * (фото — вырезка на прозрачном фоне, поэтому силуэт убираем, как только оно пришло).
 */
export function PlayerPhoto({ id, name, size = 40, className }: PlayerPhotoProps) {
  const src = id == null ? null : imageUrl.player(id);
  const [readySrc, setReadySrc] = useState<string | null>(null);
  return (
    <span className={cx('ui-photo', className)} style={{ width: size, height: size }}>
      {src == null ? (
        <>
          <Silhouette />
          <span className="ui-sr">{name}</span>
        </>
      ) : (
        <>
          {readySrc !== src && <Silhouette />}
          <SafeImg src={src} alt={name} width={size} height={size} fallback={<Silhouette />} onReady={() => setReadySrc(src)} />
        </>
      )}
    </span>
  );
}
