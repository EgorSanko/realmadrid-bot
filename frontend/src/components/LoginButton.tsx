import { useEffect, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import { BOT_PROFILE_LINK, BOT_USERNAME, inMiniApp, signIn } from '../lib/auth';
import { openExternal } from '../lib/tmaNav';
import { mountTelegramWidget, type WidgetUser } from '../lib/telegramWidget';
import '../styles/login.css';

type Phase = 'idle' | 'loading' | 'ready' | 'sending' | 'failed';

const TG_ICON = (
  <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
    <path
      fill="currentColor"
      d="M21.4 3.6 2.9 10.7c-1.3.5-1.2 1.3-.2 1.6l4.7 1.5 1.8 5.6c.2.6.4.8.9.8.4 0 .6-.2.9-.5l2.3-2.2 4.8 3.5c.9.5 1.5.2 1.7-.8l3.1-14.6c.3-1.3-.5-1.9-1.5-1.5zM9.6 14.9l-.3 3.2-1.4-4.6 10.6-6.7z"
    />
  </svg>
);

/**
 * «Войти через Telegram» на сайте. Скрипт виджета грузится только по нажатию;
 * не загрузился за 8 с — сообщение и запасной путь «Открыть в Telegram» (там вход автоматический).
 * В мини-аппе кнопка не нужна — там вход происходит сам.
 */
export function LoginButton({ hint, compact, autoStart }: { hint?: string; compact?: boolean; autoStart?: boolean }) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const slot = useRef<HTMLDivElement>(null);
  const cancel = useRef<(() => void) | null>(null);

  useEffect(() => () => cancel.current?.(), []);

  // в шапке сайта кнопка уже нажата (открыла панель входа) — сразу грузим виджет
  const startRef = useRef<() => void>(() => {});
  useEffect(() => {
    if (autoStart && !inMiniApp()) startRef.current();
  }, [autoStart]);

  if (inMiniApp()) return null;

  const start = async () => {
    if (!slot.current) return;
    setError(null);
    setPhase('loading');
    const onAuth = async (u: WidgetUser) => {
      setPhase('sending');
      try {
        await signIn(u as unknown as Record<string, unknown>);
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

  startRef.current = () => void start();

  const openInTelegram = (e: MouseEvent<HTMLAnchorElement>) => {
    if (openExternal(BOT_PROFILE_LINK)) e.preventDefault();
  };

  return (
    <div className={`tg-login${compact ? ' tg-login--compact' : ''}`}>
      {hint && phase === 'idle' && <p className="tg-login__hint">{hint}</p>}
      {(phase === 'idle' || phase === 'loading') && (
        <button type="button" className="tg-login__btn" onClick={start} disabled={phase === 'loading'} aria-busy={phase === 'loading'}>
          {TG_ICON}
          {phase === 'loading' ? 'Загружаем вход Telegram…' : 'Войти через Telegram'}
        </button>
      )}
      {/* сюда виджет Telegram вставляет свою кнопку */}
      <div ref={slot} className="tg-login__widget" hidden={phase !== 'ready' && phase !== 'sending'} />
      {phase === 'ready' && <p className="tg-login__note">Нажмите кнопку Telegram и подтвердите вход</p>}
      {phase === 'sending' && <p className="tg-login__note" role="status">Входим…</p>}
      {error && (
        <p className="tg-login__err" role="alert">
          {error}
        </p>
      )}
      {phase === 'failed' && (
        <div className="tg-login__fail" role="alert">
          <p className="tg-login__err">
            Telegram не отвечает — вход через сайт сейчас недоступен. Откройте приложение в Telegram: там вход
            произойдёт автоматически.
          </p>
          <a className="tg-login__btn" href={BOT_PROFILE_LINK} target="_blank" rel="noopener noreferrer" onClick={openInTelegram}>
            {TG_ICON}
            Открыть в Telegram
          </a>
          <button type="button" className="tg-login__retry" onClick={start}>
            Попробовать ещё раз
          </button>
        </div>
      )}
      {(phase === 'ready' || phase === 'sending') && (
        <a className="tg-login__alt" href={BOT_PROFILE_LINK} target="_blank" rel="noopener noreferrer">
          Не получается? Открыть в Telegram
        </a>
      )}
    </div>
  );
}
