import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import { Button, Card, EmptyState, ErrorState, SectionHeader, Skeleton, Tabs } from '../../ui';
import { errorText, useApiResource, type Resource } from '../../lib/apiResource';
import { useDesktop } from '../../lib/shell';
import { NewsCards, NewsRows, VideoGrid, splitByImage } from './DeskMedia';
import { HighlightLink, NewsLink, VideoTile, pickHero } from './MediaParts';
import type { NewsResponse, VideosResponse } from './mediaData';
import './media.css';

type Tab = 'all' | 'news' | 'video';
const TABS: { id: Tab; label: string }[] = [
  { id: 'all', label: 'Всё' },
  { id: 'news', label: 'Новости' },
  { id: 'video', label: 'Видео' },
];

/** Этап 9: «Медиа» по design/screens/a-media.html. Данные — /api/news и /api/videos (снимки сборщика). */
export default function MediaScreen() {
  useEffect(() => {
    document.title = 'Новости и видео «Реала» — Мадридиста';
  }, []);
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get('tab'))?.id ?? 'all') as Tab;
  const setTab = (t: Tab) => {
    setParams(t === 'all' ? {} : { tab: t }, { replace: true });
    window.scrollTo(0, 0);
  };
  const news = useApiResource<NewsResponse>('/api/news?limit=50');
  const videos = useApiResource<VideosResponse>('/api/videos?limit=30');
  const desktop = useDesktop();

  if (desktop) {
    return (
      <main className="mx mx--desk">
        <header className="topbar">
          <h1 className="topbar__title">Медиа</h1>
        </header>
        <Tabs items={TABS} value={tab} onChange={setTab} ariaLabel="Тип материалов" className="mx-desk-tabs" />
        {tab !== 'news' && <DeskVideos videos={videos} full={tab === 'video'} onAll={() => setTab('video')} />}
        {tab !== 'video' && <DeskNews news={news} full={tab === 'news'} onAll={() => setTab('news')} />}
      </main>
    );
  }

  return (
    <main className="mx">
      <header className="topbar">
        <h1 className="topbar__title">Медиа</h1>
      </header>
      <Tabs items={TABS} value={tab} onChange={setTab} ariaLabel="Тип материалов" />
      {tab === 'all' && <AllTab news={news} videos={videos} onTab={setTab} />}
      {tab === 'news' && <NewsBlock news={news} limit={null} />}
      {tab === 'video' && <VideosTab videos={videos} />}
    </main>
  );
}

function AllTab({
  news,
  videos,
  onTab,
}: {
  news: Resource<NewsResponse>;
  videos: Resource<VideosResponse>;
  onTab: (t: Tab) => void;
}) {
  const v = videos.data;
  const hl = v?.highlights?.[0];
  return (
    <>
      {videos.loading && !v ? (
        <Card bleed>
          <Skeleton height={196} radius={0} />
          <div style={{ padding: '14px 18px' }}>
            <Skeleton width="60%" height={16} />
            <Skeleton width="40%" height={12} style={{ marginTop: 8 }} />
          </div>
        </Card>
      ) : (
        hl && <HighlightLink h={hl} />
      )}
      <VideoRail videos={videos} onAll={() => onTab('video')} />
      <NewsBlock news={news} limit={5} onAll={() => onTab('news')} />
    </>
  );
}

function VideoRail({ videos, onAll }: { videos: Resource<VideosResponse>; onAll: () => void }) {
  const items = videos.data?.items ?? [];
  if (!videos.loading && !videos.data) {
    return (
      <Card ariaLabel="Видео клуба">
        <SectionHeader title="Видео клуба" />
        <ErrorState plain text={errorText(videos.error)} onRetry={videos.reload} />
      </Card>
    );
  }
  if (videos.data && !items.length) return null;
  return (
    <section aria-label="Видео клуба" className="mx-videos">
      <SectionHeader title="Видео клуба" page onAction={items.length ? onAll : undefined} />
      <div className="mx-rail" role="list">
        {videos.loading && !videos.data
          ? [0, 1].map((i) => (
              <div key={i} className="mx-rail__skel" role="listitem">
                <Skeleton width={200} height={112} radius={14} />
                <Skeleton width={170} height={13} style={{ marginTop: 8 }} />
              </div>
            ))
          : items.slice(0, 10).map((v) => (
              <div key={v.id} role="listitem" className="mx-rail__item">
                <VideoTile v={v} />
              </div>
            ))}
      </div>
    </section>
  );
}

const PAGE = 20;

function NewsBlock({ news, limit, onAll }: { news: Resource<NewsResponse>; limit: number | null; onAll?: () => void }) {
  const [shown, setShown] = useState(PAGE);
  if (news.loading && !news.data) {
    return (
      <Card ariaLabel="Новости">
        <SectionHeader title="Новости" />
        <Skeleton height={170} radius={16} style={{ marginTop: 12 }} />
        <Skeleton shape="news" rows={limit ?? 4} style={{ marginTop: 6 }} />
      </Card>
    );
  }
  if (!news.data) {
    return (
      <Card ariaLabel="Новости">
        <SectionHeader title="Новости" />
        <ErrorState plain text={errorText(news.error)} onRetry={news.reload} />
      </Card>
    );
  }
  const all = news.data.items;
  if (!all.length) {
    return (
      <Card ariaLabel="Новости">
        <SectionHeader title="Новости" />
        <EmptyState plain title="Пока нет новостей о «Реале»" text="Лента обновляется каждые 10 минут" />
      </Card>
    );
  }
  const { hero, rest } = pickHero(all);
  const list = rest.slice(0, (limit ?? shown) - 1);
  return (
    <Card ariaLabel="Новости">
      <SectionHeader title="Новости" aside={news.data.stale ? 'могли устареть' : undefined} />
      {hero && <NewsLink item={hero} variant="hero" />}
      <div className="mx-news-list">
        {list.map((n) => (
          <NewsLink key={n.id} item={n} variant="list" />
        ))}
      </div>
      {limit != null && all.length > limit && onAll && (
        <Button variant="secondary" block onClick={onAll} className="mx-more">
          Все новости
        </Button>
      )}
      {limit == null && rest.length > list.length && (
        <Button variant="secondary" block onClick={() => setShown((s) => s + PAGE)} className="mx-more">
          Показать ещё
        </Button>
      )}
    </Card>
  );
}

function VideosTab({ videos }: { videos: Resource<VideosResponse> }) {
  if (videos.loading && !videos.data) {
    return (
      <Card bleed>
        <Skeleton height={180} radius={0} />
        <div style={{ padding: '14px 18px' }}>
          <Skeleton width="60%" height={16} />
        </div>
      </Card>
    );
  }
  if (!videos.data) {
    return (
      <Card>
        <ErrorState plain text={errorText(videos.error)} onRetry={videos.reload} />
      </Card>
    );
  }
  const { highlights, items } = videos.data;
  if (!highlights.length && !items.length) {
    return (
      <Card>
        <EmptyState plain title="Видео пока нет" text="Лента канала обновляется каждые 15 минут" />
      </Card>
    );
  }
  return (
    <>
      {highlights.length > 0 && (
        <section aria-label="Обзоры матчей">
          <SectionHeader title="Обзоры матчей" page />
          {highlights.map((h) => (
            <HighlightLink key={h.match_id} h={h} height={180} />
          ))}
        </section>
      )}
      {items.length > 0 && (
        <section aria-label="Видео клуба" className="mx-videos">
          <SectionHeader title="Видео клуба" page aside={`${items.length}`} />
          <div className="mx-grid" role="list">
            {items.map((v) => (
              <div key={v.id} role="listitem">
                <VideoTile v={v} />
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

/* ---------- сайт на компьютере: сетки ---------- */

const DESK_PAGE = 18;

function DeskNews({ news, full, onAll }: { news: Resource<NewsResponse>; full: boolean; onAll: () => void }) {
  const [shown, setShown] = useState(DESK_PAGE);
  if (news.loading && !news.data) {
    return (
      <section className="dk-full mx-desk-sec" aria-label="Новости">
        <SectionHeader title="Новости" />
        <div className="dk-news">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} height={300} radius={18} />
          ))}
        </div>
      </section>
    );
  }
  if (!news.data) {
    return (
      <Card ariaLabel="Новости">
        <SectionHeader title="Новости" />
        <ErrorState plain text={errorText(news.error)} onRetry={news.reload} />
      </Card>
    );
  }
  const { cards, rows } = splitByImage(news.data.items);
  if (!cards.length && !rows.length) {
    return (
      <Card ariaLabel="Новости">
        <SectionHeader title="Новости" />
        <EmptyState plain title="Пока нет новостей о «Реале»" text="Лента обновляется каждые 10 минут" />
      </Card>
    );
  }
  const limit = full ? shown : 9;
  return (
    <section className="dk-full mx-desk-sec" aria-label="Новости">
      <SectionHeader
        title="Новости"
        aside={news.data.stale ? 'могли устареть' : undefined}
        actionLabel="Все новости"
        onAction={full ? undefined : onAll}
      />
      <div className={full && rows.length ? 'dk-split mx-desk-news' : 'mx-desk-news'}>
        <div className="dk-col">
          <NewsCards items={cards.slice(0, limit)} className={full && rows.length ? 'dk-news--2' : undefined} />
          {full && cards.length > limit && (
            <Button variant="secondary" onClick={() => setShown((x) => x + DESK_PAGE)} className="mx-more mx-desk-more">
              Показать ещё
            </Button>
          )}
        </div>
        {full && rows.length > 0 && (
          <Card ariaLabel="Коротко" className="dk-sticky mx-desk-brief">
            <SectionHeader title="Коротко" />
            <NewsRows items={rows} />
          </Card>
        )}
      </div>
    </section>
  );
}

function DeskVideos({ videos, full, onAll }: { videos: Resource<VideosResponse>; full: boolean; onAll: () => void }) {
  if (videos.loading && !videos.data) {
    return (
      <section className="dk-full mx-desk-sec" aria-label="Видео">
        <SectionHeader title="Видео" />
        <div className="dk-videos">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} height={150} radius={14} />
          ))}
        </div>
      </section>
    );
  }
  if (!videos.data) {
    return (
      <Card ariaLabel="Видео клуба">
        <SectionHeader title="Видео клуба" />
        <ErrorState plain text={errorText(videos.error)} onRetry={videos.reload} />
      </Card>
    );
  }
  const { highlights, items } = videos.data;
  if (!highlights.length && !items.length) {
    return full ? (
      <Card>
        <EmptyState plain title="Видео пока нет" text="Лента канала обновляется каждые 15 минут" />
      </Card>
    ) : null;
  }
  const clips = items.filter((v) => !v.short);
  const shorts = items.filter((v) => v.short);
  if (!full) {
    // «Всё»: обзор последнего матча крупно, рядом — свежие ролики клуба
    const hl = highlights[0];
    const tiles = [...clips, ...shorts].slice(0, hl ? 4 : 8);
    return (
      <section className="dk-full mx-desk-sec" aria-label="Видео">
        <SectionHeader title="Видео" actionLabel="Все видео" onAction={onAll} />
        <div className={hl ? 'mx-desk-vtop' : undefined}>
          {hl && <HighlightLink h={hl} />}
          <VideoGrid items={tiles} className={hl ? 'dk-videos--2' : undefined} />
        </div>
      </section>
    );
  }
  return (
    <>
      {highlights.length > 0 && (
        <section className="dk-full mx-desk-sec" aria-label="Обзоры матчей">
          <SectionHeader title="Обзоры матчей" aside={`${highlights.length}`} />
          <div className="mx-desk-hl">
            {highlights.map((h) => (
              <HighlightLink key={h.match_id} h={h} />
            ))}
          </div>
        </section>
      )}
      {clips.length > 0 && (
        <section className="dk-full mx-desk-sec" aria-label="Видео клуба">
          <SectionHeader title="Видео клуба" aside={`${clips.length}`} />
          <VideoGrid items={clips} />
        </section>
      )}
      {shorts.length > 0 && (
        <section className="dk-full mx-desk-sec" aria-label="Shorts">
          <SectionHeader title="Shorts" aside={`${shorts.length}`} />
          <VideoGrid items={shorts} className="dk-videos--shorts" />
        </section>
      )}
    </>
  );
}
