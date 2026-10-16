import { useCallback, useEffect, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import type Hls from 'hls.js';
import type { ErrorData } from 'hls.js';
import { viewport } from '@tma.js/sdk-react';
import '../styles/player.css';

type Phase = 'loading' | 'playing' | 'paused' | 'error' | 'ended';

/** Паузы перед переподключением после фатальной сетевой ошибки hls.js. */
const RECONNECT_MS = [2000, 4000, 8000];
const HIDE_CONTROLS_MS = 3000;

type WebkitVideo = HTMLVideoElement & { webkitEnterFullscreen?: () => void };
type WebkitEl = HTMLElement & { webkitRequestFullscreen?: () => void };
type WebkitDoc = Document & { webkitFullscreenElement?: Element | null; webkitExitFullscreen?: () => void };

/**
 * Нативный HLS — на Apple WebKit (iPhone/iPad, Safari, WKWebView Telegram), где
 * canPlayType('application/vnd.apple.mpegurl') отвечает «maybe».
 * Chrome 14x+ на Windows/Android тоже стал отвечать «maybe», но там берём hls.js:
 * у него наше восстановление после ошибок и предсказуемое поведение в WebView.
 * Если MSE нет вовсе, а нативный HLS заявлен — используем нативный.
 */
function prefersNativeHls(video: HTMLVideoElement): boolean {
  if (!video.canPlayType('application/vnd.apple.mpegurl')) return false;
  const hasMse = 'MediaSource' in window || 'ManagedMediaSource' in window;
  const ua = navigator.userAgent;
  const appleWebKit =
    /iP(hone|ad|od)/.test(ua) ||
    (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) ||
    (/AppleWebKit\//.test(ua) && !/(Chrome|Chromium|Android|Edg|OPR|SamsungBrowser)\//.test(ua));
  return appleWebKit || !hasMse;
}

const fullscreenElement = () =>
  document.fullscreenElement ?? (document as WebkitDoc).webkitFullscreenElement ?? null;

interface Props {
  src: string;
  /** подпись для скринридера */
  title?: string | null;
}

/**
 * HLS-плеер эфира.
 * Safari/iOS (canPlayType m3u8) — нативный HLS; остальные — hls.js, подгружается отдельным
 * чанком только при монтировании плеера (т. е. только когда эфир включён).
 * Ссылка передаётся как есть: query-строка (session id, token) не трогается,
 * сегменты запрашиваются ровно так, как их отдаёт плейлист.
 */
export function Player({ src, title }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [muted, setMuted] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [controlsOn, setControlsOn] = useState(true);
  const [fs, setFs] = useState<'off' | 'native' | 'css'>('off');
  const hideTimer = useRef(0);

  // ---------- загрузка потока ----------
  useEffect(() => {
    const video = videoRef.current as WebkitVideo;
    let cancelled = false;
    let hls: Hls | null = null;
    let reconnectTimer = 0;
    let usingHlsJs = false;

    setPhase('loading');

    const tryPlay = () => {
      video.play().catch((e: unknown) => {
        if (cancelled || (e as Error)?.name === 'AbortError') return;
        // браузер не дал автозапуск даже без звука — ждём нажатия
        setPhase((p) => (p === 'loading' ? 'paused' : p));
      });
    };

    const fail = () => {
      if (cancelled) return;
      hls?.destroy();
      hls = null;
      setPhase('error');
    };

    const startHlsJs = async () => {
      usingHlsJs = true;
      let HlsCtor: typeof Hls;
      try {
        HlsCtor = (await import('hls.js')).default;
      } catch {
        fail();
        return;
      }
      if (cancelled) return;
      if (!HlsCtor.isSupported()) {
        fail();
        return;
      }
      let netTries = 0;
      let mediaTries = 0;
      const h = new HlsCtor({
        backBufferLength: 30,
        liveDurationInfinity: true,
      });
      hls = h;
      h.on(HlsCtor.Events.MANIFEST_PARSED, tryPlay);
      h.on(HlsCtor.Events.FRAG_BUFFERED, () => {
        netTries = 0;
        mediaTries = 0;
      });
      h.on(HlsCtor.Events.ERROR, (_e, data: ErrorData) => {
        if (!data.fatal || cancelled) return;
        if (data.type === HlsCtor.ErrorTypes.MEDIA_ERROR) {
          mediaTries += 1;
          if (mediaTries === 1) h.recoverMediaError();
          else if (mediaTries === 2) {
            h.swapAudioCodec();
            h.recoverMediaError();
          } else fail();
          return;
        }
        if (data.type === HlsCtor.ErrorTypes.NETWORK_ERROR && netTries < RECONNECT_MS.length) {
          const delay = RECONNECT_MS[netTries];
          netTries += 1;
          setPhase('loading');
          window.clearTimeout(reconnectTimer);
          reconnectTimer = window.setTimeout(() => {
            if (cancelled || hls !== h) return;
            h.loadSource(src); // заново плейлист — переподключение к эфиру
          }, delay);
          return;
        }
        fail();
      });
      h.loadSource(src);
      h.attachMedia(video);
    };

    const onNativeError = () => {
      if (cancelled || usingHlsJs) return;
      // нативный HLS не справился (бывает на Android) — пробуем hls.js, если есть MSE
      if ('MediaSource' in window || 'ManagedMediaSource' in window) {
        video.removeAttribute('src');
        video.load();
        void startHlsJs();
      } else fail();
    };

    video.muted = true;
    setMuted(true);

    if (prefersNativeHls(video)) {
      video.addEventListener('error', onNativeError);
      video.src = src;
      tryPlay();
    } else {
      void startHlsJs();
    }

    return () => {
      cancelled = true;
      window.clearTimeout(reconnectTimer);
      video.removeEventListener('error', onNativeError);
      hls?.destroy();
      hls = null;
      video.removeAttribute('src');
      video.load();
    };
  }, [src, attempt]);

  // ---------- события видео ----------
  useEffect(() => {
    const v = videoRef.current!;
    const on: Record<string, () => void> = {
      playing: () => setPhase('playing'),
      pause: () => setPhase((p) => (p === 'playing' || p === 'loading' ? (v.ended ? 'ended' : 'paused') : p)),
      waiting: () => setPhase((p) => (p === 'playing' ? 'loading' : p)),
      ended: () => setPhase('ended'),
      volumechange: () => setMuted(v.muted),
    };
    for (const [k, f] of Object.entries(on)) v.addEventListener(k, f);
    return () => {
      for (const [k, f] of Object.entries(on)) v.removeEventListener(k, f);
    };
  }, []);

  // ---------- полноэкранный режим ----------
  useEffect(() => {
    const sync = () => setFs((cur) => (fullscreenElement() ? 'native' : cur === 'native' ? 'off' : cur));
    document.addEventListener('fullscreenchange', sync);
    document.addEventListener('webkitfullscreenchange', sync);
    return () => {
      document.removeEventListener('fullscreenchange', sync);
      document.removeEventListener('webkitfullscreenchange', sync);
    };
  }, []);

  const tgFullscreen = (on: boolean) => {
    try {
      if (on && viewport.requestFullscreen.isAvailable() && !viewport.isFullscreen()) {
        viewport.requestFullscreen().catch(() => {});
      } else if (!on && viewport.exitFullscreen.isAvailable() && viewport.isFullscreen()) {
        viewport.exitFullscreen().catch(() => {});
      }
    } catch {
      /* не в Telegram или старая версия клиента */
    }
  };

  const toggleFullscreen = useCallback(() => {
    const wrap = wrapRef.current as WebkitEl;
    const video = videoRef.current as WebkitVideo;
    if (fs !== 'off') {
      if (fullscreenElement()) {
        if (document.exitFullscreen) document.exitFullscreen().catch(() => {});
        else (document as WebkitDoc).webkitExitFullscreen?.();
      }
      tgFullscreen(false);
      setFs('off');
      return;
    }
    // вызов — синхронно в обработчике нажатия, иначе браузер не даст fullscreen
    if (wrap.requestFullscreen) {
      wrap
        .requestFullscreen()
        .then(() => {
          const o = screen.orientation as ScreenOrientation & { lock?: (o: string) => Promise<void> };
          o?.lock?.('landscape').catch(() => {});
        })
        .catch(() => setFs('css')); // WebView без Fullscreen API — растягиваем плеер стилями
      tgFullscreen(true);
    } else if (wrap.webkitRequestFullscreen) {
      wrap.webkitRequestFullscreen();
      tgFullscreen(true);
    } else if (video.webkitEnterFullscreen) {
      video.webkitEnterFullscreen(); // iPhone: системный плеер
    } else {
      setFs('css');
      tgFullscreen(true);
    }
  }, [fs]);

  // ---------- кнопки ----------
  const showControls = useCallback(() => {
    setControlsOn(true);
    window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => setControlsOn(false), HIDE_CONTROLS_MS);
  }, []);

  useEffect(() => {
    if (phase !== 'playing') {
      window.clearTimeout(hideTimer.current);
      setControlsOn(true);
    } else showControls();
    return () => window.clearTimeout(hideTimer.current);
  }, [phase, showControls]);

  const togglePlay = () => {
    const v = videoRef.current!;
    if (v.paused) {
      setPhase('loading');
      v.play().catch(() => setPhase('paused'));
    } else v.pause();
  };

  const toggleMute = () => {
    const v = videoRef.current!;
    v.muted = !v.muted;
    if (!v.muted && v.volume === 0) v.volume = 1;
    if (v.paused && phase !== 'error' && phase !== 'ended') v.play().catch(() => {});
  };

  const onSurfaceTap = (e: ReactPointerEvent) => {
    if ((e.target as HTMLElement).closest('button')) return;
    if (phase !== 'playing') return;
    if (controlsOn) {
      window.clearTimeout(hideTimer.current);
      setControlsOn(false);
    } else showControls();
  };

  const retry = () => setAttempt((n) => n + 1);
  const playing = phase === 'playing';
  const busy = phase === 'loading';

  return (
    <div
      ref={wrapRef}
      className={`player${fs !== 'off' ? ' player--fs' : ''}${fs === 'css' ? ' player--css-fs' : ''}${controlsOn ? '' : ' player--idle'}`}
      data-phase={phase}
      onPointerUp={onSurfaceTap}
      role="region"
      aria-label={title ? `Трансляция: ${title}` : 'Трансляция'}
    >
      <svg className="player__pitch" viewBox="0 0 390 219" aria-hidden="true" preserveAspectRatio="xMidYMid slice">
        <rect x="20" y="16" width="350" height="187" />
        <line x1="195" y1="16" x2="195" y2="203" />
        <circle cx="195" cy="110" r="30" />
        <rect x="20" y="66" width="44" height="88" />
        <rect x="326" y="66" width="44" height="88" />
      </svg>

      <video ref={videoRef} className="player__video" playsInline muted autoPlay preload="auto" />

      <div className="player__badge badge-live">
        <span className="live-dot" />
        LIVE
      </div>

      {muted && (phase === 'playing' || phase === 'loading') && (
        <button type="button" className="player__unmute" onClick={toggleMute}>
          <SoundIcon muted />
          Включить звук
        </button>
      )}

      {busy && <div className="player__spinner" role="status" aria-label="Загрузка трансляции" />}

      {phase === 'paused' && (
        <button type="button" className="player__bigplay" onClick={togglePlay} aria-label="Смотреть">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M8 5v14l11-7z" fill="currentColor" />
          </svg>
        </button>
      )}

      {(phase === 'error' || phase === 'ended') && (
        <div className="player__msg" role="alert">
          <p>{phase === 'error' ? 'Не удалось загрузить трансляцию' : 'Трансляция закончилась'}</p>
          <button type="button" className="player__retry" onClick={retry}>
            Повторить
          </button>
        </div>
      )}

      <div className="player__bar">
        <button type="button" onClick={togglePlay} aria-label={playing || busy ? 'Пауза' : 'Смотреть'} disabled={phase === 'error' || phase === 'ended'}>
          {playing || busy ? (
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <rect x="6" y="5" width="4" height="14" rx="1" />
              <rect x="14" y="5" width="4" height="14" rx="1" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M8 5v14l11-7z" />
            </svg>
          )}
        </button>
        <button type="button" onClick={toggleMute} aria-label={muted ? 'Включить звук' : 'Выключить звук'} aria-pressed={!muted}>
          <SoundIcon muted={muted} />
        </button>
        <span className="player__spacer" />
        <button type="button" onClick={toggleFullscreen} aria-label={fs !== 'off' ? 'Свернуть' : 'На весь экран'}>
          {fs !== 'off' ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}

function SoundIcon({ muted }: { muted: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 9v6h4l5 4V5L8 9z" />
      {muted ? <path d="M16.5 9.5l5 5M21.5 9.5l-5 5" /> : <path d="M16 9a4 4 0 010 6M18.5 6.5a8 8 0 010 11" />}
    </svg>
  );
}
