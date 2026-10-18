import { useEffect, useRef, useState } from 'react';
import { useLocation, useParams } from 'react-router';
import { useApiResource } from '../../lib/apiResource';
import { ExternalLink } from '../../lib/ExternalLink';
import { isVideoId, useOverlayBack, type MediaNavState } from '../../lib/mediaNav';
import { backgroundOf } from '../../lib/playerNav';
import { isDesktop, useDesktop } from '../../lib/shell';
import { useTelegramBackButton } from '../../lib/tmaNav';
import { EmptyState, Skeleton } from '../../ui';
import { VideoTile } from './MediaParts';
import { dayMonthRu, findVideo, moreVideos, ytEmbedUrl, ytWatchUrl, type VideosResponse } from './mediaData';
import './media.css';
import './reader.css';

const BACK_ICON = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M15 5l-7 7 7 7" />
  </svg>
);

const SLOW_MS = 10_000; // YouTube в России замедлен: не загрузился за 10 с — подсказку делаем заметнее
const YT_ORIGIN = 'https://www.youtube-nocookie.com';
/** Ошибки плеера YouTube «автор запретил встраивание» (у обзоров LaLiga — запрет на сторонних сайтах). */
const EMBED_BLOCKED = new Set([101, 150, 153]);

/**
 * Слушаем плеер YouTube (enablejsapi): ролик нельзя смотреть у нас — вместо его серой заглушки
 * «Видео недоступно» показываем свою карточку с кнопкой «Смотреть на YouTube».
 */
function useEmbedBlocked(frame: React.RefObject<HTMLIFrameElement | null>, id: string): boolean {
  const [blocked, setBlocked] = useState(false);
  useEffect(() => {
    setBlocked(false);
    const onMsg = (e: MessageEvent) => {
      if (e.origin !== YT_ORIGIN || e.source !== frame.current?.contentWindow) return;
      try {
        const d = typeof e.data === 'string' ? JSON.parse(e.data) : e.data;
        if (d?.event === 'onError' && EMBED_BLOCKED.has(Number(d.info))) setBlocked(true);
      } catch {
        /* чужое сообщение */
      }
    };
    window.addEventListener('message', onMsg);
    return () => window.removeEventListener('message', onMsg);
  }, [frame, id]);
  return blocked;
}

/**
 * Видео внутри приложения: /video/:id — слой поверх экрана, с которого открыли (как новость).
 * Iframe YouTube (youtube-nocookie) создаётся только здесь, когда человек открыл ролик; на экранах-списках —
 * только наши превью /img/yt. Полноэкранный режим — штатный у плеера YouTube.
 */
export default function VideoScreen() {
  const { id = '' } = useParams();
  const location = useLocation();
  const preview = (location.state as MediaNavState | null)?.video;
  const pre = preview && preview.id === id ? preview : null;
  const goBack = useOverlayBack('/media?tab=video');
  const nativeBack = useTelegramBackButton(goBack);
  const ref = useRef<HTMLDivElement>(null);
  const page = useDesktop();
  const overlay = backgroundOf(location) != null;
  const videos = useApiResource<VideosResponse>('/api/videos?limit=40');
  const found = findVideo(videos.data, id);
  const short = found?.short ?? pre?.short ?? false;
  const title = found?.title ?? pre?.title ?? null;
  const valid = isVideoId(id);

  useEffect(() => {
    const prev = document.body.style.overflow;
    // сайт на компьютере: это обычная страница, прокручивается сама страница
    if (!isDesktop()) document.body.style.overflow = 'hidden';
    ref.current?.focus({ preventScroll: true });
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') goBack();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [goBack]);
  useEffect(() => {
    ref.current?.scrollTo(0, 0);
  }, [id]);
  useEffect(() => {
    const prev = document.title;
    document.title = title ? `${title} — Мадридиста` : 'Видео — Мадридиста';
    return () => {
      document.title = prev;
    };
  }, [title]);

  const more = moreVideos(videos.data, id, short);
  const date = dayMonthRu(found?.published ?? pre?.published ?? null);

  return (
    <div
      ref={ref}
      className={overlay ? 'nr nr--overlay' : 'nr'}
      role={page ? undefined : 'dialog'}
      aria-modal={page ? undefined : true}
      aria-label={title ? `Видео: ${title}` : 'Видео'}
      tabIndex={-1}
    >
      <div className="nr-in nr-in--video">
        <header className="nr-top">
          {nativeBack ? (
            <span className="nr-top__gap" aria-hidden="true" />
          ) : (
            <button type="button" className="nr-top__back" aria-label="Назад" onClick={goBack}>
              {BACK_ICON}
            </button>
          )}
          <span className="nr-top__title">{short ? 'Shorts' : 'Видео'}</span>
          <span className="nr-top__gap" aria-hidden="true" />
        </header>

        {!valid ? (
          <EmptyState className="nr-state" title="Видео не найдено" text="Неверная ссылка на ролик" action={{ label: 'Все видео', onClick: goBack }} />
        ) : (
          <>
            <Player key={id} id={id} short={short} title={title ?? 'Видео Real Madrid'} />
            <div className="nr-pad">
              {title ? <h1 className="nr-title nr-title--video">{title}</h1> : <Skeleton width="80%" height={20} />}
              <p className="nr-meta">{metaLine(found?.subtitle ?? (short ? 'Shorts · Real Madrid' : 'Real Madrid · YouTube'), date)}</p>
            </div>
            {more.length > 0 && (
              <section className="mx-videos nr-vmore" aria-label="Ещё видео">
                <h2 className="nr-more__title nr-pad">Ещё видео</h2>
                <div className="mx-grid" role="list">
                  {more.map((v) => (
                    <div key={v.id} role="listitem">
                      <VideoTile v={v} />
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** «Ла Лига · 18 октября» — без второй даты, если подпись её уже содержит (обзоры матчей). */
function metaLine(sub: string, date: string | null): string {
  return [sub, date && !sub.includes(date) ? date : null].filter(Boolean).join(' · ');
}

function Player({ id, short, title }: { id: string; short: boolean; title: string }) {
  const [loaded, setLoaded] = useState(false);
  const [slow, setSlow] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null);
  const blocked = useEmbedBlocked(frame, id);
  useEffect(() => {
    const t = window.setTimeout(() => setSlow(true), SLOW_MS);
    return () => window.clearTimeout(t);
  }, []);
  const base = ytEmbedUrl(id);
  // enablejsapi — плеер шлёт события (в т. ч. ошибку «встраивание запрещено») в postMessage
  const src = base && `${base}&enablejsapi=1&origin=${encodeURIComponent(window.location.origin)}`;
  const watch = ytWatchUrl(id, short);
  // подписка на события плеера: без «listening» YouTube не присылает onError
  const listen = () => {
    frame.current?.contentWindow?.postMessage(JSON.stringify({ event: 'listening', id: 'rm', channel: 'widget' }), YT_ORIGIN);
  };
  if (blocked)
    return (
      <div className={short ? 'vp vp--short vp--blocked' : 'vp vp--blocked'}>
        <img className="vp-blocked__bg" src={`/img/yt/${id}.jpg`} alt="" decoding="async" />
        <div className="vp-blocked__in">
          <p className="vp-blocked__title">Этот ролик смотрят только на YouTube</p>
          <p className="vp-blocked__text">Автор запретил показывать его в других приложениях и на сайтах</p>
          <ExternalLink href={watch} className="ui-btn ui-btn--primary vp-blocked__btn">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M8 5.5v13l11-6.5z" />
            </svg>
            Смотреть на YouTube
          </ExternalLink>
        </div>
      </div>
    );
  return (
    <>
      <div className={short ? 'vp vp--short' : 'vp'}>
        {!loaded && (
          <div className="vp-poster" aria-hidden="true">
            <img src={`/img/yt/${id}.jpg`} alt="" decoding="async" />
            <span className="vp-spinner" />
          </div>
        )}
        {src && (
          <iframe
            ref={frame}
            className="vp-frame"
            src={src}
            title={title}
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
            onLoad={() => {
              setLoaded(true);
              listen();
            }}
          />
        )}
      </div>
      <p className={slow && !loaded ? 'vp-hint vp-hint--slow' : 'vp-hint'} role={slow && !loaded ? 'alert' : undefined}>
        {slow && !loaded ? 'YouTube грузится слишком долго — в России он работает с перебоями. ' : 'Не грузится? '}
        <ExternalLink href={watch} className="vp-hint__link">
          Открыть на YouTube
        </ExternalLink>
      </p>
    </>
  );
}
