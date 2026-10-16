import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router';
import type { ApiMatch } from '../../api/match';
import { useTelegramBackButton } from '../../lib/tmaNav';
import { Badge, Countdown, EmptyState, ErrorState, ScoreHeader, Skeleton, Tabs } from '../../ui';
import { LineupsTab } from './LineupsTab';
import { OverviewTab } from './OverviewTab';
import { StatsTab } from './StatsTab';
import { useMatch } from './useMatch';
import { useScrollAnchorFallback } from './useScrollAnchor';
import { compactTitle, headerView, teamRef, tournamentLine } from './view';
import './match.css';

type TabId = 'overview' | 'lineups' | 'stats';

const TABS: Array<{ id: TabId; label: string; suffix: string }> = [
  { id: 'overview', label: 'Обзор', suffix: '' },
  { id: 'lineups', label: 'Составы', suffix: '/lineups' },
  { id: 'stats', label: 'Статистика', suffix: '/stats' },
];

function tabFromPath(path: string): TabId {
  if (/\/lineups\/?$/.test(path)) return 'lineups';
  if (/\/stats\/?$/.test(path)) return 'stats';
  return 'overview';
}

const BACK_ICON = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M15 5l-7 7 7 7" />
  </svg>
);

/** Экран матча: /match/:id, /match/:id/lineups, /match/:id/stats. */
export default function MatchScreen() {
  const { id = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const tab = tabFromPath(location.pathname);

  // прямой заход по ссылке (история пуста) — «назад» ведёт в календарь, а не из приложения
  const [direct] = useState(() => location.key === 'default');
  const goBack = useCallback(() => {
    if (direct) navigate('/matches', { replace: true });
    else navigate(-1);
  }, [direct, navigate]);
  const nativeBack = useTelegramBackButton(goBack);

  const { state, reload } = useMatch(id);
  const match = state.kind === 'ok' ? state.match : null;
  const head = useMemo(() => (match ? headerView(match) : null), [match]);
  useScrollAnchorFallback(match);

  useEffect(() => {
    document.title = match ? `${compactTitle(match)} — Мадридиста` : 'Матч — Мадридиста';
  }, [match]);

  const title = match ? (tab === 'overview' ? tournamentLine(match) : compactTitle(match)) : '';
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
        <h1 className="mt-top__title">{title}</h1>
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

      {match && head && (
        <>
          {tab === 'overview' && <Header match={match} onKickoff={reload} />}
          <Tabs items={TABS} value={tab} onChange={setTab} ariaLabel="Разделы матча" />
          {match.pending ? (
            <PendingBody />
          ) : (
            <div className="mt-body" key={tab}>
              {tab === 'overview' && <OverviewTab match={match} phase={head.phase} />}
              {tab === 'lineups' && <LineupsTab match={match} phase={head.phase} />}
              {tab === 'stats' && <StatsTab match={match} phase={head.phase} />}
            </div>
          )}
        </>
      )}
    </main>
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
      {h.countdown && match.kickoff && <Countdown to={match.kickoff} className="mt-cd" onEnd={onKickoff} />}
    </>
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
