// Ответы /api/news и /api/videos и чистые функции для «Медиа». Без импортов — их гоняет node --test.

export interface NewsItemData {
  id: string;
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
