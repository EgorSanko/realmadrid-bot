/**
 * /api/match/{id}: типы ответа (форма из backend/app/model.py) и загрузка.
 *
 * Модуль без рантайм-импортов — его напрямую гоняет `node --test`.
 */

export type MatchState = 'scheduled' | 'live' | 'halftime' | 'finished' | 'postponed' | 'cancelled' | 'abandoned';
export type Side = 'home' | 'away';
export type SourceName = 'fotmob' | 'sofascore' | 'espn' | 'livescore';

export type AvailableKey =
  | 'events' | 'assists' | 'lineups' | 'lineup_positions' | 'ratings' | 'stats' | 'stats_periods'
  | 'xg' | 'shotmap' | 'shot_xg' | 'momentum' | 'potm' | 'highlights' | 'h2h' | 'form' | 'venue' | 'referee'
  | 'player_photos';

export interface ApiStatus {
  state: MatchState;
  live: boolean;
  finished: boolean;
  minute: number | null;
  added: number | null;
  label: string | null;
}

export interface ApiPerson {
  /** id FotMob (для фото); у резервных источников может не быть */
  id: number | string | null;
  name: string | null;
  photo: string | null;
}

export interface ApiTeam {
  id: number | null;
  name: string | null;
  short?: string | null;
  score: number | null;
  ht_score?: number | null;
  logo: string | null;
}

interface EventBase {
  minute: number | null;
  added: number | null;
  side: Side | null;
}

export interface ApiGoal extends EventBase {
  type: 'goal';
  player: ApiPerson | null;
  assist: ApiPerson | null;
  own_goal: boolean;
  penalty: boolean;
  shootout: boolean;
  score: [number | null, number | null] | null;
}
export interface ApiCard extends EventBase {
  type: 'card';
  card: 'yellow' | 'red' | 'second_yellow';
  player: ApiPerson | null;
  reason?: string | null;
}
export interface ApiSub extends EventBase {
  type: 'sub';
  player_in: ApiPerson | null;
  player_out: ApiPerson | null;
  injury?: boolean;
}
export interface ApiVar extends EventBase {
  type: 'var';
  player?: ApiPerson | null;
  decision?: string | null;
  text?: string | null;
  confirmed?: boolean | null;
}
export interface ApiPenaltyMissed extends EventBase {
  type: 'penalty_missed';
  player?: ApiPerson | null;
}
export interface ApiPeriod extends EventBase {
  type: 'period';
  label: string | null;
  score?: [number | null, number | null] | null;
}
export interface ApiAddedTime extends EventBase {
  type: 'added_time';
  minutes?: number | null;
}
export type ApiEvent = ApiGoal | ApiCard | ApiSub | ApiVar | ApiPenaltyMissed | ApiPeriod | ApiAddedTime;

export interface ApiLineupPlayer {
  id: number | null;
  source_id?: number | string | null;
  name: string;
  number: number | null;
  position: string | null;
  rating: number | null;
  x: number | null;
  y: number | null;
  captain: boolean;
  sub_in: number | null;
  sub_out: number | null;
  photo: string | null;
}

export interface ApiUnavailable {
  id: number | null;
  name: string;
  photo: string | null;
  /** FotMob: injury / suspension…; SofaScore: «Leg Injury» */
  type: string | null;
  /** FotMob: «Late October 2026», «Doubtful»; SofaScore: ISO-дата */
  expected_return: string | null;
}

export interface ApiLineupSide {
  team_id: number | string | null;
  formation: string | null;
  rating: number | null;
  coach: { id: number | null; name: string } | null;
  starters: ApiLineupPlayer[];
  subs: ApiLineupPlayer[];
  unavailable: ApiUnavailable[];
}

export interface ApiStat {
  key: string;
  group: string;
  home: number | null;
  away: number | null;
}

export interface ApiShot {
  /** 0..100 вдоль поля, ворота соперника — 100 (FotMob x / 105) */
  x: number;
  /** 0..100 поперёк поля (FotMob y / 68) */
  y: number;
  minute: number | null;
  added: number | null;
  side: Side;
  player: ApiPerson | null;
  outcome: 'goal' | 'saved' | 'miss' | 'post' | 'blocked';
  own_goal: boolean;
  xg: number | null;
  xgot?: number | null;
  situation?: string | null;
  period?: string | null;
}

export interface ApiH2HMatch {
  kickoff: string | null;
  tournament: string | null;
  home: { id: number | null; name: string | null };
  away: { id: number | null; name: string | null };
  /** «2 - 2» */
  score: string | null;
  finished: boolean;
}

export interface ApiFormItem {
  result: 'W' | 'D' | 'L' | null;
  score: string | null;
  kickoff: string | null;
}

export interface ApiMatch {
  id: number | null;
  kickoff: string | null;
  status: ApiStatus;
  tournament: { id: number | null; name: string | null; round: string | null; logo: string | null };
  venue: { name: string | null; city: string | null } | null;
  referee: string | null;
  attendance: number | null;
  home: ApiTeam;
  away: ApiTeam;
  events: ApiEvent[];
  lineups: { confirmed: boolean; home: ApiLineupSide; away: ApiLineupSide } | null;
  stats: { all: ApiStat[]; first_half?: ApiStat[]; second_half?: ApiStat[] } | null;
  shots: ApiShot[];
  momentum: Array<{ minute: number; value: number }>;
  potm: (ApiPerson & { side: Side | null; rating: number | null }) | null;
  highlights: { url: string; image?: string | null; source?: string | null } | null;
  h2h: {
    summary: { home_wins: number | null; draws: number | null; away_wins: number | null };
    matches: ApiH2HMatch[];
  } | null;
  form: { home: ApiFormItem[]; away: ApiFormItem[] } | null;
  available: AvailableKey[];
  /** матча нет в снимках, есть только строка календаря — сервер уже попросил сборщика */
  pending?: boolean;
  source?: SourceName;
  fetched_from?: string;
  stale?: boolean;
  age_s?: number;
  updated_at?: string;
}

/* ---------- загрузка ---------- */

export type MatchResult =
  | { kind: 'ok'; match: ApiMatch }
  /** 404: такого матча нет ни в снимках, ни в календаре */
  | { kind: 'not_found' }
  /** 503: сборщик ещё не получил данные (холодный старт) */
  | { kind: 'unavailable' }
  /** сеть, 5xx, битый JSON */
  | { kind: 'error'; message: string };

type FetchLike = (url: string, init?: { signal?: AbortSignal; cache?: RequestCache }) => Promise<{
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}>;

export function matchUrl(id: string | number): string {
  return `/api/match/${encodeURIComponent(String(id))}`;
}

function isMatch(v: unknown): v is ApiMatch {
  const o = v as ApiMatch | null;
  return !!o && typeof o === 'object' && !!o.status && typeof o.status.state === 'string' && !!o.home && !!o.away;
}

/** Нормализует ответ к безопасной форме: недостающие массивы — пустые. */
export function normalizeMatch(m: ApiMatch): ApiMatch {
  return {
    ...m,
    events: Array.isArray(m.events) ? m.events : [],
    shots: Array.isArray(m.shots) ? m.shots : [],
    momentum: Array.isArray(m.momentum) ? m.momentum : [],
    available: Array.isArray(m.available) ? m.available : [],
    tournament: m.tournament ?? { id: null, name: null, round: null, logo: null },
    venue: m.venue ?? null,
    lineups: m.lineups ?? null,
    stats: m.stats ?? null,
    potm: m.potm ?? null,
    highlights: m.highlights ?? null,
    h2h: m.h2h ?? null,
    form: m.form ?? null,
    referee: m.referee ?? null,
    attendance: m.attendance ?? null,
  };
}

export async function fetchMatch(id: string | number, signal?: AbortSignal, fetchImpl?: FetchLike): Promise<MatchResult> {
  const f: FetchLike = fetchImpl ?? ((url, init) => fetch(url, init));
  let r: Awaited<ReturnType<FetchLike>>;
  try {
    // max-age=5 в лайве: браузерный кэш не мешает, но и не держит старое дольше 5 с
    r = await f(matchUrl(id), { signal });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    return { kind: 'error', message: (e as Error).message || 'network' };
  }
  if (r.status === 404) return { kind: 'not_found' };
  if (r.status === 503) return { kind: 'unavailable' };
  if (!r.ok) return { kind: 'error', message: `HTTP ${r.status}` };
  let body: unknown;
  try {
    body = await r.json();
  } catch {
    return { kind: 'error', message: 'bad json' };
  }
  if (!isMatch(body)) return { kind: 'error', message: 'bad shape' };
  return { kind: 'ok', match: normalizeMatch(body) };
}

/** Отпечаток содержимого без служебных полей возраста — чтобы не перерисовывать одно и то же. */
export function matchFingerprint(m: ApiMatch): string {
  const { age_s, updated_at, stale, ...rest } = m;
  return JSON.stringify(rest);
}

/* ---------- когда опрашивать ---------- */

export const LIVE_POLL_MS = 10_000;
const AFTER_KICKOFF_WINDOW_MS = 3 * 60 * 60 * 1000;

/**
 * Опрашивать ли сервер раз в 10 с:
 * идёт матч / перерыв; заголовок pending (данные вот-вот появятся);
 * время начала прошло, а статус ещё «до начала» (ждём, когда сборщик увидит старт).
 * До начала и после финального свистка — не опрашиваем.
 */
export function shouldPoll(m: ApiMatch | null, now: number = Date.now()): boolean {
  if (!m) return false;
  if (m.pending) return true;
  if (m.status.live || m.status.state === 'live' || m.status.state === 'halftime') return true;
  if (m.status.state === 'scheduled' && m.kickoff) {
    const k = Date.parse(m.kickoff);
    return Number.isFinite(k) && now >= k && now - k < AFTER_KICKOFF_WINDOW_MS;
  }
  return false;
}
