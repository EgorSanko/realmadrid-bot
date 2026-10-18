import { useEffect, useMemo, useRef, useState } from 'react';
import { commentaryUrl, type ApiCommentary, type ApiMatch } from '../../api/match';
import { usePlayerLinks } from '../../lib/playerNav';
import { EmptyState, EventIcon, PlayerInline, Skeleton, Tabs, TeamCrest, type MatchEventType } from '../../ui';
import { cx } from '../../ui/format';
import { commentaryRows, freshKeys, type CommentaryRow } from './feed';
import { has, keyFeed, type FeedItem, type Phase } from './view';
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

/** «Онлайн»: «Ключевое» — наша лента по событиям (по-русски); «Все комментарии» — оригинал Opta (EN). */
export function OnlineTab({ match, phase }: { match: ApiMatch; phase: Phase }) {
  const en = has(match, 'commentary');
  const [mode, setMode] = useState<Mode>('key');
  const m = en ? mode : 'key';
  const live = phase === 'live' || phase === 'halftime';
  return (
    <section aria-label="Онлайн" className="mo">
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
      {m === 'key' ? <KeyFeed match={match} phase={phase} /> : <Commentary id={match.id ?? ''} live={live} />}
    </section>
  );
}

function KeyFeed({ match, phase }: { match: ApiMatch; phase: Phase }) {
  const items = useMemo(() => keyFeed(match), [match]);
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
  return (
    <ol className="mo-list" aria-live="polite">
      {items.map((it) =>
        it.divider ? (
          <li key={it.key} className={cx('mo-div', fresh.has(it.key) && 'is-fresh')}>
            <span>
              {it.title}
              {it.text && <> · {it.text}</>}
            </span>
          </li>
        ) : (
          <li key={it.key} className={cx('ui-card mo-item', (it.kind === 'goal' || it.kind === 'own-goal') && 'mo-item--goal', fresh.has(it.key) && 'is-fresh')}>
            <span className="mo-min">{it.minute ?? ''}</span>
            <div className="mo-body">
              <p className="mo-title">
                {ICON[it.kind] ? <EventIcon type={ICON[it.kind]!} /> : WHISTLE}
                <span>{it.title}</span>
                {it.team?.id != null && <TeamCrest id={it.team.id} name={it.team.name} size={16} className="mo-crest" />}
              </p>
              {it.players.length > 0 && (
                <div className="mo-players">
                  {it.players.map((p) => (
                    <span key={`${p.role ?? ''}${p.name}`} className="mo-player">
                      {p.role && <span className="mo-role">{p.role}</span>}
                      <PlayerInline player={{ id: p.id, name: p.name }} size={24} {...links} />
                    </span>
                  ))}
                </div>
              )}
              {it.text && <p className="mo-text">{it.text}</p>}
            </div>
          </li>
        ),
      )}
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

