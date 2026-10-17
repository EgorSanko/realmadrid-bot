import { Fragment, useState } from 'react';
import type { ApiMatch } from '../../api/match';
import { Card, EmptyState, MomentumChart, ShotMap, StatRow, Tabs, TeamCrest } from '../../ui';
import { momentumView, realSide, shortTeam, shotsView, statPeriods, statsView, teamRef, type PeriodKey, type Phase } from './view';

const PERIOD_LABEL: Record<PeriodKey, string> = { all: 'Матч', first_half: '1-й тайм', second_half: '2-й тайм' };

export function StatsTab({ match, phase }: { match: ApiMatch; phase: Phase }) {
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

  const shotCard = shots && (
    <Card ariaLabel="Карта ударов">
      <div className="mt-row">
        <h2 className="mt-h2">{rs === 'home' && match.home.id !== 8633 && match.away.id !== 8633 ? `Удары: ${shots.team}` : 'Удары Реала'}</h2>
        <span className="mt-muted mt-small">{shots.summary}</span>
      </div>
      <ShotMap shots={shots.shots} ariaLabel={`Карта ударов: ${shots.team} по воротам ${shots.opponent}`} />
    </Card>
  );

  if (!mom && !groups.length && !shots) {
    const before = phase === 'scheduled' || phase === 'postponed' || phase === 'cancelled';
    return <EmptyState className="mt-state" title={before ? 'Статистика появится по ходу матча' : 'Статистики пока нет'} />;
  }

  return (
    <>
      {mom && (
        <Card ariaLabel="Давление по ходу матча">
          <div className="mt-row">
            <h2 className="mt-h2">Давление</h2>
            <span className="mt-muted mt-small">{mom.caption}</span>
          </div>
          <MomentumChart data={mom.data} homeColor={mom.homeColor} awayColor={mom.awayColor} ticks={mom.ticks} />
        </Card>
      )}

      {groups.map((g, gi) => (
        <Fragment key={g.title}>
        <Card ariaLabel={g.title === 'Главное' ? 'Статистика' : g.title}>
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
        {/* как в макете: карта ударов сразу после «Главного», подробности — ниже */}
        {gi === 0 && shotCard}
        </Fragment>
      ))}
      {groups.length === 0 && shotCard}
    </>
  );
}
