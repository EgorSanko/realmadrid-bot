import type { CSSProperties } from 'react';
import { cx, plural } from './format';
import { PlayerPhoto } from './images';

/* ---------- RatingChip ---------- */

export interface RatingChipProps {
  value: number;
  /** sm — на поле (11px), md — в списках (12px) */
  size?: 'sm' | 'md';
  className?: string;
}

/** Оценка игрока: ≥ 8 — золото, 7–8 — средняя, < 7 — приглушённая. */
export function RatingChip({ value, size = 'md', className }: RatingChipProps) {
  const tone = value >= 8 ? 'top' : value >= 7 ? 'mid' : 'low';
  return (
    <span className={cx('ui-rating', `ui-rating--${tone}`, size === 'sm' && 'ui-rating--sm', className)} aria-label={`оценка ${value.toFixed(1)}`}>
      {value.toFixed(1)}
    </span>
  );
}

/* ---------- Pitch ---------- */

export interface PitchPlayer {
  /** id для фото; нет — силуэт */
  id?: number;
  /** фамилия латиницей: «Mbappé» */
  name: string;
  number?: number;
  rating?: number;
  /** 0..1 поперёк поля, как FotMob verticalLayout.x */
  x: number;
  /** 0..1 вдоль поля: 0 — своя линия ворот, 1 — чужая (FotMob verticalLayout.y) */
  y: number;
}

export interface PitchProps {
  players: PitchPlayer[];
  /**
   * FotMob считает x с другой стороны, чем рисуем мы (вратарь снизу,
   * атака вверх): по умолчанию ось x зеркалится.
   */
  mirrorX?: boolean;
  ariaLabel?: string;
  className?: string;
}

const PITCH_W = 358;
const PITCH_H = 470;

/** Поле с расстановкой (a-match-lineup): фото, оценка, номер, фамилия. */
export function Pitch({ players, mirrorX = true, ariaLabel = 'Стартовый состав на поле', className }: PitchProps) {
  return (
    <section className={cx('ui-pitch', className)} aria-label={ariaLabel}>
      <svg className="ui-pitch__lines" viewBox={`0 0 ${PITCH_W} ${PITCH_H}`} aria-hidden="true" preserveAspectRatio="none">
        <g fill="none" stroke="#24324F" strokeWidth="1.5" vectorEffect="non-scaling-stroke">
          <rect x="14" y="14" width="330" height="442" rx="4" vectorEffect="non-scaling-stroke" />
          <line x1="14" y1="235" x2="344" y2="235" vectorEffect="non-scaling-stroke" />
          <ellipse cx="179" cy="235" rx="44" ry="44" vectorEffect="non-scaling-stroke" />
          <rect x="94" y="14" width="170" height="70" vectorEffect="non-scaling-stroke" />
          <rect x="138" y="14" width="82" height="26" vectorEffect="non-scaling-stroke" />
          <rect x="94" y="386" width="170" height="70" vectorEffect="non-scaling-stroke" />
          <rect x="138" y="430" width="82" height="26" vectorEffect="non-scaling-stroke" />
        </g>
      </svg>
      <ul className="ui-pitch__players">
        {players.map((p, i) => {
          const left = (mirrorX ? 1 - p.x : p.x) * 100;
          const top = (1 - p.y) * 100;
          const style: CSSProperties = { left: `${left}%`, top: `${top}%` };
          return (
            <li key={p.id ?? `${p.name}-${i}`} className="ui-pl" style={style}>
              <span className="ui-pl__shirt">
                <PlayerPhoto id={p.id} name={p.name} size={40} />
                {p.rating != null && <RatingChip value={p.rating} size="sm" className="ui-pl__rating" />}
                {p.number != null && (
                  <span className="ui-pl__num" aria-label={`номер ${p.number}`}>
                    {p.number}
                  </span>
                )}
              </span>
              <span className="ui-pl__nm">{p.name}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* ---------- StatRow ---------- */

export interface StatRowProps {
  label: string;
  /** что показать: 54%, 1.41, «469 (86%)» */
  home: number | string;
  away: number | string;
  /** числа для сравнения, если из текста их не вытащить */
  homeValue?: number;
  awayValue?: number;
  /** что лучше: больше (по умолчанию), меньше или не сравнивать (карточки) */
  better?: 'higher' | 'lower' | 'none';
  /** полоса под цифрами (владение) */
  bar?: boolean;
  /** на чьей стороне Реал — его доля полосы золотая */
  accent?: 'home' | 'away';
  className?: string;
}

const num = (v: number | string) => (typeof v === 'number' ? v : parseFloat(v.replace(',', '.')));

/** Строка статистики: лучшая цифра белым, худшая — приглушённо. */
export function StatRow({ label, home, away, homeValue, awayValue, better = 'higher', bar, accent = 'away', className }: StatRowProps) {
  const h = homeValue ?? num(home);
  const a = awayValue ?? num(away);
  let hi: 'home' | 'away' | null = null;
  if (better !== 'none' && Number.isFinite(h) && Number.isFinite(a) && h !== a) {
    hi = (h > a) === (better === 'higher') ? 'home' : 'away';
  }
  const total = (Number.isFinite(h) ? h : 0) + (Number.isFinite(a) ? a : 0);
  return (
    <div className={cx('ui-st', className)}>
      <div className="ui-st__row">
        <span className={cx('ui-st__v', hi === 'home' && 'is-hi')}>{home}</span>
        <span className="ui-st__label">{label}</span>
        <span className={cx('ui-st__v', 'ui-st__v--r', hi === 'away' && 'is-hi')}>{away}</span>
      </div>
      {bar && total > 0 && (
        <div className="ui-st__bar" aria-hidden="true">
          <span style={{ flex: h }} className={accent === 'home' ? 'is-accent' : undefined} />
          <span style={{ flex: a }} className={accent === 'away' ? 'is-accent' : undefined} />
        </div>
      )}
    </div>
  );
}

/* ---------- MomentumChart ---------- */

export interface MomentumPoint {
  minute: number;
  /** > 0 — давят хозяева (столбик вверх), < 0 — гости (вниз); шкала любая, FotMob — ±100 */
  value: number;
}

export interface MomentumChartProps {
  data: MomentumPoint[];
  /** цвет столбиков хозяев / гостей */
  homeColor?: string;
  awayColor?: string;
  /** подписи под осью */
  ticks?: string[];
  ariaLabel?: string;
  className?: string;
}

/** Давление по ходу матча: столбики вверх (хозяева) и вниз (гости). */
export function MomentumChart({
  data,
  homeColor = 'var(--ui-opp)',
  awayColor = 'var(--gold)',
  ticks = ['0′', '45′', '90′'],
  ariaLabel = 'Давление по ходу матча',
  className,
}: MomentumChartProps) {
  const max = Math.max(1, ...data.map((d) => Math.abs(d.value)));
  const HALF = 56; // из 60 px половины — как в макете
  return (
    <div className={className}>
      <div className="ui-mom" role="img" aria-label={ariaLabel}>
        {data.map((d, i) => {
          const hgt = Math.round((Math.abs(d.value) / max) * HALF);
          const up = d.value > 0;
          return (
            <i key={i} title={`${d.minute}′`}>
              <span className="ui-mom__up">{up && <b style={{ height: hgt, background: homeColor }} />}</span>
              <span className="ui-mom__dn">{!up && d.value !== 0 && <b style={{ height: hgt, background: awayColor }} />}</span>
            </i>
          );
        })}
      </div>
      <div className="ui-mom__ticks">
        {ticks.map((t) => (
          <span key={t}>{t}</span>
        ))}
      </div>
    </div>
  );
}

/* ---------- ShotMap ---------- */

export interface Shot {
  /** FotMob: 0..105 вдоль поля, ворота соперника — x = 105 */
  x: number;
  /**
   * FotMob: 0..68 поперёк поля, система Opta: y = 0 — правая бровка
   * с точки зрения атакующих, y = 68 — левая. На карте (ворота сверху) левая бровка — слева.
   */
  y: number;
  xg: number;
  outcome: 'goal' | 'saved' | 'missed' | 'blocked' | 'post';
}

export interface ShotMapProps {
  shots: Shot[];
  ariaLabel?: string;
  /** легенда под картой */
  legend?: boolean;
  className?: string;
}

// геометрия из a-match-stats.html: 326×170, 1 м ≈ 4.765 px (68 м → 324 px)
const SM_W = 326;
const SM_H = 170;
const SM_S = 324 / 68;
// y растёт к левой бровке атакующих, а на карте они смотрят вверх — значит, слева: зеркалим.
// Проверено на 6106274: левый защитник Cucurella бьёт с y≈43, Malen и Soulé (правый фланг Ромы) — с y≈16–24;
// goalCrossedY > 34 ↔ onGoalShot.x < 1 (левая штанга); точки макета a-match-stats.html совпадают с этой формулой.
const smX = (y: number) => 1 + (68 - y) * SM_S;
const smY = (x: number) => 1 + (105 - x) * SM_S;
const shotR = (xg: number) => Math.min(12, 3 + 14.4 * Math.max(0, xg));

/** Сводка для заголовка: «16 ударов · xG 1.43». */
export function shotSummary(shots: Shot[]): string {
  const n = shots.length;
  const xg = shots.reduce((s, x) => s + x.xg, 0);
  return `${n} ${plural(n, ['удар', 'удара', 'ударов'])} · xG ${xg.toFixed(2)}`;
}

/** Карта ударов по половине поля; размер точки — xG, гол залит золотом. */
export function ShotMap({ shots, ariaLabel = 'Карта ударов', legend = true, className }: ShotMapProps) {
  // голы рисуем последними, чтобы были сверху
  const order = [...shots].sort((a, b) => Number(a.outcome === 'goal') - Number(b.outcome === 'goal'));
  return (
    <div className={className}>
      <svg className="ui-shots" viewBox={`0 0 ${SM_W} ${SM_H}`} role="img" aria-label={ariaLabel}>
        <g fill="none" stroke="#24324F" strokeWidth="1.5">
          <rect x="1" y="1" width="324" height="168" rx="4" />
          <rect x="66.5" y="1" width="193" height="79" />
          <rect x="119" y="1" width="88" height="26" />
          <path d="M127.5 80 A44 44 0 0 0 198.5 80" />
          <line x1="145" y1="1" x2="181" y2="1" stroke="#9AA4BC" strokeWidth="3" />
        </g>
        {order.map((s, i) => {
          const cx0 = Math.min(SM_W - 1, Math.max(1, smX(s.y)));
          const cy0 = Math.min(SM_H - 1, Math.max(1, smY(s.x)));
          const r = shotR(s.xg);
          return s.outcome === 'goal' ? (
            <circle key={i} cx={cx0.toFixed(1)} cy={cy0.toFixed(1)} r={r.toFixed(1)} fill="#D6B25E" stroke="#0A0F1E" strokeWidth="1" />
          ) : (
            <circle key={i} cx={cx0.toFixed(1)} cy={cy0.toFixed(1)} r={r.toFixed(1)} fill="none" stroke="#9AA4BC" strokeWidth="1.5" />
          );
        })}
      </svg>
      {legend && (
        <div className="ui-shots__legend">
          <span className="ui-shots__key">
            <span className="ui-ev ui-ev--goal" aria-hidden="true" />
            гол
          </span>
          <span className="ui-shots__key">
            <span className="ui-shots__ring" aria-hidden="true" />
            мимо / отбит
          </span>
          <span>размер — xG</span>
        </div>
      )}
    </div>
  );
}
