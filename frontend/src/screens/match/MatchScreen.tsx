import { useCallback, useEffect, useLayoutEffect, useMemo } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router';
import type { ApiMatch } from '../../api/match';
import { useDesktop } from '../../lib/shell';
import { useTelegramBackButton } from '../../lib/tmaNav';
import { Badge, Countdown, EmptyState, ErrorState, LeagueLogo, ScoreHeader, Skeleton, Tabs, TeamCrest } from '../../ui';
import { LineupsTab } from './LineupsTab';
import { OnlineTab } from './OnlineTab';
import { OverviewTab } from './OverviewTab';
import { StatsTab } from './StatsTab';
import { useMatch } from './useMatch';
import { useScrollAnchorFallback } from './useScrollAnchor';
import { REAL_ID, compactTitle, goals, headerView, minuteText, realSide, shortName, teamRef, tournamentLine } from './view';
import { useGoalWatch } from '../../lib/useGoalWatch';
import { takeRects } from '../../lib/flipOrigin';
import { reducedMotion } from '../../lib/motion';
import { addMatchToCalendar, canAddToCalendar } from '../../lib/nativeBridge';
import './match.css';

type TabId = 'overview' | 'lineups' | 'stats' | 'online';

const TABS: Array<{ id: TabId; label: string; suffix: string }> = [
  { id: 'overview', label: 'Обзор', suffix: '' },
  { id: 'lineups', label: 'Составы', suffix: '/lineups' },
  { id: 'stats', label: 'Статистика', suffix: '/stats' },
  { id: 'online', label: 'Онлайн', suffix: '/online' },
];

function tabFromPath(path: string): TabId {
  if (/\/lineups\/?$/.test(path)) return 'lineups';
  if (/\/stats\/?$/.test(path)) return 'stats';
  if (/\/online\/?$/.test(path)) return 'online';
  return 'overview';
}

const BACK_ICON = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M15 5l-7 7 7 7" />
  </svg>
);

/** Экран матча: /match/:id, /match/:id/lineups, /match/:id/stats, /match/:id/online. */
export default function MatchScreen() {
  const { id = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const desktop = useDesktop();
  const tab = desktop ? 'overview' : tabFromPath(location.pathname);

  // прямой заход по ссылке (за нами нет страниц приложения) — «назад» ведёт в календарь, а не из приложения.
  // idx в history.state ведёт react-router: push +1, replace — без изменений; переживает перезагрузку.
  const goBack = useCallback(() => {
    const idx = (window.history.state as { idx?: number } | null)?.idx;
    if (!idx) navigate('/matches', { replace: true });
    else navigate(-1);
  }, [navigate]);
  const nativeBack = useTelegramBackButton(goBack);

  const { state, reload } = useMatch(id);
  const match = state.kind === 'ok' ? state.match : null;
  const head = useMemo(() => (match ? headerView(match) : null), [match]);
  useScrollAnchorFallback(match);

  // пришли с карточки матча: шапка собирается — эмблемы проявляются с лёгким ростом, следом счёт/«vs».
  // Перелёт эмблем из списка (FLIP) убран: строка списка стоит там же, где в шапке цифры отсчёта, и
  // эмблемы ползли поперёк них — выглядело как сбой.
  const ready = !!head;
  useLayoutEffect(() => {
    if (!ready) return;
    if (!takeRects(`match:${id}`) || reducedMotion()) return;
    const crests = document.querySelectorAll<HTMLElement>('.mt .ui-score-head .ui-crest, .mt .mt-top__title .ui-crest');
    crests.forEach((c, i) =>
      c.animate?.([{ opacity: 0, transform: 'scale(.82)' }, { opacity: 1, transform: 'none' }], {
        duration: 420,
        delay: i * 60,
        easing: 'cubic-bezier(.22,1,.36,1)',
        fill: 'backwards',
      }),
    );
    document.querySelector<HTMLElement>('.mt .ui-score-head__score, .mt .ui-score-head .ui-mc__vs')?.animate?.(
      [{ opacity: 0, transform: 'scale(.9)' }, { opacity: 1, transform: 'none' }],
      { duration: 380, delay: 120, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' },
    );
  }, [ready, id]);

  // новый гол в лайве: Реал — праздник (плашка, конфетти), соперник — только перелистывание табло
  const hasReal = !!match && (match.home.id === REAL_ID || match.away.id === REAL_ID);
  useGoalWatch(
    match && head
      ? {
          id: match.id ?? id,
          score: head.score,
          live: head.live,
          real: hasReal ? realSide(match) : null,
          rival: hasReal ? teamRef(match, realSide(match) === 'home' ? 'away' : 'home') : undefined,
        }
      : null,
    (g) => {
      const ev = match ? goals(match).filter((x) => x.side === g.side)[g.n - 1]?.ev : undefined;
      const pid = Number(ev?.player?.id);
      return {
        minute: ev ? minuteText(ev.minute, ev.added) : head?.minute,
        scorer: ev?.player?.name ? { id: Number.isFinite(pid) && pid > 0 ? pid : undefined, name: shortName(ev.player.name) } : null,
      };
    },
  );

  useEffect(() => {
    document.title = match ? `${compactTitle(match)} — Мадридиста` : 'Матч — Мадридиста';
  }, [match]);

  const title = match ? (tab === 'overview' ? tournamentLine(match) : compactTitle(match)) : '';
  // компьютер: «Онлайн» — секцией в правой колонке, когда матч начался или есть трансляция
  const started = !!head && ['live', 'halftime', 'finished', 'abandoned'].includes(head.phase);
  const online =
    match && head && (started || match.available.includes('commentary')) ? (
      <section className="mt-desk__sec" aria-label="Онлайн-трансляция">
        <h2 className="dk-h2">Онлайн</h2>
        <OnlineTab match={match} phase={head.phase} />
      </section>
    ) : null;
  const setTab = (t: TabId) => {
    const suffix = TABS.find((x) => x.id === t)?.suffix ?? '';
    // вкладки не копят историю: «назад» уводит с матча, а не по вкладкам
    navigate(`/match/${encodeURIComponent(id)}${suffix}`, { replace: true });
  };

  return (
    <main className="mt" aria-busy={state.kind === 'loading' || undefined}>
      <header className="mt-top">
        {nativeBack ? (
          <span className="mt-top__gap" aria-hidden="true" />
        ) : (
          <button type="button" className="mt-top__back" aria-label="Назад" onClick={goBack}>
            {BACK_ICON}
          </button>
        )}
        {match && tab !== 'overview' ? (
          <TeamsTitle match={match} />
        ) : (
          <h1 className={match?.tournament.id != null ? 'mt-top__title mt-top__title--teams' : 'mt-top__title'}>
            {match?.tournament.id != null && <LeagueLogo id={match.tournament.id} name="" size={20} />}
            <span className="mt-top__tm">{title}</span>
          </h1>
        )}
        {head?.live ? <Badge tone="live" className="mt-top__live" /> : <span className="mt-top__gap" aria-hidden="true" />}
      </header>

      {state.kind === 'loading' && <LoadingBody />}
      {state.kind === 'not_found' && (
        <EmptyState
          className="mt-state"
          title="Матч не найден"
          text="Такого матча нет в календаре"
          action={{ label: 'К матчам', onClick: () => navigate('/matches') }}
        />
      )}
      {state.kind === 'unavailable' && (
        <ErrorState className="mt-state" title="Данные ещё собираются" text="Сервер только что запустился. Попробуем снова через несколько секунд" onRetry={reload} />
      )}
      {state.kind === 'error' && <ErrorState className="mt-state" onRetry={reload} />}

      {match && head && desktop && (
        // сайт на компьютере: шапка матча на всю ширину, ниже — обзор слева, составы и статистика справа (без вкладок)
        <>
          <Header match={match} onKickoff={reload} />
          {match.pending ? (
            <PendingBody />
          ) : (
            <div className="dk-split dk-split--wide-side mt-desk">
              <div className="dk-col mt-desk__col" aria-label="Обзор">
                <OverviewTab match={match} phase={head.phase} />
              </div>
              <div className="dk-col mt-desk__col">
                {/* идёт матч — «Онлайн» первым в правой колонке, после матча — в конце */}
                {head.live && online}
                <section className="mt-desk__sec" aria-label="Составы">
                  <h2 className="dk-h2">Составы</h2>
                  <LineupsTab match={match} phase={head.phase} />
                </section>
                <section className="mt-desk__sec" aria-label="Статистика">
                  <h2 className="dk-h2">Статистика</h2>
                  <StatsTab match={match} phase={head.phase} />
                </section>
                {!head.live && online}
              </div>
            </div>
          )}
        </>
      )}

      {match && head && !desktop && (
        <>
          {tab === 'overview' && <Header match={match} onKickoff={reload} />}
          <Tabs items={TABS} value={tab} onChange={setTab} ariaLabel="Разделы матча" className={head.live ? 'mt-tabs--live' : undefined} />
          {match.pending ? (
            <PendingBody />
          ) : (
            <div className="mt-body" key={tab}>
              {tab === 'overview' && <OverviewTab match={match} phase={head.phase} />}
              {tab === 'lineups' && <LineupsTab match={match} phase={head.phase} />}
              {tab === 'stats' && <StatsTab match={match} phase={head.phase} />}
              {tab === 'online' && <OnlineTab match={match} phase={head.phase} />}
            </div>
          )}
        </>
      )}
    </main>
  );
}

/** «[эмб] Roma 3 : 4 Real Madrid [эмб]» — заголовок вкладок без большой шапки; текст — тот же compactTitle. */
function TeamsTitle({ match }: { match: ApiMatch }) {
  const h = teamRef(match, 'home');
  const a = teamRef(match, 'away');
  const full = compactTitle(match);
  const mid = full.slice((match.home.name ?? '').length, full.length - (match.away.name ?? '').length).trim();
  return (
    <h1 className="mt-top__title mt-top__title--teams" aria-label={full}>
      {h.id != null && <TeamCrest id={h.id} name="" size={20} />}
      <span className="mt-top__tm" aria-hidden="true">
        {h.name}
      </span>
      <span className="mt-top__sc" aria-hidden="true">
        {mid}
      </span>
      <span className="mt-top__tm" aria-hidden="true">
        {a.name}
      </span>
      {a.id != null && <TeamCrest id={a.id} name="" size={20} />}
    </h1>
  );
}

function Header({ match, onKickoff }: { match: ApiMatch; onKickoff: () => void }) {
  const h = headerView(match);
  return (
    <>
      <ScoreHeader
        home={teamRef(match, 'home')}
        away={teamRef(match, 'away')}
        status={h.status}
        score={h.score}
        kickoff={match.kickoff ?? undefined}
        minute={h.minute}
        statusText={h.statusText}
        scorers={h.scorers}
      />
      {h.countdown && match.kickoff && <Countdown to={match.kickoff} className="mt-cd" onEnd={onKickoff} liveOnEnd />}
      {h.countdown && match.kickoff && canAddToCalendar() && <CalendarButton match={match} />}
    </>
  );
}

/** Только в приложении из RuStore: матч — в календарь телефона (системный экран «Новое событие»). */
function CalendarButton({ match }: { match: ApiMatch }) {
  const title = `${match.home.name ?? ''} — ${match.away.name ?? ''}`.trim();
  const place = [match.venue?.name, match.venue?.city].filter(Boolean).join(', ') || null;
  const what = [match.tournament?.name, match.tournament?.round].filter(Boolean).join(', ');
  return (
    <button
      type="button"
      className="ui-btn ui-btn--secondary ui-btn--block mt-cal"
      onClick={() =>
        addMatchToCalendar(title, match.kickoff!, place, `${what ? `${what}. ` : ''}Мадридиста: https://realmadridfan.ru/match/${match.id ?? ''}`)
      }
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <rect x="3.5" y="5" width="17" height="15" rx="3" />
        <path d="M3.5 10h17M8 3v4M16 3v4" />
      </svg>
      Добавить в календарь
    </button>
  );
}

function LoadingBody() {
  return (
    <div className="mt-loading">
      <Skeleton shape="match" />
      <Skeleton shape="list" rows={4} className="mt-loading__list" />
    </div>
  );
}

function PendingBody() {
  return (
    <section className="ui-card mt-pending" aria-live="polite">
      <p className="mt-pending__title">Данные подгружаются</p>
      <p className="mt-pending__text">Обновим автоматически через несколько секунд</p>
      <Skeleton shape="stats" rows={4} />
    </section>
  );
}
