import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router';
import type { ApiMatch } from '../../api/match';
import { t } from '../../lib/i18n';
import { useDesktop } from '../../lib/shell';
import { useTelegramBackButton } from '../../lib/tmaNav';
import { Badge, Countdown, EmptyState, ErrorState, LeagueLogo, ScoreHeader, Skeleton, Tabs, TeamCrest, formatTime, formatWeekdayShort } from '../../ui';
import { cx } from '../../ui/format';
import { RoundCard } from './ExtraCards';
import { roundView } from './extras';
import { zonesView } from './info';
import { LineupsTab } from './LineupsTab';
import { OnlineTab } from './OnlineTab';
import { H2HTab, OverviewTab } from './OverviewTab';
import { DESK_TABS, MOBILE_TABS, TAB_LABEL, deskTabHref, mobileTabHref, pickTab, tabFromLocation, type MatchTab } from './matchTabs';
import { StatsTab } from './StatsTab';
import { useMatch } from './useMatch';
import { useScrollAnchorFallback } from './useScrollAnchor';
import {
  REAL_ID,
  compactTitle,
  goals,
  h2hView,
  has,
  headerView,
  keyFeed,
  lineupView,
  minuteText,
  momentumView,
  realSide,
  shortName,
  shortTeam,
  shotsView,
  statPeriods,
  teamRef,
  tournamentLine,
  type HeaderView,
  type Phase,
} from './view';
import { useGoalWatch } from '../../lib/useGoalWatch';
import { takeRects } from '../../lib/flipOrigin';
import { reducedMotion } from '../../lib/motion';
import { addMatchToCalendar, canAddToCalendar } from '../../lib/nativeBridge';
import './match.css';

const MOBILE_ITEMS = MOBILE_TABS.map((id) => ({ id, label: TAB_LABEL[id] }));

const BACK_ICON = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M15 5l-7 7 7 7" />
  </svg>
);

/**
 * Экран матча. Телефон: /match/:id, /match/:id/lineups, /match/:id/stats, /match/:id/online.
 * Компьютер: те же вкладки (+ «Турнир», «Очные встречи») — /match/:id?tab=…; см. matchTabs.ts.
 */
export default function MatchScreen() {
  const { id = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const desktop = useDesktop();
  const urlTab = tabFromLocation(location.pathname, location.search);

  // прямой заход по ссылке (за нами нет страниц приложения) — «назад» ведёт в календарь, а не из приложения.
  // idx в history.state ведёт react-router: push +1, replace — без изменений; переживает перезагрузку.
  const goBack = useCallback(() => {
    const idx = (window.history.state as { idx?: number } | null)?.idx;
    if (!idx) navigate('/matches', { replace: true });
    else navigate(-1);
  }, [navigate]);
  const nativeBack = useTelegramBackButton(goBack);

  const { state, reload } = useMatch(id);
  const match = state.kind === 'ok' ? state.match : null;
  const head = useMemo(() => (match ? headerView(match) : null), [match]);
  useScrollAnchorFallback(match);
  const shownDesk = useMemo<MatchTab[]>(() => (match && head ? deskTabs(match, head.phase) : ['overview']), [match, head]);
  const tab: MatchTab = pickTab(urlTab, desktop ? shownDesk : MOBILE_TABS);

  // пришли с карточки матча: шапка собирается — эмблемы проявляются с лёгким ростом, следом счёт/«vs».
  // Перелёт эмблем из списка (FLIP) убран: строка списка стоит там же, где в шапке цифры отсчёта, и
  // эмблемы ползли поперёк них — выглядело как сбой.
  const ready = !!head;
  useLayoutEffect(() => {
    if (!ready) return;
    if (!takeRects(`match:${id}`) || reducedMotion()) return;
    const crests = document.querySelectorAll<HTMLElement>('.mt .ui-score-head .ui-crest, .mt .mt-top__title .ui-crest');
    crests.forEach((c, i) =>
      c.animate?.([{ opacity: 0, transform: 'scale(.82)' }, { opacity: 1, transform: 'none' }], {
        duration: 420,
        delay: i * 60,
        easing: 'cubic-bezier(.22,1,.36,1)',
        fill: 'backwards',
      }),
    );
    document.querySelector<HTMLElement>('.mt .ui-score-head__score, .mt .ui-score-head .ui-mc__vs')?.animate?.(
      [{ opacity: 0, transform: 'scale(.9)' }, { opacity: 1, transform: 'none' }],
      { duration: 380, delay: 120, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' },
    );
  }, [ready, id]);

  // новый гол в лайве: Реал — праздник (плашка, конфетти), соперник — только перелистывание табло
  const hasReal = !!match && (match.home.id === REAL_ID || match.away.id === REAL_ID);
  useGoalWatch(
    match && head
      ? {
          id: match.id ?? id,
          score: head.score,
          live: head.live,
          real: hasReal ? realSide(match) : null,
          rival: hasReal ? teamRef(match, realSide(match) === 'home' ? 'away' : 'home') : undefined,
        }
      : null,
    (g) => {
      const ev = match ? goals(match).filter((x) => x.side === g.side)[g.n - 1]?.ev : undefined;
      const pid = Number(ev?.player?.id);
      return {
        minute: ev ? minuteText(ev.minute, ev.added) : head?.minute,
        scorer: ev?.player?.name ? { id: Number.isFinite(pid) && pid > 0 ? pid : undefined, name: shortName(ev.player.name) } : null,
      };
    },
  );

  useEffect(() => {
    document.title = match ? t('{title} — Мадридиста', { title: compactTitle(match) }) : t('Матч — Мадридиста');
  }, [match]);

  // большая шапка: на компьютере — всегда, на телефоне — только в «Обзоре»
  const bigHead = desktop || tab === 'overview';
  const title = match ? (bigHead ? tournamentLine(match) : compactTitle(match)) : '';
  const setTab = (next: MatchTab) => {
    // вкладки не копят историю: «назад» уводит с матча, а не по вкладкам
    navigate(desktop ? deskTabHref(id, next, location.search) : mobileTabHref(id, next, location.search), { replace: true });
  };

  return (
    <main className="mt" aria-busy={state.kind === 'loading' || undefined}>
      <header className="mt-top">
        {nativeBack ? (
          <span className="mt-top__gap" aria-hidden="true" />
        ) : (
          <button type="button" className="mt-top__back" aria-label={t('Назад')} onClick={goBack}>
            {BACK_ICON}
          </button>
        )}
        {match && !bigHead ? (
          <TeamsTitle match={match} />
        ) : (
          <h1 className={match?.tournament.id != null ? 'mt-top__title mt-top__title--teams' : 'mt-top__title'}>
            {match?.tournament.id != null && <LeagueLogo id={match.tournament.id} name="" size={20} />}
            <span className="mt-top__tm">{title}</span>
          </h1>
        )}
        {head?.live ? <Badge tone="live" className="mt-top__live" /> : <span className="mt-top__gap" aria-hidden="true" />}
      </header>

      {state.kind === 'loading' && <LoadingBody />}
      {state.kind === 'not_found' && (
        <EmptyState
          className="mt-state"
          title={t('Матч не найден')}
          text={t('Такого матча нет в календаре')}
          action={{ label: t('К матчам'), onClick: () => navigate('/matches') }}
        />
      )}
      {state.kind === 'unavailable' && (
        <ErrorState className="mt-state" title={t('Данные ещё собираются')} text={t('Сервер только что запустился. Попробуем снова через несколько секунд')} onRetry={reload} />
      )}
      {state.kind === 'error' && <ErrorState className="mt-state" onRetry={reload} />}

      {match && head && desktop && (
        // сайт на компьютере (как у FotMob): шапка матча, под ней прилипающие вкладки; при прокрутке шапка
        // сворачивается в тонкую полосу «эмблемы · счёт · минута» над вкладками
        <DeskMatch match={match} head={head} tab={tab} tabs={shownDesk} onTab={setTab} onKickoff={reload} />
      )}

      {match && head && !desktop && (
        <>
          {tab === 'overview' && <Header match={match} onKickoff={reload} />}
          <Tabs items={MOBILE_ITEMS} value={tab} onChange={setTab} ariaLabel={t('Разделы матча')} className={head.live ? 'mt-tabs--live' : undefined} />
          {match.pending ? (
            <PendingBody />
          ) : (
            <div className="mt-body" key={tab}>
              {tab === 'overview' && <OverviewTab match={match} phase={head.phase} />}
              {tab === 'lineups' && <LineupsTab match={match} phase={head.phase} />}
              {tab === 'stats' && <StatsTab match={match} phase={head.phase} />}
              {tab === 'online' && <OnlineTab match={match} phase={head.phase} />}
            </div>
          )}
        </>
      )}
    </main>
  );
}

/** Какие вкладки показывать на компьютере: без данных — вкладки нет. */
function deskTabs(m: ApiMatch, phase: Phase): MatchTab[] {
  const started = ['live', 'halftime', 'finished', 'abandoned'].includes(phase);
  const ok: Record<MatchTab, boolean> = {
    overview: true,
    lineups: lineupView(m, 'home') != null || lineupView(m, 'away') != null,
    stats: statPeriods(m).length > 0 || !!momentumView(m) || !!shotsView(m) || !!zonesView(m),
    online: started || has(m, 'commentary') || keyFeed(m).length > 0,
    table: !!roundView(m),
    h2h: !!h2hView(m),
  };
  return DESK_TABS.filter((t) => ok[t]);
}

const LIVE_DOT = <span className="mt-dot" aria-hidden="true" />;

/** Компьютер: шапка, прилипающие вкладки (со свёрнутой шапкой над ними) и содержимое вкладки. */
function DeskMatch({
  match,
  head,
  tab,
  tabs,
  onTab,
  onKickoff,
}: {
  match: ApiMatch;
  head: HeaderView;
  tab: MatchTab;
  tabs: MatchTab[];
  onTab: (t: MatchTab) => void;
  onKickoff: () => void;
}) {
  const mark = useRef<HTMLDivElement>(null);
  const [stuck, setStuck] = useState(false);

  // вкладки прилипли под шапкой сайта — значит, большая шапка матча ушла под них: показываем тонкую полосу
  useEffect(() => {
    let raf = 0;
    const check = () => {
      raf = 0;
      const el = mark.current;
      if (!el) return;
      setStuck(el.getBoundingClientRect().top <= dockTop() + 1);
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(check);
    };
    check();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [match.pending]);

  const choose = (t: MatchTab) => {
    onTab(t);
    // ниже шапки — новая вкладка с начала, а шапка остаётся свёрнутой
    const el = mark.current;
    if (!el) return;
    const top = el.getBoundingClientRect().top + window.scrollY - dockTop();
    if (window.scrollY > top) window.scrollTo({ top });
  };

  const items = tabs.map((id) => ({ id, label: TAB_LABEL[id], icon: id === 'online' && head.live ? LIVE_DOT : undefined }));

  return (
    <>
      <Header match={match} onKickoff={onKickoff} />
      {match.pending ? (
        <PendingBody />
      ) : (
        <>
          <div ref={mark} className="mt-dock-mark" aria-hidden="true" />
          <div className={cx('mt-dock', stuck && 'is-stuck')}>
            <MiniBar match={match} head={head} shown={stuck} />
            <Tabs items={items} value={tab} onChange={choose} ariaLabel={t('Разделы матча')} variant="pill" className="mt-dtabs" />
          </div>
          <div className={`mt-pane mt-pane--${tab}`} key={tab} role="tabpanel" aria-label={TAB_LABEL[tab]}>
            {tab === 'overview' && <OverviewTab match={match} phase={head.phase} desk onStats={() => choose('stats')} />}
            {tab === 'lineups' && <LineupsTab match={match} phase={head.phase} desk />}
            {tab === 'stats' && <StatsTab match={match} phase={head.phase} desk />}
            {tab === 'online' && <OnlineTab match={match} phase={head.phase} panel />}
            {tab === 'table' && <RoundCard match={match} expanded />}
            {tab === 'h2h' && <H2HTab match={match} phase={head.phase} />}
          </div>
        </>
      )}
    </>
  );
}

/** Отступ прилипших вкладок от верха окна: шапка сайта + тонкая полоса матча (переменные — desktop.css, match.css). */
function dockTop(): number {
  const cs = getComputedStyle(document.documentElement);
  const px = (v: string, d: number) => {
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : d;
  };
  return px(cs.getPropertyValue('--sh-h'), 68) + px(cs.getPropertyValue('--mt-bar-h'), 56);
}

/** Свёрнутая шапка: эмблемы · счёт · минута/статус · LIVE; нажатие — наверх к большой шапке. */
function MiniBar({ match, head, shown }: { match: ApiMatch; head: HeaderView; shown: boolean }) {
  const h = teamRef(match, 'home');
  const a = teamRef(match, 'away');
  let status: string;
  if (head.phase === 'live') status = head.minute ?? head.statusText ?? t('Идёт матч');
  else if (head.statusText) status = head.statusText;
  else if (head.phase === 'finished') status = t('Матч завершён');
  else status = match.kickoff ? `${formatWeekdayShort(match.kickoff)} · ${formatTime(match.kickoff)} ${t('МСК')}` : '';
  return (
    <button
      type="button"
      className={cx('mt-bar', shown && 'is-on')}
      tabIndex={shown ? 0 : -1}
      aria-hidden={!shown}
      aria-label={t('{title}. Наверх', { title: compactTitle(match) })}
      onClick={() => window.scrollTo({ top: 0, behavior: reducedMotion() ? 'auto' : 'smooth' })}
    >
      <span className="mt-bar__team">
        <span className="mt-bar__name">{shortTeam(h.name)}</span>
        {h.id != null && <TeamCrest id={h.id} name="" size={28} />}
      </span>
      <span className="mt-bar__mid">
        <b className="mt-bar__score">{head.status === 'upcoming' || !head.score ? 'VS' : `${head.score[0]} : ${head.score[1]}`}</b>
        {status && <span className={cx('mt-bar__st', head.phase === 'live' && 'is-live')}>{status}</span>}
      </span>
      <span className="mt-bar__team mt-bar__team--r">
        {a.id != null && <TeamCrest id={a.id} name="" size={28} />}
        <span className="mt-bar__name">{shortTeam(a.name)}</span>
      </span>
      {head.live && <Badge tone="live" className="mt-bar__live" />}
    </button>
  );
}

/** «[эмб] Roma 3 : 4 Real Madrid [эмб]» — заголовок вкладок без большой шапки; текст — тот же compactTitle. */
function TeamsTitle({ match }: { match: ApiMatch }) {
  const h = teamRef(match, 'home');
  const a = teamRef(match, 'away');
  const full = compactTitle(match);
  const mid = full.slice((match.home.name ?? '').length, full.length - (match.away.name ?? '').length).trim();
  return (
    <h1 className="mt-top__title mt-top__title--teams" aria-label={full}>
      {h.id != null && <TeamCrest id={h.id} name="" size={20} />}
      <span className="mt-top__tm" aria-hidden="true">
        {h.name}
      </span>
      <span className="mt-top__sc" aria-hidden="true">
        {mid}
      </span>
      <span className="mt-top__tm" aria-hidden="true">
        {a.name}
      </span>
      {a.id != null && <TeamCrest id={a.id} name="" size={20} />}
    </h1>
  );
}

function Header({ match, onKickoff }: { match: ApiMatch; onKickoff: () => void }) {
  const h = headerView(match);
  return (
    <>
      <ScoreHeader
        home={teamRef(match, 'home')}
        away={teamRef(match, 'away')}
        status={h.status}
        score={h.score}
        kickoff={match.kickoff ?? undefined}
        minute={h.minute}
        statusText={h.statusText}
        scorers={h.scorers}
      />
      {h.countdown && match.kickoff && <Countdown to={match.kickoff} className="mt-cd" onEnd={onKickoff} liveOnEnd />}
      {h.countdown && match.kickoff && canAddToCalendar() && <CalendarButton match={match} />}
    </>
  );
}

/** Только в приложении из RuStore: матч — в календарь телефона (системный экран «Новое событие»). */
function CalendarButton({ match }: { match: ApiMatch }) {
  const title = `${match.home.name ?? ''} — ${match.away.name ?? ''}`.trim();
  const place = [match.venue?.name, match.venue?.city].filter(Boolean).join(', ') || null;
  const what = [match.tournament?.name, match.tournament?.round].filter(Boolean).join(', ');
  return (
    <button
      type="button"
      className="ui-btn ui-btn--secondary ui-btn--block mt-cal"
      onClick={() =>
        addMatchToCalendar(title, match.kickoff!, place, `${what ? `${what}. ` : ''}${t('Мадридиста')}: https://realmadridfan.ru/match/${match.id ?? ''}`)
      }
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <rect x="3.5" y="5" width="17" height="15" rx="3" />
        <path d="M3.5 10h17M8 3v4M16 3v4" />
      </svg>
      {t('Добавить в календарь')}
    </button>
  );
}

function LoadingBody() {
  return (
    <div className="mt-loading">
      <Skeleton shape="match" />
      <Skeleton shape="list" rows={4} className="mt-loading__list" />
    </div>
  );
}

function PendingBody() {
  return (
    <section className="ui-card mt-pending" aria-live="polite">
      <p className="mt-pending__title">{t('Данные подгружаются')}</p>
      <p className="mt-pending__text">{t('Обновим автоматически через несколько секунд')}</p>
      <Skeleton shape="stats" rows={4} />
    </section>
  );
}
