import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { LoginButton } from '../../components/LoginButton';
import { UserAvatar } from '../../components/UserAvatar';
import { AuthFetchError, BOT_USERNAME, authFetch, inMiniApp, signOut, useAuth } from '../../lib/auth';
import { historyRow, isSoftUnavailable, pointsTiles } from '../../lib/profile';
import type { League, PredictMe } from '../../lib/profile';
import { copyText, shareLink } from '../../lib/share';
import { inviteLink } from '../../lib/startParam';
import { useSpaLink } from '../../lib/spaLink';
import { useTelegramBackButton } from '../../lib/tmaNav';
import { Card, ErrorState, SectionHeader, Skeleton, TeamCrest, formatDayShort, plural } from '../../ui';
import './profile.css';

const BACK_ICON = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M15 5l-7 7 7 7" />
  </svg>
);

type Load<T> = { kind: 'loading' } | { kind: 'ok'; data: T } | { kind: 'empty' } | { kind: 'error'; message: string };

/** GET с входом; 503/404 (данные ещё не подключены) — пустое состояние, не ошибка. */
function useAuthed<T>(path: string, enabled: boolean): [Load<T>, () => void] {
  const [state, setState] = useState<Load<T>>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const ctl = new AbortController();
    setState({ kind: 'loading' });
    authFetch<T>(path, { signal: ctl.signal })
      .then((data) => setState({ kind: 'ok', data }))
      .catch((e: Error) => {
        if (ctl.signal.aborted) return;
        if (e instanceof AuthFetchError && isSoftUnavailable(e.status)) setState({ kind: 'empty' });
        else setState({ kind: 'error', message: e.message });
      });
    return () => ctl.abort();
  }, [path, enabled, attempt]);
  return [state, useCallback(() => setAttempt((a) => a + 1), [])];
}

export default function ProfileScreen() {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const link = useSpaLink();
  const tma = inMiniApp();
  const flash = (location.state as { flash?: string } | null)?.flash ?? null;

  const goBack = useCallback(() => {
    const idx = (window.history.state as { idx?: number } | null)?.idx;
    if (!idx) navigate('/', { replace: true });
    else navigate(-1);
  }, [navigate]);
  const nativeBack = useTelegramBackButton(goBack);

  useEffect(() => {
    document.title = 'Профиль — Мадридиста';
  }, []);

  const authed = auth.status === 'user';

  return (
    <main className="pf" aria-busy={auth.status === 'loading' || undefined}>
      <header className="pf-top">
        {nativeBack ? (
          <span className="pf-top__gap" aria-hidden="true" />
        ) : (
          <button type="button" className="pf-top__back" aria-label="Назад" onClick={goBack}>
            {BACK_ICON}
          </button>
        )}
        <h1 className="pf-top__title">Профиль</h1>
        <span className="pf-top__gap" aria-hidden="true" />
      </header>

      {flash && (
        <p className="pf-flash" role="status">
          {flash}
        </p>
      )}

      {auth.status === 'loading' && (
        <section className="pf-hero">
          <Skeleton width={84} height={84} radius="50%" />
          <Skeleton width={160} height={18} style={{ marginTop: 14 }} />
        </section>
      )}

      {auth.status === 'anon' && (
        <>
          <section className="pf-hero">
            <UserAvatar src={null} size={84} />
            <p className="pf-hero__name">Болельщик</p>
            <p className="pf-hero__sub">Вы не вошли</p>
          </section>
          <Card className="pf-login">
            {tma ? (
              <p className="pf-muted">Входим через Telegram…</p>
            ) : (
              <LoginButton hint="Войдите через Telegram, чтобы видеть свои очки, прогнозы и лиги. Пароль не нужен." />
            )}
          </Card>
        </>
      )}

      {authed && auth.user && (
        <>
          <section className="pf-hero">
            <UserAvatar src={auth.user.avatar} size={84} />
            <p className="pf-hero__name">{fullName(auth.user.first_name, auth.user.last_name) || auth.user.name}</p>
            {auth.user.username && <p className="pf-hero__sub">@{auth.user.username}</p>}
          </section>
          <Profile link={link} />
          {auth.isAdmin && (
            <Card className="pf-admin">
              <a className="pf-row-link" {...link('/admin')}>
                <span>
                  <b>Управление эфиром</b>
                  <span className="pf-muted pf-block">Включить или остановить трансляцию</span>
                </span>
                <span aria-hidden="true">›</span>
              </a>
            </Card>
          )}
          {!tma && (
            <div className="pf-logout">
              <button
                type="button"
                className="ui-btn ui-btn--outline ui-btn--block"
                onClick={async () => {
                  await signOut();
                }}
              >
                Выйти
              </button>
            </div>
          )}
        </>
      )}
    </main>
  );
}

function fullName(first: string, last: string | null): string {
  return [first, last].filter(Boolean).join(' ').trim();
}

type LinkFn = ReturnType<typeof useSpaLink>;

function Profile({ link }: { link: LinkFn }) {
  const [me, reloadMe] = useAuthed<PredictMe>('/api/predict/me', true);
  const [leagues, reloadLeagues] = useAuthed<{ leagues: League[] }>('/api/predict/leagues', true);
  const data = me.kind === 'ok' ? me.data : null;
  const tiles = useMemo(() => pointsTiles(data), [data]);
  const rows = useMemo(() => (data?.history ?? []).slice(0, 5).map(historyRow), [data]);

  return (
    <>
      <SectionHeader title="Мои очки" page aside={data?.season.label ? `сезон ${data.season.label}` : undefined} />
      {me.kind === 'loading' ? (
        <div className="pf-tiles">
          {tiles.map((t) => (
            <Skeleton key={t.label} height={78} radius={18} />
          ))}
        </div>
      ) : me.kind === 'error' ? (
        <ErrorState className="pf-state" text={me.message} onRetry={reloadMe} />
      ) : (
        <div className="pf-tiles" aria-label="Мои очки">
          {tiles.map((t) => (
            <div key={t.label} className="pf-tile">
              <span className="pf-tile__label">{t.label}</span>
              <span className="pf-tile__value">{t.value}</span>
              {t.sub && <span className="pf-tile__sub">{t.sub}</span>}
            </div>
          ))}
        </div>
      )}

      <SectionHeader
        title="Мои прогнозы"
        page
        aside={data && data.predictions > 0 ? `${data.predictions} ${plural(data.predictions, ['прогноз', 'прогноза', 'прогнозов'])}` : undefined}
      />
      <Card className="pf-card">
        {me.kind === 'loading' ? (
          <Skeleton shape="list" rows={3} />
        ) : rows.length === 0 ? (
          <div className="pf-empty">
            <p className="pf-empty__title">Прогнозов пока нет</p>
            <p className="pf-muted">Угадайте счёт ближайшего матча Реала — за точный счёт 5 очков.</p>
            <a className="ui-btn ui-btn--primary ui-btn--block" {...link('/predict')}>
              Сделать прогноз
            </a>
          </div>
        ) : (
          <ul className="pf-list" aria-label="Последние прогнозы">
            {rows.map((r) => (
              <li key={r.id}>
                <a className="pf-pred" {...link(r.href)}>
                  <span className="pf-pred__date">{formatDayShort(r.kickoff)}</span>
                  <span className="pf-pred__teams">
                    <Crest t={r.home} />
                    <b className="pf-pred__pick" aria-label={`Прогноз ${r.pick}`}>
                      {r.pick}
                    </b>
                    <Crest t={r.away} />
                  </span>
                  <span className="pf-pred__note">{r.note}</span>
                  {r.points != null ? (
                    <span className={`pf-pts pf-pts--${r.tone}`}>+{r.points}</span>
                  ) : (
                    <span className="pf-pts pf-pts--none" aria-hidden="true" />
                  )}
                </a>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <SectionHeader title="Мои лиги" page />
      <Card className="pf-card">
        {leagues.kind === 'loading' ? (
          <Skeleton shape="list" rows={2} />
        ) : leagues.kind === 'error' ? (
          <ErrorState plain text={leagues.message} onRetry={reloadLeagues} />
        ) : leagues.kind === 'empty' || leagues.data.leagues.length === 0 ? (
          <div className="pf-empty">
            <p className="pf-empty__title">Вы пока не в лиге</p>
            <p className="pf-muted">Создайте лигу с друзьями в прогнозах или откройте ссылку-приглашение.</p>
            <a className="ui-btn ui-btn--secondary ui-btn--block" {...link('/predict')}>
              К прогнозам
            </a>
          </div>
        ) : (
          <ul className="pf-list" aria-label="Мои лиги">
            {leagues.data.leagues.map((lg) => (
              <LeagueRow key={lg.id} lg={lg} />
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

function Crest({ t }: { t: { id: number | null; name: string } }) {
  return (
    <span className="pf-crest" title={t.name}>
      {t.id != null ? <TeamCrest id={t.id} name={t.name} size={28} /> : <span className="pf-crest__ph" aria-hidden="true" />}
    </span>
  );
}

function LeagueRow({ lg }: { lg: League }) {
  const url = inviteLink(lg.code, lg.invite_link, BOT_USERNAME);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (!msg) return;
    const t = window.setTimeout(() => setMsg(null), 2500);
    return () => window.clearTimeout(t);
  }, [msg]);
  const text = `Присоединяйся к моей лиге прогнозов «${lg.name}» в Мадридисте`;
  return (
    <li className="pf-league">
      <div className="pf-league__head">
        <b className="pf-league__name">{lg.name}</b>
        <span className="pf-muted">
          {lg.members} {plural(lg.members, ['участник', 'участника', 'участников'])}
          {lg.is_owner ? ' · вы создатель' : ''}
        </span>
      </div>
      <p className="pf-league__link" title={url}>
        {url}
      </p>
      <div className="pf-league__actions">
        <button
          type="button"
          className="ui-btn ui-btn--secondary"
          onClick={async () => setMsg((await copyText(url)) ? 'Ссылка скопирована' : 'Не удалось скопировать')}
        >
          Скопировать
        </button>
        <button
          type="button"
          className="ui-btn ui-btn--secondary"
          onClick={async () => {
            const r = await shareLink(url, text);
            if (r === 'copied') setMsg('Ссылка скопирована');
            if (r === 'failed') setMsg('Не удалось поделиться');
          }}
        >
          Поделиться
        </button>
      </div>
      {msg && (
        <p className="pf-league__msg" role="status">
          {msg}
        </p>
      )}
    </li>
  );
}
