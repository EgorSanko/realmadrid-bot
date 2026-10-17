import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router';
import { backgroundOf, type PlayerNavState } from '../../lib/playerNav';
import { useSpaLink } from '../../lib/spaLink';
import { useTelegramBackButton } from '../../lib/tmaNav';
import {
  Card,
  EmptyState,
  ErrorState,
  EventIcon,
  Flag,
  LeagueLogo,
  PlayerPhoto,
  RatingChip,
  Skeleton,
  Tabs,
  TeamCrest,
} from '../../ui';
import { returnInfo } from '../team/teamData';
import {
  ageFromBirth,
  ageText,
  careerView,
  contractText,
  countryRu,
  dateLong,
  flagIso,
  footRu,
  injuryNameRu,
  keyStats,
  moneyText,
  positionsRu,
  recentView,
  roleRu,
  seasonHead,
  seasonShort,
  seasonView,
  statusTitle,
  updatedText,
  type ApiPlayer,
} from './playerData';
import { usePlayer } from './usePlayer';
import './playerCard.css';

type TabId = 'season' | 'matches' | 'career';

const BACK_ICON = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M15 5l-7 7 7 7" />
  </svg>
);

const REAL_ID = 8633;

/** Карточка игрока /player/:id — полноэкранный слой поверх экрана, с которого её открыли. */
export default function PlayerScreen() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const nav = (location.state as PlayerNavState | null) ?? null;
  const overlay = backgroundOf(location) != null;
  const { state, reload } = usePlayer(id);
  const p = state.kind === 'ok' ? state.player : null;
  const ref = useRef<HTMLDivElement>(null);

  // прямой заход (под карточкой ничего нет) — «назад» ведёт в раздел, а не из приложения
  const goBack = useCallback(() => {
    const idx = (window.history.state as { idx?: number } | null)?.idx;
    if (overlay && idx) navigate(-1);
    else navigate(p && p.team?.id !== REAL_ID ? '/' : '/team', { replace: true });
  }, [navigate, overlay, p]);
  const nativeBack = useTelegramBackButton(goBack);

  // фон не прокручивается под карточкой; фокус — в карточку; Esc закрывает
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    ref.current?.focus({ preventScroll: true });
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') goBack();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [goBack]);
  useEffect(() => {
    ref.current?.scrollTo(0, 0);
  }, [id]);

  const name = p?.name ?? (nav?.player && String(nav.player.id) === id ? nav.player.name : null);
  useEffect(() => {
    const prev = document.title;
    document.title = name ? `${name} — Мадридиста` : 'Игрок — Мадридиста';
    return () => {
      document.title = prev;
    };
  }, [name]);

  const numericId = /^\d+$/.test(id) ? Number(id) : undefined;

  return (
    <div ref={ref} className="pc" role="dialog" aria-modal="true" aria-label={name ? `Карточка игрока: ${name}` : 'Карточка игрока'} tabIndex={-1}>
      <div className="pc-in">
        <header className="pc-top">
          {nativeBack ? (
            <span className="pc-top__gap" aria-hidden="true" />
          ) : (
            <button type="button" className="pc-top__back" aria-label="Назад" onClick={goBack}>
              {BACK_ICON}
            </button>
          )}
          <span className="pc-top__title">Игрок</span>
          <span className="pc-top__gap" aria-hidden="true" />
        </header>

        {p ? (
          <PlayerBody p={p} />
        ) : state.kind === 'not_found' ? (
          <EmptyState className="pc-state" title="Игрок не найден" text="Источник не знает такого игрока" action={{ label: 'К составу', onClick: () => navigate('/team') }} />
        ) : state.kind === 'error' ? (
          <ErrorState
            className="pc-state"
            title={state.unavailable ? 'Данные игрока недоступны' : 'Не удалось загрузить'}
            text={state.unavailable ? 'Источник сейчас не отвечает — попробуй чуть позже' : 'Проверь соединение и попробуй ещё раз'}
            onRetry={reload}
          />
        ) : (
          <Waiting id={numericId} name={name} pending={state.kind === 'pending'} />
        )}
      </div>
    </div>
  );
}

function Waiting({ id, name, pending }: { id?: number; name: string | null; pending: boolean }) {
  return (
    <div aria-busy="true">
      <section className="pc-hero">
        <div className="pc-hero__photo">
          {id != null && name ? <PlayerPhoto id={id} name={name} size={104} /> : <Skeleton width={104} height={104} radius="50%" />}
        </div>
        <div className="pc-hero__main">
          {name ? <h1 className="pc-hero__name">{name}</h1> : <Skeleton width="70%" height={22} />}
          <Skeleton width="45%" height={14} style={{ marginTop: 12 }} />
          <Skeleton width="60%" height={14} style={{ marginTop: 10 }} />
        </div>
      </section>
      <Card className="pc-wait" ariaLabel="Загрузка">
        <p className="pc-wait__title" role="status">
          Загружаем данные игрока…
        </p>
        {pending && <p className="pc-wait__text">Собираем карточку — обычно это несколько секунд</p>}
        <Skeleton shape="stats" rows={4} style={{ marginTop: 12 }} />
      </Card>
    </div>
  );
}

function PlayerBody({ p }: { p: ApiPlayer }) {
  const has = (k: string) => p.available.includes(k);
  const tabs = useMemo(() => {
    const on = (k: string) => p.available.includes(k);
    const t: Array<{ id: TabId; label: string }> = [];
    if (on('season') && p.season?.tournaments.length) t.push({ id: 'season', label: 'Сезон' });
    if (on('recent') && p.recent.length) t.push({ id: 'matches', label: 'Последние матчи' });
    if ((on('career') && p.career.length) || (on('national') && p.national.length)) t.push({ id: 'career', label: 'Карьера' });
    return t;
  }, [p]);
  const [tab, setTab] = useState<TabId | null>(tabs[0]?.id ?? null);
  const current = tabs.find((t) => t.id === tab)?.id ?? tabs[0]?.id ?? null;
  const upd = updatedText(p.updated_at);

  return (
    <>
      <Hero p={p} />
      {has('status') && p.status && <StatusCard p={p} />}
      <Facts p={p} />
      {has('season') && p.season && <KeyRow p={p} />}
      {tabs.length > 1 && <Tabs items={tabs} value={current ?? tabs[0].id} onChange={setTab} ariaLabel="Разделы карточки" />}
      {current === 'season' && <SeasonCard p={p} />}
      {current === 'matches' && <RecentCard p={p} />}
      {current === 'career' && <CareerCard p={p} />}
      <p className="pc-foot">
        {p.stale ? 'Данные могли устареть · ' : ''}
        {p.source === 'sofascore' ? 'SofaScore' : 'FotMob'}
        {upd ? ` · обновлено в ${upd} МСК` : ''}
      </p>
    </>
  );
}

function Hero({ p }: { p: ApiPlayer }) {
  const pos = positionsRu(p.positions);
  const iso = flagIso(p.country?.flag);
  const country = p.country ? countryRu(iso, p.country.name) : null;
  const role = roleRu(p.role);
  return (
    <section className="pc-hero" aria-label="Игрок">
      <div className="pc-hero__photo">
        <PlayerPhoto id={p.id} name={p.name ?? ''} size={104} />
        {p.number != null && (
          <span className="pc-hero__num" aria-label={`номер ${p.number}`}>
            {p.number}
          </span>
        )}
      </div>
      <div className="pc-hero__main">
        <h1 className="pc-hero__name">{p.name}</h1>
        {(pos.length > 0 || role) && (
          <div className="pc-hero__pos">
            {pos.map((x, i) => (
              <span key={x} className={i === 0 ? 'pc-pos pc-pos--main' : 'pc-pos'}>
                {x}
              </span>
            ))}
            {role && <span className="pc-hero__role">{role}</span>}
          </div>
        )}
        {p.team?.name && (
          <div className="pc-hero__row">
            {p.team.id != null && p.team.logo && <TeamCrest id={p.team.id} name="" size={20} />}
            <span className="pc-ell">{p.team.name}</span>
            {p.team.on_loan && <span className="pc-tag">аренда</span>}
          </div>
        )}
        {country && (
          <div className="pc-hero__row">
            {iso && <Flag iso2={iso} name="" width={20} />}
            <span className="pc-ell">{country}</span>
          </div>
        )}
      </div>
    </section>
  );
}

function StatusCard({ p }: { p: ApiPlayer }) {
  const s = p.status!;
  const r = returnInfo(s.expected_return);
  const what = injuryNameRu(s.name);
  const title = statusTitle(s);
  return (
    <section className="ui-card pc-status" aria-label={title}>
      <div className="pc-status__head">
        <span className="ui-badge ui-badge--injury">{title.toLowerCase()}</span>
        {what && <span className="pc-status__what">{what}</span>}
      </div>
      <p className="pc-status__when">
        {r.back ? r.text : r.past ? `Возвращение ожидалось: ${r.text}` : `Возвращение: ${r.text}`}
      </p>
    </section>
  );
}

function Facts({ p }: { p: ApiPlayer }) {
  const age = ageFromBirth(p.birth) ?? p.age;
  const items: Array<{ k: string; v: string; sub?: string | null }> = [];
  const at = ageText(age);
  if (at) items.push({ k: 'Возраст', v: at, sub: dateLong(p.birth) });
  if (p.height) items.push({ k: 'Рост', v: `${p.height} см` });
  const foot = footRu(p.foot);
  if (foot) items.push({ k: 'Нога', v: foot });
  const val = p.available.includes('value') ? moneyText(p.value_eur) : null;
  if (val) items.push({ k: 'Стоимость', v: val });
  const ct = p.available.includes('contract') ? contractText(p.contract_until) : null;
  if (ct) items.push({ k: 'Контракт до', v: ct });
  if (!items.length) return null;
  return (
    <section className="pc-facts" aria-label="Данные игрока">
      {items.map((f) => (
        <div key={f.k} className="pc-fact">
          <div className="pc-fact__k">{f.k}</div>
          <div className="pc-fact__v">{f.v}</div>
          {f.sub && <div className="pc-fact__sub">{f.sub}</div>}
        </div>
      ))}
    </section>
  );
}

function KeyRow({ p }: { p: ApiPlayer }) {
  const stats = keyStats(p);
  if (!stats.length) return null;
  const s = p.season!;
  return (
    <section className="pc-key" aria-label="Сезон в цифрах">
      <div className="pc-key__cap">
        Сезон {seasonShort(s.name)}
        {s.team?.name ? ` · ${s.team.name}` : ''}
        {s.partial ? ' · по последним матчам' : ''}
      </div>
      <div className="pc-key__grid">
        {stats.map((x) => (
          <div key={x.label} className="pc-key__tile">
            <div className={x.gold ? 'pc-key__v disp gold' : 'pc-key__v disp'}>{x.value}</div>
            <div className="pc-key__k">{x.label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function SeasonCard({ p }: { p: ApiPlayer }) {
  const v = seasonView(p);
  if (!v) return null;
  const head = seasonHead(p);
  return (
    <Card ariaLabel="Сезон по турнирам" className="pc-season">
      <div className="pc-srow pc-srow--head" aria-hidden="true">
        <span className="pc-srow__name">Турнир</span>
        {head.map((h) => (
          <span key={h} className="pc-srow__c">
            {h}
          </span>
        ))}
      </div>
      <ul className="pc-list">
        {v.rows.map((r) => (
          <li key={r.key} className="pc-srow">
            <span className="pc-srow__name">
              {r.league.id != null && r.league.logo ? (
                <LeagueLogo id={r.league.id} name="" size={24} />
              ) : (
                <span className="ui-crest-gap" style={{ width: 24, height: 24 }} aria-hidden="true" />
              )}
              <span className="pc-srow__t">
                <span className="pc-ell">{r.name}</span>
                {r.note && <span className="pc-srow__note">{r.note}</span>}
              </span>
            </span>
            {r.cells.map((c, i) => (
              <span key={i} className={i === r.cells.length - 1 ? 'pc-srow__c pc-srow__c--r' : 'pc-srow__c'} aria-label={`${head[i]}: ${c}`}>
                {c}
              </span>
            ))}
          </li>
        ))}
        {v.total && (
          <li className="pc-srow pc-srow--total">
            <span className="pc-srow__name">
              <span className="ui-crest-gap" style={{ width: 24, height: 24 }} aria-hidden="true" />
              <span className="pc-srow__t">Всего</span>
            </span>
            {v.total.map((c, i) => (
              <span key={i} className="pc-srow__c" aria-label={`${head[i]}: ${c}`}>
                {c}
              </span>
            ))}
          </li>
        )}
      </ul>
      <p className="pc-legend">И — матчи, Мин — минуты, {p.role === 'GK' ? 'Сух — сухие матчи, Проп — пропущено' : 'Г — голы, П — передачи'}, Оц — средняя оценка</p>
    </Card>
  );
}

function RecentCard({ p }: { p: ApiPlayer }) {
  const rows = recentView(p);
  const link = useSpaLink();
  if (!rows.length) return null;
  return (
    <Card ariaLabel="Последние матчи" className="pc-recent">
      <ul className="pc-list">
        {rows.map((m) => {
          const body = (
            <>
              <span className="pc-rm__date">
                <span>{m.date}</span>
                {m.tournament.id != null && m.tournament.logo && <LeagueLogo id={m.tournament.id} name={m.tournamentName} size={16} />}
              </span>
              {m.opponent?.id != null && m.opponent.logo ? (
                <TeamCrest id={m.opponent.id} name="" size={28} />
              ) : (
                <span className="ui-crest-gap" style={{ width: 28, height: 28 }} aria-hidden="true" />
              )}
              <span className="pc-rm__main">
                <span className="pc-rm__opp">{m.opponent?.name ?? '—'}</span>
                <span className="pc-rm__sub">
                  {m.goals > 0 && <EventIcon type="goal" className="pc-rm__goal" />}
                  <span className="pc-ell">{[m.venue, m.deeds].filter(Boolean).join(' · ')}</span>
                </span>
              </span>
              <span className={`pc-rm__score pc-rm__score--${m.result ?? 'n'}`}>{m.score}</span>
              {m.rating != null ? <RatingChip value={m.rating} /> : <span className="pc-rm__norate" aria-hidden="true" />}
            </>
          );
          return (
            <li key={m.key}>
              {m.href ? (
                <a
                  className="pc-rm"
                  {...link(m.href)}
                  aria-label={`${m.date}, ${m.opponent?.name ?? ''}, ${m.venue}, счёт ${m.score} — к матчу`}
                >
                  {body}
                </a>
              ) : (
                <div className="pc-rm">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function CareerCard({ p }: { p: ApiPlayer }) {
  const clubs = careerView(p.career);
  const nat = careerView(p.national);
  const group = (title: string, list: ReturnType<typeof careerView>) =>
    list.length > 0 && (
      <section aria-label={title}>
        <h3 className="pc-group">{title}</h3>
        <ul className="pc-list">
          {list.map((c) => (
            <li key={c.key} className="pc-cr">
              {c.team?.id != null && c.team.logo ? (
                <TeamCrest id={c.team.id} name="" size={28} />
              ) : (
                <span className="ui-crest-gap" style={{ width: 28, height: 28 }} aria-hidden="true" />
              )}
              <span className="pc-cr__main">
                <span className="pc-cr__name">
                  <span className="pc-ell">{c.team?.name ?? '—'}</span>
                  {c.loan && <span className="pc-tag">аренда</span>}
                </span>
                {c.stats && <span className="pc-cr__sub">{c.stats}</span>}
              </span>
              <span className={c.active ? 'pc-cr__years gold' : 'pc-cr__years'}>{c.years}</span>
            </li>
          ))}
        </ul>
      </section>
    );
  return (
    <Card ariaLabel="Карьера" className="pc-career">
      {group('Клубы', clubs)}
      {group('Сборная', nat)}
    </Card>
  );
}
