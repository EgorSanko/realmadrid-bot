import { useState, type ReactNode } from 'react';
import { Chip } from './base';
import { cx } from './format';

/** Превью новости/видео: пока грузится — тёмная плашка; не загрузилось — плашка остаётся без картинки. */
function Thumb({ src, className, onFail }: { src: string; className: string; onFail?: () => void }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <img
      className={className}
      src={src}
      alt=""
      loading="lazy"
      decoding="async"
      draggable={false}
      onError={() => {
        setFailed(true);
        onFail?.();
      }}
      onLoad={(e) => {
        if (e.currentTarget.naturalWidth <= 1) {
          setFailed(true);
          onFail?.();
        }
      }}
    />
  );
}

/* ---------- NewsItem ---------- */

export interface NewsItemProps {
  title: string;
  /** «Спорт-Экспресс» */
  source: string;
  /** «2 ч назад» — дописывается к источнику */
  time?: string;
  href?: string;
  imageUrl?: string;
  /**
   * row — строка на главной (превью 84×64);
   * list — строка в ленте «Медиа» с разделителем (88×66);
   * hero — крупная новость с картинкой во всю ширину
   */
  variant?: 'row' | 'list' | 'hero';
  className?: string;
}

/** Новость. Нет картинки или она не загрузилась — блок превью убирается. */
export function NewsItem({ title, source, time, href, imageUrl, variant = 'row', className }: NewsItemProps) {
  const [noImg, setNoImg] = useState(!imageUrl);
  const Tag = href != null ? 'a' : 'article';
  return (
    <Tag className={cx('ui-news', `ui-news--${variant}`, className)} href={href}>
      {!noImg && imageUrl && (
        <span className="ui-news__thumb">
          <Thumb src={imageUrl} className="ui-news__img" onFail={() => setNoImg(true)} />
        </span>
      )}
      <div className="ui-news__body">
        <div className="ui-news__title">{title}</div>
        <div className="ui-news__src">
          {source}
          {time && ` · ${time}`}
        </div>
      </div>
    </Tag>
  );
}

/* ---------- VideoCard ---------- */

export interface VideoCardProps {
  title: string;
  /** «Лига чемпионов · 14 октября», «Real Madrid · YouTube» */
  subtitle?: string;
  href?: string;
  thumbnailUrl?: string;
  /** hero — большая карточка; tile — плитка 200 px для горизонтальной ленты */
  variant?: 'hero' | 'tile';
  /** hero: плашка слева сверху («Обзор матча») */
  tag?: string;
  /** hero: подпись справа снизу («YouTube») */
  provider?: string;
  /** hero: высота превью; в макетах 196 (Медиа) и 180 (матч) */
  height?: number;
  className?: string;
}

const PLAY = (size: number) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M8 5v14l11-7z" />
  </svg>
);

export function VideoCard({
  title,
  subtitle,
  href,
  thumbnailUrl,
  variant = 'hero',
  tag,
  provider,
  height = 196,
  className,
}: VideoCardProps) {
  const Tag = href != null ? 'a' : 'article';
  if (variant === 'tile') {
    return (
      <Tag className={cx('ui-vtile', className)} href={href}>
        <span className="ui-vtile__screen">
          {thumbnailUrl && <Thumb src={thumbnailUrl} className="ui-video__img" />}
          <span className="ui-vtile__play">{PLAY(16)}</span>
        </span>
        <div className="ui-vtile__title">{title}</div>
        {subtitle && <div className="ui-vtile__sub">{subtitle}</div>}
      </Tag>
    );
  }
  return (
    <Tag className={cx('ui-card', 'ui-card--bleed', 'ui-video', className)} href={href}>
      <span className="ui-video__screen" style={{ height }}>
        {thumbnailUrl && <Thumb src={thumbnailUrl} className="ui-video__img" />}
        <span className="ui-video__play">{PLAY(22)}</span>
        {tag && <Chip label={tag} className="ui-video__tag" />}
        {provider && <span className="ui-video__provider">{provider}</span>}
      </span>
      <div className="ui-video__body">
        <div className={cx('ui-video__title', height < 190 && 'ui-video__title--sm')}>{title}</div>
        {subtitle && <div className="ui-video__sub">{subtitle}</div>}
      </div>
    </Tag>
  );
}

/* ---------- ScoreStepper ---------- */

export interface ScoreStepperProps {
  value: number;
  onChange: (v: number) => void;
  /** для подписей кнопок: «Меньше голов — Real Madrid» */
  teamName: string;
  min?: number;
  max?: number;
  disabled?: boolean;
  className?: string;
}

/** «− 2 +» для прогноза счёта. */
export function ScoreStepper({ value, onChange, teamName, min = 0, max = 15, disabled, className }: ScoreStepperProps) {
  return (
    <div className={cx('ui-stepper', className)} role="group" aria-label={`Голы — ${teamName}`}>
      <button
        type="button"
        className="ui-stepper__btn ui-stepper__btn--minus"
        aria-label={`Меньше голов — ${teamName}`}
        disabled={disabled || value <= min}
        onClick={() => onChange(Math.max(min, value - 1))}
      >
        −
      </button>
      <span className="ui-stepper__val" aria-live="polite">
        {value}
      </span>
      <button
        type="button"
        className="ui-stepper__btn"
        aria-label={`Больше голов — ${teamName}`}
        disabled={disabled || value >= max}
        onClick={() => onChange(Math.min(max, value + 1))}
      >
        +
      </button>
    </div>
  );
}

/** Два степпера через двоеточие — как в карточке прогноза. */
export function ScorePicker({ children }: { children: [ReactNode, ReactNode] }) {
  return (
    <div className="ui-score-pick">
      {children[0]}
      <span className="ui-score-pick__sep" aria-hidden="true">
        :
      </span>
      {children[1]}
    </div>
  );
}

/* ---------- LeaderboardRow ---------- */

export interface LeaderboardRowProps {
  rank: number;
  name: string;
  points: number;
  /** аватар из Telegram; нет или не загрузился — первая буква имени */
  avatarUrl?: string;
  /** строка текущего пользователя — подсвечена */
  isMe?: boolean;
  className?: string;
}

export function LeaderboardRow({ rank, name, points, avatarUrl, isMe, className }: LeaderboardRowProps) {
  const [imgOk, setImgOk] = useState(true);
  const letter = (isMe ? 'Я' : name.trim()[0] ?? '?').toUpperCase();
  return (
    <div className={cx('ui-lb', isMe && 'is-me', className)}>
      <span className={cx('ui-lb__rank', rank <= 3 && 'is-top')}>{rank}</span>
      <span className="ui-lb__av" aria-hidden="true">
        {avatarUrl && imgOk ? (
          <img src={avatarUrl} alt="" width={36} height={36} loading="lazy" decoding="async" onError={() => setImgOk(false)} />
        ) : (
          letter
        )}
      </span>
      <span className="ui-lb__name">{name}</span>
      <b className="ui-lb__pts">{points}</b>
    </div>
  );
}
