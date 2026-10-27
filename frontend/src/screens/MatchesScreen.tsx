import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
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
import { t, tc } from '../lib/i18n';
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
  { id: 'calendar', label: t('Календарь') },
  { id: 'results', label: t('Результаты') },
  { id: 'tables', label: t('Таблица') },
];

const fixturesPoll = (d: ApiFixtures | null) => (d?.matches?.some((m) => m.status?.live) ? 15_000 : 60_000);
const tablesPoll = () => 5 * 60_000;

export default function MatchesScreen() {
  const [tab, setTab] = useState<CompTab>('all');
  const [params] = useSearchParams();
  const initialView = params.get('view');
  const [view, setView] = useState<View>(
    initialView === 'results' || initialView === 'tables' ? initialView : 'calendar',
  );
  const [allUpcoming, setAllUpcoming] = useState(false);
  const [allResults, setAllResults] = useState(false);
  const fx = usePoll<ApiFixtures>('/api/fixtures', fixturesPoll);
  const tb = usePoll<ApiTables>('/api/tables', tablesPoll);
  const link = useSpaLink();
  const desktop = useDesktop();

  useEffect(() => {
    document.title = t('Матчи «Реала»: календарь, результаты, таблица — Мадридиста');
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
      <section className="ui-card" aria-label={view === 'results' ? t('Результаты') : t('Ближайшие матчи')}>
        <SectionHeader title={view === 'results' ? t('Результаты') : t('Ближайшие')} />
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
        <section className="ui-card" aria-label={t('Ближайшие матчи')}>
          <SectionHeader title={t('Ближайшие')} aside={note ?? undefined} />
          {up.length === 0 ? (
            <EmptyState plain title={t('Ближайших матчей нет')} text={t('Календарь обновится, когда турнир опубликует даты')} />
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
              more={t('Весь календарь · {n}', { n: lists.upcoming.length })}
              less={tc('list', 'Свернуть')}
            />
          )}
        </section>
    );
    const resultsCard = (
        <section className="ui-card" aria-label={t('Результаты')}>
          <SectionHeader title={t('Результаты')} aside={note ?? undefined} />
          {res.length === 0 ? (
            <EmptyState plain title={t('Пока без результатов')} text={t('Здесь появятся сыгранные матчи')} />
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
              more={t('Все результаты · {n}', { n: lists.results.length })}
              less={tc('list', 'Свернуть')}
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
      <section className="ui-card" aria-label={t('Таблица')}>
        <SectionHeader title={tab === 'ucl' ? t('Лига чемпионов') : t('Ла Лига')} />
        <Skeleton shape="table" rows={6} />
      </section>
    );
  } else if (!tb.data) {
    // таблицы — второстепенны: без своей ошибки на весь экран, если календарь уже есть
    tablesBlock = fx.data ? (
      <ErrorState title={t('Таблица не загрузилась')} text={errorText(tb.error).text} onRetry={tb.reload} />
    ) : null;
  } else {
    tablesBlock = (
      <>
        {showLaliga && laliga && <LeagueTable key="ll" table={laliga} title={t('Ла Лига')} />}
        {showUcl && ucl && <LeagueTable key="ucl" table={ucl} title={t('Лига чемпионов')} />}
      </>
    );
  }

  // сайт на компьютере: ближайшие и результаты слева, таблицы справа — всё сразу, без вкладок раздела
  if (desktop) {
    return (
      <main className="matches matches--desk">
        <header className="topbar">
          <h1 className="topbar__title">{t('Матчи')}</h1>
          <span className="topbar__aside">{aside}</span>
        </header>
        <div className="dk-split dk-split--matches">
          <div className="dk-col">
            <Tabs items={COMP_TABS} value={tab} onChange={onTab} ariaLabel={t('Фильтр турниров')} variant="pill" className="matches__comp" />
            {fixturesBlock}
            {resultsBlock}
          </div>
          <aside className="dk-col" aria-label={t('Турнирные таблицы')}>
            {tablesBlock}
          </aside>
        </div>
      </main>
    );
  }

  return (
    <main className="matches">
      <header className="topbar">
        <h1 className="topbar__title">{t('Матчи')}</h1>
        <span className="topbar__aside">{aside}</span>
      </header>
      <Tabs items={VIEW_TABS} value={view} onChange={setView} ariaLabel={t('Раздел')} />
      <Tabs items={COMP_TABS} value={tab} onChange={onTab} ariaLabel={t('Фильтр турниров')} variant="pill" className="matches__comp" />
      {view === 'tables' ? tablesBlock : fixturesBlock}
    </main>
  );
}
