import { useEffect, useMemo, useState } from 'react';
import type { ApiFixtures, ApiTables } from '../lib/api';
import {
  COMP_TABS,
  LALIGA_ID,
  UCL_ID,
  errorText,
  splitFixtures,
  staleNote,
  tableFor,
  type CompTab,
} from '../lib/mapMatches';
import { useDesktop } from '../lib/shell';
import { useSpaLink } from '../lib/spaLink';
import { usePoll } from '../lib/usePoll';
import { EmptyState, ErrorState, SectionHeader, Skeleton, Tabs } from '../ui';
import { MatchRow } from '../ui/matchExtra';
import { LeagueTable, MoreButton } from './LeagueTable';
import './screens.css';

const UPCOMING_SHOWN = 8;
const RESULTS_SHOWN = 10;

/** что показываем: ближайшие, сыгранные или таблицы — сразу видно, где прошлые матчи */
type View = 'calendar' | 'results' | 'tables';
const VIEW_TABS: Array<{ id: View; label: string }> = [
  { id: 'calendar', label: 'Календарь' },
  { id: 'results', label: 'Результаты' },
  { id: 'tables', label: 'Таблица' },
];

const fixturesPoll = (d: ApiFixtures | null) => (d?.matches?.some((m) => m.status?.live) ? 15_000 : 60_000);
const tablesPoll = () => 5 * 60_000;

export default function MatchesScreen() {
  const [tab, setTab] = useState<CompTab>('all');
  const [view, setView] = useState<View>('calendar');
  const [allUpcoming, setAllUpcoming] = useState(false);
  const [allResults, setAllResults] = useState(false);
  const fx = usePoll<ApiFixtures>('/api/fixtures', fixturesPoll);
  const tb = usePoll<ApiTables>('/api/tables', tablesPoll);
  const link = useSpaLink();
  const desktop = useDesktop();

  useEffect(() => {
    document.title = 'Матчи «Реала»: календарь, результаты, таблица — Мадридиста';
  }, []);

  const lists = useMemo(() => (fx.data ? splitFixtures(fx.data.matches, tab) : null), [fx.data, tab]);
  const laliga = tableFor(tb.data?.tables, LALIGA_ID);
  const ucl = tableFor(tb.data?.tables, UCL_ID);
  const note = staleNote(fx.data);
  const aside = COMP_TABS.find((t) => t.id === tab)!.aside;

  const onTab = (t: CompTab) => {
    setTab(t);
    setAllUpcoming(false);
    setAllResults(false);
  };

  let fixturesBlock;
  let resultsBlock;
  if (!fx.data && fx.loading) {
    fixturesBlock = (
      <section className="ui-card" aria-label={view === 'results' ? 'Результаты' : 'Ближайшие матчи'}>
        <SectionHeader title={view === 'results' ? 'Результаты' : 'Ближайшие'} />
        <Skeleton shape="list" rows={5} />
      </section>
    );
  } else if (!lists) {
    const e = errorText(fx.error);
    fixturesBlock = <ErrorState title={e.title} text={e.text} onRetry={fx.reload} />;
  } else {
    const up = allUpcoming ? lists.upcoming : lists.upcoming.slice(0, UPCOMING_SHOWN);
    const res = allResults ? lists.results : lists.results.slice(0, RESULTS_SHOWN);
    const upcomingCard = (
        <section className="ui-card" aria-label="Ближайшие матчи">
          <SectionHeader title="Ближайшие" aside={note ?? undefined} />
          {up.length === 0 ? (
            <EmptyState plain title="Ближайших матчей нет" text="Календарь обновится, когда турнир опубликует даты" />
          ) : (
            <div className="screen-list">
              {up.map((m) => (
                <MatchRow key={m.id} kind="upcoming" {...m} {...link(m.href)} />
              ))}
            </div>
          )}
          {lists.upcoming.length > UPCOMING_SHOWN && (
            <MoreButton
              open={allUpcoming}
              onToggle={() => setAllUpcoming((v) => !v)}
              more={`Весь календарь · ${lists.upcoming.length}`}
              less="Свернуть"
            />
          )}
        </section>
    );
    const resultsCard = (
        <section className="ui-card" aria-label="Результаты">
          <SectionHeader title="Результаты" aside={note ?? undefined} />
          {res.length === 0 ? (
            <EmptyState plain title="Пока без результатов" text="Здесь появятся сыгранные матчи" />
          ) : (
            <div className="screen-list">
              {res.map((m) => (
                <MatchRow key={m.id} kind="result" {...m} {...link(m.href)} />
              ))}
            </div>
          )}
          {lists.results.length > RESULTS_SHOWN && (
            <MoreButton
              open={allResults}
              onToggle={() => setAllResults((v) => !v)}
              more={`Все результаты · ${lists.results.length}`}
              less="Свернуть"
            />
          )}
        </section>
    );
    fixturesBlock = view === 'results' ? resultsCard : upcomingCard;
    resultsBlock = resultsCard;
    if (desktop) fixturesBlock = upcomingCard;
  }

  const showLaliga = tab !== 'ucl';
  const showUcl = tab !== 'laliga';
  let tablesBlock;
  if (!tb.data && tb.loading) {
    tablesBlock = (
      <section className="ui-card" aria-label="Таблица">
        <SectionHeader title={tab === 'ucl' ? 'Лига чемпионов' : 'Ла Лига'} />
        <Skeleton shape="table" rows={6} />
      </section>
    );
  } else if (!tb.data) {
    // таблицы — второстепенны: без своей ошибки на весь экран, если календарь уже есть
    tablesBlock = fx.data ? (
      <ErrorState title="Таблица не загрузилась" text={errorText(tb.error).text} onRetry={tb.reload} />
    ) : null;
  } else {
    tablesBlock = (
      <>
        {showLaliga && laliga && <LeagueTable key="ll" table={laliga} title="Ла Лига" />}
        {showUcl && ucl && <LeagueTable key="ucl" table={ucl} title="Лига чемпионов" />}
      </>
    );
  }

  // сайт на компьютере: ближайшие и результаты слева, таблицы справа — всё сразу, без вкладок раздела
  if (desktop) {
    return (
      <main className="matches matches--desk">
        <header className="topbar">
          <h1 className="topbar__title">Матчи</h1>
          <span className="topbar__aside">{aside}</span>
        </header>
        <div className="dk-split dk-split--matches">
          <div className="dk-col">
            <Tabs items={COMP_TABS} value={tab} onChange={onTab} ariaLabel="Фильтр турниров" variant="pill" className="matches__comp" />
            {fixturesBlock}
            {resultsBlock}
          </div>
          <aside className="dk-col" aria-label="Турнирные таблицы">
            {tablesBlock}
          </aside>
        </div>
      </main>
    );
  }

  return (
    <main className="matches">
      <header className="topbar">
        <h1 className="topbar__title">Матчи</h1>
        <span className="topbar__aside">{aside}</span>
      </header>
      <Tabs items={VIEW_TABS} value={view} onChange={setView} ariaLabel="Раздел" />
      <Tabs items={COMP_TABS} value={tab} onChange={onTab} ariaLabel="Фильтр турниров" variant="pill" className="matches__comp" />
      {view === 'tables' ? tablesBlock : fixturesBlock}
    </main>
  );
}
