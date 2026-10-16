import { NewsItem, VideoCard } from '../../ui';
import { ExternalLink } from '../../lib/ExternalLink';
import {
  highlightSubtitle,
  newsTime,
  videoSubtitle,
  type HighlightData,
  type NewsItemData,
  type VideoData,
} from './mediaData';

/** Новость-ссылка: в Telegram открывается через openLink, в браузере — в новой вкладке. */
export function NewsLink({ item, variant }: { item: NewsItemData; variant: 'row' | 'list' | 'hero' }) {
  return (
    <ExternalLink href={item.url} className="mx-link">
      <NewsItem
        title={item.title}
        source={item.source}
        time={newsTime(item.published)}
        imageUrl={item.image ?? undefined}
        variant={variant}
      />
    </ExternalLink>
  );
}

export function HighlightLink({ h, height = 196 }: { h: HighlightData; height?: number }) {
  return (
    <ExternalLink href={h.url} className="mx-link" ariaLabel={`Обзор матча ${h.title}`}>
      <VideoCard
        title={h.title}
        subtitle={highlightSubtitle(h)}
        thumbnailUrl={h.thumb}
        tag="Обзор матча"
        height={height}
      />
    </ExternalLink>
  );
}

export function VideoTile({ v }: { v: VideoData }) {
  return (
    <ExternalLink href={v.url} className={v.short ? 'mx-link mx-tile mx-tile--short' : 'mx-link mx-tile'}>
      <VideoCard variant="tile" title={v.title} subtitle={videoSubtitle(v)} thumbnailUrl={v.thumb} />
      {v.short && <span className="mx-short-tag">Shorts</span>}
    </ExternalLink>
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
