import { useState } from 'react';
import type { ApiMatch, Side } from '../../api/match';
import { usePlayerLinks } from '../../lib/playerNav';
import { Card, EmptyState, EventIcon, Pitch, PlayerInline, PlayerPhoto, PlayerTap, RatingChip, Tabs, TeamCrest } from '../../ui';
import { lineupView, realSide, teamRef, type Phase } from './view';

const LATER = 'Составы появятся примерно за час до матча';

/** desk — компьютер: поле слева, «Замены» и «Не играли» колонками рядом. */
export function LineupsTab({ match, phase, desk }: { match: ApiMatch; phase: Phase; desk?: boolean }) {
  const rs = realSide(match);
  const [side, setSide] = useState<Side>(rs);
  const before = phase === 'scheduled' || phase === 'postponed';
  const view = lineupView(match, side);
  const both = lineupView(match, side === 'home' ? 'away' : 'home') != null && view != null;
  const links = usePlayerLinks();

  if (!view) {
    return <EmptyState className="mt-state" title={before ? LATER : 'Составов нет'} text={before ? undefined : 'Источник не прислал составы на этот матч'} />;
  }

  const order: Side[] = rs === 'home' ? ['home', 'away'] : ['away', 'home'];
  const finished = phase === 'finished' || phase === 'abandoned';

  const main = (
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
            items={order.map((s) => {
              const t = teamRef(match, s);
              return { id: s, label: match[s].name ?? '', icon: t.id != null ? <TeamCrest id={t.id} name="" size={20} /> : undefined };
            })}
            value={side}
            onChange={setSide}
          />
        ) : (
          <span className="mt-lu-head__team">
            {view.team.id != null && <TeamCrest id={view.team.id} name="" size={20} />}
            <span>{view.team.name}</span>
          </span>
        )}
        {(view.formation || view.avgRating != null) && (
          <div className="mt-lu-head__meta">
            {view.formation && <div className="mt-lu-head__formation">{view.formation}</div>}
            {view.avgRating != null && <div className="mt-muted mt-small">средняя оценка {view.avgRating.toFixed(1)}</div>}
          </div>
        )}
      </div>

      {view.pitch ? (
        <Pitch players={view.pitch} ariaLabel={`Стартовый состав: ${view.team.name}`} {...links} />
      ) : (
        <Card ariaLabel="Стартовый состав">
          <h2 className="mt-h2">Стартовый состав</h2>
          <ul className="mt-list">
            {view.starters.map((p) => (
              <li key={p.key}>
                <PlayerTap player={p} {...links} className="mt-li">
                  <PlayerPhoto id={p.id} name={p.name} size={36} />
                  <div className="mt-li__body">
                    <div className="mt-li__name">
                      {p.number != null && <span className="mt-li__num">{p.number}</span>}
                      {p.name}
                    </div>
                  </div>
                  {p.rating != null && <RatingChip value={p.rating} />}
                </PlayerTap>
              </li>
            ))}
          </ul>
        </Card>
      )}

    </>
  );
  const subs = (
    <>
      {view.subs.length > 0 && (
        <Card ariaLabel="Замены">
          <h2 className="mt-h2">Замены</h2>
          <ul className="mt-list">
            {view.subs.map((p) => (
              <li key={p.key}>
                <PlayerTap player={p} {...links} className="mt-li">
                  <PlayerPhoto id={p.id} name={p.name} size={36} />
                  <div className="mt-li__body">
                    <div className="mt-li__name">
                      {p.number != null && <span className="mt-li__num">{p.number}</span>}
                      {p.name}
                    </div>
                    <div className="mt-li__sub">{p.detail}</div>
                  </div>
                  {p.rating != null ? <RatingChip value={p.rating} /> : p.scored && <EventIcon type="goal" />}
                </PlayerTap>
              </li>
            ))}
          </ul>
          {view.bench.length > 0 && (
            <div className="mt-bench">
              <h3 className="mt-bench__cap">В запасе</h3>
              <ul className="mt-bench__list">
                {view.bench.map((b) => (
                  <li key={b.key}>
                    <PlayerInline player={b} size={24} {...links} className="mt-bench__who" />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      )}

    </>
  );
  const out = (
    <>
      {(view.unavailable.length > 0 || view.coach) && (
        <Card ariaLabel={finished ? 'Не играли' : 'Не сыграют'}>
          {view.unavailable.length > 0 && (
            <>
              <h2 className="mt-h2">{finished ? 'Не играли' : 'Не сыграют'}</h2>
              <ul className="mt-out">
                {view.unavailable.map((u) => (
                  <li key={u.key} className="mt-out__row">
                    <PlayerInline player={u} size={28} {...links} className="mt-out__who" />
                    <span className="mt-muted mt-out__why">{u.reason}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {view.coach && (
            <div className={view.unavailable.length ? 'mt-coach' : 'mt-coach mt-coach--solo'}>
              {/* id тренера — FotMob: фото с нашего сервера; карточки тренера нет — без ссылки */}
              {view.coach.id != null && <PlayerPhoto id={view.coach.id} name={view.coach.name} size={36} />}
              <span className="mt-coach__body">
                <span className="mt-coach__name">{view.coach.name}</span>
                <span className="mt-coach__role">главный тренер</span>
              </span>
            </div>
          )}
        </Card>
      )}
    </>
  );
  if (desk) {
    const n = 1 + (view.subs.length > 0 ? 1 : 0) + (view.unavailable.length > 0 || view.coach ? 1 : 0);
    return (
      <div className={`mt-lu-desk mt-lu-desk--${n}`}>
        <div className="mt-lu-desk__main">{main}</div>
        {view.subs.length > 0 && <div className="mt-lu-desk__col">{subs}</div>}
        {(view.unavailable.length > 0 || view.coach) && <div className="mt-lu-desk__col">{out}</div>}
      </div>
    );
  }

  return (
    <>
      {main}
      {subs}
      {out}
    </>
  );
}
