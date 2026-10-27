import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { LoginButton } from '../../components/LoginButton';
import { useAuth } from '../../lib/auth';
import { levelTitle, plural } from '../../lib/games';
import { t } from '../../lib/i18n';
import type { GameId, LevelCard, WeekBoard } from '../../lib/games';
import { LeaderboardRow, Skeleton } from '../../ui';
import { gamesFetch } from './kit';

/** Шапка раздела «Игры» — одна на прогнозах, викторине и пенальти. */
export function GamesHeader({ aside }: { aside?: ReactNode }) {
  return (
    <header className="topbar">
      <h1 className="topbar__title">{t('Игры')}</h1>
      {aside != null && <span className="gm-top__aside">{aside}</span>}
    </header>
  );
}

/** Карточки уровней: крупные, с делениями сложности и рекордом. */
export function LevelPicker<L extends string>({
  levels,
  best,
  onPick,
  note,
}: {
  levels: LevelCard<L>[];
  best: (level: L) => number | null;
  onPick: (level: L) => void;
  note?: (level: L) => ReactNode;
}) {
  return (
    <div className="gm-levels" role="list">
      {levels.map((l, i) => {
        const b = best(l.id);
        return (
          <button key={l.id} type="button" role="listitem" className={`gm-level gm-level--${i + 1}`} onClick={() => onPick(l.id)}>
            <span className="gm-level__pips" aria-hidden="true">
              {[1, 2, 3, 4].map((p) => (
                <i key={p} className={p <= l.pips ? 'on' : undefined} />
              ))}
            </span>
            <span className="gm-level__title">{l.title}</span>
            <span className="gm-level__text">{l.text}</span>
            {note && <span className="gm-level__note">{note(l.id)}</span>}
            <span className="gm-level__best">{b != null ? <>{t('Рекорд')} <b>{b}</b></> : t('Ещё не играли')}</span>
            <span className="gm-level__go" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M9 6l6 6-6 6" />
              </svg>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** «Лучшие за неделю» по игре: аватары, лучший результат недели, моё место. */
export function WeeklyBoard({ game, ver }: { game: GameId; ver: number }) {
  const auth = useAuth();
  const [board, setBoard] = useState<WeekBoard | null | 'error'>(null);
  useEffect(() => {
    let alive = true;
    setBoard(null);
    gamesFetch<WeekBoard>(`/leaderboard?game=${game}&limit=10`)
      .then((r) => alive && setBoard(r))
      .catch(() => alive && setBoard('error'));
    return () => {
      alive = false;
    };
  }, [game, ver, auth.status]);

  let body: ReactNode;
  if (board === null) body = <Skeleton shape="list" rows={3} />;
  else if (board === 'error') body = <p className="gm-muted">{t('Рейтинг сейчас недоступен — попробуйте позже.')}</p>;
  else if (board.top.length === 0) body = <p className="gm-muted">{t('На этой неделе ещё никто не играл — станьте первым.')}</p>;
  else {
    const meBelow = board.me && board.me.rank != null && !board.top.some((r) => r.is_me);
    body = (
      <div className="gm-board__rows">
        {board.top.map((r) => (
          <LeaderboardRow
            key={`${r.rank}-${r.name}`}
            rank={r.rank}
            name={r.name}
            points={r.score}
            avatarUrl={r.avatar ?? undefined}
            silhouette
            isMe={r.is_me}
            sub={`${levelTitle(game, r.level)} · ${r.played} ${plural(r.played, ['игра', 'игры', 'игр'])}`}
          />
        ))}
        {meBelow && board.me && (
          <LeaderboardRow rank={board.me.rank!} name={t('Вы')} points={board.me.score} avatarUrl={auth.user?.avatar ?? undefined} silhouette isMe />
        )}
      </div>
    );
  }
  const week = board && board !== 'error' ? board.week.label : null;
  return (
    <section className="ui-card gm-board" aria-label={t('Лучшие за неделю')}>
      <div className="gm-board__head">
        <h2 className="gm-h2">{t('Лучшие за неделю')}</h2>
        {week && <span className="gm-muted">{week}</span>}
      </div>
      {body}
      {auth.status === 'anon' && (
        <div className="gm-board__login">
          <p className="gm-muted">{t('Без входа рекорд хранится только на этом устройстве. Войдите, чтобы попасть в рейтинг.')}</p>
          <LoginButton />
        </div>
      )}
    </section>
  );
}

export function ErrorNote({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <div className="gm-error" role="alert">
      <span>{text}</span>
      {onRetry && (
        <button type="button" className="gm-error__retry" onClick={onRetry}>
          {t('Повторить')}
        </button>
      )}
    </div>
  );
}
