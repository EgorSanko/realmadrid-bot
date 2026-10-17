import { useEffect, useLayoutEffect, useMemo, useRef, type MouseEvent } from 'react';
import type { ApiMatch } from '../../api/match';
import { usePlayerLinks } from '../../lib/playerNav';
import { openExternal } from '../../lib/tmaNav';
import {
  Card,
  EmptyState,
  FixtureRow,
  FormStrip,
  PlayerInline,
  RatingChip,
  SectionHeader,
  TeamCrest,
  Timeline,
  VideoCard,
  formatDayShort,
  type PlayerLinkProps,
} from '../../ui';
import {
  aboutRows,
  bestOfSide,
  formView,
  h2hView,
  has,
  highlightView,
  potmView,
  realSide,
  timelineView,
  tournamentName,
  type Phase,
  type StarView,
} from './view';

const BEFORE = new Set<Phase>(['scheduled', 'postponed', 'cancelled']);

export function OverviewTab({ match, phase }: { match: ApiMatch; phase: Phase }) {
  const before = BEFORE.has(phase);
  const hl = highlightView(match);
  const best = bestOfSide(match, realSide(match));
  const potm = potmView(match);
  const tl = useMemo(() => (has(match, 'events') ? timelineView(match) : null), [match]);
  const about = aboutRows(match);
  const h2h = before ? h2hView(match) : null;
  const form = before ? formView(match) : null;
  const live = phase === 'live' || phase === 'halftime';
  const links = usePlayerLinks();

  const nothing = !hl && !best && !potm && !tl?.items.length && !about.length && !h2h && !form && !live;

  return (
    <>
      {hl && <Highlight match={match} hl={hl} />}

      {(best || potm) && (
        <section aria-label="Лучшие игроки" className={best && potm ? 'mt-stars' : 'mt-stars mt-stars--one'}>
          {best && <StarCard caption="Лучший у Реала" star={best} />}
          {potm && <StarCard caption="Игрок матча" star={potm} />}
        </section>
      )}

      {tl && tl.items.length > 0 ? (
        <Card ariaLabel="Хронология">
          <h2 className="mt-h2 mt-h2--tl">Хронология</h2>
          <LiveTimeline view={tl} links={links} />
        </Card>
      ) : (
        live && (
          <Card ariaLabel="Хронология">
            <h2 className="mt-h2">Хронология</h2>
            <p className="mt-muted mt-gap">Пока без голов и карточек</p>
          </Card>
        )
      )}

      {h2h && (
        <Card ariaLabel="Личные встречи">
          <SectionHeader title="Личные встречи" />
          <div className="mt-h2h">
            <div className="mt-h2h__col">
              <b>{h2h.home.wins}</b>
              <span className="mt-h2h__team">
                {h2h.home.id != null && <TeamCrest id={h2h.home.id} name="" size={20} />}
                <span>{h2h.home.name}</span>
              </span>
            </div>
            <div className="mt-h2h__col">
              <b>{h2h.draws}</b>
              <span>ничьи</span>
            </div>
            <div className="mt-h2h__col">
              <b>{h2h.away.wins}</b>
              <span className="mt-h2h__team">
                {h2h.away.id != null && <TeamCrest id={h2h.away.id} name="" size={20} />}
                <span>{h2h.away.name}</span>
              </span>
            </div>
          </div>
          {h2h.matches.length > 0 && (
            <div className="mt-h2h__list">
              {h2h.matches.map((x) => (
                <FixtureRow key={x.kickoff} kind="result" crests kickoff={x.kickoff} home={x.home} away={x.away} score={x.score} result={x.result} />
              ))}
            </div>
          )}
        </Card>
      )}

      {form && (
        <Card ariaLabel="Форма команд">
          <SectionHeader title="Форма" aside="последние матчи" />
          {form.map((f) => (
            <div key={f.side} className="mt-form">
              <span className="mt-form__team">
                {f.team.id != null && <TeamCrest id={f.team.id} name="" size={24} />}
                <span>{f.team.name}</span>
              </span>
              <FormStrip results={f.results} />
            </div>
          ))}
        </Card>
      )}

      {about.length > 0 && (
        <Card ariaLabel="О матче" className="mt-about">
          {about.map(([k, v]) => (
            <div key={k} className="mt-about__row">
              <span className="mt-about__k">{k}</span>
              <span>{v}</span>
            </div>
          ))}
        </Card>
      )}

      {nothing && (
        <EmptyState
          className="mt-state"
          title={before ? 'Подробности появятся ближе к матчу' : 'Подробностей пока нет'}
          text={before ? 'Составы — примерно за час до начала' : undefined}
        />
      )}
    </>
  );
}

function StarCard({ caption, star }: { caption: string; star: StarView }) {
  const links = usePlayerLinks();
  return (
    <div className="ui-card ui-card--flush mt-star">
      <div className="mt-star__cap">{caption}</div>
      <div className="mt-star__row">
        <PlayerInline player={{ id: star.id, name: star.name }} size={32} className="mt-star__name" {...links} />
        <RatingChip value={star.rating} />
      </div>
    </div>
  );
}

function Highlight({ match, hl }: { match: ApiMatch; hl: NonNullable<ReturnType<typeof highlightView>> }) {
  const ref = useRef<HTMLDivElement>(null);
  // VideoCard рисует обычную <a>; в браузере — новая вкладка, в Telegram — openLink
  useEffect(() => {
    const a = ref.current?.querySelector('a');
    if (a) {
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
    }
  }, [hl.href]);
  const onClick = (e: MouseEvent) => {
    if (openExternal(hl.href)) e.preventDefault();
  };
  const sub = [tournamentName(match), match.kickoff ? formatDayShort(match.kickoff) : null].filter(Boolean).join(' · ');
  return (
    <div ref={ref} onClickCapture={onClick} className="mt-video">
      <VideoCard title={hl.title} subtitle={sub} href={hl.href} thumbnailUrl={hl.thumb} provider={hl.provider} height={180} />
    </div>
  );
}

/** Хронология + короткая подсветка нового гола (только для голов, пришедших после первой загрузки). */
function LiveTimeline({ view, links }: { view: ReturnType<typeof timelineView>; links: PlayerLinkProps }) {
  const ref = useRef<HTMLDivElement>(null);
  const seen = useRef<Set<string> | null>(null);

  useLayoutEffect(() => {
    const keys = view.goalKeys.filter((k): k is string => !!k);
    const prev = seen.current;
    seen.current = new Set(keys);
    if (!prev) return;
    const rows = ref.current?.querySelectorAll(':scope > ol > li');
    if (!rows) return;
    view.goalKeys.forEach((k, i) => {
      if (!k || prev.has(k)) return;
      const li = rows[i];
      if (!li) return;
      li.classList.remove('mt-new');
      void (li as HTMLElement).offsetWidth; // перезапуск анимации
      li.classList.add('mt-new');
      // таймер не снимаем при перерисовке: класс должен уйти в любом случае
      window.setTimeout(() => li.classList.remove('mt-new'), 2600);
    });
  }, [view]);

  return (
    <div ref={ref} className="mt-tl">
      <Timeline items={view.items} {...links} />
    </div>
  );
}
