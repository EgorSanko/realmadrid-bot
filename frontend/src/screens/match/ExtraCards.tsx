import { useId, useState, type MouseEvent } from 'react';
import type { ApiMatch, ApiRound } from '../../api/match';
import type { MatchesResponse } from '../../lib/predict';
import { useSpaLink } from '../../lib/spaLink';
import { Badge, Card, LeagueLogo, TeamCrest, formatTime, formatWeekdayShort } from '../../ui';
import { cx } from '../../ui/format';
import { useAuthedGet } from '../predict/usePredict';
import { insightsView, pollView, roundRows, roundTitle, roundView, type PollContext, type RoundRowView, type RoundView } from './extras';
import type { Phase } from './view';
import './extras.css';

const REAL_ID = 8633;

/* ---------- «Кто победит?» ---------- */

/** Прогноз пользователя и открыт ли приём — из /api/predict/matches (только до начала матча Реала). */
function usePollContext(match: ApiMatch, before: boolean): PollContext {
  const ours = match.home.id === REAL_ID || match.away.id === REAL_ID;
  const [st] = useAuthedGet<MatchesResponse>(before && ours ? '/api/predict/matches' : null);
  if (st.kind !== 'ok') return {};
  const n = st.data.next;
  if (!n || String(n.id) !== String(match.id)) return {};
  return { accepting: n.accepting, mine: n.my_prediction ? { home: n.my_prediction.home, away: n.my_prediction.away } : null };
}

export function PollCard({ match, phase }: { match: ApiMatch; phase: Phase }) {
  const before = phase === 'scheduled';
  const ctx = usePollContext(match, before);
  const v = pollView(match, before ? ctx : {});
  const link = useSpaLink();
  if (!v) return null;
  const cap = before ? 'до начала матча' : phase === 'finished' ? 'итог опроса' : 'во время матча';
  const head = (side: 'home' | 'away') => {
    const t = match[side];
    return (
      <span className={cx('mp-head', side === 'away' && 'mp-head--r')}>
        {t.logo && t.id != null && <TeamCrest id={t.id} name="" size={20} />}
        <span>{t.name}</span>
      </span>
    );
  };
  return (
    <Card ariaLabel="Кто победит?" className="mp">
      <div className="mt-row">
        <h2 className="mt-h2">Кто победит?</h2>
        <span className="mt-muted mt-small">{cap}</span>
      </div>
      {v.rows.length > 0 && (
        <div className="mp-heads" aria-hidden="true">
          {head('home')}
          <span className="mp-head mp-head--x">Ничья</span>
          {head('away')}
        </div>
      )}
      {v.rows.map((r) => (
        <div key={r.key} className={cx('mp-row', r.key === 'ours' && 'mp-row--ours')}>
          <div className="mp-row__cap">
            <b>{r.label}</b>
            <span>{r.sub}</span>
            {r.key === 'ours' && v.mine && <span className="mp-mine">твой прогноз {v.mine}</span>}
          </div>
          <div
            className="mp-bar"
            role="img"
            aria-label={`${r.label}: победа ${match.home.name} ${r.parts[0].pct}%, ничья ${r.parts[1].pct}%, победа ${match.away.name} ${r.parts[2].pct}%`}
          >
            {r.parts.map((p, i) => (
              <span key={p.k} className={cx('mp-seg', p.leader && 'is-lead')} style={{ flexGrow: Math.max(p.pct, 1), animationDelay: `${i * 70}ms` }}>
                <b>{p.pct}%</b>
              </span>
            ))}
          </div>
        </div>
      ))}
      {(v.need != null || v.cta) && (
        <div className="mp-ours">
          {v.need != null && (
            <p className="mp-ours__text">
              <b>Прогнозы Мадридисты: {v.have > 0 ? `уже ${v.have} из ${v.of}` : `пока ни одного из ${v.of}`}.</b> Как наберётся {v.of} — покажем, за кого болельщики.
            </p>
          )}
          {v.cta && (
            <a className="mp-cta" {...link('/predict')}>
              Сделай прогноз
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M9 6l6 6-6 6" />
              </svg>
            </a>
          )}
        </div>
      )}
      {v.rows.some((r) => r.key === 'fotmob') && <p className="mp-foot">Голоса пользователей FotMob · наш опрос — прогнозы счёта</p>}
    </Card>
  );
}

/* ---------- «Интересные факты» ---------- */

export function InsightsCard({ match, collapsed }: { match: ApiMatch; collapsed?: boolean }) {
  const v = insightsView(match);
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!v) return null;
  const body = (
    <>
      {v.main && (
        <div className="mi-main">
          <span className="mi-main__cap">Главный факт</span>
          <p className="mi-main__text">{v.main}</p>
        </div>
      )}
      {v.teams.map((t) => (
        <div key={t.id ?? t.name} className="mi-team">
          <p className="mi-team__name">
            {t.id != null && <TeamCrest id={t.id} name="" size={20} />}
            <span>{t.name}</span>
          </p>
          <ul className="mi-list">
            {t.items.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      ))}
    </>
  );
  if (collapsed)
    return (
      <section className="ui-card mi-facts mi-facts--fold" aria-label="Интересные факты">
        <button type="button" className="mi-facts__toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
          <span className="mt-h2">Факты к матчу</span>
          <span className="mi-facts__n">{v.count}</span>
          <svg className="mx-chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
        {open && (
          <div id={id} className="mi-facts__body">
            {body}
          </div>
        )}
      </section>
    );
  return (
    <Card ariaLabel="Интересные факты" className="mi-facts">
      <h2 className="mt-h2">Интересные факты</h2>
      {body}
    </Card>
  );
}

/* ---------- «Матчи тура» ---------- */

const ROUND_FOLD = 10;

function RoundRow({ r, href }: { r: RoundRowView; href?: { href: string; onClick: (e?: MouseEvent<HTMLElement>) => void } }) {
  const side = (s: 'home' | 'away') => {
    const t = r[s];
    return (
      <span className={cx('mr-team', t.win && 'is-win')}>
        {t.id != null ? <TeamCrest id={t.id} name="" size={20} /> : <span className="mr-team__gap" />}
        <span className="mr-team__name">{t.name}</span>
        <span className={cx('mr-team__sc', (r.state === 'live' || r.state === 'halftime') && 'is-live')}>{t.score ?? (r.state === 'scheduled' ? '' : '–')}</span>
      </span>
    );
  };
  const status =
    r.state === 'live' || r.state === 'halftime' ? (
      <Badge tone="live" className="mr-live">
        {r.label}
      </Badge>
    ) : r.state === 'scheduled' ? (
      <span className="mr-time">{r.kickoff ? formatTime(r.kickoff) : '—'}</span>
    ) : (
      <span className="mr-done">{r.label}</span>
    );
  const inner = (
    <>
      <span className="mr-teams">
        {side('home')}
        {side('away')}
      </span>
      <span className="mr-st">{status}</span>
    </>
  );
  const cls = cx('mr-row', r.ours && 'is-ours');
  return href ? (
    <a className={cls} {...href} aria-current={r.ours ? 'true' : undefined}>
      {inner}
    </a>
  ) : (
    <div className={cls}>{inner}</div>
  );
}

/** expanded — сразу все матчи тура (вкладка «Турнир» на компьютере). */
export function RoundCard({ match, expanded }: { match: ApiMatch; expanded?: boolean }) {
  const v = roundView(match);
  const link = useSpaLink();
  const [all, setAll] = useState(!!expanded);
  if (!v) return null;
  return <RoundBody v={v} link={link} all={all} onAll={() => setAll(true)} />;
}

function RoundBody({ v, link, all, onAll }: { v: RoundView; link: ReturnType<typeof useSpaLink>; all: boolean; onAll: () => void }) {
  const total = v.days.reduce((n, d) => n + d.rows.length, 0);
  let left = all || total <= ROUND_FOLD + 2 ? Infinity : ROUND_FOLD;
  // в длинном туре (ЛЧ: 18 матчей) наш матч не должен оказаться под «показать все»
  const days = v.days
    .map((d) => {
      const rows = d.rows.filter((r) => {
        if (r.ours) return true;
        if (left <= 0) return false;
        left -= 1;
        return true;
      });
      return { ...d, rows };
    })
    .filter((d) => d.rows.length);
  const shown = days.reduce((n, d) => n + d.rows.length, 0);
  return (
    <Card ariaLabel="Матчи тура" className="mr">
      <div className="mt-row">
        <h2 className="mt-h2 mr-title">
          {v.leagueId != null && <LeagueLogo id={v.leagueId} name="" size={22} />}
          <span>{v.title}</span>
        </h2>
        <span className="mt-muted mt-small">{v.live ? `идёт ${v.live} · ${v.played}` : v.played}</span>
      </div>
      {days.map((d) => (
        <div key={d.key} className="mr-day">
          <p className="mr-day__cap">{d.kickoff ? formatWeekdayShort(d.kickoff) : 'Дата уточняется'}</p>
          {d.rows.map((r) => (
            <RoundRow key={r.key} r={r} href={!r.ours && r.id != null && (r.home.id === REAL_ID || r.away.id === REAL_ID) ? link(`/match/${r.id}`) : undefined} />
          ))}
        </div>
      ))}
      {shown < total && (
        <button type="button" className="mr-more" onClick={onAll}>
          Все матчи тура · {total}
        </button>
      )}
      <p className="mp-foot">Время московское</p>
    </Card>
  );
}

/** Главная во время матча Реала: компактная лента тура — эмблемы и счёт, наш матч первым. */
export function RoundStrip({ round, matchId }: { round: ApiRound; matchId?: number | string | null }) {
  const rows = roundRows(round, matchId);
  if (!rows.length) return null;
  // наш матч, потом идущие, потом последние сыгранные и ближайшие
  const rank = (r: RoundRowView) => (r.ours ? 0 : r.state === 'live' || r.state === 'halftime' ? 1 : r.state === 'finished' ? 2 : 3);
  const list = [...rows].sort((a, b) => rank(a) - rank(b) || (rank(a) === 2 ? (b.kickoff ?? '').localeCompare(a.kickoff ?? '') : 0)).slice(0, 8);
  const finished = rows.filter((r) => r.state === 'finished').length;
  return (
    <section className="ui-card mr-strip" aria-label="Матчи тура">
      <div className="mt-row">
        <h2 className="mr-strip__title">
          {round.league.id != null && <LeagueLogo id={round.league.id} name="" size={18} />}
          <span>{roundTitle(round)}</span>
        </h2>
        <span className="mt-muted mt-small">
          {finished} из {rows.length} сыграно
        </span>
      </div>
      <div className="mr-strip__list">
        {list.map((r) => (
          <div key={r.key} className={cx('mr-mini', r.ours && 'is-ours')}>
            {(['home', 'away'] as const).map((s) => (
              <span key={s} className={cx('mr-mini__t', r[s].win && 'is-win')}>
                {r[s].id != null ? <TeamCrest id={r[s].id!} name={r[s].name} size={20} /> : <span className="mr-team__gap" />}
                <b>{r[s].score ?? ''}</b>
              </span>
            ))}
            <span className={cx('mr-mini__st', (r.state === 'live' || r.state === 'halftime') && 'is-live')}>
              {r.state === 'scheduled' ? (r.kickoff ? formatTime(r.kickoff) : '—') : r.state === 'finished' ? 'FT' : r.label}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
