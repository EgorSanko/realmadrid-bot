// Ответы /api/news и /api/videos и чистые функции для «Медиа». Без импортов — их гоняет node --test.

export interface NewsItemData {
  id: string;
  aid: string; // короткий id для /news/:aid
  title: string;
  summary: string;
  source: string; // «Спорт-Экспресс»
  url: string;
  published: string | null; // ISO UTC
  image: string | null; // /img/news/<host-key>/<path>
  also: string[];
}

export interface NewsResponse {
  source: string;
  updated_at: string;
  age_s: number;
  stale: boolean;
  available: string[];
  count: number;
  items: NewsItemData[];
}

export interface VideoData {
  id: string;
  title: string;
  published: string | null;
  thumb: string; // /img/yt/{id}.jpg
  url: string;
  short: boolean;
  kind: 'short' | 'highlights' | 'goals' | 'video';
  channel: string;
}

export interface HighlightData {
  match_id: number;
  video_id: string;
  title: string; // «Roma 3:4 Real Madrid»
  home: { id: number; name: string; score: number | null };
  away: { id: number; name: string; score: number | null };
  tournament: { id: number | null; name: string | null };
  kickoff: string | null;
  thumb: string;
  url: string;
}

export interface VideosResponse {
  source: string | null;
  updated_at: string | null;
  stale: boolean;
  available: string[];
  highlights: HighlightData[];
  count: number;
  items: VideoData[];
}

const TOURNAMENT_RU: Record<number, string> = {
  87: 'Ла Лига',
  42: 'Лига чемпионов',
  138: 'Кубок Испании',
  139: 'Суперкубок Испании',
  73: 'Клубный чемпионат мира',
};

export function tournamentRu(t: { id: number | null; name: string | null } | null | undefined): string | null {
  if (!t) return null;
  return (t.id != null && TOURNAMENT_RU[t.id]) || t.name || null;
}

const MONTHS_GEN = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
];
const MSK_MS = 3 * 3600e3; // Москва — UTC+3 без перехода на летнее время

function msk(iso: string): Date {
  return new Date(Date.parse(iso) + MSK_MS);
}

/** «14 октября» по МСК */
export function dayMonthRu(iso: string | null | undefined): string | null {
  if (!iso || Number.isNaN(Date.parse(iso))) return null;
  const d = msk(iso);
  return `${d.getUTCDate()} ${MONTHS_GEN[d.getUTCMonth()]}`;
}

/** Время новости: «только что», «12 мин назад», «3 ч назад», «вчера, 21:40», «14 октября, 18:30» (МСК). */
export function newsTime(iso: string | null | undefined, now: Date = new Date()): string | undefined {
  if (!iso || Number.isNaN(Date.parse(iso))) return undefined;
  const diff = (now.getTime() - Date.parse(iso)) / 1000;
  if (diff < 60) return 'только что';
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`;
  if (diff < 6 * 3600) return `${Math.floor(diff / 3600)} ч назад`;
  const d = msk(iso);
  const n = new Date(now.getTime() + MSK_MS);
  const hhmm = `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
  const dayKey = (x: Date) => `${x.getUTCFullYear()}-${x.getUTCMonth()}-${x.getUTCDate()}`;
  if (dayKey(d) === dayKey(n)) return `сегодня, ${hhmm}`;
  const y = new Date(n.getTime() - 86400e3);
  if (dayKey(d) === dayKey(y)) return `вчера, ${hhmm}`;
  return `${d.getUTCDate()} ${MONTHS_GEN[d.getUTCMonth()]}, ${hhmm}`;
}

/** Подпись под роликом: «Shorts · Real Madrid», «Real Madrid · YouTube». */
export function videoSubtitle(v: Pick<VideoData, 'short' | 'channel'>): string {
  return v.short ? `Shorts · ${v.channel || 'Real Madrid'}` : `${v.channel || 'Real Madrid'} · YouTube`;
}

/** Подпись обзора: «Лига чемпионов · 14 октября». */
export function highlightSubtitle(h: Pick<HighlightData, 'tournament' | 'kickoff'>): string {
  return [tournamentRu(h.tournament), dayMonthRu(h.kickoff)].filter(Boolean).join(' · ');
}

/* ---------- чтение новости и просмотр видео внутри приложения ---------- */

/** «Ещё новости» в ответе /api/news/{aid} */
export interface NewsBrief {
  aid: string;
  title: string;
  source: string;
  published: string | null;
  image: string | null;
}

/** /api/news/{aid}: full — есть текст; pending — сборщик ещё качает; иначе — лид и ссылка на источник. */
export interface ArticleData {
  aid: string;
  id: string;
  title: string;
  source: string; // «Спорт-Экспресс»
  site: string;
  url: string; // оригинал у источника
  published: string | null;
  image: string | null;
  image_caption: string | null;
  summary: string;
  lead: string | null;
  html: string | null; // безопасный HTML (белый список на сервере)
  author: string | null;
  origin: string | null; // первоисточник, на который ссылается сайт («AS»)
  words: number | null;
  full: boolean;
  pending: boolean;
  reason?: 'no_text' | 'unavailable' | 'busy' | 'expired'; // expired — текст старше 90 дней удалён
  available: string[];
  more: NewsBrief[];
}

/** Время чтения: ~180 слов в минуту, не меньше минуты. */
export function readingTime(words: number | null | undefined): string | null {
  if (!words || words < 1) return null;
  return `${Math.max(1, Math.round(words / 180))} мин чтения`;
}

/** Подпись под заголовком: «Спорт-Экспресс · 3 ч назад · 2 мин чтения». */
export function articleMeta(a: Pick<ArticleData, 'source' | 'published' | 'words'>, now: Date = new Date()): string {
  return [a.source, newsTime(a.published, now), readingTime(a.words)].filter(Boolean).join(' · ');
}

const YT_ID = /^[A-Za-z0-9_-]{11}$/;

/** Встроенный плеер — только youtube-nocookie и только для правильного id. */
export function ytEmbedUrl(id: string): string | null {
  if (!YT_ID.test(id)) return null;
  return `https://www.youtube-nocookie.com/embed/${id}?playsinline=1&rel=0&modestbranding=1`;
}

export function ytWatchUrl(id: string, short = false): string {
  return short ? `https://www.youtube.com/shorts/${id}` : `https://www.youtube.com/watch?v=${id}`;
}

/** id ролика YouTube из ссылки (watch, youtu.be, shorts, embed) — для обзора с экрана матча. */
export function youtubeIdOf(url: string | null | undefined): string | null {
  if (!url) return null;
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return null;
  }
  const host = u.hostname.replace(/^(www\.|m\.)/, '');
  let id: string | null = null;
  if (host === 'youtu.be') id = u.pathname.split('/')[1] ?? null;
  else if (host === 'youtube.com' || host === 'youtube-nocookie.com') {
    if (u.pathname === '/watch') id = u.searchParams.get('v');
    else {
      const m = u.pathname.match(/^\/(?:shorts|embed|live|v)\/([^/?#]+)/);
      id = m ? m[1] : null;
    }
  }
  return id && YT_ID.test(id) ? id : null;
}

/** Ролик для экрана /video/:id: из ленты канала или из обзоров матчей. */
export interface VideoView {
  id: string;
  title: string;
  published: string | null;
  short: boolean;
  subtitle: string;
}

export function findVideo(data: VideosResponse | null | undefined, id: string): VideoView | null {
  if (!data) return null;
  const v = data.items.find((x) => x.id === id);
  if (v) return { id, title: v.title, published: v.published, short: v.short, subtitle: videoSubtitle(v) };
  const h = data.highlights.find((x) => x.video_id === id);
  if (h) return { id, title: `Обзор матча: ${h.title}`, published: h.kickoff, short: false, subtitle: highlightSubtitle(h) };
  return null;
}

/** «Ещё видео»: того же формата (шорты к шортам), без текущего. */
export function moreVideos(data: VideosResponse | null | undefined, id: string, short: boolean, n = 6): VideoData[] {
  const items = (data?.items ?? []).filter((v) => v.id !== id);
  const same = items.filter((v) => v.short === short);
  return [...same, ...items.filter((v) => v.short !== short)].slice(0, n);
}
