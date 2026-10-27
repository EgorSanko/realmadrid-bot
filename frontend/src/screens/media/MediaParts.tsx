import { NewsItem, VideoCard } from '../../ui';
import { t } from '../../lib/i18n';
import { newsHref, useMediaNav, videoHref } from '../../lib/mediaNav';
import {
  highlightSubtitle,
  newsTime,
  videoSubtitle,
  type HighlightData,
  type NewsItemData,
  type VideoData,
} from './mediaData';

/**
 * Новость открывается внутри приложения: /news/:aid — слой чтения поверх текущего экрана.
 * На сайт источника не уводим; клик с модификаторами — как у обычной ссылки (новая вкладка приложения).
 */
export function NewsLink({ item, variant }: { item: NewsItemData; variant: 'row' | 'list' | 'hero' }) {
  const { openNews } = useMediaNav();
  return (
    <a
      href={newsHref(item.aid)}
      className="mx-link"
      onClick={(e) =>
        openNews({ aid: item.aid, title: item.title, source: item.source, image: item.image, published: item.published }, e)
      }
    >
      <NewsItem
        title={item.title}
        source={item.source}
        time={newsTime(item.published)}
        imageUrl={item.image ?? undefined}
        variant={variant}
      />
    </a>
  );
}

/** Обзор матча — встроенный плеер на /video/:id (iframe YouTube создаётся только там). */
export function HighlightLink({ h, height = 196 }: { h: HighlightData; height?: number }) {
  const { openVideo } = useMediaNav();
  return (
    <a
      href={videoHref(h.video_id)}
      className="mx-link"
      aria-label={t('Обзор матча {title}', { title: h.title })}
      onClick={(e) =>
        openVideo({ id: h.video_id, title: t('Обзор матча: {title}', { title: h.title }), short: false, published: h.kickoff }, e)
      }
    >
      <VideoCard
        title={h.title}
        subtitle={highlightSubtitle(h)}
        thumbnailUrl={h.thumb}
        tag={t('Обзор матча')}
        height={height}
      />
    </a>
  );
}

export function VideoTile({ v }: { v: VideoData }) {
  const { openVideo } = useMediaNav();
  return (
    <a
      href={videoHref(v.id)}
      className={v.short ? 'mx-link mx-tile mx-tile--short' : 'mx-link mx-tile'}
      onClick={(e) => openVideo({ id: v.id, title: v.title, short: v.short, published: v.published }, e)}
    >
      <VideoCard variant="tile" title={v.title} subtitle={videoSubtitle(v)} thumbnailUrl={v.thumb} />
      {v.short && <span className="mx-short-tag">Shorts</span>}
    </a>
  );
}

/** Главная новость — первая с картинкой среди трёх свежих, иначе просто первая. */
export function pickHero(items: NewsItemData[]): { hero: NewsItemData | null; rest: NewsItemData[] } {
  if (!items.length) return { hero: null, rest: [] };
  const idx = Math.max(
    0,
    items.slice(0, 3).findIndex((i) => i.image),
  );
  return { hero: items[idx], rest: items.filter((_, i) => i !== idx) };
}
