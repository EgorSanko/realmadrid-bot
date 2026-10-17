import { useEffect, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import { BOT_PROFILE_LINK, BOT_USERNAME, inMiniApp, signIn } from '../lib/auth';
import { showToast } from '../lib/toast';
import { openExternal } from '../lib/tmaNav';
import { mountTelegramWidget, type WidgetUser } from '../lib/telegramWidget';
import { CodeLogin, TG_ICON } from './CodeLogin';
import '../styles/login.css';

type Mode = 'idle' | 'code' | 'widget';

/**
 * «Войти через Telegram» на сайте. По нажатию — вход по коду через бота (components/CodeLogin.tsx):
 * ничего не грузится с telegram.org, работает и там, где telegram.org не открывается.
 * Запасной путь — ссылка «Другой способ входа»: официальный виджет Telegram, только по нажатию.
 * `autoStart` — сразу показать код (панель входа в шапке ПК уже открыта нажатием).
 * В мини-аппе кнопка не нужна — там вход происходит сам по initData.
 */
export function LoginButton({ hint, compact, autoStart }: { hint?: string; compact?: boolean; autoStart?: boolean }) {
  const [mode, setMode] = useState<Mode>(autoStart ? 'code' : 'idle');

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
      {mode === 'code' && <CodeLogin onAlt={() => setMode('widget')} />}
      {mode === 'widget' && <WidgetLogin onBack={() => setMode('code')} />}
    </div>
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
