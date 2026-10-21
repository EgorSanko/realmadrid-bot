import { Fragment, useState, type CSSProperties } from 'react';
import type { ApiMatch, ApiZone } from '../../api/match';
import { Card, EmptyState, MomentumChart, ShotMap, StatRow, Tabs, TeamCrest, useInViewOnce } from '../../ui';
import { cx } from '../../ui/format';
import { zoneHeat, zonesView, type ZonesView } from './info';
import { momentumView, realSide, shortTeam, shotsView, statPeriods, statsView, teamRef, type PeriodKey, type Phase } from './view';
import './info.css';

const PERIOD_LABEL: Record<PeriodKey, string> = { all: 'Матч', first_half: '1-й тайм', second_half: '2-й тайм' };

/** desk — компьютер: группы показателей в две колонки слева, давление, удары и зоны — колонкой справа. */
export function StatsTab({ match, phase, desk }: { match: ApiMatch; phase: Phase; desk?: boolean }) {
  const periods = statPeriods(match);
  const [period, setPeriod] = useState<PeriodKey>('all');
  const p = periods.includes(period) ? period : 'all';
  const groups = periods.length ? statsView(match, p) : [];
  const mom = momentumView(match);
  const rs = realSide(match);
  const shots = shotsView(match, rs);
  const accent = rs;
  const home = teamRef(match, 'home');
  const away = teamRef(match, 'away');
  const zones = zonesView(match, p);

  const shotCard = shots && (
    <Card ariaLabel="Карта ударов">
      <div className="mt-row">
        <h2 className="mt-h2">{rs === 'home' && match.home.id !== 8633 && match.away.id !== 8633 ? `Удары: ${shots.team}` : 'Удары Реала'}</h2>
        <span className="mt-muted mt-small">{shots.summary}</span>
      </div>
      <ShotMap shots={shots.shots} ariaLabel={`Карта ударов: ${shots.team} по воротам ${shots.opponent}`} />
    </Card>
  );

  if (!mom && !groups.length && !shots && !zones) {
    const before = phase === 'scheduled' || phase === 'postponed' || phase === 'cancelled';
    return <EmptyState className="mt-state" title={before ? 'Статистика появится по ходу матча' : 'Статистики пока нет'} />;
  }

  const momCard = mom && (
    <Card ariaLabel="Давление по ходу матча">
      <div className="mt-row">
        <h2 className="mt-h2">Давление</h2>
        <span className="mt-muted mt-small">{mom.caption}</span>
      </div>
      <MomentumChart data={mom.data} homeColor={mom.homeColor} awayColor={mom.awayColor} ticks={mom.ticks} />
    </Card>
  );
  const groupCard = (g: (typeof groups)[number], gi: number) => (
    <Card key={g.title} ariaLabel={g.title === 'Главное' ? 'Статистика' : g.title}>
      <div className="mt-row">
        <span className="mt-muted mt-small mt-team mt-team--crest">
          {home.id != null && <TeamCrest id={home.id} name="" size={20} />}
          <span>{shortTeam(match.home.name)}</span>
        </span>
        <h2 className="mt-h2">{g.title}</h2>
        <span className="mt-muted mt-small mt-team mt-team--r mt-team--crest">
          <span>{shortTeam(match.away.name)}</span>
          {away.id != null && <TeamCrest id={away.id} name="" size={20} />}
        </span>
      </div>
      {gi === 0 && periods.length > 1 && (
        <Tabs
          variant="outline"
          ariaLabel="Период"
          className="mt-periods"
          items={periods.map((id) => ({ id, label: PERIOD_LABEL[id] }))}
          value={p}
          onChange={setPeriod}
        />
      )}
      <div className="mt-stats">
        {g.rows.map((r) => (
          <StatRow
            key={r.key}
            label={r.label}
            home={r.home}
            away={r.away}
            homeValue={r.homeValue}
            awayValue={r.awayValue}
            better={r.better}
            bar={r.bar}
            accent={accent}
          />
        ))}
      </div>
    </Card>
  );
  const zonesCard = zones && <ZonesCard match={match} zones={zones} />;

  if (desk) {
    const side = momCard || shotCard || zonesCard;
    return (
      <div className={side && groups.length ? 'mt-sg' : 'mt-sg mt-sg--one'}>
        {groups.length > 0 && <div className="mt-sg__groups">{groups.map(groupCard)}</div>}
        {side && (
          <div className="mt-sg__side">
            {momCard}
            {shotCard}
            {zonesCard}
          </div>
        )}
      </div>
    );
  }

  return (
    <>
      {momCard}
      {groups.map((g, gi) => (
        <Fragment key={g.title}>
          {groupCard(g, gi)}
          {/* как в макете: карта ударов сразу после «Главного», подробности — ниже */}
          {gi === 0 && shotCard}
        </Fragment>
      ))}
      {groups.length === 0 && shotCard}
      {zonesCard}
    </>
  );
}

const LANES: Array<[keyof ApiZone, string]> = [
  ['left', 'левый'],
  ['center', 'центр'],
  ['right', 'правый'],
];

/** Зоны атак: у каждой команды — половина поля (атака вверх), три фланга с долей атак; горячая зона — золото. */
function ZonesCard({ match, zones }: { match: ApiMatch; zones: ZonesView }) {
  const [ref, seen] = useInViewOnce<HTMLDivElement>(0.4);
  const side = (s: 'home' | 'away') => {
    const t = teamRef(match, s);
    const z = zones[s];
    return (
      <div key={s} className="mz-side">
        <div className="mz-team">
          {t.id != null && <TeamCrest id={t.id} name="" size={20} />}
          <span>{shortTeam(match[s].name)}</span>
        </div>
        <div className="mz-pitch" role="img" aria-label={`${t.name}: левый фланг ${z.left}%, центр ${z.center}%, правый фланг ${z.right}%`}>
          {LANES.map(([k, label], i) => (
            <div key={k} className={cx('mz-lane', zones.hot[s] === k && 'is-hot')}>
              <span className="mz-lane__heat" style={{ opacity: zoneHeat(z[k]), '--d': `${(s === 'away' ? 3 : 0) * 60 + i * 60}ms` } as CSSProperties} />
              <span className="mz-lane__pct">{z[k]}%</span>
              <span className="mz-lane__lbl">{label}</span>
            </div>
          ))}
          <svg className="mz-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M12 19V5M6 11l6-6 6 6" />
          </svg>
        </div>
      </div>
    );
  };
  return (
    <Card ariaLabel="Зоны атак">
      <h2 className="mt-h2">Зоны атак</h2>
      <div ref={ref} className={cx('mz-pitches', 'mo-reveal', seen && 'is-in')}>
        {side('home')}
        {side('away')}
      </div>
      <p className="mz-note">Доля атак по флангам, направление — вверх</p>
    </Card>
  );
}

const KEY_STATS = ['possession', 'xg', 'shots_total', 'shots_on_target', 'big_chances', 'corners'];

/** Обзор на компьютере: 4–6 главных показателей с полосами и ссылка на вкладку «Статистика». */
export function KeyStats({ match, onAll }: { match: ApiMatch; onAll?: () => void }) {
  if (!statPeriods(match).length) return null;
  const by = new Map(statsView(match, 'all').flatMap((g) => g.rows.map((r) => [r.key, r] as const)));
  const rows = KEY_STATS.map((k) => by.get(k)).filter((r) => r != null);
  if (rows.length < 3) return null;
  const home = teamRef(match, 'home');
  const away = teamRef(match, 'away');
  return (
    <Card ariaLabel="Главные показатели" className="mt-keystats">
      <div className="mt-row">
        <span className="mt-muted mt-small mt-team mt-team--crest">
          {home.id != null && <TeamCrest id={home.id} name="" size={20} />}
          <span>{shortTeam(match.home.name)}</span>
        </span>
        <h2 className="mt-h2">Статистика</h2>
        <span className="mt-muted mt-small mt-team mt-team--r mt-team--crest">
          <span>{shortTeam(match.away.name)}</span>
          {away.id != null && <TeamCrest id={away.id} name="" size={20} />}
        </span>
      </div>
      <div className="mt-stats">
        {rows.map((r) => (
          <StatRow key={r.key} label={r.label} home={r.home} away={r.away} homeValue={r.homeValue} awayValue={r.awayValue} better={r.better} bar accent={realSide(match)} />
        ))}
      </div>
      {onAll && (
        <button type="button" className="mt-more" onClick={onAll}>
          Вся статистика
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </button>
      )}
    </Card>
  );
}
