import { NewsLink, VideoTile } from './MediaParts';
import type { NewsItemData, VideoData } from './mediaData';
import './media.css';

/*
 * Сетки новостей и видео для сайта на компьютере (главная и «Медиа»).
 * Только настоящие картинки: в сетку карточек идут новости с картинкой, остальные — строками рядом.
 */

/** Новости с картинкой — первыми, порядок по времени внутри групп сохраняется. */
export function splitByImage(items: NewsItemData[]): { cards: NewsItemData[]; rows: NewsItemData[] } {
  return { cards: items.filter((i) => i.image), rows: items.filter((i) => !i.image) };
}

export function NewsCards({ items, className }: { items: NewsItemData[]; className?: string }) {
  return (
    <div className={className ? `dk-news ${className}` : 'dk-news'} role="list">
      {items.map((n) => (
        <div key={n.id} role="listitem" className="dk-news__cell">
          <NewsLink item={n} variant="hero" />
        </div>
      ))}
    </div>
  );
}

export function NewsRows({ items }: { items: NewsItemData[] }) {
  return (
    <div className="mx-news-list dk-news-rows">
      {items.map((n) => (
        <NewsLink key={n.id} item={n} variant="list" />
      ))}
    </div>
  );
}

export function VideoGrid({ items, className }: { items: VideoData[]; className?: string }) {
  return (
    <div className={className ? `dk-videos ${className}` : 'dk-videos'} role="list">
      {items.map((v) => (
        <div key={v.id} role="listitem">
          <VideoTile v={v} />
        </div>
      ))}
    </div>
  );
}
