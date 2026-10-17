// Чтение новостей и видео внутри приложения: чистые функции mediaData. Запуск: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  articleMeta,
  findVideo,
  moreVideos,
  readingTime,
  youtubeIdOf,
  ytEmbedUrl,
  ytWatchUrl,
  type VideosResponse,
} from '../src/screens/media/mediaData.ts';

const NOW = new Date('2026-10-17T12:00:00Z');

test('время чтения и подпись под заголовком', () => {
  assert.equal(readingTime(null), null);
  assert.equal(readingTime(0), null);
  assert.equal(readingTime(60), '1 мин чтения');
  assert.equal(readingTime(1194), '7 мин чтения');
  assert.equal(
    articleMeta({ source: 'Спорт-Экспресс', published: '2026-10-17T09:00:00Z', words: 362 }, NOW),
    'Спорт-Экспресс · 3 ч назад · 2 мин чтения',
  );
  assert.equal(articleMeta({ source: 'Sports.ru', published: null, words: null }, NOW), 'Sports.ru');
});

test('встроенный плеер — только youtube-nocookie и только правильный id', () => {
  assert.equal(
    ytEmbedUrl('dQw4w9WgXcQ'),
    'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?playsinline=1&rel=0&modestbranding=1',
  );
  assert.equal(ytEmbedUrl('bad id"><script>'), null);
  assert.equal(ytEmbedUrl('short'), null);
  assert.equal(ytWatchUrl('dQw4w9WgXcQ'), 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');
  assert.equal(ytWatchUrl('dQw4w9WgXcQ', true), 'https://www.youtube.com/shorts/dQw4w9WgXcQ');
});

test('id ролика из ссылки обзора матча', () => {
  assert.equal(youtubeIdOf('https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1'), 'dQw4w9WgXcQ');
  assert.equal(youtubeIdOf('https://youtu.be/dQw4w9WgXcQ'), 'dQw4w9WgXcQ');
  assert.equal(youtubeIdOf('https://m.youtube.com/shorts/dQw4w9WgXcQ'), 'dQw4w9WgXcQ');
  assert.equal(youtubeIdOf('https://www.youtube.com/embed/dQw4w9WgXcQ'), 'dQw4w9WgXcQ');
  assert.equal(youtubeIdOf('https://www.laliga.com/video/123'), null);
  assert.equal(youtubeIdOf('https://evil.example/watch?v=dQw4w9WgXcQ'), null);
  assert.equal(youtubeIdOf('not a url'), null);
  assert.equal(youtubeIdOf(null), null);
});

const V = (id: string, short: boolean) => ({
  id, title: `Ролик ${id}`, published: '2026-10-16T10:00:00Z', thumb: `/img/yt/${id}.jpg`,
  url: `https://www.youtube.com/watch?v=${id}`, short, kind: short ? 'short' : 'video', channel: 'Real Madrid',
}) as VideosResponse['items'][number];

const DATA: VideosResponse = {
  source: 'youtube', updated_at: null, stale: false, available: ['videos'], count: 4,
  items: [V('aaaaaaaaaaa', false), V('bbbbbbbbbbb', true), V('ccccccccccc', true), V('ddddddddddd', false)],
  highlights: [{
    match_id: 1, video_id: 'hhhhhhhhhhh', title: 'Roma 3:4 Real Madrid',
    home: { id: 1, name: 'Roma', score: 3 }, away: { id: 8633, name: 'Real Madrid', score: 4 },
    tournament: { id: 42, name: 'Champions League' }, kickoff: '2026-10-14T19:00:00Z',
    thumb: '/img/yt/hhhhhhhhhhh.jpg', url: 'https://www.youtube.com/watch?v=hhhhhhhhhhh',
  }],
};

test('ролик для экрана видео: из ленты канала и из обзоров матчей', () => {
  const s = findVideo(DATA, 'bbbbbbbbbbb');
  assert.equal(s?.short, true);
  assert.equal(s?.subtitle, 'Shorts · Real Madrid');
  const h = findVideo(DATA, 'hhhhhhhhhhh');
  assert.equal(h?.title, 'Обзор матча: Roma 3:4 Real Madrid');
  assert.equal(h?.short, false);
  assert.equal(h?.subtitle, 'Лига чемпионов · 14 октября');
  assert.equal(findVideo(DATA, 'zzzzzzzzzzz'), null);
  assert.equal(findVideo(null, 'aaaaaaaaaaa'), null);
});

test('«Ещё видео»: сначала того же формата, без текущего', () => {
  assert.deepEqual(moreVideos(DATA, 'bbbbbbbbbbb', true).map((v) => v.id), ['ccccccccccc', 'aaaaaaaaaaa', 'ddddddddddd']);
  assert.deepEqual(moreVideos(DATA, 'aaaaaaaaaaa', false, 2).map((v) => v.id), ['ddddddddddd', 'bbbbbbbbbbb']);
  assert.deepEqual(moreVideos(null, 'aaaaaaaaaaa', false), []);
});
