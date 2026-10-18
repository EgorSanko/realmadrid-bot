import type { CSSProperties, MouseEventHandler, ReactNode } from 'react';
import { cx } from './format';
import { LeagueLogo } from './images';

/* ---------- Card ---------- */

export interface CardProps {
  children: ReactNode;
  /** как .card в макете: отступы 14px 16px 0; false — без внешних отступов (для сеток) */
  inset?: boolean;
  /** без внутренних отступов — для карточек с картинкой во всю ширину */
  bleed?: boolean;
  as?: 'section' | 'div' | 'article';
  ariaLabel?: string;
  className?: string;
  style?: CSSProperties;
}

export function Card({ children, inset = true, bleed, as: Tag = 'section', ariaLabel, className, style }: CardProps) {
  return (
    <Tag
      aria-label={ariaLabel}
      className={cx('ui-card', !inset && 'ui-card--flush', bleed && 'ui-card--bleed', className)}
      style={style}
    >
      {children}
    </Tag>
  );
}

/* ---------- SectionHeader ---------- */

export interface SectionHeaderProps {
  title: string;
  /** серый текст справа («после 8 туров») */
  aside?: ReactNode;
  /** ссылка справа; по умолчанию текст «Все» */
  actionLabel?: string;
  href?: string;
  onAction?: () => void;
  /** заголовок на странице, вне карточки: отступы 22px 16px 0 */
  page?: boolean;
  className?: string;
  style?: CSSProperties;
}

export function SectionHeader({
  title,
  aside,
  actionLabel = 'Все',
  href,
  onAction,
  page,
  className,
  style,
}: SectionHeaderProps) {
  const hasAction = href != null || onAction != null;
  return (
    <div className={cx('ui-section-head', page && 'ui-section-head--page', className)} style={style}>
      <h2 className="ui-section-head__title">{title}</h2>
      {aside != null && <span className="ui-section-head__aside">{aside}</span>}
      {hasAction &&
        (href != null ? (
          <a className="ui-section-head__action" href={href} onClick={onAction}>
            {actionLabel}
          </a>
        ) : (
          <button type="button" className="ui-section-head__action" onClick={onAction}>
            {actionLabel}
          </button>
        ))}
    </div>
  );
}

/* ---------- Tabs ---------- */

export interface TabItem<T extends string> {
  id: T;
  label: string;
  /** картинка перед подписью (эмблема команды в pill) */
  icon?: ReactNode;
}

export interface TabsProps<T extends string> {
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  ariaLabel: string;
  /**
   * segmented — «Обзор / Составы / Статистика» (по умолчанию);
   * outline — «Матч / 1-й тайм / 2-й тайм»;
   * pill — выбор команды, золотая рамка у выбранной
   */
  variant?: 'segmented' | 'outline' | 'pill';
  /** для segmented: внешние отступы 14px 16px 0, как в макете */
  inset?: boolean;
  className?: string;
  style?: CSSProperties;
}

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  variant = 'segmented',
  inset = true,
  className,
  style,
}: TabsProps<T>) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cx('ui-tabs', `ui-tabs--${variant}`, variant === 'segmented' && !inset && 'ui-tabs--flush', className)}
      style={style}
    >
      {items.map((it) => {
        const on = it.id === value;
        return (
          <button
            key={it.id}
            type="button"
            role="tab"
            aria-selected={on}
            className={cx('ui-tabs__tab', 'ui-press', on && 'is-on', it.icon != null && 'ui-tabs__tab--icon')}
            onClick={() => onChange(it.id)}
          >
            {it.icon != null ? (
              <>
                {it.icon}
                <span className="ui-tabs__lbl">{it.label}</span>
              </>
            ) : (
              it.label
            )}
          </button>
        );
      })}
    </div>
  );
}

/* ---------- Chip ---------- */

export interface ChipProps {
  /** «Ла Лига», «ЛЧ» */
  label: string;
  /** gold — Ла Лига и по умолчанию; ucl — синий, Лига чемпионов (как в календаре) */
  tone?: 'gold' | 'ucl';
  /** sm 11px (календарь), md 12px, lg 13px (главная) */
  size?: 'sm' | 'md' | 'lg';
  /** id турнира — показать логотип перед названием */
  leagueId?: number;
  className?: string;
}

export function Chip({ label, tone = 'gold', size = 'md', leagueId, className }: ChipProps) {
  return (
    <span className={cx('ui-chip', `ui-chip--${size}`, tone === 'ucl' && 'ui-chip--ucl', className)}>
      {leagueId != null && <LeagueLogo id={leagueId} name="" size={14} />}
      {label}
    </span>
  );
}

/* ---------- Badge ---------- */

export interface BadgeProps {
  /** live — красная плашка с точкой («LIVE», «В ЭФИРЕ»); injury — «травма» */
  tone: 'live' | 'injury';
  children?: ReactNode;
  className?: string;
}

export function Badge({ tone, children, className }: BadgeProps) {
  if (tone === 'live')
    return (
      <span className={cx('ui-badge', 'ui-badge--live', className)}>
        <span className="ui-badge__dot" aria-hidden="true" />
        {children ?? 'LIVE'}
      </span>
    );
  return <span className={cx('ui-badge', 'ui-badge--injury', className)}>{children ?? 'травма'}</span>;
}

/* ---------- Button ---------- */

export interface ButtonProps {
  children: ReactNode;
  /** primary — золотая «Сохранить прогноз»; secondary — тёмная плашка; outline — рамка */
  variant?: 'primary' | 'secondary' | 'outline';
  /** во всю ширину (по умолчанию, как в макетах) */
  block?: boolean;
  href?: string;
  onClick?: MouseEventHandler<HTMLElement>;
  disabled?: boolean;
  type?: 'button' | 'submit';
  className?: string;
  style?: CSSProperties;
}

export function Button({
  children,
  variant = 'primary',
  block = true,
  href,
  onClick,
  disabled,
  type = 'button',
  className,
  style,
}: ButtonProps) {
  const cls = cx('ui-btn', 'ui-press', `ui-btn--${variant}`, block && 'ui-btn--block', className);
  if (href != null && !disabled)
    return (
      <a className={cls} href={href} onClick={onClick} style={style}>
        {children}
      </a>
    );
  return (
    <button type={type} className={cls} onClick={onClick} disabled={disabled} style={style}>
      {children}
    </button>
  );
}

/* ---------- Skeleton ---------- */

export interface SkeletonProps {
  /**
   * готовая форма карточки: match — ближайший матч; list — строки списка;
   * news — новости с превью; table — таблица; stats — строки статистики.
   * Не задано — один прямоугольник width×height.
   */
  shape?: 'match' | 'list' | 'news' | 'table' | 'stats';
  rows?: number;
  width?: number | string;
  height?: number | string;
  radius?: number | string;
  className?: string;
  style?: CSSProperties;
}

function Bone({ w, h, r, style }: { w?: number | string; h?: number | string; r?: number | string; style?: CSSProperties }) {
  return <span className="ui-skel" style={{ width: w, height: h, borderRadius: r, ...style }} />;
}

export function Skeleton({ shape, rows = 3, width, height, radius, className, style }: SkeletonProps) {
  if (!shape) return <Bone w={width ?? '100%'} h={height ?? 14} r={radius} style={style} />;
  const list = Array.from({ length: rows }, (_, i) => i);
  let body: ReactNode;
  switch (shape) {
    case 'match':
      body = (
        <div className="ui-mc ui-skel-card" style={{ margin: 0 }}>
          <div className="ui-skel-row">
            <Bone w={70} h={25} r={8} />
            <Bone w={150} h={14} />
          </div>
          <div className="ui-mc__teams">
            <div className="ui-mc__team">
              <Bone w={68} h={68} r="50%" />
              <Bone w={96} h={14} />
            </div>
            <Bone w={22} h={14} />
            <div className="ui-mc__team">
              <Bone w={68} h={68} r="50%" />
              <Bone w={80} h={14} />
            </div>
          </div>
          <div className="ui-skel-row" style={{ justifyContent: 'center', marginTop: 24, gap: 24 }}>
            <Bone w={64} h={50} r={10} />
            <Bone w={64} h={50} r={10} />
            <Bone w={64} h={50} r={10} />
          </div>
          <Bone w={180} h={13} style={{ margin: '18px auto 0' }} />
        </div>
      );
      break;
    case 'list':
      body = list.map((i) => (
        <div key={i} className="ui-skel-li">
          <Bone w={36} h={36} r={12} />
          <div style={{ flex: 1 }}>
            <Bone w={`${60 - (i % 3) * 10}%`} h={14} />
            <Bone w="35%" h={11} style={{ marginTop: 6 }} />
          </div>
        </div>
      ));
      break;
    case 'news':
      body = list.map((i) => (
        <div key={i} className="ui-skel-news">
          <Bone w={84} h={64} r={12} />
          <div style={{ flex: 1 }}>
            <Bone w="95%" h={13} />
            <Bone w={`${70 - (i % 2) * 15}%`} h={13} style={{ marginTop: 6 }} />
            <Bone w={90} h={11} style={{ marginTop: 8 }} />
          </div>
        </div>
      ));
      break;
    case 'table':
      body = list.map((i) => (
        <div key={i} className="ui-skel-tr">
          <Bone w={14} h={13} />
          <Bone w={`${45 - (i % 3) * 6}%`} h={13} />
          <span style={{ flex: 1 }} />
          <Bone w={28} h={13} />
          <Bone w={22} h={13} />
        </div>
      ));
      break;
    case 'stats':
      body = list.map((i) => (
        <div key={i} className="ui-skel-st">
          <Bone w={34} h={14} />
          <Bone w={`${38 - (i % 3) * 6}%`} h={13} />
          <Bone w={34} h={14} />
        </div>
      ));
      break;
  }
  return (
    <div className={cx('ui-skeleton', className)} style={style} role="status" aria-busy="true" aria-label="Загрузка">
      {body}
    </div>
  );
}

/* ---------- EmptyState / ErrorState ---------- */

export interface EmptyStateProps {
  title: string;
  text?: string;
  /** svg-иконка 24×24 (stroke), по умолчанию — пустой календарь */
  icon?: ReactNode;
  action?: { label: string; onClick?: () => void; href?: string };
  /** внутри карточки: без своей рамки и фона */
  plain?: boolean;
  className?: string;
}

const ICON_EMPTY = (
  <>
    <rect x="4" y="5" width="16" height="15" rx="2" />
    <path d="M4 10h16M9 3v4M15 3v4" />
  </>
);
const ICON_ERROR = (
  <>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5v5.5M12 16.2v.3" />
  </>
);

function StateBox({
  icon,
  title,
  text,
  plain,
  className,
  live,
  children,
}: {
  icon: ReactNode;
  title: string;
  text?: string;
  plain?: boolean;
  className?: string;
  live: 'polite' | 'assertive';
  children?: ReactNode;
}) {
  return (
    <div className={cx('ui-state', plain && 'ui-state--plain', className)} role={live === 'assertive' ? 'alert' : 'status'}>
      <span className="ui-state__icon" aria-hidden="true">
        <svg viewBox="0 0 24 24">{icon}</svg>
      </span>
      <p className="ui-state__title">{title}</p>
      {text && <p className="ui-state__text">{text}</p>}
      {children}
    </div>
  );
}

export function EmptyState({ title, text, icon, action, plain, className }: EmptyStateProps) {
  return (
    <StateBox icon={icon ?? ICON_EMPTY} title={title} text={text} plain={plain} className={className} live="polite">
      {action && (
        <Button variant="secondary" block={false} href={action.href} onClick={action.onClick} className="ui-state__btn">
          {action.label}
        </Button>
      )}
    </StateBox>
  );
}

export interface ErrorStateProps {
  title?: string;
  text?: string;
  onRetry?: () => void;
  retryLabel?: string;
  plain?: boolean;
  className?: string;
}

export function ErrorState({
  title = 'Не удалось загрузить',
  text = 'Проверь соединение и попробуй ещё раз',
  onRetry,
  retryLabel = 'Повторить',
  plain,
  className,
}: ErrorStateProps) {
  return (
    <StateBox icon={ICON_ERROR} title={title} text={text} plain={plain} className={className} live="assertive">
      {onRetry && (
        <Button variant="secondary" block={false} onClick={onRetry} className="ui-state__btn">
          {retryLabel}
        </Button>
      )}
    </StateBox>
  );
}
