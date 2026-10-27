import { useMemo } from 'react';
import { useNavigate } from 'react-router';
import type { ApiFixtures } from '../../lib/api';
import { splitFixtures } from '../../lib/mapMatches';
import { useSpaLink } from '../../lib/spaLink';
import { t } from '../../lib/i18n';
import { usePoll } from '../../lib/usePoll';
import { SectionHeader, Skeleton } from '../../ui';
import { MatchRow } from '../../ui/matchExtra';

/** Последние сыгранные матчи для главной (по просьбе владельца — не один, а три):
 *  эмблемы, счёт напротив команд, логотип турнира, В/Н/П; «Все» → вкладка «Результаты». */
export function RecentResults({ limit = 3 }: { limit?: number }) {
  const fx = usePoll<ApiFixtures>('/api/fixtures', () => 5 * 60_000);
  const link = useSpaLink();
  const navigate = useNavigate();
  const rows = useMemo(() => (fx.data ? splitFixtures(fx.data.matches, 'all').results.slice(0, limit) : []), [fx.data, limit]);

  if (!fx.data && fx.loading) {
    return (
      <section className="ui-card" aria-label={t('Последние матчи')}>
        <SectionHeader title={t('Последние матчи')} />
        <Skeleton shape="list" rows={limit} />
      </section>
    );
  }
  if (!rows.length) return null;
  return (
    <section className="ui-card" aria-label={t('Последние матчи')}>
      <SectionHeader title={t('Последние матчи')} actionLabel={t('Все')} onAction={() => navigate('/matches?view=results')} />
      <div className="screen-list">
        {rows.map((m) => (
          <MatchRow key={m.id} kind="result" {...m} {...link(m.href)} />
        ))}
      </div>
    </section>
  );
}
