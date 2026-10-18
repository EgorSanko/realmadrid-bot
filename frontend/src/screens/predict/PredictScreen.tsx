import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent, RefObject } from 'react';
import { GamesTabs } from '../../components/GamesTabs';
import { LoginButton } from '../../components/LoginButton';
import { useDesktop } from '../../lib/shell';
import { AuthFetchError, BOT_USERNAME, authFetch, inMiniApp, useAuth } from '../../lib/auth';
import { EXACT_SEEN_KEY, RULE_LINES, boardView, exactToCelebrate, historyItem, predictError, summaryTiles } from '../../lib/predict';
import { reducedMotion } from '../../lib/motion';
import type { HistoryItem, Leaderboard, MeHistoryEntry } from '../../lib/predict';
import type { League, PredictMe } from '../../lib/profile';
import { copyText, shareLink } from '../../lib/share';
import { inviteLink } from '../../lib/startParam';
import { useSpaLink } from '../../lib/spaLink';
import {
  CountUp,
  EmptyState,
  ErrorState,
  LeaderboardRow,
  PlayerPhoto,
  Skeleton,
  Tabs,
  TeamCrest,
  formatDayShort,
  plural,
} from '../../ui';
import { PredictForm } from './PredictForm';
import { useAuthedGet, usePredictMatches } from './usePredict';
import type { Load } from './usePredict';
import './predict.css';

type BoardTab = 'season' | 'month' | 'leagues';

/** сколько строк рейтинга показываем; меня ниже топа — отдельной строкой */
const TOP = 10;

function loadError<T>(s: Load<T>): string | null {
  if (s.kind !== 'error') return null;
  return predictError(s.status, s.code, s.message).message;
}

export default function PredictScreen() {
  const auth = useAuth();
  const authed = auth.status === 'user';
  const matches = usePredictMatches();
  const [meVer, setMeVer] = useState(0);
  const [leaguesVer, setLeaguesVer] = useState(0);
  const [me, reloadMe] = useAuthedGet<PredictMe>(authed ? '/api/predict/me' : null, [meVer]);
  const [leagues, reloadLeagues] = useAuthedGet<{ leagues: League[] }>(authed ? '/api/predict/leagues' : null, [leaguesVer]);

  useEffect(() => {
    document.title = 'Прогнозы на матчи «Реала» — Мадридиста';
  }, []);

  const meData = authed && me.kind === 'ok' ? me.data : null;
  const season = meData?.season.label;
  const desktop = useDesktop();

  // сайт на компьютере: ввод прогноза и свои итоги слева, рейтинг и лиги справа
  if (desktop) {
    return (
      <main className="pd pd--desk">
        <header className="topbar pd-top">
          <h1 className="topbar__title">Игры</h1>
          {season && <span className="pd-top__aside">прогнозы · сезон {season}</span>}
        </header>
        <GamesTabs />
        <div className="dk-split pd-desk">
          <div className="dk-col">
      {/* Мои итоги / вход */}
      {authed ? (
        me.kind === 'ok' ? (
          <section className="pd-tiles" aria-label="Мои итоги">
            {summaryTiles(me.data.season).map((t) => (
              <div key={t.label} className="pd-tile">
                <span className="pd-tile__label">{t.label}</span>
                <TileValue value={t.value} gold={t.gold} />
              </div>
            ))}
          </section>
        ) : me.kind === 'error' ? null : (
          <div className="pd-tiles" aria-hidden="true">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} height={82} radius={18} />
            ))}
          </div>
        )
      ) : (
        <section className="ui-card pd-anon" aria-label="Вход">
          <p className="pd-anon__title">Угадывай счёт матчей Реала</p>
          <p className="pd-muted">Очки, место в рейтинге и лиги с друзьями — после входа через Telegram.</p>
          {auth.status === 'loading' ? null : inMiniApp() ? (
            <p className="pd-muted">Входим через Telegram…</p>
          ) : matches.state.kind === 'ok' && matches.state.data.next?.accepting ? null : (
            // есть открытый матч — кнопка входа в его карточке, рядом со «Сохранить»; иначе — здесь
            <LoginButton />
          )}
        </section>
      )}

      {/* Ближайший открытый матч */}
      {matches.state.kind === 'loading' ? (
        <Skeleton height={420} radius={22} className="pd-skel" />
      ) : matches.state.kind === 'error' ? (
        <ErrorState className="pd-state" text={loadError(matches.state) ?? undefined} onRetry={matches.reload} />
      ) : matches.state.data.next ? (
        <PredictForm
          match={matches.state.data.next}
          onSaved={(p) => {
            matches.setMyPrediction(p);
            setMeVer((v) => v + 1);
          }}
          onClosed={matches.reload}
        />
      ) : (
        <EmptyState className="pd-state" title="Ближайших матчей нет" text="Прогноз можно будет сделать, как только появится расписание" />
      )}

      {authed && <MyPredictions me={me} onRetry={reloadMe} />}

      {/* Правила */}
      <section className="ui-card pd-rules" aria-label="Как начисляются очки">
        <h2 className="pd-h2">Очки</h2>
        {RULE_LINES.map((r) => (
          <div key={r.label} className="pd-rule">
            <span>{r.label}</span>
            <b className={r.gold ? 'is-gold' : undefined}>+{r.points}</b>
          </div>
        ))}
        <p className="pd-rules__note">
          За счёт засчитывается лучшее из трёх; бомбардир — сверху. Счёт — после основного и дополнительного времени, без серии пенальти.
          Автогол соперника автором первого гола не считается.
        </p>
      </section>

          </div>
          <aside className="dk-col" aria-label="Рейтинг и лиги">
      <Board authed={authed} leagues={leagues} myName={auth.user?.name ?? 'Ты'} myAvatar={auth.user?.avatar ?? null} />

      <Invite
        authed={authed}
        leagues={leagues}
        onRetry={reloadLeagues}
        onCreated={() => {
          setLeaguesVer((v) => v + 1);
        }}
      />
          </aside>
        </div>
      </main>
    );
  }

  return (
    <main className="pd">
      <header className="topbar pd-top">
        <h1 className="topbar__title">Игры</h1>
        {season && <span className="pd-top__aside">прогнозы · сезон {season}</span>}
      </header>
      <GamesTabs />

      {/* Мои итоги / вход */}
      {authed ? (
        me.kind === 'ok' ? (
          <section className="pd-tiles" aria-label="Мои итоги">
            {summaryTiles(me.data.season).map((t) => (
              <div key={t.label} className="pd-tile">
                <span className="pd-tile__label">{t.label}</span>
                <TileValue value={t.value} gold={t.gold} />
              </div>
            ))}
          </section>
        ) : me.kind === 'error' ? null : (
          <div className="pd-tiles" aria-hidden="true">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} height={82} radius={18} />
            ))}
          </div>
        )
      ) : (
        <section className="ui-card pd-anon" aria-label="Вход">
          <p className="pd-anon__title">Угадывай счёт матчей Реала</p>
          <p className="pd-muted">Очки, место в рейтинге и лиги с друзьями — после входа через Telegram.</p>
          {auth.status === 'loading' ? null : inMiniApp() ? (
            <p className="pd-muted">Входим через Telegram…</p>
          ) : matches.state.kind === 'ok' && matches.state.data.next?.accepting ? null : (
            // есть открытый матч — кнопка входа в его карточке, рядом со «Сохранить»; иначе — здесь
            <LoginButton />
          )}
        </section>
      )}

      {/* Ближайший открытый матч */}
      {matches.state.kind === 'loading' ? (
        <Skeleton height={420} radius={22} className="pd-skel" />
      ) : matches.state.kind === 'error' ? (
        <ErrorState className="pd-state" text={loadError(matches.state) ?? undefined} onRetry={matches.reload} />
      ) : matches.state.data.next ? (
        <PredictForm
          match={matches.state.data.next}
          onSaved={(p) => {
            matches.setMyPrediction(p);
            setMeVer((v) => v + 1);
          }}
          onClosed={matches.reload}
        />
      ) : (
        <EmptyState className="pd-state" title="Ближайших матчей нет" text="Прогноз можно будет сделать, как только появится расписание" />
      )}

      {/* Правила */}
      <section className="ui-card pd-rules" aria-label="Как начисляются очки">
        <h2 className="pd-h2">Очки</h2>
        {RULE_LINES.map((r) => (
          <div key={r.label} className="pd-rule">
            <span>{r.label}</span>
            <b className={r.gold ? 'is-gold' : undefined}>+{r.points}</b>
          </div>
        ))}
        <p className="pd-rules__note">
          За счёт засчитывается лучшее из трёх; бомбардир — сверху. Счёт — после основного и дополнительного времени, без серии пенальти.
          Автогол соперника автором первого гола не считается.
        </p>
      </section>

      <Board authed={authed} leagues={leagues} myName={auth.user?.name ?? 'Ты'} myAvatar={auth.user?.avatar ?? null} />

      {authed && <MyPredictions me={me} onRetry={reloadMe} />}

      <Invite
        authed={authed}
        leagues={leagues}
        onRetry={reloadLeagues}
        onCreated={() => {
          setLeaguesVer((v) => v + 1);
        }}
      />
    </main>
  );
}

/* ---------- рейтинг ---------- */

function Board({
  authed,
  leagues,
  myName,
  myAvatar,
}: {
  authed: boolean;
  leagues: Load<{ leagues: League[] }>;
  myName: string;
  myAvatar: string | null;
}) {
  const [tab, setTab] = useState<BoardTab>('season');
  const list = authed && leagues.kind === 'ok' ? leagues.data.leagues : [];
  const [leagueId, setLeagueId] = useState<number | null>(null);
  const lid = leagueId != null && list.some((l) => l.id === leagueId) ? leagueId : list[0]?.id ?? null;
  const path =
    tab === 'season'
      ? `/api/predict/leaderboard?period=season&limit=${TOP}`
      : tab === 'month'
        ? `/api/predict/leaderboard?period=month&limit=${TOP}`
        : lid != null
          ? `/api/predict/leaderboard?period=season&league=${lid}&limit=${TOP}`
          : null;
  const [lb, reload] = useAuthedGet<Leaderboard>(path);
  const view = useMemo(() => (lb.kind === 'ok' ? boardView(lb.data, myName, myAvatar) : null), [lb, myName, myAvatar]);
  // при смене вкладки старый ответ ещё на экране, пока не пришёл новый — его не показываем
  const stale =
    lb.kind === 'ok' && (tab === 'leagues' ? lb.data.league?.id !== lid : lb.data.league != null || lb.data.period !== tab);

  let body;
  if (tab === 'leagues' && !authed) {
    body = <p className="pd-muted pd-board__msg">Лиги видны после входа через Telegram.</p>;
  } else if (tab === 'leagues' && leagues.kind === 'ok' && list.length === 0) {
    body = <p className="pd-muted pd-board__msg">Вы пока не в лиге — создайте свою ниже и позовите друзей.</p>;
  } else if (lb.kind === 'loading' || stale || (tab === 'leagues' && lid == null)) {
    body = <Skeleton shape="list" rows={4} />;
  } else if (lb.kind === 'error') {
    body = <ErrorState plain text={loadError(lb) ?? undefined} onRetry={reload} />;
  } else if (view && view.empty) {
    body = <p className="pd-muted pd-board__msg">Пока пусто: очки появятся после первого сыгранного матча.</p>;
  } else if (view) {
    body = (
      <div className="pd-board__rows">
        {view.rows.map((r) => (
          <LeaderboardRow
            key={`${r.rank}-${r.name}`}
            rank={r.rank}
            name={r.is_me ? `${r.name} · ты` : r.name}
            points={r.points}
            avatarUrl={r.avatar ?? undefined}
            isMe={r.is_me}
            silhouette
          />
        ))}
        {view.meRow && (
          <LeaderboardRow
            rank={view.meRow.rank}
            name={`${view.meRow.name} · ты`}
            points={view.meRow.points}
            avatarUrl={view.meRow.avatar ?? undefined}
            isMe
            silhouette
            className="pd-board__me"
          />
        )}
      </div>
    );
  }

  return (
    <section className="ui-card pd-board" aria-label="Рейтинг">
      <div className="pd-board__head">
        <h2 className="pd-h2">Рейтинг</h2>
        {lb.kind === 'ok' && !stale && (
          <span className="pd-muted">
            {lb.data.total} {plural(lb.data.total, ['участник', 'участника', 'участников'])}
          </span>
        )}
      </div>
      <Tabs<BoardTab>
        ariaLabel="Период рейтинга"
        inset={false}
        className="pd-board__tabs"
        value={tab}
        onChange={setTab}
        items={[
          { id: 'season', label: 'Сезон' },
          { id: 'month', label: 'Месяц' },
          { id: 'leagues', label: 'Лиги' },
        ]}
      />
      {tab === 'leagues' && list.length > 0 && (
        <Tabs<string>
          ariaLabel="Моя лига"
          variant="pill"
          className="pd-board__leagues"
          value={String(lid)}
          onChange={(id) => setLeagueId(Number(id))}
          items={list.map((l) => ({ id: String(l.id), label: l.name }))}
        />
      )}
      {body}
    </section>
  );
}

/* ---------- итоги ---------- */

/** Число плитки отсчитывается от нуля при появлении и к новому значению при изменении. */
function TileValue({ value, gold }: { value: string; gold?: boolean }) {
  const n = Number(value);
  const cls = `pd-tile__value${gold ? ' is-gold' : ''}`;
  return /^\d+$/.test(value) ? <CountUp value={n} fromZero className={cls} /> : <span className={cls}>{value}</span>;
}

/* ---------- мои прогнозы ---------- */

function readSeen(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(EXACT_SEEN_KEY) || '[]');
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

/**
 * Угаданный точный счёт — праздник один раз: когда строка впервые попадает на экран, по ней проходит
 * золотой блик, «+5» впечатывается, из него бьёт конфетти. Показанные — в localStorage (rmExactSeen).
 */
function useExactCelebration(items: HistoryItem[], list: RefObject<HTMLUListElement | null>) {
  useEffect(() => {
    const ids = exactToCelebrate(items, readSeen());
    const root = list.current;
    if (!ids.length || !root || typeof IntersectionObserver !== 'function') return;
    const rows = ids.map((id) => root.querySelector<HTMLElement>(`li[data-mid="${CSS.escape(id)}"]`)).filter((x): x is HTMLElement => !!x);
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          io.unobserve(e.target);
          const li = e.target as HTMLElement;
          const id = li.dataset.mid!;
          try {
            localStorage.setItem(EXACT_SEEN_KEY, JSON.stringify([...readSeen(), id].slice(-100)));
          } catch {
            /* приватный режим */
          }
          if (reducedMotion()) continue;
          li.classList.add('is-exact-new');
          {
            const host = document.createElement('i');
            host.className = 'pd-hist__burst';
            li.appendChild(host);
            void import('../../lib/confetti').then(({ burst }) =>
              burst(host, { count: 22, delay: 180, spread: 80, speed: [240, 460], duration: [900, 1250], gravity: 900, jitter: 8 }).then(() => host.remove()),
            );
          }
        }
      },
      { threshold: 0.9 },
    );
    rows.forEach((r) => io.observe(r));
    return () => io.disconnect();
  }, [items, list]);
}

function MyPredictions({ me, onRetry }: { me: Load<PredictMe>; onRetry: () => void }) {
  const link = useSpaLink();
  const items = useMemo(
    () => (me.kind === 'ok' ? (me.data.history as unknown as MeHistoryEntry[]).slice(0, 10).map(historyItem) : []),
    [me],
  );
  const list = useRef<HTMLUListElement>(null);
  useExactCelebration(items, list);
  return (
    <section className="ui-card pd-mine" aria-label="Мои прогнозы">
      <h2 className="pd-h2">Мои прогнозы</h2>
      {me.kind === 'loading' ? (
        <Skeleton shape="list" rows={3} />
      ) : me.kind === 'error' ? (
        <ErrorState plain text={loadError(me) ?? undefined} onRetry={onRetry} />
      ) : items.length === 0 ? (
        <p className="pd-muted">Прогнозов пока нет — начни с ближайшего матча.</p>
      ) : (
        <ul className="pd-hist" ref={list}>
          {items.map((h) => (
            <li key={h.id} data-mid={h.id}>
              <a className="pd-hist__row" {...link(`/match/${encodeURIComponent(h.id)}`)}>
                <span className="pd-hist__date">{formatDayShort(h.kickoff)}</span>
                <span className="pd-hist__teams">
                  {h.home.id != null ? <TeamCrest id={h.home.id} name={h.home.name} size={28} /> : <span className="pd-hist__ph" />}
                  <span className="pd-hist__score">
                    <b aria-label={`Мой прогноз ${h.pick}`}>{h.pick}</b>
                    <span className="pd-hist__res">{h.result ? `итог ${h.result}` : 'итог —'}</span>
                  </span>
                  {h.away.id != null ? <TeamCrest id={h.away.id} name={h.away.name} size={28} /> : <span className="pd-hist__ph" />}
                </span>
                <span className="pd-hist__note">
                  {h.scorerPick && <PlayerPhoto id={Number(h.scorerPick)} name="Мой бомбардир" size={22} className="pd-hist__sc" />}
                  {h.note}
                </span>
                <span className={`pd-hist__pts pd-hist__pts--${h.tone}`}>{h.points != null ? `+${h.points}` : '·'}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/* ---------- лиги: создать и позвать друга ---------- */

function Invite({
  authed,
  leagues,
  onRetry,
  onCreated,
}: {
  authed: boolean;
  leagues: Load<{ leagues: League[] }>;
  onRetry: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fresh, setFresh] = useState<League | null>(null);
  const own = authed && leagues.kind === 'ok' ? leagues.data.leagues.filter((l) => l.is_owner) : [];
  const shown = fresh && !own.some((l) => l.id === fresh.id) ? [fresh, ...own] : own;

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const lg = await authFetch<League>('/api/predict/leagues', { method: 'POST', body: { name } });
      setFresh(lg);
      setName('');
      onCreated();
    } catch (ex) {
      const fe = ex instanceof AuthFetchError ? ex : new AuthFetchError(0, null, '');
      setErr(fe.status === 409 || fe.status === 422 ? fe.message : predictError(fe.status, fe.code, fe.message).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="ui-card pd-invite" aria-label="Позвать друга в лигу">
      <h2 className="pd-h2">Позвать друга в лигу</h2>
      <p className="pd-muted">Своя лига — отдельный рейтинг для друзей. Друг откроет ссылку в Telegram и сразу окажется в лиге.</p>
      {!authed ? (
        <p className="pd-muted pd-invite__anon">Создать лигу можно после входа через Telegram.</p>
      ) : (
        <>
          {leagues.kind === 'error' && <ErrorState plain text={loadError(leagues) ?? undefined} onRetry={onRetry} />}
          {shown.map((lg) => (
            <InviteRow key={lg.id} lg={lg} />
          ))}
          <form className="pd-invite__form" onSubmit={create}>
            <label className="ui-sr" htmlFor="pd-league-name">
              Название лиги
            </label>
            <input
              id="pd-league-name"
              className="pd-input"
              value={name}
              maxLength={40}
              placeholder={shown.length ? 'Ещё одна лига, например «Офис»' : 'Название, например «Пенья Бернабеу»'}
              onChange={(e) => setName(e.target.value)}
            />
            <button type="submit" className="ui-btn ui-btn--outline pd-invite__btn" disabled={busy || !name.trim()}>
              {busy ? 'Создаём…' : 'Создать лигу'}
            </button>
          </form>
          {err && (
            <p className="pd-msg pd-msg--err" role="alert">
              {err}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function InviteRow({ lg }: { lg: League }) {
  const url = inviteLink(lg.code, lg.invite_link, BOT_USERNAME);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (!msg) return;
    const t = window.setTimeout(() => setMsg(null), 2500);
    return () => window.clearTimeout(t);
  }, [msg]);
  return (
    <div className="pd-league">
      <div className="pd-league__head">
        <b>{lg.name}</b>
        <span className="pd-muted">
          {lg.members} {plural(lg.members, ['участник', 'участника', 'участников'])}
        </span>
      </div>
      <p className="pd-league__link" title={url}>
        {url}
      </p>
      <div className="pd-league__actions">
        <button
          type="button"
          className="ui-btn ui-btn--secondary"
          onClick={async () => setMsg((await copyText(url)) ? 'Ссылка скопирована' : 'Не удалось скопировать')}
        >
          Скопировать
        </button>
        <button
          type="button"
          className="ui-btn ui-btn--primary pd-league__share"
          onClick={async () => {
            const r = await shareLink(url, `Присоединяйся к моей лиге прогнозов «${lg.name}» в Мадридисте`);
            if (r === 'copied') setMsg('Ссылка скопирована');
            if (r === 'failed') setMsg('Не удалось поделиться');
          }}
        >
          Поделиться
        </button>
      </div>
      {msg && (
        <p className="pd-league__msg" role="status">
          {msg}
        </p>
      )}
    </div>
  );
}
