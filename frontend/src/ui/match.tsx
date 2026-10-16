import { Fragment, useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { Chip } from './base';
import {
  cx,
  formatDayShort,
  formatKickoff,
  formatMinute,
  formatTime,
  formatWeekdayShort,
  plural,
  toMs,
  type DateInput,
} from './format';
import { TeamCrest } from './images';

export interface TeamRef {
  /** id для /img/team/{id}.png; нет — эмблема не показывается */
  id?: number;
  /** латиницей, как отдаёт источник: «Real Madrid», «Sevilla» */
  name: string;
}

export interface CompetitionRef {
  id?: number;
  /** «Ла Лига», «Лига чемпионов» */
  name: string;
  /** короткое имя для календаря: «ЛЛ», «ЛЧ» */
  short?: string;
  tone?: 'gold' | 'ucl';
}

export type MatchStatus = 'upcoming' | 'live' | 'finished';
export type Outcome = 'W' | 'D' | 'L';

function Crest({ team, size }: { team: TeamRef; size: 24 | 36 | 52 | 56 | 68 }) {
  // без id держим место пустым — без самодельной заглушки
  if (team.id == null) return <span className="ui-crest-gap" style={{ width: size, height: size }} aria-hidden="true" />;
  return <TeamCrest id={team.id} name={team.name} size={size} />;
}

/* ---------- Countdown ---------- */

export interface CountdownProps {
  /** время начала матча */
  to: DateInput;
  /** что показать, когда время вышло */
  endedLabel?: ReactNode;
  onEnd?: () => void;
  className?: string;
}

function useMinuteClock(target: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    let timer = 0;
    const schedule = () => {
      const t = Date.now();
      setNow(t);
      const left = target - t;
      if (left <= 0) return;
      // следующее срабатывание — ровно когда сменится минута на табло
      timer = window.setTimeout(schedule, (left % 60_000) + 30);
    };
    schedule();
    // фоновые вкладки и свёрнутый Telegram тормозят таймеры — сверяемся при возврате
    const onVis = () => {
      if (document.visibilityState === 'visible') {
        window.clearTimeout(timer);
        schedule();
      }
    };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [target]);
  return now;
}

const pad2 = (n: number) => String(n).padStart(2, '0');

/** Обратный отсчёт «дни : часы : минуты» до начала матча. Тикает сам. */
export function Countdown({ to, endedLabel = 'Матч начинается', onEnd, className }: CountdownProps) {
  const target = toMs(to);
  const now = useMinuteClock(target);
  const left = Math.max(0, target - now);
  const ended = left === 0;

  useEffect(() => {
    if (ended) onEnd?.();
  }, [ended, onEnd]);

  if (ended) return <div className={cx('ui-cd', 'ui-cd--ended', className)}>{endedLabel}</div>;

  const totalMin = Math.floor(left / 60_000);
  const d = Math.floor(totalMin / 1440);
  const h = Math.floor((totalMin % 1440) / 60);
  const m = totalMin % 60;
  const units: Array<[number, string]> = [
    [d, plural(d, ['день', 'дня', 'дней'])],
    [h, plural(h, ['час', 'часа', 'часов'])],
    [m, plural(m, ['минута', 'минуты', 'минут'])],
  ];
  return (
    <div className={cx('ui-cd', className)} role="timer" aria-label={`До начала: ${units.map(([n, w]) => `${n} ${w}`).join(' ')}`}>
      {units.map(([n, w], i) => (
        <Fragment key={i}>
          {i > 0 && (
            <span className="ui-cd__sep" aria-hidden="true">
              :
            </span>
          )}
          <span className="ui-cd__unit" aria-hidden="true">
            <span className="ui-cd__num">{pad2(n)}</span>
            <span className="ui-cd__lbl">{w}</span>
          </span>
        </Fragment>
      ))}
    </div>
  );
}

/* ---------- MatchCard ---------- */

export interface MatchCardProps {
  status: MatchStatus;
  competition: CompetitionRef;
  kickoff: DateInput;
  home: TeamRef;
  away: TeamRef;
  /** [хозяева, гости] — для live и finished */
  score?: [number, number];
  /** live: минута «67′» */
  minute?: string;
  /** live: «2-й тайм», «Перерыв» */
  period?: string;
  /** upcoming: «Сантьяго Бернабеу, Мадрид» */
  venue?: string;
  /** finished: подпись сверху, по умолчанию дата («Прошлый матч») */
  caption?: string;
  /** finished: кнопка справа */
  actionLabel?: string;
  href?: string;
  onClick?: () => void;
  /** live: что-то под счётом (голы, ссылка) */
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
}

/**
 * Карточка матча в трёх состояниях:
 * upcoming — как «Ближайший матч» на главной (a-home), с обратным отсчётом;
 * live — как счёт в a-live; finished — как «Прошлый матч» на главной.
 */
export function MatchCard(props: MatchCardProps) {
  const { status, competition, kickoff, home, away, score, className, style, href, onClick } = props;

  if (status === 'finished') {
    const body = (
      <>
        <div className="ui-mc-past__main">
          <div className="ui-mc-past__cap">
            {props.caption ?? formatDayShort(kickoff)} · {competition.name}
          </div>
          <div className="ui-mc-past__line">
            <span>{home.name}</span>
            <span className="ui-mc-past__score">{score ? `${score[0]} : ${score[1]}` : '– : –'}</span>
            <span>{away.name}</span>
          </div>
        </div>
        <span className="ui-mc-past__act">{props.actionLabel ?? 'Обзор'}</span>
      </>
    );
    const cls = cx('ui-mc-past', className);
    return href != null ? (
      <a className={cls} href={href} onClick={onClick} style={style}>
        {body}
      </a>
    ) : (
      <section className={cls} onClick={onClick} style={style} aria-label="Прошлый матч">
        {body}
      </section>
    );
  }

  if (status === 'live') {
    return (
      <section className={cx('ui-mc', 'ui-mc--live', className)} style={style} aria-label="Счёт">
        <div className="ui-mc__top ui-mc__top--sm">
          <Chip label={competition.name} />
          <span>{props.period}</span>
        </div>
        <div className="ui-mc__teams">
          <div className="ui-mc__team">
            <Crest team={home} size={52} />
            <span className="ui-mc__name">{home.name}</span>
          </div>
          <div className="ui-mc__mid">
            <div className="ui-mc__score">{score ? `${score[0]} : ${score[1]}` : '0 : 0'}</div>
            {props.minute && <div className="ui-mc__minute">{props.minute}</div>}
          </div>
          <div className="ui-mc__team">
            <Crest team={away} size={52} />
            <span className="ui-mc__name">{away.name}</span>
          </div>
        </div>
        {props.children}
      </section>
    );
  }

  return (
    <section className={cx('ui-mc', className)} style={style} aria-label="Ближайший матч">
      <div className="ui-mc__top">
        <Chip label={competition.name} size="lg" />
        <span>{formatKickoff(kickoff)}</span>
      </div>
      <div className="ui-mc__teams ui-mc__teams--lg">
        <div className="ui-mc__team ui-mc__team--lg">
          <Crest team={home} size={68} />
          <span className="ui-mc__name ui-mc__name--lg">{home.name}</span>
        </div>
        <span className="ui-mc__vs">VS</span>
        <div className="ui-mc__team ui-mc__team--lg">
          <Crest team={away} size={68} />
          <span className="ui-mc__name ui-mc__name--lg">{away.name}</span>
        </div>
      </div>
      <Countdown to={kickoff} className="ui-mc__cd" />
      {props.venue && <div className="ui-mc__venue">{props.venue}</div>}
    </section>
  );
}

/* ---------- ScoreHeader ---------- */

export interface ScorerLine {
  name: string;
  /** «51′», «90+2′» */
  minutes: string[];
}

export interface ScoreHeaderProps {
  home: TeamRef;
  away: TeamRef;
  status: MatchStatus;
  score?: [number, number];
  kickoff?: DateInput;
  /** live: «67′» — золотом под счётом */
  minute?: string;
  /** своя подпись под счётом; по умолчанию «Матч завершён · 14 окт» / время начала */
  statusText?: string;
  scorers?: { home: ScorerLine[]; away: ScorerLine[] };
  className?: string;
}

const scorerText = (list: ScorerLine[]) => list.map((s) => `${s.name} ${s.minutes.join(' ')}`).join(', ');

/** Шапка страницы матча (a-match-events): эмблемы, счёт, статус, авторы голов. */
export function ScoreHeader({ home, away, status, score, kickoff, minute, statusText, scorers, className }: ScoreHeaderProps) {
  let sub: ReactNode = statusText;
  if (sub == null) {
    if (status === 'finished') sub = `Матч завершён${kickoff != null ? ` · ${formatDayShort(kickoff)}` : ''}`;
    else if (status === 'upcoming' && kickoff != null) sub = `${formatWeekdayShort(kickoff)} · ${formatTime(kickoff)} МСК`;
  }
  return (
    <section className={cx('ui-score-head', className)} aria-label="Счёт">
      <div className="ui-score-head__grid">
        <div className="ui-mc__team">
          <Crest team={home} size={56} />
          <span className="ui-mc__name">{home.name}</span>
        </div>
        <div className="ui-mc__mid">
          {status === 'upcoming' ? (
            <div className="ui-mc__vs">VS</div>
          ) : (
            <div className="ui-score-head__score">{score ? `${score[0]} : ${score[1]}` : '0 : 0'}</div>
          )}
          {status === 'live' && minute ? (
            <div className="ui-mc__minute">{minute}</div>
          ) : (
            sub != null && <div className="ui-score-head__status">{sub}</div>
          )}
        </div>
        <div className="ui-mc__team">
          <Crest team={away} size={56} />
          <span className="ui-mc__name">{away.name}</span>
        </div>
      </div>
      {scorers && (scorers.home.length > 0 || scorers.away.length > 0) && (
        <div className="ui-score-head__scorers">
          <span>{scorerText(scorers.home)}</span>
          <span>{scorerText(scorers.away)}</span>
        </div>
      )}
    </section>
  );
}

/* ---------- FormStrip ---------- */

const OUTCOME_LETTER: Record<Outcome, string> = { W: 'В', D: 'Н', L: 'П' };
const OUTCOME_WORD: Record<Outcome, string> = { W: 'победа', D: 'ничья', L: 'поражение' };

export function OutcomeBadge({ result, size = 26 }: { result: Outcome; size?: number }) {
  return (
    <span
      className={cx('ui-form__item', `ui-form__item--${result}`)}
      style={{ width: size, height: size }}
      title={OUTCOME_WORD[result]}
    >
      {OUTCOME_LETTER[result]}
    </span>
  );
}

export interface FormStripProps {
  /** от старого к новому */
  results: Outcome[];
  size?: number;
  className?: string;
}

/** Форма: квадраты В / Н / П. */
export function FormStrip({ results, size = 26, className }: FormStripProps) {
  return (
    <div className={cx('ui-form', className)} role="img" aria-label={`Форма: ${results.map((r) => OUTCOME_WORD[r]).join(', ')}`}>
      {results.map((r, i) => (
        <OutcomeBadge key={i} result={r} size={size} />
      ))}
    </div>
  );
}

/* ---------- FixtureRow ---------- */

interface FixtureBase {
  kickoff: DateInput;
  home: TeamRef;
  away: TeamRef;
  href?: string;
  onClick?: () => void;
  className?: string;
}

export interface UpcomingFixture extends FixtureBase {
  kind: 'upcoming';
  competition: CompetitionRef;
  /** «Бернабеу», «Эль Класико» */
  note?: string;
  /** ближайший матч — золотая рамка */
  highlighted?: boolean;
}

export interface ResultFixture extends FixtureBase {
  kind: 'result';
  score: [number, number];
  /** итог для нашей команды */
  result?: Outcome;
}

export type FixtureRowProps = UpcomingFixture | ResultFixture;

/** Строка календаря (kind="upcoming") или результатов (kind="result"), как в a-fixtures. */
export function FixtureRow(props: FixtureRowProps) {
  const { kickoff, home, away, href, onClick, className } = props;
  const label = `${home.name} — ${away.name}`;
  const Tag = href != null ? 'a' : 'div';
  if (props.kind === 'result') {
    return (
      <Tag className={cx('ui-fx', className)} href={href} onClick={onClick} aria-label={href != null ? label : undefined}>
        <span className="ui-fx__date-sm">{formatDayShort(kickoff)}</span>
        <div className="ui-fx__line">
          {home.name} <b className="ui-fx__score">{`${props.score[0]} : ${props.score[1]}`}</b> {away.name}
        </div>
        {props.result && <OutcomeBadge result={props.result} size={24} />}
      </Tag>
    );
  }
  const c = props.competition;
  return (
    <Tag
      className={cx('ui-fx', props.highlighted && 'ui-fx--next', className)}
      href={href}
      onClick={onClick}
      aria-label={href != null ? label : undefined}
    >
      <div className="ui-fx__date">
        <div className="ui-fx__day">{formatWeekdayShort(kickoff)}</div>
        <div className="ui-fx__time">{formatTime(kickoff)}</div>
      </div>
      <div className="ui-fx__teams">
        <div className="ui-fx__team">{home.name}</div>
        <div className="ui-fx__team">{away.name}</div>
        {props.note && <div className="ui-fx__note">{props.note}</div>}
      </div>
      <Chip label={c.short ?? c.name} tone={c.tone} size="sm" />
    </Tag>
  );
}

/* ---------- StandingsTable ---------- */

export interface StandingRow {
  pos: number;
  team: TeamRef;
  played: number;
  goalsFor: number;
  goalsAgainst: number;
  points: number;
}

export interface StandingZone {
  /** позиции включительно */
  from: number;
  to: number;
  color: string;
  label: string;
}

export interface StandingsTableProps {
  rows: StandingRow[];
  /** чья строка подсвечивается (Реал) */
  highlightTeamId?: number;
  zones?: StandingZone[];
  /** хвост подписи под таблицей: «вся таблица — по нажатию» */
  footnote?: string;
  className?: string;
}

export function StandingsTable({ rows, highlightTeamId, zones = [], footnote, className }: StandingsTableProps) {
  const zoneOf = (pos: number) => zones.find((z) => pos >= z.from && pos <= z.to);
  return (
    <div className={className}>
      <table className="ui-table">
        <thead>
          <tr>
            <th className="ui-table__pos">#</th>
            <th className="ui-table__team">Команда</th>
            <th>И</th>
            <th>Мячи</th>
            <th className="ui-table__pts">О</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const z = zoneOf(r.pos);
            const me = highlightTeamId != null && r.team.id === highlightTeamId;
            return (
              <tr key={r.pos} className={cx(me && 'is-me')} aria-current={me || undefined}>
                <td className="ui-table__pos" style={{ borderLeftColor: z ? z.color : 'transparent' }}>
                  {r.pos}
                </td>
                <td className="ui-table__team">{r.team.name}</td>
                <td className="ui-table__num">{r.played}</td>
                <td className="ui-table__num">{`${r.goalsFor}-${r.goalsAgainst}`}</td>
                <td className="ui-table__pts">{r.points}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {(zones.length > 0 || footnote) && (
        <div className="ui-table__legend">
          {zones.map((z, i) => (
            <Fragment key={i}>
              <span className="ui-table__zone" style={{ background: z.color }} />
              <span>{z.label}</span>
            </Fragment>
          ))}
          {footnote && <span>{zones.length > 0 ? `· ${footnote}` : footnote}</span>}
        </div>
      )}
    </div>
  );
}

/* ---------- EventIcon ---------- */

export type MatchEventType = 'goal' | 'own-goal' | 'penalty-missed' | 'yellow' | 'second-yellow' | 'red' | 'sub' | 'var';

const EVENT_LABEL: Record<MatchEventType, string> = {
  goal: 'Гол',
  'own-goal': 'Автогол',
  'penalty-missed': 'Незабитый пенальти',
  yellow: 'Жёлтая карточка',
  'second-yellow': 'Вторая жёлтая',
  red: 'Красная карточка',
  sub: 'Замена',
  var: 'VAR',
};

/** Значок события. Чистый CSS/SVG. */
export function EventIcon({ type, className }: { type: MatchEventType; className?: string }) {
  const common = { role: 'img', 'aria-label': EVENT_LABEL[type], className: cx('ui-ev', `ui-ev--${type}`, className) } as const;
  if (type === 'var')
    return (
      <svg {...common} viewBox="0 0 16 14" width="16" height="14">
        <rect x="1" y="1" width="14" height="9" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M5 13h6M8 10v3" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    );
  if (type === 'penalty-missed')
    return (
      <svg {...common} viewBox="0 0 14 14" width="14" height="14">
        <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M3.2 10.8l7.6-7.6" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    );
  if (type === 'sub')
    return (
      <span {...common}>
        <svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true">
          <path d="M4.5 9.5V4.5M3 6l1.5-1.5L6 6M9.5 4.5v5M8 8l1.5 1.5L11 8" fill="none" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      </span>
    );
  return <span {...common} />;
}

/* ---------- Timeline ---------- */

export interface TimelineEvent {
  kind?: 'event';
  minute: number;
  addedTime?: number;
  side: 'home' | 'away';
  type: MatchEventType;
  /** «Mbappé»; для замены — кто вышел */
  player: string;
  /** «пас Diomande», «ушёл Vinícius» */
  detail?: string;
  /** счёт после гола */
  score?: [number, number];
}

export interface TimelineDivider {
  kind: 'divider';
  /** «Перерыв · 1:1» */
  label: string;
}

export type TimelineItem = TimelineEvent | TimelineDivider;

/** Хронология матча с осью по центру: хозяева слева, гости справа (a-match-events). */
export function Timeline({ items, className }: { items: TimelineItem[]; className?: string }) {
  return (
    <ol className={cx('ui-tl', className)}>
      {items.map((it, i) => {
        if (it.kind === 'divider')
          return (
            <li key={i} className="ui-tl__half">
              <span>{it.label}</span>
            </li>
          );
        const home = it.side === 'home';
        const score = it.score && (
          <span className={cx('ui-tl__score', !home && 'ui-tl__score--l')}>{`${it.score[0]}:${it.score[1]}`}</span>
        );
        const icon = <EventIcon type={it.type} />;
        const body = (
          <div className={home ? 'ui-tl__l' : 'ui-tl__r'}>
            <div className="ui-tl__name">
              {home ? (
                <>
                  {icon} {it.player} {score}
                </>
              ) : (
                <>
                  {score}
                  {it.player} {icon}
                </>
              )}
            </div>
            {it.detail && <div className="ui-tl__sub">{it.detail}</div>}
          </div>
        );
        return (
          <li key={i} className="ui-tl__row">
            {home ? body : <div />}
            <span className="ui-tl__min">{formatMinute(it.minute, it.addedTime)}</span>
            {home ? <div /> : body}
          </li>
        );
      })}
    </ol>
  );
}
