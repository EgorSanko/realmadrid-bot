/**
 * Дополнения к набору для главной и «Матчей», которых нет в match.tsx:
 * — HeroMatchCard: большая карточка матча с логотипом турнира, тремя состояниями и ссылкой;
 * — CalendarRow: строка «Ближайших» с логотипом турнира в плашке (Кубок, Суперкубок) и состоянием «идёт».
 * Вёрстка и классы — те же, что у MatchCard / FixtureRow; свои стили — в matchExtra.css.
 */
import { useRef, type MouseEventHandler, type ReactNode } from 'react';
import { t, tc } from '../lib/i18n';
import { Badge, Chip } from './base';
import { cx, formatKickoff, formatTime, formatWeekdayShort, formatDayShort, type DateInput } from './format';
import { FlipScore } from './flip';
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
  live: t('Весь матч: события, составы, статистика'),
  finished: tc('match', 'Обзор матча'),
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
        <Countdown to={kickoff} className="ui-mc__cd" onEnd={props.onKickoff} liveOnEnd />
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
          <span>{live ? props.period : `${t('Матч завершён')} · ${formatDayShort(kickoff)}`}</span>
        </div>
        <div className="ui-mc__teams">
          <div className="ui-mc__team">
            <Crest team={home} size={52} />
            <span className="ui-mc__name">{home.name}</span>
          </div>
          <div className="ui-mc__mid">
            <div className="ui-mc__score">{live && score ? <FlipScore score={score} /> : sc}</div>
            {live && props.minute && <div className="ui-mc__minute">{props.minute}</div>}
            {!live && <div className="hero-mc__final">{t('Финальный свисток')}</div>}
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

  // матч начался на глазах (отсчёт → лайв) — содержимое карточки входит с переходом; при открытии — без него
  const prev = useRef(status);
  const started = useRef(false);
  if (prev.current !== status) {
    started.current = prev.current === 'upcoming' && status === 'live';
    prev.current = status;
  }

  const label =
    status === 'live' ? t('Идёт матч: {home} — {away}', { home: home.name, away: away.name }) : status === 'finished' ? t('Матч завершён') : t('Ближайший матч');
  const cls = cx('ui-mc', status === 'live' && 'ui-mc--live', 'hero-mc', `hero-mc--${status}`, started.current && 'hero-mc--started', className);
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

/** Строка «Ближайших» — теперь та же MatchRow: эмблемы команд и логотип турнира вместо «ЛЛ»/«ЛЧ»
 *  (просьба владельца — нигде не показывать турниры текстовыми сокращениями). */
export function CalendarRow({ competition, ...rest }: CalendarRowProps) {
  return <MatchRow kind="upcoming" competition={competition} {...rest} />;
}

/* ---------- MatchRow ---------- */

export interface MatchRowProps {
  kind: 'upcoming' | 'result';
  kickoff: DateInput;
  home: TeamRef;
  away: TeamRef;
  competition: CompetitionRef;
  /** result: счёт [хозяева, гости]; upcoming, идёт — текущий счёт */
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
  // идущий матч — голы напротив команд, как у сыгранного, но без «проигравшей» серости
  const goals = done || (!!p.live && score != null);
  const win = done ? (score![0] === score![1] ? null : score![0] > score![1] ? 0 : 1) : null;
  const team = (t: TeamRef, i: 0 | 1) => (
    <div className={cx('mrow__team', done && win !== null && win !== i && 'mrow__team--lost')}>
      {t.id != null ? <TeamCrest id={t.id} name={t.name} size={24} /> : <span className="mrow__crest-gap" aria-hidden="true" />}
      <span className="mrow__name">{t.name}</span>
      {goals && <b className="mrow__goals">{score![i]}</b>}
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
  const label = goals ? `${home.name} ${score![0]}:${score![1]} ${away.name}, ${c.name}` : `${home.name} — ${away.name}, ${c.name}`;
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
