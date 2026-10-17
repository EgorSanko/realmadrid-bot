/**
 * Дополнения к набору для главной и «Матчей», которых нет в match.tsx:
 * — HeroMatchCard: большая карточка матча с логотипом турнира, тремя состояниями и ссылкой;
 * — CalendarRow: строка «Ближайших» с логотипом турнира в плашке (Кубок, Суперкубок) и состоянием «идёт».
 * Вёрстка и классы — те же, что у MatchCard / FixtureRow; свои стили — в matchExtra.css.
 */
import type { MouseEventHandler, ReactNode } from 'react';
import { Badge, Chip } from './base';
import { cx, formatKickoff, formatTime, formatWeekdayShort, formatDayShort, type DateInput } from './format';
import { LeagueLogo, TeamCrest } from './images';
import { Countdown, OutcomeBadge, type CompetitionRef, type MatchStatus, type Outcome, type TeamRef } from './match';
import './matchExtra.css';

type CrestSize = 52 | 68;

function Crest({ team, size }: { team: TeamRef; size: CrestSize }) {
  if (team.id == null) return <span className="ui-crest-gap" style={{ width: size, height: size }} aria-hidden="true" />;
  return <TeamCrest id={team.id} name={team.name} size={size} />;
}

export interface HeroMatchCardProps {
  status: MatchStatus;
  competition: CompetitionRef;
  kickoff: DateInput;
  home: TeamRef;
  away: TeamRef;
  score?: [number, number];
  /** live: «67′» */
  minute?: string;
  /** live: «2-й тайм» */
  period?: string;
  /** upcoming: «Estadio Bernabéu, Madrid» */
  venue?: string;
  href?: string;
  onClick?: MouseEventHandler<HTMLAnchorElement>;
  /** upcoming: отсчёт дошёл до нуля */
  onKickoff?: () => void;
  /** под карточкой внутри (подпись «обновлено …») */
  footer?: ReactNode;
  className?: string;
}

const MORE_LABEL: Record<MatchStatus, string> = {
  upcoming: '',
  live: 'Весь матч: события, составы, статистика',
  finished: 'Обзор матча',
};

/**
 * Карточка «Ближайший матч» (a-home.html) в трёх состояниях:
 * upcoming — отсчёт; live — счёт, минута и LIVE (a-live.html); finished — итог сразу после свистка.
 */
export function HeroMatchCard(props: HeroMatchCardProps) {
  const { status, competition, kickoff, home, away, score, href, onClick, className } = props;
  const chip = <Chip label={competition.name} size={status === 'upcoming' ? 'lg' : 'md'} leagueId={competition.id} />;
  const sc = score ? `${score[0]} : ${score[1]}` : status === 'live' ? '0 : 0' : '– : –';

  let body: ReactNode;
  if (status === 'upcoming') {
    body = (
      <>
        <div className="ui-mc__top">
          {chip}
          <span className="hero-mc__when">{formatKickoff(kickoff)}</span>
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
        <Countdown to={kickoff} className="ui-mc__cd" onEnd={props.onKickoff} />
        {props.venue && <div className="ui-mc__venue">{props.venue}</div>}
      </>
    );
  } else {
    const live = status === 'live';
    body = (
      <>
        <div className="ui-mc__top ui-mc__top--sm">
          <span className="hero-mc__tags">
            {live && <Badge tone="live" />}
            {chip}
          </span>
          <span>{live ? props.period : `Матч завершён · ${formatDayShort(kickoff)}`}</span>
        </div>
        <div className="ui-mc__teams">
          <div className="ui-mc__team">
            <Crest team={home} size={52} />
            <span className="ui-mc__name">{home.name}</span>
          </div>
          <div className="ui-mc__mid">
            <div className="ui-mc__score">{sc}</div>
            {live && props.minute && <div className="ui-mc__minute">{props.minute}</div>}
            {!live && <div className="hero-mc__final">Финальный свисток</div>}
          </div>
          <div className="ui-mc__team">
            <Crest team={away} size={52} />
            <span className="ui-mc__name">{away.name}</span>
          </div>
        </div>
        {href != null && <span className="hero-mc__more">{MORE_LABEL[status]}</span>}
      </>
    );
  }

  const label =
    status === 'live' ? `Идёт матч: ${home.name} — ${away.name}` : status === 'finished' ? 'Матч завершён' : 'Ближайший матч';
  const cls = cx('ui-mc', status === 'live' && 'ui-mc--live', 'hero-mc', `hero-mc--${status}`, className);
  return (
    <section className="hero-wrap" aria-label={label}>
      {href != null ? (
        <a className={cls} href={href} onClick={onClick}>
          {body}
        </a>
      ) : (
        <div className={cls}>{body}</div>
      )}
      {props.footer}
    </section>
  );
}

/* ---------- CalendarRow ---------- */

export interface CalendarRowProps {
  kickoff: DateInput;
  home: TeamRef;
  away: TeamRef;
  competition: CompetitionRef & { withLogo?: boolean };
  note?: string;
  /** идёт: минута «67′» — вместо времени LIVE */
  live?: string;
  highlighted?: boolean;
  href?: string;
  onClick?: MouseEventHandler<HTMLAnchorElement>;
  className?: string;
}

/** Строка «Ближайших» (a-fixtures.html). Как FixtureRow kind="upcoming", плюс логотип турнира и LIVE. */
export function CalendarRow({ kickoff, home, away, competition: c, note, live, highlighted, href, onClick, className }: CalendarRowProps) {
  const inner = (
    <>
      <div className="ui-fx__date">
        {live ? (
          <>
            <Badge tone="live" />
            <div className="ui-fx__time cal-row__minute">{live}</div>
          </>
        ) : (
          <>
            <div className="ui-fx__day">{formatWeekdayShort(kickoff)}</div>
            <div className="ui-fx__time">{formatTime(kickoff)}</div>
          </>
        )}
      </div>
      <div className="ui-fx__teams">
        {[home, away].map((t, i) => (
          <div key={i} className="ui-fx__team cal-row__team">
            {t.id != null ? (
              <TeamCrest id={t.id} name="" size={20} />
            ) : (
              <span className="ui-crest-gap" style={{ width: 20, height: 20 }} aria-hidden="true" />
            )}
            <span className="cal-row__nm">{t.name}</span>
          </div>
        ))}
        {note && <div className="ui-fx__note">{note}</div>}
      </div>
      <Chip label={c.short ?? c.name} tone={c.tone} size="sm" leagueId={c.withLogo ? c.id : undefined} className="cal-row__chip" />
    </>
  );
  const cls = cx('ui-fx', 'cal-row', highlighted && 'ui-fx--next', className);
  const label = `${home.name} — ${away.name}, ${c.name}`;
  return href != null ? (
    <a className={cls} href={href} onClick={onClick} aria-label={label}>
      {inner}
    </a>
  ) : (
    <div className={cls} aria-label={label}>
      {inner}
    </div>
  );
}

/* ---------- MatchRow ---------- */

export interface MatchRowProps {
  kind: 'upcoming' | 'result';
  kickoff: DateInput;
  home: TeamRef;
  away: TeamRef;
  competition: CompetitionRef;
  /** result: счёт [хозяева, гости] */
  score?: [number, number];
  /** result: исход для Реала */
  result?: Outcome;
  /** upcoming: «дома» / «в гостях» / стадион */
  note?: string;
  /** upcoming, идёт: «67′» */
  live?: string;
  highlighted?: boolean;
  href?: string;
  onClick?: MouseEventHandler<HTMLAnchorElement>;
  className?: string;
}

/**
 * Строка матча для «Матчей»: эмблемы обеих команд, логотип турнира вместо «ЛЛ»/«ЛЧ».
 * Будущий матч — дата и время слева; сыгранный — дата, голы напротив каждой команды и В/Н/П.
 */
export function MatchRow(p: MatchRowProps) {
  const { kind, kickoff, home, away, competition: c, score, result, href, onClick, className } = p;
  const done = kind === 'result' && score != null;
  const win = done ? (score![0] === score![1] ? null : score![0] > score![1] ? 0 : 1) : null;
  const team = (t: TeamRef, i: 0 | 1) => (
    <div className={cx('mrow__team', done && win !== null && win !== i && 'mrow__team--lost')}>
      {t.id != null ? <TeamCrest id={t.id} name={t.name} size={24} /> : <span className="mrow__crest-gap" aria-hidden="true" />}
      <span className="mrow__name">{t.name}</span>
      {done && <b className="mrow__goals">{score![i]}</b>}
    </div>
  );
  const inner = (
    <>
      <div className="mrow__when">
        {p.live ? (
          <>
            <Badge tone="live" />
            <span className="mrow__minute">{p.live}</span>
          </>
        ) : (
          <>
            <span className="mrow__day">{done ? formatDayShort(kickoff) : formatWeekdayShort(kickoff)}</span>
            {!done && <span className="mrow__time">{formatTime(kickoff)}</span>}
          </>
        )}
      </div>
      <div className="mrow__teams">
        {team(home, 0)}
        {team(away, 1)}
        {p.note && <div className="mrow__note">{p.note}</div>}
      </div>
      <div className="mrow__side">
        {c.id != null ? (
          <LeagueLogo id={c.id} name={c.name} size={24} />
        ) : (
          <span className="mrow__comp">{c.short ?? c.name}</span>
        )}
        {done && result && <OutcomeBadge result={result} size={20} />}
      </div>
    </>
  );
  const label = done ? `${home.name} ${score![0]}:${score![1]} ${away.name}, ${c.name}` : `${home.name} — ${away.name}, ${c.name}`;
  const cls = cx('mrow', p.highlighted && 'mrow--next', className);
  return href != null ? (
    <a className={cls} href={href} onClick={onClick} aria-label={label}>
      {inner}
    </a>
  ) : (
    <div className={cls} aria-label={label}>
      {inner}
    </div>
  );
}
