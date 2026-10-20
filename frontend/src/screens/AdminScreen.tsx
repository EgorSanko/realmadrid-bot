import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { retrieveRawInitData } from '@tma.js/sdk-react';
import { LoginButton } from '../components/LoginButton';
import { Player } from '../components/Player';
import { authHeaders, useAuth } from '../lib/auth';
import { ApiError, adminRequest } from '../lib/stream';
import type { AdminStreamState } from '../lib/stream';
import { describeExpiry, formatMsk } from '../lib/linkExpiry';
import { isMixedContent, linkError } from '../lib/linkCheck';
import { AdminStats } from './AdminStats';
import '../styles/admin.css';

const TOKEN_KEY = 'rm-admin-token';

const readToken = () => {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? '';
  } catch {
    return '';
  }
};
const writeToken = (v: string) => {
  try {
    if (v) sessionStorage.setItem(TOKEN_KEY, v);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* приватный режим — токен просто не запомнится */
  }
};

/** initData из Telegram (только внутри мини-аппа). */
function telegramInitData(): string | null {
  if (!document.documentElement.classList.contains('tma')) return null;
  try {
    return retrieveRawInitData() || null;
  } catch {
    return null;
  }
}

type Msg = { kind: 'ok' | 'err'; text: string } | null;

/** Скрытая админка эфира: /admin (нет в нижнем меню). */
export default function AdminScreen() {
  const initData = useMemo(telegramInitData, []);
  const [token, setToken] = useState(readToken);
  const [tokenDraft, setTokenDraft] = useState('');
  const me = useAuth();
  // мини-апп — initData; введённый токен — он; иначе сессия входа через Telegram (cookie / Session),
  // если вошёл админ. Токен остаётся запасным способом.
  const sessionAdmin = me.status === 'user' && me.isAdmin;
  const auth = useMemo((): Record<string, string> | null => {
    if (initData) return { Authorization: `tma ${initData}` };
    if (token) return { 'X-Admin-Token': token };
    if (sessionAdmin) return authHeaders();
    return null;
  }, [initData, token, sessionAdmin]);

  const [state, setState] = useState<AdminStreamState | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [url, setUrl] = useState('');
  const [title, setTitle] = useState('');
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    document.title = 'Эфир — админка';
    const t = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(t);
  }, []);

  const onAuthFail = useCallback(
    (e: unknown) => {
      const text = e instanceof Error ? e.message : 'Нет доступа';
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        setState(null);
        setAuthError(text);
        if (!initData) {
          writeToken('');
          setToken('');
        }
        return true;
      }
      return false;
    },
    [initData],
  );

  // проверка доступа и текущий статус
  useEffect(() => {
    if (!auth) return;
    let alive = true;
    adminRequest<AdminStreamState>('GET', '/api/admin/stream', auth)
      .then((s) => {
        if (!alive) return;
        setAuthError(null);
        setState(s);
        if (s.live && s.url) {
          setUrl((u) => u || s.url!);
          setTitle((t) => t || s.title || '');
          setPreview((p) => p ?? s.url);
        }
      })
      .catch((e) => {
        if (!alive) return;
        if (!onAuthFail(e)) setMsg({ kind: 'err', text: (e as Error).message });
      });
    return () => {
      alive = false;
    };
  }, [auth, onAuthFail]);

  const error = linkError(url);
  const mixed = isMixedContent(url, window.location.protocol);
  const expiry = !error ? describeExpiry(url, now) : null;
  const liveExpiry = state?.live && state.url ? describeExpiry(state.url, now) : null;

  const start = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    setMsg(null);
    if (error || !auth) return;
    setBusy(true);
    try {
      const s = await adminRequest<AdminStreamState>('POST', '/api/admin/stream/start', auth, {
        url: url.trim(),
        title: title.trim() || null,
      });
      setState(s);
      setPreview(s.url);
      setMsg({ kind: 'ok', text: 'Эфир включён — плеер появится у зрителей в течение 20 секунд' });
    } catch (err) {
      if (!onAuthFail(err)) setMsg({ kind: 'err', text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!auth) return;
    setBusy(true);
    setMsg(null);
    try {
      const s = await adminRequest<AdminStreamState>('POST', '/api/admin/stream/stop', auth);
      setState(s);
      setPreview(null);
      setMsg({ kind: 'ok', text: 'Эфир остановлен' });
    } catch (err) {
      if (!onAuthFail(err)) setMsg({ kind: 'err', text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const login = (e: FormEvent) => {
    e.preventDefault();
    const t = tokenDraft.trim();
    if (!t) return;
    setAuthError(null);
    writeToken(t);
    setToken(t);
    setTokenDraft('');
  };

  const logout = () => {
    writeToken('');
    setToken('');
    setState(null);
    setPreview(null);
  };

  // ---------- вход ----------
  if (!auth && !initData && me.status === 'loading') {
    return (
      <main className="admin">
        <header className="topbar">
          <h1 className="topbar__title">Эфир</h1>
        </header>
        <p className="admin-hint admin-pad">Проверяем доступ…</p>
      </main>
    );
  }

  if (!auth || (!state && authError)) {
    return (
      <main className="admin">
        <header className="topbar">
          <h1 className="topbar__title">Эфир</h1>
        </header>
        <section className="admin-card">
          {initData ? (
            <p className="admin-msg admin-msg--err" role="alert">
              {authError ?? 'Нет доступа'}. Админка доступна только владельцу.
            </p>
          ) : (
            <>
              <div className="admin-form">
                {me.status === 'user' && me.user ? (
                  <p className="admin-msg admin-msg--err" role="alert">
                    Вы вошли как {me.user.name} — у этого аккаунта нет доступа к эфиру.
                  </p>
                ) : (
                  <LoginButton hint="Владельцу достаточно войти через Telegram — токен не нужен." />
                )}
              </div>
              <p className="admin-or">или по токену</p>
            <form onSubmit={login} className="admin-form">
              <label className="admin-label" htmlFor="admin-token">
                Админ-токен
              </label>
              <input
                id="admin-token"
                className="admin-input"
                type="password"
                autoComplete="current-password"
                value={tokenDraft}
                onChange={(e) => setTokenDraft(e.target.value)}
                placeholder="Введите токен"
              />
              {authError && (
                <p className="admin-msg admin-msg--err" role="alert">
                  {authError}
                </p>
              )}
              <button type="submit" className="admin-btn admin-btn--gold" disabled={!tokenDraft.trim()}>
                Войти
              </button>
              <p className="admin-hint">Токен хранится только в этой вкладке и забудется после её закрытия.</p>
            </form>
            </>
          )}
        </section>
      </main>
    );
  }

  if (!state) {
    return (
      <main className="admin">
        <header className="topbar">
          <h1 className="topbar__title">Эфир</h1>
        </header>
        <p className="admin-hint admin-pad">{msg ? msg.text : 'Проверяем доступ…'}</p>
      </main>
    );
  }

  // ---------- управление ----------
  return (
    <main className="admin">
      <header className="topbar">
        <h1 className="topbar__title">Эфир</h1>
        {!initData && token && (
          <button type="button" className="admin-link" onClick={logout}>
            Выйти
          </button>
        )}
      </header>

      {/* статистика — только по входу через Telegram (initData или сессия), не по админ-токену */}
      <AdminStats canFetch={!!initData || sessionAdmin} />

      <section className="admin-card admin-status" aria-live="polite">
        {state.live ? (
          <>
            <span className="badge-live">
              <span className="live-dot" />
              ИДЁТ ЭФИР
            </span>
            <p className="admin-status__line">
              {state.title ? <b>{state.title}</b> : 'Без названия'}
              {state.started_at && <span className="muted"> · с {formatMsk(new Date(state.started_at), now)} (МСК)</span>}
            </p>
            <p className="admin-status__url" title={state.url ?? ''}>
              {state.url}
            </p>
            {liveExpiry && <p className={`admin-exp admin-exp--${liveExpiry.level}`}>{liveExpiry.text}</p>}
          </>
        ) : (
          <>
            <span className="admin-off">Эфир выключен</span>
            <p className="admin-hint">Зрители видят «Трансляция появится здесь».</p>
          </>
        )}
      </section>

      <form className="admin-card admin-form" onSubmit={start} noValidate>
        <label className="admin-label" htmlFor="stream-url">
          Ссылка на поток (m3u8)
        </label>
        <textarea
          id="stream-url"
          className="admin-input admin-input--url"
          rows={3}
          inputMode="url"
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder="https://…/chunks.m3u8?…"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setMsg(null);
          }}
          onBlur={() => setTouched(true)}
          aria-invalid={touched && !!error}
          aria-describedby="stream-url-hints"
        />
        <div id="stream-url-hints">
          {touched && error && <p className="admin-msg admin-msg--err">{error}</p>}
          {mixed && (
            <p className="admin-msg admin-msg--warn" role="alert">
              http-ссылка не будет работать на https-сайте: браузер зрителя заблокирует поток. Попросите у поставщика
              ссылку на https://
            </p>
          )}
          {expiry && <p className={`admin-exp admin-exp--${expiry.level}`}>{expiry.text}</p>}
        </div>

        <label className="admin-label" htmlFor="stream-title">
          Название <span className="muted">(необязательно)</span>
        </label>
        <input
          id="stream-title"
          className="admin-input"
          maxLength={200}
          placeholder="Реал Мадрид — Севилья"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />

        {msg && (
          <p className={`admin-msg admin-msg--${msg.kind}`} role={msg.kind === 'err' ? 'alert' : 'status'}>
            {msg.text}
          </p>
        )}

        <div className="admin-actions">
          <button type="submit" className="admin-btn admin-btn--gold" disabled={busy}>
            Начать эфир
          </button>
          <button type="button" className="admin-btn admin-btn--danger" onClick={stop} disabled={busy || !state.live}>
            Остановить
          </button>
        </div>
        <button
          type="button"
          className="admin-btn admin-btn--ghost"
          disabled={!!error}
          onClick={() => {
            setTouched(true);
            if (!error) setPreview(url.trim());
          }}
        >
          Предпросмотр
        </button>
      </form>

      {preview && (
        <section className="admin-preview" aria-label="Предпросмотр">
          <p className="admin-label admin-pad">Предпросмотр</p>
          <Player key={preview} src={preview} title="предпросмотр" />
        </section>
      )}
    </main>
  );
}
