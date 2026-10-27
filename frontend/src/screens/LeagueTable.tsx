import { useMemo, useState } from 'react';
import type { ApiTable } from '../lib/api';
import { compactRows, roundsAside, standingRows, usRow, zonesFor } from '../lib/mapMatches';
import { t } from '../lib/i18n';
import { useSpaLink } from '../lib/spaLink';
import { SectionHeader, StandingsTable } from '../ui';

export function MoreButton({ open, onToggle, more, less }: { open: boolean; onToggle: () => void; more: string; less: string }) {
  return (
    <button type="button" className="screen-more" aria-expanded={open} onClick={onToggle}>
      {open ? less : more}
    </button>
  );
}

/** Таблица турнира: верх и строки вокруг Реала, «Вся таблица» раскрывает целиком. */
export function LeagueTable({ table, title }: { table: ApiTable; title: string }) {
  const [full, setFull] = useState(false);
  const all = useMemo(() => standingRows(table), [table]);
  const us = usRow(table);
  const { rows, collapsed } = compactRows(all, us?.pos ?? null);
  const shown = full || !collapsed ? all : rows;
  return (
    <section className="ui-card" aria-label={t('Таблица: {title}', { title })}>
      <SectionHeader title={title} aside={roundsAside(table)} />
      <StandingsTable
        rows={shown}
        highlightTeamId={us?.team.id ?? undefined}
        zones={zonesFor(table, shown)}
        rememberKey={`rmTablePos:${table.league.id}`}
      />
      {collapsed && (
        <MoreButton open={full} onToggle={() => setFull((v) => !v)} more={t('Вся таблица')} less={t('Свернуть таблицу')} />
      )}
    </section>
  );
}

/** Сжатая таблица для боковой колонки главной на компьютере: топ-5 и по две строки вокруг Реала. */
export function LeagueTableMini({ table, title }: { table: ApiTable; title: string }) {
  const link = useSpaLink();
  const all = useMemo(() => standingRows(table), [table]);
  const us = usRow(table);
  const { rows } = compactRows(all, us?.pos ?? null, 5, 2);
  return (
    <section className="ui-card dk-table-mini" aria-label={t('Таблица: {title}', { title })}>
      <SectionHeader title={title} aside={roundsAside(table)} />
      <StandingsTable rows={rows} highlightTeamId={us?.team.id ?? undefined} zones={zonesFor(table, rows)} rememberKey={`rmTablePos:${table.league.id}`} />
      <a className="screen-more" {...link('/matches')}>
        {t('Вся таблица и календарь')}
      </a>
    </section>
  );
}
