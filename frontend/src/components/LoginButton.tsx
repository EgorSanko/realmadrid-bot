import { useEffect, useRef, useState } from 'react';
import type { FormEvent, MouseEvent } from 'react';
import { BOT_PROFILE_LINK, BOT_USERNAME, inMiniApp, reviewSignIn, signIn } from '../lib/auth';
import { isNativeApp } from '../lib/shell';
import { showToast } from '../lib/toast';
import { openExternal } from '../lib/tmaNav';
import { mountTelegramWidget, type WidgetUser } from '../lib/telegramWidget';
import { CodeLogin, TG_ICON } from './CodeLogin';
import '../styles/login.css';

type Mode = 'idle' | 'code' | 'widget' | 'review';

/**
 * «Войти через Telegram» на сайте. По нажатию — вход по коду через бота (components/CodeLogin.tsx):
 * ничего не грузится с telegram.org, работает и там, где telegram.org не открывается.
 * Запасной путь — ссылка «Другой способ входа»: официальный виджет Telegram, только по нажатию.
 * `autoStart` — сразу показать код (панель входа в шапке ПК уже открыта нажатием).
 * В мини-аппе кнопка не нужна — там вход происходит сам по initData.
 * В приложении из RuStore виджета нет (в WebView он не работает: «Bot domain invalid»), зато есть
 * «У меня есть код доступа» (в профиле) — поле для постоянного кода проверки (модератор магазина не может войти через Telegram).
 */
export function LoginButton({
  hint,
  compact,
  autoStart,
  accessCode,
}: {
  hint?: string;
  compact?: boolean;
  autoStart?: boolean;
  /** показать «У меня есть код доступа» (только в приложении, только в профиле) */
  accessCode?: boolean;
}) {
  const [mode, setMode] = useState<Mode>(autoStart ? 'code' : 'idle');
  const native = isNativeApp();

  if (inMiniApp()) return null;

  return (
    <div className={`tg-login${compact ? ' tg-login--compact' : ''}`}>
      {hint && mode === 'idle' && <p className="tg-login__hint">{hint}</p>}
      {mode === 'idle' && (
        <button type="button" className="tg-login__btn" onClick={() => setMode('code')}>
          {TG_ICON}
          Войти через Telegram
        </button>
      )}
      {mode === 'code' && <CodeLogin onAlt={native ? undefined : () => setMode('widget')} />}
      {mode === 'widget' && !native && <WidgetLogin onBack={() => setMode('code')} />}
      {mode === 'review' && <ReviewLogin onBack={() => setMode('idle')} />}
      {native && accessCode && mode !== 'review' && (
        <button type="button" className="tg-login__alt" onClick={() => setMode('review')}>
          У меня есть код доступа
        </button>
      )}
    </div>
  );
}

/** Вход постоянным кодом доступа (для проверки приложения в магазине): поле ввода и «Войти». */
function ReviewLogin({ onBack }: { onBack: () => void }) {
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const st = await reviewSignIn(code.trim());
      showToast(st.user ? `Вы вошли как ${st.user.name}` : 'Вы вошли');
    } catch (err) {
      setError((err as Error).message || 'Не удалось войти');
      setBusy(false);
    }
  };

  return (
    <form className="review-login" onSubmit={(e) => void submit(e)}>
      <label className="review-login__label" htmlFor="review-code">
        Код доступа
      </label>
      <input
        id="review-code"
        className="review-login__input"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        autoComplete="off"
        autoCapitalize="characters"
        autoCorrect="off"
        spellCheck={false}
        inputMode="text"
        maxLength={40}
        placeholder="XXXX-XXXX-XXXX"
        autoFocus
      />
      {error && (
        <p className="tg-login__err" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="tg-login__btn" disabled={busy || !code.trim()}>
        {busy ? 'Входим…' : 'Войти'}
      </button>
      <button type="button" className="tg-login__alt" onClick={onBack}>
        Войти через Telegram
      </button>
    </form>
  );
}

type Phase = 'loading' | 'ready' | 'sending' | 'failed';

/**
 * Официальный Telegram Login Widget — запасной способ. Скрипт с telegram.org грузится только после
 * нажатия «Другой способ входа»; не загрузился за 8 с — сообщение и «Открыть в Telegram».
 */
function WidgetLogin({ onBack }: { onBack: () => void }) {
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<string | null>(null);
  const slot = useRef<HTMLDivElement>(null);
  const cancel = useRef<(() => void) | null>(null);

  const start = async () => {
    if (!slot.current) return;
    cancel.current?.();
    setError(null);
    setPhase('loading');
    const onAuth = async (u: WidgetUser) => {
      setPhase('sending');
      try {
        const st = await signIn(u as unknown as Record<string, unknown>);
        if (st.user) showToast(`Вы вошли как ${st.user.name}`);
        cancel.current?.();
        cancel.current = null;
      } catch (e) {
        setError((e as Error).message || 'Не удалось войти');
        setPhase('ready');
      }
    };
    const w = mountTelegramWidget(slot.current, BOT_USERNAME, onAuth);
    cancel.current = w.cancel;
    try {
      await w.loaded;
      setPhase((p) => (p === 'loading' ? 'ready' : p));
    } catch {
      w.cancel();
      cancel.current = null;
      setPhase('failed');
    }
  };

  const startRef = useRef(start);
  startRef.current = start;
  useEffect(() => {
    void startRef.current();
    return () => cancel.current?.();
  }, []);

  const openInTelegram = (e: MouseEvent<HTMLAnchorElement>) => {
    if (openExternal(BOT_PROFILE_LINK)) e.preventDefault();
  };

  return (
    <>
      {phase === 'loading' && (
        <p className="tg-login__note" role="status">
          Загружаем вход Telegram…
        </p>
      )}
      {/* сюда виджет Telegram вставляет свою кнопку */}
      <div ref={slot} className="tg-login__widget" hidden={phase !== 'ready' && phase !== 'sending'} />
      {phase === 'ready' && <p className="tg-login__note">Нажмите кнопку Telegram и подтвердите вход</p>}
      {phase === 'sending' && (
        <p className="tg-login__note" role="status">
          Входим…
        </p>
      )}
      {error && (
        <p className="tg-login__err" role="alert">
          {error}
        </p>
      )}
      {phase === 'failed' && (
        <div className="tg-login__fail" role="alert">
          <p className="tg-login__err">
            Виджет Telegram не загрузился — telegram.org сейчас недоступен. Войдите по коду или откройте приложение в
            Telegram: там вход произойдёт автоматически.
          </p>
          <a className="tg-login__btn" href={BOT_PROFILE_LINK} target="_blank" rel="noopener noreferrer" onClick={openInTelegram}>
            {TG_ICON}
            Открыть в Telegram
          </a>
          <button type="button" className="tg-login__retry" onClick={() => void start()}>
            Попробовать ещё раз
          </button>
        </div>
      )}
      <button type="button" className="tg-login__alt" onClick={onBack}>
        Войти по коду
      </button>
    </>
  );
}
