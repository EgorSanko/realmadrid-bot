import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from 'react';
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

/** Телефон: сенсорный экран и короткая сторона меньше 600 px (планшеты и ПК — нет). */
const isPhone = () =>
  window.matchMedia('(pointer: coarse)').matches && Math.min(screen.width, screen.height) < 600;

type LockableOrientation = ScreenOrientation & { lock?: (o: string) => Promise<void>; unlock?: () => void };
const orientation = () => (screen.orientation as LockableOrientation | undefined) ?? undefined;

/** Громкость меняется программно? На iPhone/iPad volume только для чтения — там громкость кнопками телефона. */
const canSetVolume = (() => {
  let r: boolean | null = null;
  return () => {
    if (r == null) {
      try {
        const t = document.createElement('video');
        t.volume = 0.5;
        r = Math.abs(t.volume - 0.5) < 0.01;
      } catch {
        r = false;
      }
    }
    return r;
  };
})();

const VOL_KEY = 'rmVolume';
function savedVolume(): number {
  try {
    const n = Number(localStorage.getItem(VOL_KEY));
    if (Number.isFinite(n) && n > 0 && n <= 1) return n;
  } catch {
    /* хранилище недоступно */
  }
  return 1;
}
function saveVolume(n: number) {
  try {
    localStorage.setItem(VOL_KEY, String(n));
  } catch {
    /* хранилище недоступно */
  }
}

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
  const [volume, setVolume] = useState(savedVolume);
  const volumeOk = canSetVolume();
  const [attempt, setAttempt] = useState(0);
  const [controlsOn, setControlsOn] = useState(true);
  const [fs, setFs] = useState<'off' | 'native' | 'css'>('off');
  /** на телефоне в полном экране картинка всегда горизонтальная: если сам экран
   *  остаётся вертикальным (Telegram, iPhone, запрет поворота) — поворачиваем сцену CSS-ом */
  const [rotate, setRotate] = useState(false);
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
    if (canSetVolume()) video.volume = savedVolume();

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
      volumechange: () => {
        setMuted(v.muted);
        setVolume(v.volume);
      },
    };
    for (const [k, f] of Object.entries(on)) v.addEventListener(k, f);
    return () => {
      for (const [k, f] of Object.entries(on)) v.removeEventListener(k, f);
    };
  }, []);

  // ---------- полноэкранный режим ----------
  // Схема одна для всех устройств:
  //  ПК            — Fullscreen API на блоке плеера (стандартный или webkit);
  //  Android Chrome — Fullscreen API + попытка повернуть экран (orientation.lock);
  //  Telegram, iPhone, WebView без API — плеер растягивается стилями на весь экран,
  //                   в Telegram вдобавок разворачивается само мини-приложение.
  //  На телефоне, пока экран вертикальный, сцена плеера повёрнута на 90° (см. player.css).
  useEffect(() => {
    const sync = () =>
      setFs((cur) => {
        if (fullscreenElement()) return 'native';
        if (cur === 'native') {
          // вышли системным жестом/Esc — вернуть экран и мини-апп в обычное состояние
          orientation()?.unlock?.();
          tgFullscreen(false);
          setRotate(false);
          return 'off';
        }
        return cur;
      });
    document.addEventListener('fullscreenchange', sync);
    document.addEventListener('webkitfullscreenchange', sync);
    return () => {
      document.removeEventListener('fullscreenchange', sync);
      document.removeEventListener('webkitfullscreenchange', sync);
    };
  }, []);

  // в режиме «на стилях» системная кнопка «Назад» должна сворачивать плеер, а не уводить со страницы;
  // и страница под плеером не должна прокручиваться
  useEffect(() => {
    if (fs !== 'css') return;
    const root = document.documentElement;
    const prevOverflow = root.style.overflow;
    root.style.overflow = 'hidden';
    history.pushState({ playerFs: true }, '');
    const onPop = () => {
      tgFullscreen(false);
      setRotate(false);
      setFs('off');
    };
    window.addEventListener('popstate', onPop);
    return () => {
      root.style.overflow = prevOverflow;
      window.removeEventListener('popstate', onPop);
    };
  }, [fs]);

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
      orientation()?.unlock?.();
      tgFullscreen(false);
      setRotate(false);
      // «на стилях» мы сами добавили запись в историю — снимаем её, выход сделает обработчик popstate
      if (fs === 'css' && history.state?.playerFs) history.back();
      else setFs('off');
      return;
    }
    const phone = isPhone();
    // вертикальный ролик (редкость) не поворачиваем
    setRotate(phone && !(video.videoHeight > video.videoWidth));
    const cssFallback = () => {
      setFs('css');
      tgFullscreen(true);
    };
    // вызов — синхронно в обработчике нажатия, иначе браузер не даст fullscreen
    if (wrap.requestFullscreen) {
      wrap
        .requestFullscreen({ navigationUI: 'hide' })
        .then(() => {
          // Android Chrome умеет повернуть экран сам; где не умеет — сцену повернёт CSS
          if (phone) orientation()?.lock?.('landscape').catch(() => {});
        })
        .catch(cssFallback); // Telegram Android / WebView без Fullscreen API
      tgFullscreen(true);
    } else if (wrap.webkitRequestFullscreen) {
      wrap.webkitRequestFullscreen(); // Safari на Mac и iPad
      tgFullscreen(true);
      // если WebKit молча не перешёл в полный экран — растягиваем стилями
      window.setTimeout(() => {
        if (!fullscreenElement()) setFs((cur) => (cur === 'off' ? 'css' : cur));
      }, 400);
    } else if (phone || !video.webkitEnterFullscreen) {
      // iPhone (Safari и Telegram): системный плеер не поворачивается при блокировке поворота,
      // поэтому свой полный экран на стилях — с горизонтальной картинкой всегда
      cssFallback();
    } else {
      video.webkitEnterFullscreen();
    }
  }, [fs]);

  // ---------- кнопки ----------
  // мышь над панелью кнопок — кнопки не прячем (объявлено здесь: нужно showControls)
  const overBar = useRef(false);
  const barRef = useRef<HTMLDivElement>(null);
  const showControls = useCallback(() => {
    setControlsOn(true);
    window.clearTimeout(hideTimer.current);
    if (overBar.current) return;
    hideTimer.current = window.setTimeout(() => {
      if (!overBar.current) setControlsOn(false);
    }, HIDE_CONTROLS_MS);
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
    if (!v.muted && v.volume === 0) v.volume = savedVolume(); // после ползунка в ноль — прежняя громкость
    if (v.paused && phase !== 'error' && phase !== 'ended') v.play().catch(() => {});
  };

  // громкость берём у самого видео: состояние React между быстрыми нажатиями ещё не обновилось
  const currentVolume = () => {
    const v = videoRef.current!;
    return v.muted ? 0 : v.volume;
  };
  /** ползунок и стрелки ↑/↓: 0 — то же, что выключить звук; громкость запоминается между заходами */
  const changeVolume = (n: number) => {
    const v = videoRef.current!;
    const x = Math.min(1, Math.max(0, Math.round(n * 100) / 100));
    v.volume = x;
    v.muted = x === 0;
    if (x > 0) saveVolume(x);
    if (x > 0 && v.paused && phase !== 'error' && phase !== 'ended') v.play().catch(() => {});
  };

  // колесо мыши над кнопкой звука/ползунком — громкость (свой слушатель: в React wheel пассивный,
  // страницу под плеером тогда не остановить)
  const volRef = useRef<HTMLDivElement>(null);
  const wheelRef = useRef<(dy: number) => void>(() => {});
  wheelRef.current = (dy) => changeVolume(currentVolume() + (dy < 0 ? 0.05 : -0.05));
  useEffect(() => {
    const el = volRef.current;
    if (!el || !volumeOk) return;
    const onWheel = (e: WheelEvent) => {
      if (e.deltaY === 0) return;
      e.preventDefault();
      wheelRef.current(e.deltaY);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [volumeOk]);

  // Мышь (ПК): движение показывает кнопки и курсор, клик — пауза/продолжить (как в YouTube),
  // двойной клик — во весь экран. Касание (телефон): тап показывает/прячет кнопки.
  const onSurfaceTap = (e: ReactPointerEvent) => {
    if ((e.target as HTMLElement).closest('button, input')) return;
    if (e.pointerType === 'mouse') {
      if (e.button !== 0) return;
      if (phase === 'playing' || phase === 'paused') togglePlay();
      showControls();
      return;
    }
    if (phase !== 'playing') return;
    if (controlsOn) {
      window.clearTimeout(hideTimer.current);
      setControlsOn(false);
    } else showControls();
  };
  const onSurfaceMove = (e: ReactPointerEvent) => {
    if (e.pointerType !== 'mouse') return;
    // над полосой кнопок (по координатам: сама полоса прозрачна для мыши между кнопками)
    const r = barRef.current?.getBoundingClientRect();
    overBar.current = !!r && e.clientY >= r.top - 8 && e.clientY <= r.bottom && e.clientX >= r.left && e.clientX <= r.right;
    if (!controlsOn) setControlsOn(true);
    window.clearTimeout(hideTimer.current);
    // пока мышь над панелью кнопок — не прячем
    if (phase === 'playing' && !overBar.current) {
      hideTimer.current = window.setTimeout(() => setControlsOn(false), HIDE_CONTROLS_MS);
    }
  };
  const onSurfaceLeave = (e: ReactPointerEvent) => {
    if (e.pointerType !== 'mouse' || phase !== 'playing') return;
    overBar.current = false;
    window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => setControlsOn(false), 800);
  };
  // клавиши, когда плеер в фокусе (обработчик на самом плеере, не глобальный)
  const onKey = (e: ReactKeyboardEvent) => {
    if ((e.target as HTMLElement).closest('button') && (e.key === ' ' || e.key === 'Enter')) return;
    const k = e.key.toLowerCase();
    if ((k === 'arrowup' || k === 'arrowdown') && volumeOk) {
      e.preventDefault();
      changeVolume(currentVolume() + (k === 'arrowup' ? 0.1 : -0.1));
      showControls();
      return;
    }
    // стрелки влево/вправо над ползунком — его собственные
    if ((e.target as HTMLElement).tagName === 'INPUT' && k.startsWith('arrow')) return;
    if (k === ' ' || k === 'k' || k === 'л') {
      e.preventDefault();
      togglePlay();
    } else if (k === 'f' || k === 'а') {
      e.preventDefault();
      toggleFullscreen();
    } else if (k === 'm' || k === 'ь') {
      e.preventDefault();
      toggleMute();
    } else return;
    showControls();
  };

  const retry = () => setAttempt((n) => n + 1);
  const playing = phase === 'playing';
  const busy = phase === 'loading';

  return (
    <div
      ref={wrapRef}
      className={`player${fs !== 'off' ? ' player--fs' : ''}${fs === 'css' ? ' player--css-fs' : ''}${fs !== 'off' && rotate ? ' player--rotate' : ''}${controlsOn ? '' : ' player--idle'}`}
      data-phase={phase}
      onPointerUp={onSurfaceTap}
      onPointerMove={onSurfaceMove}
      onPointerLeave={onSurfaceLeave}
      onKeyDown={onKey}
      tabIndex={0}
      role="region"
      aria-label={title ? `Трансляция: ${title}` : 'Трансляция'}
    >
      {/* сцена: всё содержимое плеера. Её, а не сам блок, поворачиваем на телефоне —
          браузер запрещает трансформировать элемент, который в полноэкранном режиме */}
      <div
        className="player__stage"
        onDoubleClick={(e) => {
          if (!(e.target as HTMLElement).closest('button, input')) toggleFullscreen();
        }}
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

      <div className="player__bar" ref={barRef}>
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
        <div className="player__vol" ref={volRef}>
          <button type="button" onClick={toggleMute} aria-label={muted ? 'Включить звук' : 'Выключить звук'} aria-pressed={!muted}>
            <SoundIcon muted={muted || volume === 0} level={volume} />
          </button>
          {volumeOk && (
            <input
              type="range"
              className="player__vol-range"
              min={0}
              max={1}
              step={0.05}
              value={muted ? 0 : volume}
              style={{ '--p': `${(muted ? 0 : volume) * 100}%` } as CSSProperties}
              onChange={(e) => changeVolume(Number(e.target.value))}
              aria-label="Громкость"
              aria-valuetext={`${Math.round((muted ? 0 : volume) * 100)}%`}
            />
          )}
        </div>
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
    </div>
  );
}

function SoundIcon({ muted, level = 1 }: { muted: boolean; level?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 9v6h4l5 4V5L8 9z" />
      {muted ? (
        <path d="M16.5 9.5l5 5M21.5 9.5l-5 5" />
      ) : level < 0.5 ? (
        <path d="M16 9a4 4 0 010 6" />
      ) : (
        <path d="M16 9a4 4 0 010 6M18.5 6.5a8 8 0 010 11" />
      )}
    </svg>
  );
}
