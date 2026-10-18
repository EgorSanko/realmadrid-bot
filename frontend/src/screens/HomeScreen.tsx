import { Suspense, lazy, useEffect, useMemo, useState } from 'react';
import { ScreenHeader } from '../components/ScreenHeader';
import { StreamBlock } from '../components/StreamBlock';
import type { ApiHome } from '../lib/api';
import {
  errorText,
  formOpponents,
  formResults,
  heroOf,
  homePollMs,
  lastMatchOf,
  leagueSummary,
  matchStatusOf,
  RM_ID,
  splitFixtures,
  staleNote,
} from '../lib/mapMatches';
import { isNativeApp, useDesktop } from '../lib/shell';
import { useSpaLink } from '../lib/spaLink';
import { useStream } from '../lib/stream';
import { usePoll } from '../lib/usePoll';
import { useGoalWatch } from '../lib/useGoalWatch';
import { DEBUG_GOAL_DELAY, debugGoalHome, debugGoalMode } from '../dev/debugGoal';
import { EmptyState, ErrorState, FormStrip, LeagueLogo, Skeleton, plural } from '../ui';
import { CalendarRow, HeroMatchCard } from '../ui/matchExtra';
import { HomeDesk } from './home/HomeDesk';
import { RoundStrip } from './match/ExtraCards';
import { RecentResults } from './home/RecentResults';
import { LatestNews } from './media/LatestNews';
import './screens.css';

const HomePredict = lazy(() => import('./predict/HomePredict'));

/** Тик раз в минуту — для подписи «обновлено N мин назад» и смены «только что сыгран» → «ближайший». */
function useNow(stepMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), stepMs);
    return () => window.clearInterval(t);
  }, [stepMs]);
  return now;
}

export default function HomeScreen() {
  const stream = useStream();
  const home = usePoll<ApiHome>('/api/home', (d) => homePollMs(d));
  const link = useSpaLink();
  const now = useNow();
  const desktop = useDesktop();

  useEffect(() => {
    document.title = isNativeApp()
      ? 'Мадридиста — фан-приложение Real Madrid: матчи, новости, прогнозы'
      : 'Мадридиста — фан-приложение Real Madrid: матчи, трансляции, новости';
  }, []);

  // dev: ?debugGoal=1 — ближайший матч «идёт», через 2,5 с гол (в прод-сборку не попадает)
  const [dbgTick, setDbgTick] = useState(0);
  useEffect(() => {
    if (!import.meta.env.DEV || !debugGoalMode()) return;
    const t = window.setTimeout(() => setDbgTick(1), DEBUG_GOAL_DELAY + 100);
    return () => window.clearTimeout(t);
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const d = useMemo(() => (import.meta.env.DEV ? debugGoalHome(home.data) : home.data), [home.data, dbgTick]);
  const view = useMemo(() => {
    if (!d) return null;
    const hero = heroOf(d, now);
    const last = lastMatchOf(d);
    // если сверху итог только что сыгранного матча — ниже показываем следующий, а не тот же матч ещё раз
    const heroIsLast = hero != null && last != null && hero.id === last.id;
    const nextRow =
      heroIsLast && d.next && matchStatusOf(d.next.status) === 'upcoming'
        ? splitFixtures([d.next], 'all').upcoming[0]
        : null;
    return {
      hero,
      last: heroIsLast ? null : last,
      nextRow,
      form: formResults(d),
      formOpp: formOpponents(d),
      league: leagueSummary(d),
      leagueId: d.laliga?.league?.id ?? null,
    };
  }, [d, now]);

  // гол Реала в лайве — праздник (автора слой спросит сам); гол соперника — только табло
  const hero = view?.hero;
  useGoalWatch(
    hero && hero.status !== 'upcoming'
      ? {
          id: hero.id,
          score: hero.score,
          live: hero.status === 'live',
          real: hero.home.id === RM_ID ? 'home' : hero.away.id === RM_ID ? 'away' : null,
          rival: hero.home.id === RM_ID ? hero.away : hero.home,
        }
      : null,
    () => ({ minute: hero?.minute }),
  );

  const note = d ? staleNote(d, home.receivedAt ? (now - home.receivedAt) / 1000 : 0) : null;
  const err = errorText(home.error);

  const heroBlock =
    !d && home.loading ? (
      <Skeleton shape="match" className="hero-wrap" />
    ) : !d ? (
      <ErrorState title={err.title} text={err.text} onRetry={home.reload} />
    ) : view?.hero ? (
      <HeroMatchCard
        {...view.hero}
        {...link(view.hero.href)}
        onKickoff={home.reload}
        footer={note && <p className="screen-note">{note}</p>}
      />
    ) : (
      <EmptyState title="Ближайших матчей нет" text="Расписание появится, как только его опубликуют" />
    );
  // идёт матч Реала — под ним лента его тура (Ла Лига, ЛЧ); сервер отдаёт round только в лайве
  const roundBlock = d?.round && d.next?.status?.live ? <RoundStrip round={d.round} matchId={d.next.id} /> : null;

  const lastBlock =
    !d && home.loading ? (
      <div className="home-skel-last" aria-hidden="true">
        <Skeleton height={86} radius={20} />
      </div>
    ) : view?.last ? (
      <RecentResults limit={3} />
    ) : view?.nextRow ? (
      <>
        <section className="ui-card home-next" aria-label="Следующий матч">
          <div className="home-tile__cap">Следующий матч</div>
          <CalendarRow {...view.nextRow} highlighted={false} {...link(view.nextRow.href)} />
        </section>
        <RecentResults limit={3} />
      </>
    ) : null;

  // сайт на компьютере: две колонки и лента на всю ширину (мини-апп и телефон — как раньше, ниже)
  if (desktop) {
    return (
      <HomeDesk
        hero={
          <>
            {heroBlock}
            {roundBlock}
          </>
        }
        last={lastBlock}
        stream={stream}
        loading={!d && home.loading}
        form={view?.form ?? []}
        formOpp={view?.formOpp ?? []}
        heroId={view?.hero?.id ?? null}
      />
    );
  }

  return (
    <main className="home">
      <ScreenHeader title="Главная" brand live={!!stream?.live} />

      {/* 1. Ближайший матч / идёт / итог */}
      {heroBlock}
      {roundBlock}

      {/* 2. Трансляция (этап 3) — без изменений */}
      <StreamBlock stream={stream} />

      {/* 3. Прогноз на ближайший матч: ввод счёта прямо здесь (ленивый чанк) */}
      <Suspense fallback={<Skeleton height={148} radius={24} style={{ margin: '14px 16px 0', width: 'auto' }} />}>
        <HomePredict />
      </Suspense>

      {/* 4. Форма и место в Ла Лиге */}
      {!d && home.loading ? (
        <div className="home-grid" aria-hidden="true">
          <Skeleton height={104} radius={20} />
          <Skeleton height={104} radius={20} />
        </div>
      ) : (
        view &&
        (view.form.length > 0 || view.league) && (
          <div className="home-grid">
            {view.form.length > 0 && (
              <section className="home-tile" aria-label="Форма">
                <div className="home-tile__cap">Форма, {view.form.length} {plural(view.form.length, ['матч', 'матча', 'матчей'])}</div>
                <FormStrip results={view.form} opponents={view.formOpp} size={24} className="home-tile__form" />
              </section>
            )}
            {view.league && (
              <a className="home-tile" aria-label="Таблица Ла Лиги" {...link('/matches')}>
                <div className="home-tile__cap home-tile__cap--logo">
                  {view.leagueId != null && <LeagueLogo id={view.leagueId} name="" size={16} />}
                  Ла Лига
                </div>
                <div className="home-tile__pos">
                  <span className="disp">{view.league.pos}</span>
                  <span>{view.league.line}</span>
                </div>
                {view.league.gap && <div className="home-tile__cap home-tile__gap">{view.league.gap}</div>}
              </a>
            )}
          </div>
        )
      )}

      {/* 5. Последние 3 матча (или следующий, если сверху итог только что сыгранного) */}
      {lastBlock}

      {/* 6. новости — блок раздела «Медиа»; нет данных — блок не показывается */}
      <LatestNews limit={3} />
    </main>
  );
}
