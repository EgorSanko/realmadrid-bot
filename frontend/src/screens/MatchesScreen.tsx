import { useEffect, useMemo, useState } from 'react';
import type { ApiFixtures, ApiTable, ApiTables } from '../lib/api';
import {
  COMP_TABS,
  LALIGA_ID,
  UCL_ID,
  compactRows,
  errorText,
  roundsAside,
  splitFixtures,
  standingRows,
  staleNote,
  tableFor,
  usRow,
  zonesFor,
  type CompTab,
} from '../lib/mapMatches';
import { useSpaLink } from '../lib/spaLink';
import { usePoll } from '../lib/usePoll';
import { EmptyState, ErrorState, FixtureRow, SectionHeader, Skeleton, StandingsTable, Tabs } from '../ui';
import { CalendarRow } from '../ui/matchExtra';
import './screens.css';

const UPCOMING_SHOWN = 6;
const RESULTS_SHOWN = 5;

const fixturesPoll = (d: ApiFixtures | null) => (d?.matches?.some((m) => m.status?.live) ? 15_000 : 60_000);
const tablesPoll = () => 5 * 60_000;

function MoreButton({ open, onToggle, more, less }: { open: boolean; onToggle: () => void; more: string; less: string }) {
  return (
    <button type="button" className="screen-more" aria-expanded={open} onClick={onToggle}>
      {open ? less : more}
    </button>
  );
}

function LeagueTable({ table, title }: { table: ApiTable; title: string }) {
  const [full, setFull] = useState(false);
  const all = useMemo(() => standingRows(table), [table]);
  const us = usRow(table);
  const { rows, collapsed } = compactRows(all, us?.pos ?? null);
  const shown = full || !collapsed ? all : rows;
  return (
    <section className="ui-card" aria-label={`Таблица: ${title}`}>
      <SectionHeader title={title} aside={roundsAside(table)} />
      <StandingsTable rows={shown} highlightTeamId={us?.team.id ?? undefined} zones={zonesFor(table, shown)} />
      {collapsed && (
        <MoreButton open={full} onToggle={() => setFull((v) => !v)} more="Вся таблица" less="Свернуть таблицу" />
      )}
    </section>
  );
}

export default function MatchesScreen() {
  const [tab, setTab] = useState<CompTab>('all');
  const [allUpcoming, setAllUpcoming] = useState(false);
  const [allResults, setAllResults] = useState(false);
  const fx = usePoll<ApiFixtures>('/api/fixtures', fixturesPoll);
  const tb = usePoll<ApiTables>('/api/tables', tablesPoll);
  const link = useSpaLink();

  useEffect(() => {
    document.title = 'Матчи — Мадридиста';
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
  if (!fx.data && fx.loading) {
    fixturesBlock = (
      <>
        <section className="ui-card" aria-label="Ближайшие матчи">
          <SectionHeader title="Ближайшие" />
          <Skeleton shape="list" rows={4} />
        </section>
        <section className="ui-card" aria-label="Результаты">
          <SectionHeader title="Результаты" />
          <Skeleton shape="list" rows={3} />
        </section>
      </>
    );
  } else if (!lists) {
    const e = errorText(fx.error);
    fixturesBlock = <ErrorState title={e.title} text={e.text} onRetry={fx.reload} />;
  } else {
    const up = allUpcoming ? lists.upcoming : lists.upcoming.slice(0, UPCOMING_SHOWN);
    const res = allResults ? lists.results : lists.results.slice(0, RESULTS_SHOWN);
    fixturesBlock = (
      <>
        <section className="ui-card" aria-label="Ближайшие матчи">
          <SectionHeader title="Ближайшие" aside={note ?? undefined} />
          {up.length === 0 ? (
            <EmptyState plain title="Ближайших матчей нет" text="Календарь обновится, когда турнир опубликует даты" />
          ) : (
            <div className="screen-list">
              {up.map((m) => (
                <CalendarRow key={m.id} {...m} {...link(m.href)} />
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
        <section className="ui-card" aria-label="Результаты">
          <SectionHeader title="Результаты" />
          {res.length === 0 ? (
            <EmptyState plain title="Пока без результатов" text="Здесь появятся сыгранные матчи" />
          ) : (
            <div className="screen-list">
              {res.map((m) => (
                <FixtureRow
                  key={m.id}
                  kind="result"
                  kickoff={m.kickoff}
                  home={m.home}
                  away={m.away}
                  score={m.score}
                  result={m.result}
                  {...link(m.href)}
                />
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
      </>
    );
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

  return (
    <main className="matches">
      <header className="topbar">
        <h1 className="topbar__title">Матчи</h1>
        <span className="topbar__aside">{aside}</span>
      </header>
      <Tabs items={COMP_TABS} value={tab} onChange={onTab} ariaLabel="Фильтр турниров" />
      {fixturesBlock}
      {tablesBlock}
    </main>
  );
}
