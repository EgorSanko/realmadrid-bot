import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { commentaryUrl, type ApiCommentary, type ApiMatch } from '../../api/match';
import { usePlayerLinks } from '../../lib/playerNav';
import { Badge, EmptyState, EventIcon, PlayerInline, Skeleton, Tabs, TeamCrest, type MatchEventType } from '../../ui';
import { cx } from '../../ui/format';
import { commentaryRows, freshKeys, type CommentaryRow } from './feed';
import { feedCounts, filterFeed, has, keyFeed, type FeedFilter, type FeedItem, type Phase } from './view';
import './online.css';

type Mode = 'key' | 'en';
const POLL_MS = 30_000;

const ICON: Partial<Record<FeedItem['kind'], MatchEventType>> = {
  goal: 'goal',
  'own-goal': 'own-goal',
  yellow: 'yellow',
  'second-yellow': 'second-yellow',
  red: 'red',
  sub: 'sub',
  var: 'var',
  'penalty-missed': 'penalty-missed',
};

const EN_ICON: Partial<Record<CommentaryRow['type'], MatchEventType>> = {
  goal: 'goal',
  own_goal: 'own-goal',
  penalty_goal: 'goal',
  yellow: 'yellow',
  second_yellow: 'second-yellow',
  red: 'red',
  sub: 'sub',
  var: 'var',
  penalty_missed: 'penalty-missed',
  penalty_saved: 'penalty-missed',
};

const WHISTLE = (
  <svg className="mo-whistle" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="9" cy="14" r="5" />
    <path d="M13 11.5l8-4.5v4l-6.6 2.6M9 9V6" />
  </svg>
);
const SPARK = (
  <svg className="mo-spark" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M13 3L5 13.5h6L10 21l8-10.5h-6z" />
  </svg>
);

/** Новые записи сверху — плавно появляются (только opacity/transform; prefers-reduced-motion — без движения). */
function useFresh(keys: string[]): Set<string> {
  const seen = useRef<Set<string> | null>(null);
  const sig = keys.join('|');
  return useMemo(() => {
    const r = freshKeys(seen.current, keys);
    seen.current = r.seen;
    return r.fresh;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);
}

const FILTERS: Array<{ id: FeedFilter; label: string }> = [
  { id: 'all', label: 'Все' },
  { id: 'goals', label: 'Голы' },
  { id: 'cards', label: 'Карточки' },
  { id: 'subs', label: 'Замены' },
];

const EMPTY_FILTER: Record<Exclude<FeedFilter, 'all'>, string> = {
  goals: 'Голов пока нет',
  cards: 'Карточек пока нет',
  subs: 'Замен пока нет',
};

/**
 * «Онлайн»: «Ключевое» — наша лента по событиям (по-русски), компактными строками, с фильтром;
 * «Все комментарии» — оригинал Opta (EN).
 * panel — сайт на компьютере: своя карточка с заголовком, высотой в экран и своей прокруткой; шапка (заголовок,
 * вкладки, фильтр) прилипает сверху.
 */
export function OnlineTab({ match, phase, panel }: { match: ApiMatch; phase: Phase; panel?: boolean }) {
  const en = has(match, 'commentary');
  const [mode, setMode] = useState<Mode>('key');
  const [filter, setFilter] = useState<FeedFilter>('all');
  const m = en ? mode : 'key';
  const live = phase === 'live' || phase === 'halftime';
  const items = useMemo(() => keyFeed(match), [match]);
  const counts = useMemo(() => feedCounts(items), [items]);
  const chips = m === 'key' && items.length > 0;
  const top = panel || en || chips;
  return (
    <section aria-label={panel ? 'Онлайн-трансляция' : 'Онлайн'} className={cx('mo', panel && 'mo--panel')}>
      {top && (
        <div className="mo-top">
          {panel && (
            <h2 className="dk-h2 mo-h">
              Онлайн
              {live && <Badge tone="live" className="mo-live" />}
            </h2>
          )}
          {en && (
            <Tabs
              variant="outline"
              ariaLabel="Режим трансляции"
              className="mo-modes"
              items={[
                { id: 'key', label: 'Ключевое' },
                { id: 'en', label: 'Все комментарии (EN)' },
              ]}
              value={m}
              onChange={setMode}
            />
          )}
          {chips && (
            <div className="mo-chips" role="group" aria-label="Какие события показать">
              {FILTERS.map((f) => {
                const n = f.id === 'all' ? null : counts[f.id];
                return (
                  <button
                    key={f.id}
                    type="button"
                    className={cx('mo-chip', filter === f.id && 'is-on')}
                    aria-pressed={filter === f.id}
                    disabled={n === 0}
                    onClick={() => setFilter(f.id)}
                  >
                    {f.label}
                    {n != null && <span className="mo-chip__n">{n}</span>}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
      {m === 'key' ? <KeyFeed items={items} filter={filter} phase={phase} /> : <Commentary id={match.id ?? ''} live={live} />}
    </section>
  );
}

const isGoal = (k: FeedItem['kind']) => k === 'goal' || k === 'own-goal';

/** «Гол!» → «Гол», «Гол с пенальти!» → «Гол с пенальти»: во второй строке, рядом с передачей. */
const goalWord = (t: string) => t.replace(/!$/, '');

const CARD_NOTE: Partial<Record<FeedItem['kind'], string>> = { 'second-yellow': 'вторая жёлтая — удаление', red: 'удаление' };

function KeyFeed({ items, filter, phase }: { items: FeedItem[]; filter: FeedFilter; phase: Phase }) {
  const shown = useMemo(() => filterFeed(items, filter), [items, filter]);
  const fresh = useFresh(items.map((x) => x.key));
  const links = usePlayerLinks();
  if (!items.length) {
    const before = phase === 'scheduled' || phase === 'postponed' || phase === 'cancelled' || phase === 'pending';
    return (
      <EmptyState
        className="mt-state"
        title={before ? 'Трансляция начнётся с первым свистком' : 'Пока без событий'}
        text={before ? 'Голы, карточки и замены появятся здесь по ходу матча' : undefined}
      />
    );
  }
  if (!shown.length) return <p className="mo-none">{filter === 'all' ? 'Пока без событий' : EMPTY_FILTER[filter]}</p>;
  const who = (p: FeedItem['players'][number] | undefined, cls?: string) =>
    p ? <PlayerInline player={{ id: p.id, name: p.name }} size={22} className={cls} {...links} /> : null;
  return (
    <ol className="mo-list mo-list--key" aria-live="polite">
      {shown.map((it) => {
        if (it.divider)
          return (
            <li key={it.key} className={cx('mo-div', fresh.has(it.key) && 'is-fresh')}>
              <span>
                {it.title}
                {it.text && <> · {it.text}</>}
              </span>
            </li>
          );
        const goal = isGoal(it.kind);
        const icon = ICON[it.kind] ? <EventIcon type={ICON[it.kind]!} /> : WHISTLE;
        const crest = it.team?.id != null ? <TeamCrest id={it.team.id} name={it.team.name} size={16} className="mo-crest" /> : null;
        const main = it.players.find((p) => !p.role || p.role === 'вышел');
        const assist = it.players.find((p) => p.role === 'пас');
        const out = it.players.find((p) => p.role === 'ушёл');
        let body: ReactNode;
        if (goal) {
          body = (
            <>
              <span className="mo-line">
                {who(main, 'mo-scorer')}
                {it.score && (
                  <b className="mo-score">
                    {it.score[0]}:{it.score[1]}
                  </b>
                )}
              </span>
              <span className="mo-line mo-sub">
                <span>{goalWord(it.title)}</span>
                {assist && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span>пас</span>
                    {who(assist)}
                  </>
                )}
              </span>
            </>
          );
        } else if (it.kind === 'sub') {
          body = (
            <span className="mo-line">
              <span className="ui-sr">вышел</span>
              {who(main, 'mo-in')}
              {out && (
                <>
                  <span className="mo-swap" aria-hidden="true">
                    ↔
                  </span>
                  <span className="ui-sr">ушёл</span>
                  {who(out, 'mo-out')}
                </>
              )}
              {it.text && <span className="mo-tag">травма</span>}
            </span>
          );
        } else if (it.kind === 'start' || it.kind === 'second') {
          body = <span className="mo-line mo-phase">{it.title}</span>;
        } else {
          // карточки, VAR, незабитый пенальти: игрок, пояснение — приглушённо
          const note = it.kind === 'var' || it.kind === 'penalty-missed' ? it.title : CARD_NOTE[it.kind];
          body = (
            <span className="mo-line">
              {who(main)}
              {note && <span className="mo-note">{note}</span>}
            </span>
          );
        }
        return (
          <li key={it.key} className={cx('mo-row', goal && 'mo-row--goal', fresh.has(it.key) && 'is-fresh')}>
            <span className="mo-min">{it.minute ?? ''}</span>
            <span className="mo-ico">{icon}</span>
            <span className="mo-main">{body}</span>
            {crest}
          </li>
        );
      })}
    </ol>
  );
}

type CmLoad = { kind: 'loading' } | { kind: 'ok'; data: ApiCommentary } | { kind: 'error' };

function Commentary({ id, live }: { id: number | string; live: boolean }) {
  const [st, setSt] = useState<CmLoad>({ kind: 'loading' });
  useEffect(() => {
    let alive = true;
    let timer = 0;
    let ctl: AbortController | null = null;
    const load = async () => {
      ctl?.abort();
      ctl = new AbortController();
      try {
        const r = await fetch(commentaryUrl(id), { signal: ctl.signal });
        const body = r.ok ? ((await r.json()) as ApiCommentary) : null;
        if (!alive) return;
        if (body && Array.isArray(body.items)) setSt({ kind: 'ok', data: body });
        else setSt((s) => (s.kind === 'ok' ? s : { kind: 'error' }));
      } catch (e) {
        if ((e as Error).name !== 'AbortError' && alive) setSt((s) => (s.kind === 'ok' ? s : { kind: 'error' }));
      }
      // в лайве — раз в 30 с и только пока вкладка видна
      if (alive && live) timer = window.setTimeout(tick, POLL_MS);
    };
    const tick = () => {
      if (document.visibilityState === 'visible') void load();
      else timer = window.setTimeout(tick, POLL_MS);
    };
    void load();
    return () => {
      alive = false;
      window.clearTimeout(timer);
      ctl?.abort();
    };
  }, [id, live]);

  const rows = useMemo(() => (st.kind === 'ok' ? commentaryRows(st.data.items) : []), [st]);
  const fresh = useFresh(rows.map((r) => r.key));
  const links = usePlayerLinks();

  if (st.kind === 'loading') return <Skeleton shape="list" rows={5} className="mo-skel" />;
  if (st.kind === 'error' || !rows.length) return <EmptyState className="mt-state" title="Комментариев пока нет" text="Попробуем снова через минуту" />;
  return (
    <>
      <ol className="mo-list" aria-live="polite">
        {rows.map((r) => (
          <CommentaryItem key={r.key} r={r} fresh={fresh.has(r.key)} links={links} />
        ))}
      </ol>
      <p className="mo-src">Текст: Opta via FotMob, на английском</p>
    </>
  );
}

function CommentaryItem({ r, fresh, links }: { r: CommentaryRow; fresh: boolean; links: ReturnType<typeof usePlayerLinks> }) {
  const [open, setOpen] = useState(false);
  const icon = EN_ICON[r.type] ? <EventIcon type={EN_ICON[r.type]!} /> : r.type === 'chance' ? SPARK : r.title ? WHISTLE : null;
  return (
    <li className={cx('ui-card mo-item', r.goal && 'mo-item--goal', fresh && 'is-fresh')}>
      <span className="mo-min">{r.minute ?? ''}</span>
      <div className="mo-body">
        {(r.title || r.players.length > 0) && (
          <div className="mo-head">
            {r.title && (
              <p className="mo-title">
                {icon}
                <span>{r.title}</span>
              </p>
            )}
            {r.players.length > 0 && (
              <span className="mo-players mo-players--r">
                {r.players.map((p) => (
                  <PlayerInline key={p.name} player={{ id: p.id, name: p.name }} size={22} {...links} />
                ))}
              </span>
            )}
          </div>
        )}
        <p className={cx('mo-en', r.long && !open && 'is-clamped')} lang="en">
          {r.text}
        </p>
        {r.long && (
          <button type="button" className="mo-more" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? 'свернуть' : 'ещё'}
          </button>
        )}
      </div>
    </li>
  );
}

