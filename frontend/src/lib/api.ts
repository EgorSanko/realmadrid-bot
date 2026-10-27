/**
 * Клиент нашего API (только чтение) и формы ответов — по backend/app/model.py и main.py.
 * Клиент ходит только по относительным путям /api/*; внешних запросов нет.
 */
import type { ApiRound } from '../api/match';
import { withLang } from './i18n';

/** Общие поля каждого ответа: откуда и когда снимок. */
export interface ApiMeta {
  source?: string;
  updated_at?: string | null;
  age_s?: number | null;
  stale?: boolean;
  available?: string[];
}

export interface ApiTeam {
  id: number | null;
  /** латиницей, как отдаёт источник */
  name: string | null;
  short?: string | null;
  score?: number | null;
  logo?: string | null;
}

export interface ApiTournament {
  id: number | null;
  name: string | null;
  round?: string | null;
  logo?: string | null;
}

export type ApiState = 'scheduled' | 'live' | 'halftime' | 'finished' | 'postponed' | 'cancelled' | 'abandoned';

export interface ApiStatus {
  state: ApiState;
  live: boolean;
  finished: boolean;
  minute: number | null;
  added: number | null;
  label?: string | null;
}

export type ApiResult = 'W' | 'D' | 'L';

/** Строка календаря (/api/fixtures) и краткая карточка матча (/api/home next/last). */
export interface ApiFixture {
  id: number;
  kickoff: string;
  tournament: ApiTournament;
  home: ApiTeam;
  away: ApiTeam;
  status: ApiStatus;
  is_home?: boolean | null;
  result?: ApiResult | null;
  venue?: { name?: string | null; city?: string | null } | null;
}

export interface ApiFormItem {
  id: number;
  result: ApiResult | null;
  kickoff: string;
  opponent: ApiTeam;
  score: string;
  tournament: string;
}

export interface ApiLaliga {
  league: { id: number; name: string; logo?: string | null };
  pos: number;
  pts: number;
  played: number;
  w: number;
  d: number;
  l: number;
  gd: number;
  leader_pts: number | null;
}

export interface ApiHome extends ApiMeta {
  next: ApiFixture | null;
  last: ApiFixture | null;
  /** от нового к старому */
  form: ApiFormItem[];
  laliga: ApiLaliga | null;
  /** идёт матч Реала — матчи его тура (Ла Лига, ЛЧ); иначе null */
  round?: ApiRound | null;
}

export interface ApiFixtures extends ApiMeta {
  tournaments?: Record<string, number>;
  matches: ApiFixture[];
}

export interface ApiTableRow {
  pos: number;
  team: ApiTeam;
  played: number;
  w: number;
  d: number;
  l: number;
  gf: number;
  ga: number;
  gd: number;
  pts: number;
  zone: { label: string; color: string } | null;
  is_us: boolean;
}

export interface ApiTable {
  league: { id: number; name: string; logo?: string | null };
  rows: ApiTableRow[];
}

export interface ApiTables extends ApiMeta {
  tables: ApiTable[];
}

/** Ошибка запроса: status 0 — нет сети; 503 + code «no_data» — сборщик ещё не получил данные. */
export class ApiFetchError extends Error {
  status: number;
  code: string | null;
  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = 'ApiFetchError';
    this.status = status;
    this.code = code;
  }
}

export async function fetchApi<T>(path: string, signal?: AbortSignal): Promise<T> {
  let r: Response;
  try {
    r = await fetch(withLang(path), { cache: 'no-store', signal, headers: { Accept: 'application/json' } });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new ApiFetchError(0, null, 'Нет соединения');
  }
  if (!r.ok) {
    let code: string | null = null;
    try {
      const j = (await r.json()) as { error?: unknown };
      if (typeof j.error === 'string') code = j.error;
    } catch {
      /* не JSON */
    }
    throw new ApiFetchError(r.status, code, `HTTP ${r.status}`);
  }
  try {
    return (await r.json()) as T;
  } catch {
    throw new ApiFetchError(r.status, 'bad_json', 'Ответ сервера не разобрать');
  }
}
