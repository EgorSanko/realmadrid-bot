import { useEffect, useLayoutEffect, useMemo, useRef, type MouseEvent } from 'react';
import type { ApiMatch } from '../../api/match';
import { usePlayerLinks } from '../../lib/playerNav';
import { openExternal } from '../../lib/tmaNav';
import { plainClick, useMediaNav, videoHref } from '../../lib/mediaNav';
import { youtubeIdOf } from '../media/mediaData';
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
import { InsightsCard, PollCard, RoundCard } from './ExtraCards';
import { MatchInfo } from './MatchInfo';
import { KeyStats } from './StatsTab';
import { insightsView, pollView, roundView } from './extras';
import {
  aboutRows,
  bestOfSide,
  formView,
  h2hView,
  has,
  highlightView,
  potmView,
  realSide,
  statPeriods,
  timelineView,
  tournamentName,
  type Phase,
  type StarView,
} from './view';

const BEFORE = new Set<Phase>(['scheduled', 'postponed', 'cancelled']);

/**
 * desk — компьютер (две колонки, как у FotMob): слева хронология (до матча — факты и форма), справа лучшие игроки,
 * «Кто победит?», стадион, судья и главные показатели. Тур и личные встречи там — отдельными вкладками.
 */
export function OverviewTab({ match, phase, desk, onStats }: { match: ApiMatch; phase: Phase; desk?: boolean; onStats?: () => void }) {
  const before = BEFORE.has(phase);
  const hl = highlightView(match);
  const best = bestOfSide(match, realSide(match));
  const potm = potmView(match);
  const tl = useMemo(() => (has(match, 'events') ? timelineView(match) : null), [match]);
  const about = aboutRows(match);
  const h2h = before && !desk ? h2hView(match) : null;
  const form = before ? formView(match) : null;
  const live = phase === 'live' || phase === 'halftime';
  const links = usePlayerLinks();

  const finished = phase === 'finished';
  // карточки из отдельных снимков: факты — до матча и (свёрнуто) в лайве; тур и «Кто победит?» — всегда
  const facts = (before || live) && insightsView(match) ? <InsightsCard match={match} collapsed={live} /> : null;
  const poll = pollView(match) || before ? <PollCard match={match} phase={phase} /> : null;
  const round = roundView(match) && !desk ? <RoundCard match={match} /> : null;

  const nothing = !hl && !best && !potm && !tl?.items.length && !about.length && !h2h && !form && !live && !facts && !round && !pollView(match);

  const starsEl = (best || potm) && (
    <section aria-label="Лучшие игроки" className={best && potm ? 'mt-stars' : 'mt-stars mt-stars--one'}>
      {best && <StarCard caption="Лучший у Реала" star={best} />}
      {potm && <StarCard caption="Игрок матча" star={potm} />}
    </section>
  );
  const tlEl = tl && tl.items.length > 0 ? (
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
  );
  const h2hEl = h2h && <H2HCard h2h={h2h} />;
  const formEl = form && <FormCard form={form} />;
  const nothingEl = nothing && (
    <EmptyState
      className="mt-state"
      title={before ? 'Подробности появятся ближе к матчу' : 'Подробностей пока нет'}
      text={before ? 'Составы — примерно за час до начала' : undefined}
    />
  );
  const pollEl = (before || live || finished) && poll;

  if (desk) {
    const info = about.length > 0 && <MatchInfo match={match} dense />;
    const stats = statPeriods(match).length > 0 && <KeyStats match={match} onAll={onStats} />;
    // «Кто победит?» и главные показатели — в ту колонку, что короче (примерные высоты карточек в px)
    let l = (tl?.items.length ? 70 + tl.items.length * 36 : live ? 110 : 0) + (facts ? (live ? 90 : 420) : 0) + (formEl ? 170 : 0);
    let r = (hl ? 280 : 0) + (starsEl ? 110 : 0) + (info ? 340 : 0);
    const put = (h: number): 'l' | 'r' => {
      if (l + h <= r + 120) {
        l += h;
        return 'l';
      }
      r += h;
      return 'r';
    };
    const pollAt = pollEl ? put(270) : null;
    const statsAt = stats ? put(380) : null;
    const left = l > 0;
    return (
      <div className={left ? 'mt-ov' : 'mt-ov mt-ov--one'}>
        {left && (
          <div className="mt-ov__col">
            {tlEl}
            {facts}
            {formEl}
            {pollAt === 'l' && pollEl}
            {statsAt === 'l' && stats}
          </div>
        )}
        <div className="mt-ov__col">
          {hl && <Highlight match={match} hl={hl} />}
          {starsEl}
          {pollAt === 'r' && pollEl}
          {info}
          {statsAt === 'r' && stats}
          {nothingEl}
        </div>
      </div>
    );
  }

  return (
    <>
      {hl && <Highlight match={match} hl={hl} />}
      {starsEl}
      {tlEl}
      {pollEl}
      {facts}
      {h2hEl}
      {formEl}
      {/* стадион, погода, судья: в лайве — одной строкой, по нажатию раскрывается */}
      {live && round}
      {about.length > 0 && <MatchInfo match={match} compact={live} />}
      {!live && round}
      {nothingEl}
    </>
  );
}

/** Личные встречи: счёт побед и последние матчи между командами. */
export function H2HCard({ h2h }: { h2h: NonNullable<ReturnType<typeof h2hView>> }) {
  return (
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
  );
}

/** Вкладка «Очные встречи» на компьютере: личные встречи и форма команд (до матча форма — в «Обзоре»). */
export function H2HTab({ match, phase }: { match: ApiMatch; phase: Phase }) {
  const h2h = h2hView(match, 10);
  const form = BEFORE.has(phase) ? null : formView(match);
  if (!h2h) return null;
  return (
    <div className={form ? 'mt-ov' : 'mt-ov mt-ov--one'}>
      <div className="mt-ov__col">
        <H2HCard h2h={h2h} />
      </div>
      {form && (
        <div className="mt-ov__col">
          <FormCard form={form} />
        </div>
      )}
    </div>
  );
}

function FormCard({ form }: { form: NonNullable<ReturnType<typeof formView>> }) {
  return (
    <Card ariaLabel="Форма команд">
      <SectionHeader title="Форма" aside="последние матчи" />
      {form.map((f) => (
        <div key={f.side} className="mt-form">
          <span className="mt-form__team">
            {f.team.id != null && <TeamCrest id={f.team.id} name="" size={24} />}
            <span>{f.team.name}</span>
          </span>
          <FormStrip results={f.results} opponents={f.opponents} />
        </div>
      ))}
    </Card>
  );
}

function StarCard({ caption, star }: { caption: string; star: StarView }) {
  const links = usePlayerLinks();
  return (
    <div className="ui-card ui-card--flush mt-star">
      <div className="mt-star__row mt-star__row--cap">
        <span className="mt-star__cap">{caption}</span>
        <RatingChip value={star.rating} />
      </div>
      <div className="mt-star__row">
        <PlayerInline player={{ id: star.id, name: star.name }} size={32} className="mt-star__name" {...links} />
      </div>
    </div>
  );
}

function Highlight({ match, hl }: { match: ApiMatch; hl: NonNullable<ReturnType<typeof highlightView>> }) {
  const ref = useRef<HTMLDivElement>(null);
  const { openVideo } = useMediaNav();
  // ролик YouTube — встроенный плеер внутри приложения (/video/:id); другой провайдер — внешняя ссылка
  const ytId = youtubeIdOf(hl.href);
  useEffect(() => {
    const a = ref.current?.querySelector('a');
    if (a && !ytId) {
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
    }
  }, [hl.href, ytId]);
  const onClick = (e: MouseEvent<HTMLElement>) => {
    if (ytId) {
      if (!plainClick(e)) return;
      e.preventDefault();
      openVideo({ id: ytId, title: hl.title, short: false, published: match.kickoff ?? null });
      return;
    }
    if (openExternal(hl.href)) e.preventDefault();
  };
  const sub = [tournamentName(match), match.kickoff ? formatDayShort(match.kickoff) : null].filter(Boolean).join(' · ');
  return (
    <div ref={ref} onClickCapture={onClick} className="mt-video">
      <VideoCard title={hl.title} subtitle={sub} href={ytId ? videoHref(ytId) : hl.href} thumbnailUrl={hl.thumb} provider={hl.provider} height={180} />
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
