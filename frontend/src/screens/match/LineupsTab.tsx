import { useState } from 'react';
import type { ApiMatch, Side } from '../../api/match';
import { Card, EmptyState, EventIcon, Pitch, PlayerPhoto, RatingChip, Tabs } from '../../ui';
import { lineupView, realSide, type Phase } from './view';

const LATER = 'Составы появятся примерно за час до матча';

export function LineupsTab({ match, phase }: { match: ApiMatch; phase: Phase }) {
  const rs = realSide(match);
  const [side, setSide] = useState<Side>(rs);
  const before = phase === 'scheduled' || phase === 'postponed';
  const view = lineupView(match, side);
  const both = lineupView(match, side === 'home' ? 'away' : 'home') != null && view != null;

  if (!view) {
    return <EmptyState className="mt-state" title={before ? LATER : 'Составов нет'} text={before ? undefined : 'Источник не прислал составы на этот матч'} />;
  }

  const order: Side[] = rs === 'home' ? ['home', 'away'] : ['away', 'home'];
  const finished = phase === 'finished' || phase === 'abandoned';

  return (
    <>
      {!view.confirmed && (
        <section className="ui-card mt-note" aria-label="Составы">
          <p className="mt-note__title">{LATER}</p>
          <p className="mt-note__text">Пока — ожидаемый состав</p>
        </section>
      )}

      <div className="mt-lu-head">
        {both ? (
          <Tabs
            variant="pill"
            ariaLabel="Команда"
            items={order.map((s) => ({ id: s, label: match[s].name ?? '' }))}
            value={side}
            onChange={setSide}
          />
        ) : (
          <span className="mt-lu-head__team">{view.team.name}</span>
        )}
        {(view.formation || view.avgRating != null) && (
          <div className="mt-lu-head__meta">
            {view.formation && <div className="mt-lu-head__formation">{view.formation}</div>}
            {view.avgRating != null && <div className="mt-muted mt-small">средняя оценка {view.avgRating.toFixed(1)}</div>}
          </div>
        )}
      </div>

      {view.pitch ? (
        <Pitch players={view.pitch} ariaLabel={`Стартовый состав: ${view.team.name}`} />
      ) : (
        <Card ariaLabel="Стартовый состав">
          <h2 className="mt-h2">Стартовый состав</h2>
          <ul className="mt-list">
            {view.starters.map((p) => (
              <li key={p.key} className="mt-li">
                <PlayerPhoto id={p.id} name={p.name} size={36} />
                <div className="mt-li__body">
                  <div className="mt-li__name">
                    {p.number != null && <span className="mt-li__num">{p.number}</span>}
                    {p.name}
                  </div>
                </div>
                {p.rating != null && <RatingChip value={p.rating} />}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {view.subs.length > 0 && (
        <Card ariaLabel="Замены">
          <h2 className="mt-h2">Замены</h2>
          <ul className="mt-list">
            {view.subs.map((p) => (
              <li key={p.key} className="mt-li">
                <PlayerPhoto id={p.id} name={p.name} size={36} />
                <div className="mt-li__body">
                  <div className="mt-li__name">
                    {p.number != null && <span className="mt-li__num">{p.number}</span>}
                    {p.name}
                  </div>
                  <div className="mt-li__sub">{p.detail}</div>
                </div>
                {p.rating != null ? <RatingChip value={p.rating} /> : p.scored && <EventIcon type="goal" />}
              </li>
            ))}
          </ul>
          {view.bench.length > 0 && <p className="mt-bench">В запасе: {view.bench.join(', ')}</p>}
        </Card>
      )}

      {(view.unavailable.length > 0 || view.coach) && (
        <Card ariaLabel={finished ? 'Не играли' : 'Не сыграют'}>
          {view.unavailable.length > 0 && (
            <>
              <h2 className="mt-h2">{finished ? 'Не играли' : 'Не сыграют'}</h2>
              <ul className="mt-out">
                {view.unavailable.map((u) => (
                  <li key={u.key}>
                    <span>{u.name}</span> <span className="mt-muted">· {u.reason}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {view.coach && (
            <p className={view.unavailable.length ? 'mt-coach' : 'mt-coach mt-coach--solo'}>Главный тренер — {view.coach}</p>
          )}
        </Card>
      )}
    </>
  );
}
