import { useCallback, useEffect, useRef, useState } from 'react';
import { BOT_USERNAME } from '../lib/auth';
import { countdown, spacedCode } from '../lib/codeFormat';
import { checkCode, POLL_MS, requestCode, type LoginCode } from '../lib/codeLogin';
import type { QrCode } from '../lib/qr';

type Phase = 'loading' | 'active' | 'expired' | 'error' | 'done';

export const TG_ICON = (
  <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
    <path
      fill="currentColor"
      d="M21.4 3.6 2.9 10.7c-1.3.5-1.2 1.3-.2 1.6l4.7 1.5 1.8 5.6c.2.6.4.8.9.8.4 0 .6-.2.9-.5l2.3-2.2 4.8 3.5c.9.5 1.5.2 1.7-.8l3.1-14.6c.3-1.3-.5-1.9-1.5-1.5zM9.6 14.9l-.3 3.2-1.4-4.6 10.6-6.7z"
    />
  </svg>
);

/** Компьютер с мышью — тогда QR для входа с телефона имеет смысл. */
function desktopPointer(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;
}

/**
 * Вход по коду через бота: «Открыть Telegram» (deep link со «Старт»), 6 цифр для ручной отправки боту,
 * QR на компьютере. Пока код жив — опрос статуса раз в 1,5 с; подтвердили — сессия, тост «Вы вошли как …».
 */
export function CodeLogin({ onAlt }: { onAlt?: () => void }) {
  const [phase, setPhase] = useState<Phase>('loading');
  const [code, setCode] = useState<LoginCode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [copied, setCopied] = useState(false);
  const busy = useRef(false);
  const alive = useRef(true);
  const abort = useRef<AbortController | null>(null);

  const issue = useCallback(async () => {
    setPhase('loading');
    setError(null);
    setCopied(false);
    try {
      const c = await requestCode();
      if (!alive.current) return;
      setCode(c);
      setNow(Date.now());
      setPhase('active');
    } catch (e) {
      if (!alive.current) return;
      setError((e as Error).message || 'Не удалось получить код');
      setPhase('error');
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void issue();
    return () => {
      alive.current = false;
      abort.current?.abort();
    };
  }, [issue]);

  const poll = useCallback(async () => {
    if (busy.current || !alive.current) return;
    busy.current = true;
    const ctl = new AbortController();
    abort.current = ctl;
    try {
      const r = await checkCode(ctl.signal);
      if (!alive.current) return;
      if (r.state === 'ok') {
        setPhase('done');
      } else if (r.state === 'expired') {
        setPhase('expired');
      }
    } catch {
      /* сеть моргнула — спросим в следующий раз */
    } finally {
      busy.current = false;
    }
  }, []);

  // опрос статуса и обратный отсчёт, пока код жив
  useEffect(() => {
    if (phase !== 'active' || !code) return;
    const tick = () => {
      const t = Date.now();
      setNow(t);
      if (t >= code.expiresAt) {
        void poll().then(() => alive.current && setPhase((p) => (p === 'active' ? 'expired' : p)));
      }
    };
    const pollId = window.setInterval(() => void poll(), POLL_MS);
    const tickId = window.setInterval(tick, 1000);
    // вернулись из Telegram во вкладку — спросить сразу, не ждать таймера
    const onVisible = () => {
      if (document.visibilityState === 'visible') void poll();
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onVisible);
    return () => {
      window.clearInterval(pollId);
      window.clearInterval(tickId);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onVisible);
    };
  }, [phase, code, poll]);

  const copy = async () => {
    if (!code) return;
    let ok = false;
    try {
      await navigator.clipboard.writeText(code.code);
      ok = true;
    } catch {
      const ta = document.createElement('textarea');
      ta.value = code.code;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        ok = document.execCommand('copy');
      } catch {
        ok = false;
      }
      ta.remove();
    }
    setCopied(ok);
    if (ok) window.setTimeout(() => alive.current && setCopied(false), 2000);
  };

  const left = code ? code.expiresAt - now : 0;

  return (
    <div className="code-login" data-phase={phase}>
      {phase === 'loading' && (
        <p className="tg-login__note" role="status">
          Получаем код входа…
        </p>
      )}

      {phase === 'error' && (
        <div className="tg-login__fail" role="alert">
          <p className="tg-login__err">{error}</p>
          <button type="button" className="tg-login__retry" onClick={() => void issue()}>
            Попробовать ещё раз
          </button>
        </div>
      )}

      {phase === 'active' && code && (
        <>
          <a className="tg-login__btn code-login__open" href={code.deepLink} target="_blank" rel="noopener noreferrer">
            {TG_ICON}
            Открыть Telegram
          </a>
          <p className="code-login__how">Откроется бот — нажмите в нём «Старт», и вход завершится здесь.</p>

          <div className="code-login__code">
            <span className="code-login__digits" aria-label={`Код входа ${code.code.split('').join(' ')}`}>
              {spacedCode(code.code)}
            </span>
            <button type="button" className="code-login__copy" onClick={() => void copy()}>
              {copied ? 'Скопировано' : 'Скопировать'}
            </button>
          </div>
          <p className="code-login__how">
            или отправьте код боту <b>@{code.bot || BOT_USERNAME}</b>
          </p>

          {desktopPointer() && <QrBlock link={code.deepLink} />}

          <p className="code-login__status" role="status">
            <span className="code-login__spin" aria-hidden="true" />
            Ждём подтверждения в Telegram… <span className="code-login__left">{countdown(left)}</span>
          </p>
        </>
      )}

      {phase === 'expired' && (
        <div className="code-login__expired">
          <p className="tg-login__note" role="status">
            Код истёк — получите новый.
          </p>
          <button type="button" className="tg-login__btn" onClick={() => void issue()}>
            Получить новый код
          </button>
        </div>
      )}

      {phase === 'done' && (
        <p className="tg-login__note" role="status">
          Готово, вы вошли.
        </p>
      )}

      {onAlt && phase !== 'done' && (
        <button type="button" className="tg-login__alt" onClick={onAlt}>
          Другой способ входа
        </button>
      )}
    </div>
  );
}

/** QR со ссылкой входа — отсканировать телефоном. Генератор (lib/qr.ts) — ленивым чанком. */
function QrBlock({ link }: { link: string }) {
  const [qr, setQr] = useState<{ qr: QrCode; path: string } | null>(null);
  useEffect(() => {
    let live = true;
    void import('../lib/qr').then(({ encodeQr, qrPath }) => {
      if (!live) return;
      const q = encodeQr(link);
      setQr({ qr: q, path: qrPath(q) });
    });
    return () => {
      live = false;
    };
  }, [link]);
  const side = qr ? qr.qr.size + 8 : 0;
  return (
    <div className="code-login__qr">
      <div className="code-login__qrimg">
        {qr && (
          <svg viewBox={`0 0 ${side} ${side}`} width="132" height="132" shapeRendering="crispEdges" role="img" aria-label="QR-код для входа с телефона">
            <rect width={side} height={side} fill="#fff" />
            <path d={qr.path} fill="#000" />
          </svg>
        )}
      </div>
      <p className="code-login__qrtext">
        Telegram на телефоне? Наведите камеру на код — откроется бот, нажмите «Старт».
      </p>
    </div>
  );
}
