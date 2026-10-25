import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, FormEvent, RefObject } from 'react';
import { GamesTabs } from '../../components/GamesTabs';
import { LoginButton } from '../../components/LoginButton';
import { useDesktop } from '../../lib/shell';
import { AuthFetchError, BOT_USERNAME, authFetch, inMiniApp, useAuth } from '../../lib/auth';
import {
  EXACT_SEEN_KEY,
  RULE_LINES,
  boardView,
  exactToCelebrate,
  historyItem,
  matchTitle,
  nextLine,
  placeLine,
  predictError,
  summaryTiles,
  waitingPeople,
} from '../../lib/predict';
import { reducedMotion } from '../../lib/motion';
import type { BoardView, HistoryItem, Leaderboard, LeagueHeader, MeHistoryEntry } from '../../lib/predict';
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
  formatKickoff,
  formatWeekdayShort,
  plural,
} from '../../ui';
import { PredictForm } from './PredictForm';
import { useAuthedGet, usePredictMatches } from './usePredict';
import type { Load } from './usePredict';
import { cx } from '../../ui/format';
import './predict.css';

type BoardTab = 'season' | 'month' | 'leagues';

/** рейтинг целиком — все участники (потолок сервера) в окне с прокруткой; себя ищут кнопкой «Найти себя» */
const TOP = 1000;
/** волна появления строк — только у первых, иначе нижние приезжают через несколько секунд */
const WAVE = 15;
/** больше строк — рейтинг прокручивается внутри своего окна, и лиги под ним не уезжают вниз страницы */
const BOX_ROWS = 8;

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
      <Board authed={authed} leagues={leagues} ver={leaguesVer} myName={auth.user?.name ?? 'Ты'} myAvatar={auth.user?.avatar ?? null} />

      <Invite
        authed={authed}
        leagues={leagues}
        onRetry={reloadLeagues}
        onChanged={() => {
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

      <Board authed={authed} leagues={leagues} ver={leaguesVer} myName={auth.user?.name ?? 'Ты'} myAvatar={auth.user?.avatar ?? null} />

      {authed && <MyPredictions me={me} onRetry={reloadMe} />}

      <Invite
        authed={authed}
        leagues={leagues}
        onRetry={reloadLeagues}
        onChanged={() => {
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
  ver,
  myName,
  myAvatar,
}: {
  authed: boolean;
  leagues: Load<{ leagues: League[] }>;
  /** меняется после создания, переименования, удаления лиги — перечитать */
  ver: number;
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
  const [lb, reload] = useAuthedGet<Leaderboard>(path, [ver]);
  const inLeague = tab === 'leagues' && lid != null;
  // шапка лиги: участники и кто уже сделал прогноз на ближайший матч
  const [head, reloadHead] = useAuthedGet<LeagueHeader>(inLeague ? `/api/predict/leagues/${lid}` : null, [ver]);
  const headData = head.kind === 'ok' && head.data.id === lid ? head.data : null;
  const view = useMemo(() => (lb.kind === 'ok' ? boardView(lb.data, myName, myAvatar) : null), [lb, myName, myAvatar]);
  const rowsRef = useRef<HTMLDivElement>(null);
  const meOff = useMeOffscreen(rowsRef, view);
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
  } else if (view && inLeague && !view.started) {
    // у всех 0 сыгранных — не ряды нулей, а с какого матча старт и кто уже готов
    body = headData ? (
      <LeagueStart head={headData} />
    ) : head.kind === 'error' ? (
      <ErrorState plain text={loadError(head) ?? undefined} onRetry={reloadHead} />
    ) : (
      <Skeleton shape="list" rows={2} />
    );
  } else if (view && view.empty) {
    body = <p className="pd-muted pd-board__msg">Пока пусто: очки появятся после первого сыгранного матча.</p>;
  } else if (view) {
    body = (
      <div className={cx('pd-board__rows', view.rows.length > BOX_ROWS && 'pd-board__rows--box')} ref={rowsRef}>
        {view.rows.map((r, i) => (
          <LeaderboardRow
            key={`${r.rank}-${r.name}`}
            rank={r.place}
            name={r.is_me ? `${r.name} · ты` : r.name}
            sub={r.sub}
            points={r.points}
            avatarUrl={r.avatar ?? undefined}
            isMe={r.is_me}
            silhouette
            rankFrom={r.is_me && lb.kind === 'ok' ? lb.data.total : undefined}
            style={{ '--i': Math.min(i, WAVE) } as CSSProperties}
          />
        ))}
        {view.meRow && (
          <LeaderboardRow
            rankFrom={lb.kind === 'ok' ? lb.data.total : undefined}
            style={{ '--i': Math.min(view.rows.length, WAVE) } as CSSProperties}
            rank={view.meRow.place}
            name={`${view.meRow.name} · ты`}
            sub={view.meRow.sub}
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
        {lb.kind === 'ok' && !stale && !inLeague && (
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
      {/* одна лига — её название в шапке, переключатель не нужен */}
      {tab === 'leagues' && list.length > 1 && (
        <Tabs<string>
          ariaLabel="Моя лига"
          variant="pill"
          className="pd-board__leagues"
          value={String(lid)}
          onChange={(id) => setLeagueId(Number(id))}
          items={list.map((l) => ({ id: String(l.id), label: l.name }))}
        />
      )}
      {inLeague && (
        <LeagueHead
          league={list.find((l) => l.id === lid)!}
          head={headData}
          view={view && !stale ? view : null}
          total={lb.kind === 'ok' && !stale ? lb.data.total : null}
        />
      )}
      {body}
      {meOff && view?.myPlace != null && lb.kind === 'ok' && !stale && (
        <button type="button" className="pd-findme" onClick={() => scrollToMe(rowsRef.current)}>
          <span>
            Ты <b>{view.myPlace}-й</b> из {lb.data.total}
          </span>
          <span className="pd-findme__go">
            Найти себя
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </span>
        </button>
      )}
    </section>
  );
}

/** Моя строка рейтинга не видна (в окне рейтинга или на экране) — тогда показываем кнопку «Найти себя». */
function useMeOffscreen(rowsRef: RefObject<HTMLDivElement | null>, view: BoardView | null): boolean {
  const [off, setOff] = useState(false);
  useEffect(() => {
    const row = rowsRef.current?.querySelector('.ui-lb.is-me');
    if (!row || typeof IntersectionObserver === 'undefined') {
      setOff(false);
      return;
    }
    const box = rowsRef.current?.classList.contains('pd-board__rows--box') ? rowsRef.current : null;
    const io = new IntersectionObserver(([e]) => setOff(e.intersectionRatio < 0.9), { root: box, threshold: [0, 0.9] });
    io.observe(row);
    return () => io.disconnect();
  }, [rowsRef, view]);
  return off;
}

/** Прокрутить к своей строке (внутри окна рейтинга, страница остаётся на месте) и коротко подсветить её. */
function scrollToMe(rows: HTMLDivElement | null) {
  const row = rows?.querySelector<HTMLElement>('.ui-lb.is-me');
  if (!rows || !row) return;
  const behavior = reducedMotion() ? 'auto' : 'smooth';
  if (rows.classList.contains('pd-board__rows--box')) {
    rows.scrollTo({ top: row.offsetTop - (rows.clientHeight - row.offsetHeight) / 2, behavior });
  } else {
    row.scrollIntoView({ block: 'center', behavior });
  }
  row.classList.remove('is-found');
  void row.offsetWidth; // перезапуск анимации при повторном нажатии
  row.classList.add('is-found');
}

/* ---------- лига: шапка и старт ---------- */

function initial(name: string): string {
  return (name.replace(/^@/, '').trim()[0] ?? '?').toUpperCase();
}

/** Аватар участника: фото или первая буква имени. */
function Face({ name, avatar, me }: { name: string; avatar: string | null; me?: boolean }) {
  const [ok, setOk] = useState(true);
  return (
    <span className={`pd-face${me ? ' is-me' : ''}`}>
      {avatar && ok ? (
        <img src={avatar} alt="" width={28} height={28} loading="lazy" decoding="async" onError={() => setOk(false)} />
      ) : (
        initial(name)
      )}
    </span>
  );
}

/** Аватарки стопкой: первые пятеро и «+N». */
function Faces({ faces, total }: { faces: Array<{ name: string; avatar: string | null; is_me?: boolean }>; total: number }) {
  const shown = faces.slice(0, 5);
  const more = total - shown.length;
  if (!shown.length) return null;
  return (
    <span className="pd-faces" aria-hidden="true">
      {shown.map((f, i) => (
        <Face key={`${i}-${f.name}`} name={f.name} avatar={f.avatar} me={f.is_me} />
      ))}
      {more > 0 && <span className="pd-face pd-face--more">+{more}</span>}
    </span>
  );
}

function LeagueHead({
  league,
  head,
  view,
  total,
}: {
  league: League;
  head: LeagueHeader | null;
  view: BoardView | null;
  total: number | null;
}) {
  const members = head?.members ?? league.members;
  const place = view && total != null ? placeLine(view, total) : null;
  const next = head?.next_match ?? null;
  // до старта лиги ближайший матч и кто готов — в блоке «Лига стартует», здесь не повторяем
  const showNext = head != null && next != null && !!view?.started;
  return (
    <div className="pd-lhead">
      <div className="pd-lhead__top">
        <div className="pd-lhead__title">
          <b>{head?.name ?? league.name}</b>
          <span className="pd-muted">
            {members} {plural(members, ['участник', 'участника', 'участников'])}
            {place && (
              <>
                {' · '}
                <span className="pd-lhead__place">{place}</span>
              </>
            )}
          </span>
        </div>
        <Faces faces={head?.people ?? league.faces ?? []} total={members} />
      </div>
      {showNext && head && next && (
        <div className="pd-lhead__next">
          <span className="pd-lhead__match">
            Ближайший матч: {matchTitle(next)} · <span className="pd-nowrap">{formatWeekdayShort(next.kickoff_utc)}</span>
          </span>
          <PredictedBar done={head.predicted_next_count} of={head.members} label={nextLine(head)} />
        </div>
      )}
    </div>
  );
}

/** «прогнозы сделали 1 из 2» и полоска заполненности. */
function PredictedBar({ done, of, label }: { done: number; of: number; label: string | null }) {
  return (
    <span className="pd-pbar">
      <span className="pd-pbar__label">{label}</span>
      <span className="pd-pbar__track" role="img" aria-label={`Прогнозы сделали ${done} из ${of}`}>
        <span className="pd-pbar__fill" style={{ width: `${of ? Math.round((done / of) * 100) : 0}%` }} />
      </span>
    </span>
  );
}

/** Лига ещё без сыгранных матчей: с какого матча старт и кто уже сделал прогноз. */
function LeagueStart({ head }: { head: LeagueHeader }) {
  const next = head.next_match;
  const people = waitingPeople(head);
  return (
    <div className="pd-lstart">
      {next ? (
        <>
          <p className="pd-lstart__title">
            Лига стартует с матча <b>{matchTitle(next)}</b>
          </p>
          <p className="pd-muted">{formatKickoff(next.kickoff_utc)}</p>
          <PredictedBar done={head.predicted_next_count} of={head.members} label={nextLine(head)} />
        </>
      ) : (
        <>
          <p className="pd-lstart__title">Лига стартует с ближайшего матча Реала</p>
          <p className="pd-muted">Расписание пока не объявили — когда матч появится, здесь будет видно, кто уже сделал прогноз.</p>
        </>
      )}
      <ul className="pd-lstart__people">
        {people.map((p, i) => (
          <li key={`${i}-${p.name}`} className="pd-lstart__row">
            <Face name={p.name} avatar={p.avatar} me={p.is_me} />
            <span className="pd-lstart__name">
              <span className="pd-lstart__nm">{p.is_me ? `${p.name} · ты` : p.name}</span>
              {p.is_owner && <span className="pd-lstart__tag">создатель</span>}
            </span>
            {p.state === 'done' ? (
              <span className="pd-lstart__st is-done">
                прогноз сделан
                <svg className="pd-check" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 12.5l4.5 4.5L19 7.5" />
                </svg>
              </span>
            ) : p.state === 'wait' ? (
              <span className="pd-lstart__st">ждём</span>
            ) : null}
          </li>
        ))}
      </ul>
      {next && <p className="pd-lstart__note">Чужой счёт не виден до начала матча — только то, что прогноз сделан.</p>}
    </div>
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

/* ---------- лиги: создать, позвать друга, переименовать, удалить, выйти ---------- */

/** Ошибка действия с лигой: понятные (403/404/409/422) — текстом сервера, остальное — общим. */
function leagueError(ex: unknown): string {
  const fe = ex instanceof AuthFetchError ? ex : new AuthFetchError(0, null, '');
  return [403, 404, 409, 422].includes(fe.status) && fe.message ? fe.message : predictError(fe.status, fe.code, fe.message).message;
}

function Invite({
  authed,
  leagues,
  onRetry,
  onChanged,
}: {
  authed: boolean;
  leagues: Load<{ leagues: League[] }>;
  onRetry: () => void;
  /** лигу создали, переименовали, удалили или из неё вышли — перечитать списки */
  onChanged: () => void;
}) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fresh, setFresh] = useState<League | null>(null);
  // удалённые/покинутые — прячем сразу, не дожидаясь нового списка
  const [gone, setGone] = useState<number[]>([]);
  const all = authed && leagues.kind === 'ok' ? leagues.data.leagues : [];
  const shown = (fresh && !all.some((l) => l.id === fresh.id) ? [...all, fresh] : all).filter((l) => !gone.includes(l.id));

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const lg = await authFetch<League>('/api/predict/leagues', { method: 'POST', body: { name } });
      setFresh(lg);
      setName('');
      onChanged();
    } catch (ex) {
      setErr(leagueError(ex));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="ui-card pd-invite" aria-label="Лиги с друзьями">
      <h2 className="pd-h2">Лиги с друзьями</h2>
      <p className="pd-muted">Своя лига — отдельный рейтинг для друзей. Друг откроет ссылку в Telegram и сразу окажется в лиге.</p>
      {!authed ? (
        <p className="pd-muted pd-invite__anon">Создать лигу можно после входа через Telegram.</p>
      ) : (
        <>
          {leagues.kind === 'error' && <ErrorState plain text={loadError(leagues) ?? undefined} onRetry={onRetry} />}
          {shown.map((lg) => (
            <InviteRow
              key={lg.id}
              lg={lg}
              onChanged={onChanged}
              onGone={() => {
                setGone((g) => [...g, lg.id]);
                if (fresh?.id === lg.id) setFresh(null);
                onChanged();
              }}
            />
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

type RowMode = 'idle' | 'rename' | 'delete' | 'leave';

function InviteRow({ lg, onChanged, onGone }: { lg: League; onChanged: () => void; onGone: () => void }) {
  const url = inviteLink(lg.code, lg.invite_link, BOT_USERNAME);
  const [msg, setMsg] = useState<string | null>(null);
  const [mode, setMode] = useState<RowMode>('idle');
  const [draft, setDraft] = useState(lg.name);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!msg) return;
    const t = window.setTimeout(() => setMsg(null), 2500);
    return () => window.clearTimeout(t);
  }, [msg]);
  const open = (m: RowMode) => {
    setMode(m);
    setErr(null);
    if (m === 'rename') setDraft(lg.name);
  };
  const run = async (fn: () => Promise<unknown>, after: () => void) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      after();
    } catch (ex) {
      setErr(leagueError(ex));
    } finally {
      setBusy(false);
    }
  };
  const rename = (e: FormEvent) => {
    e.preventDefault();
    if (draft.trim() === lg.name) return open('idle');
    void run(
      () => authFetch<League>(`/api/predict/leagues/${lg.id}`, { method: 'PATCH', body: { name: draft } }),
      () => {
        setMode('idle');
        setMsg('Название сохранено');
        onChanged();
      },
    );
  };
  const remove = () =>
    void run(
      () => authFetch(mode === 'delete' ? `/api/predict/leagues/${lg.id}` : `/api/predict/leagues/${lg.id}/membership`, { method: 'DELETE' }),
      onGone,
    );
  const confirm = mode === 'delete' || mode === 'leave';

  return (
    <div className="pd-league">
      {mode === 'rename' ? (
        <form className="pd-league__rename" onSubmit={rename}>
          <label className="pd-league__lbl" htmlFor={`pd-league-rn-${lg.id}`}>
            Новое название
          </label>
          <input
            id={`pd-league-rn-${lg.id}`}
            className="pd-input"
            value={draft}
            maxLength={40}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') open('idle');
            }}
          />
          <div className="pd-league__actions">
            <button type="button" className="ui-btn ui-btn--secondary" onClick={() => open('idle')} disabled={busy}>
              Отмена
            </button>
            <button type="submit" className="ui-btn ui-btn--primary pd-league__share" disabled={busy || !draft.trim()}>
              {busy ? 'Сохраняем…' : 'Сохранить'}
            </button>
          </div>
        </form>
      ) : (
        <div className="pd-league__head">
          <div className="pd-league__title">
            <b>{lg.name}</b>
            <span className="pd-muted">
              {lg.members} {plural(lg.members, ['участник', 'участника', 'участников'])}
              {lg.is_owner ? ' · ты создатель' : ''}
            </span>
          </div>
          <Faces faces={lg.faces ?? []} total={lg.members} />
        </div>
      )}

      {confirm && (
        <div className="pd-league__confirm" role="alertdialog" aria-label={mode === 'delete' ? 'Удалить лигу' : 'Выйти из лиги'}>
          <p className="pd-league__q">
            {mode === 'delete'
              ? `Удалить лигу «${lg.name}»? Её рейтинг пропадёт у всех участников. Прогнозы и очки в общем рейтинге останутся.`
              : `Выйти из лиги «${lg.name}»? Вернуться можно по ссылке-приглашению.`}
          </p>
          <div className="pd-league__actions">
            <button type="button" className="ui-btn ui-btn--secondary" onClick={() => open('idle')} disabled={busy}>
              Отмена
            </button>
            <button type="button" className="ui-btn pd-league__danger" onClick={remove} disabled={busy}>
              {busy ? (mode === 'delete' ? 'Удаляем…' : 'Выходим…') : mode === 'delete' ? 'Удалить' : 'Выйти'}
            </button>
          </div>
        </div>
      )}

      {mode === 'idle' && (
        <>
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
          <div className="pd-league__more">
            {lg.is_owner ? (
              <>
                <button type="button" className="pd-league__act" onClick={() => open('rename')}>
                  Переименовать
                </button>
                <button type="button" className="pd-league__act is-danger" onClick={() => open('delete')}>
                  Удалить
                </button>
              </>
            ) : (
              <button type="button" className="pd-league__act is-danger" onClick={() => open('leave')}>
                Выйти из лиги
              </button>
            )}
          </div>
        </>
      )}
      {err && (
        <p className="pd-msg pd-msg--err" role="alert">
          {err}
        </p>
      )}
      {msg && (
        <p className="pd-league__msg" role="status">
          {msg}
        </p>
      )}
    </div>
  );
}
