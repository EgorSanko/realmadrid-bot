import { Suspense, lazy, useMemo, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { StreamBlock } from '../../components/StreamBlock';
import type { ApiFixtures, ApiTables } from '../../lib/api';
import { useApiResource } from '../../lib/apiResource';
import { LALIGA_ID, splitFixtures, tableFor } from '../../lib/mapMatches';
import { useSpaLink } from '../../lib/spaLink';
import type { StreamState } from '../../lib/stream';
import { usePoll } from '../../lib/usePoll';
import { Card, FormStrip, SectionHeader, Skeleton, plural, type Outcome, type TeamRef } from '../../ui';
import { CalendarRow } from '../../ui/matchExtra';
import { LeagueTableMini } from '../LeagueTable';
import { NewsCards, VideoGrid, splitByImage } from '../media/DeskMedia';
import { HighlightLink } from '../media/MediaParts';
import type { NewsResponse, VideosResponse } from '../media/mediaData';
import './homeDesk.css';

const HomePredict = lazy(() => import('../predict/HomePredict'));

const fixturesPoll = (d: ApiFixtures | null) => (d?.matches?.some((m) => m.status?.live) ? 15_000 : 60_000);
const tablesPoll = () => 5 * 60_000;

/**
 * Главная сайта на компьютере. Слева — матч, эфир (плеер на всю ширину колонки), прогноз, прошлый матч;
 * справа — таблица Ла Лиги, форма, ближайшие матчи; ниже на всю ширину — новости и видео.
 * Блоки матча и прошлого матча — те же, что в мобильной главной (их собирает HomeScreen).
 */
export function HomeDesk({
  hero,
  last,
  stream,
  loading,
  form,
  formOpp,
  heroId,
}: {
  hero: ReactNode;
  last: ReactNode;
  stream: StreamState | null;
  loading: boolean;
  form: Outcome[];
  formOpp: Array<TeamRef | undefined>;
  heroId: number | null;
}) {
  const link = useSpaLink();
  const navigate = useNavigate();
  const fx = usePoll<ApiFixtures>('/api/fixtures', fixturesPoll);
  const tb = usePoll<ApiTables>('/api/tables', tablesPoll);
  const news = useApiResource<NewsResponse>('/api/news?limit=30');
  const videos = useApiResource<VideosResponse>('/api/videos?limit=30');

  const upcoming = useMemo(
    () => (fx.data ? splitFixtures(fx.data.matches, 'all').upcoming.filter((m) => m.id !== heroId).slice(0, 3) : null),
    [fx.data, heroId],
  );
  const laliga = tableFor(tb.data?.tables, LALIGA_ID);
  const newsCards = news.data ? splitByImage(news.data.items).cards.slice(0, 6) : [];
  const hl = videos.data?.highlights?.[0];
  const clips = (videos.data?.items ?? []).filter((v) => !v.short).slice(0, 4);
  const shorts = (videos.data?.items ?? []).filter((v) => v.short);
  const videoTiles = clips.length >= 3 ? clips : [...clips, ...shorts].slice(0, 4);

  return (
    <main className="home home--desk">
      <h1 className="ui-sr">Мадридиста — фан-приложение Real Madrid</h1>
      <div className="dk-split">
        <div className="dk-col">
          {hero}
          <StreamBlock stream={stream} />
          <Suspense fallback={<Skeleton height={148} radius={24} />}>
            <HomePredict />
          </Suspense>
          {last}
        </div>

        <aside className="dk-col" aria-label="Ла Лига, форма и календарь">
          {laliga ? (
            <LeagueTableMini table={laliga} title="Ла Лига" />
          ) : tb.loading && !tb.data ? (
            <Card ariaLabel="Ла Лига">
              <SectionHeader title="Ла Лига" />
              <Skeleton shape="table" rows={7} />
            </Card>
          ) : null}

          {loading ? (
            <Skeleton height={104} radius={20} />
          ) : (
            form.length > 0 && (
              <Card ariaLabel="Форма" className="hd-form">
                <SectionHeader title="Форма" aside={`${form.length} ${plural(form.length, ['матч', 'матча', 'матчей'])}`} />
                <FormStrip results={form} opponents={formOpp} size={28} className="hd-form__strip" />
              </Card>
            )
          )}

          {upcoming == null ? (
            fx.loading ? (
              <Card ariaLabel="Ближайшие матчи">
                <SectionHeader title="Ближайшие матчи" />
                <Skeleton shape="list" rows={3} />
              </Card>
            ) : null
          ) : (
            upcoming.length > 0 && (
              <Card ariaLabel="Ближайшие матчи" className="hd-next">
                <SectionHeader title="Ближайшие матчи" actionLabel="Календарь" onAction={() => navigate('/matches')} />
                {upcoming.map((m) => (
                  <CalendarRow key={m.id} {...m} highlighted={false} {...link(m.href)} />
                ))}
              </Card>
            )
          )}
        </aside>
      </div>

      {(news.loading || newsCards.length > 0) && (
        <section className="dk-full" aria-label="Новости">
          <SectionHeader title="Новости" actionLabel="Все новости" onAction={() => navigate('/media?tab=news')} className="hd-head" />
          {news.loading && !news.data ? (
            <div className="dk-news">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} height={300} radius={18} />
              ))}
            </div>
          ) : (
            <NewsCards items={newsCards} />
          )}
        </section>
      )}

      {(hl || videoTiles.length > 0) && (
        <section className="dk-full" aria-label="Видео">
          <SectionHeader title="Видео" actionLabel="Все видео" onAction={() => navigate('/media?tab=video')} className="hd-head" />
          <div className={hl ? 'hd-videos hd-videos--hl' : 'hd-videos'}>
            {hl && <HighlightLink h={hl} />}
            <VideoGrid items={videoTiles} className="hd-videos__grid" />
          </div>
        </section>
      )}
    </main>
  );
}
