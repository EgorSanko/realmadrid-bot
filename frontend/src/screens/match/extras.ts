/**
 * «Интересные факты», «Матчи тура» и «Кто победит?»: отдельные снимки сборщика (insights, round, poll)
 * внутри ответа /api/match → данные карточек. Нет данных — null, карточка не показывается.
 * Чистые функции без рантайм-импортов (только типы) — их проверяет `node --test`.
 */
import type { ApiMatch, ApiOutcomes, ApiRound, ApiStatus, AvailableKey, Side } from '../../api/match';

const has = (m: ApiMatch, k: AvailableKey) => m.available.includes(k);
const REAL_ID = 8633;

const plural = (n: number, f: [string, string, string]) => {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return f[2];
  if (b > 1 && b < 5) return f[1];
  if (b === 1) return f[0];
  return f[2];
};

/* ---------- интересные факты ---------- */

export interface InsightsView {
  main: string | null;
  teams: Array<{ id?: number; name: string; side: Side | null; items: string[] }>;
  count: number;
}

export function insightsView(m: ApiMatch): InsightsView | null {
  const ins = m.insights;
  if (!ins || !has(m, 'insights')) return null;
  const teams = ins.teams
    .filter((t) => t.items.length > 0)
    .map((t) => {
      const side: Side | null = t.team_id != null && t.team_id === m.home.id ? 'home' : t.team_id != null && t.team_id === m.away.id ? 'away' : null;
      return { id: t.team_id ?? undefined, name: side ? m[side].name ?? '' : '', side, items: t.items };
    });
  const count = teams.reduce((n, t) => n + t.items.length, 0) + (ins.main ? 1 : 0);
  if (!count) return null;
  // Реал первым
  teams.sort((a, b) => Number(b.id === REAL_ID) - Number(a.id === REAL_ID));
  return { main: ins.main, teams, count };
}

/* ---------- матчи тура ---------- */

const TOURNAMENT_RU: Record<number, string> = { 87: 'Ла Лига', 42: 'Лига чемпионов' };

export type RoundState = 'scheduled' | 'live' | 'halftime' | 'finished' | 'off';

export interface RoundRowView {
  key: string;
  id?: number;
  home: { id?: number; name: string; score: number | null; win: boolean };
  away: { id?: number; name: string; score: number | null; win: boolean };
  state: RoundState;
  /** live: «46′», перерыв: «Перерыв», завершён: «Завершён», перенесён: «Перенесён» */
  label: string | null;
  kickoff: string | null;
  ours: boolean;
}

export interface RoundView {
  /** «Ла Лига · 9-й тур» */
  title: string;
  leagueId?: number;
  /** «сыграно 8 из 10» */
  played: string;
  live: number;
  days: Array<{ key: string; kickoff: string | null; rows: RoundRowView[] }>;
}

const minuteOf = (s: ApiStatus) => (s.minute != null ? (s.added ? `${s.minute}+${s.added}′` : `${s.minute}′`) : null);

/** День по Москве (UTC+3) — группировка строк тура. */
const mskDay = (iso: string | null) => (iso ? new Date(Date.parse(iso) + 3 * 3600_000).toISOString().slice(0, 10) : 'tba');

function rowState(s: ApiStatus): [RoundState, string | null] {
  switch (s.state) {
    case 'live':
      return ['live', minuteOf(s) ?? 'идёт'];
    case 'halftime':
      return ['halftime', 'Перерыв'];
    case 'finished':
      return ['finished', 'Завершён'];
    case 'postponed':
      return ['off', 'Перенесён'];
    case 'cancelled':
      return ['off', 'Отменён'];
    case 'abandoned':
      return ['off', 'Прерван'];
    default:
      return ['scheduled', null];
  }
}

export function roundTitle(r: Pick<ApiRound, 'league' | 'round'>): string {
  const name = (r.league.id != null && TOURNAMENT_RU[r.league.id]) || r.league.name || '';
  const rd = (r.round ?? '').trim();
  return [name, /^\d+$/.test(rd) ? `${rd}-й тур` : null].filter(Boolean).join(' · ');
}

export function roundRows(r: ApiRound, matchId?: number | string | null): RoundRowView[] {
  return r.matches.map((x, i) => {
    const [state, label] = rowState(x.status);
    const started = state !== 'scheduled' && x.home.score != null && x.away.score != null;
    const hs = started ? x.home.score : null;
    const as = started ? x.away.score : null;
    const done = state === 'finished';
    return {
      key: String(x.id ?? i),
      id: x.id ?? undefined,
      home: { id: x.home.logo ? x.home.id ?? undefined : undefined, name: x.home.name ?? '', score: hs, win: done && hs! > as! },
      away: { id: x.away.logo ? x.away.id ?? undefined : undefined, name: x.away.name ?? '', score: as, win: done && as! > hs! },
      state,
      label,
      kickoff: x.kickoff,
      ours: matchId != null ? String(x.id) === String(matchId) : x.is_ours,
    };
  });
}

export function roundView(m: ApiMatch): RoundView | null {
  const r = m.round;
  if (!r || !has(m, 'round') || !r.matches.length) return null;
  const rows = roundRows(r, m.id);
  const days: RoundView['days'] = [];
  for (const row of rows) {
    const key = mskDay(row.kickoff);
    const last = days[days.length - 1];
    if (last && last.key === key) last.rows.push(row);
    else days.push({ key, kickoff: row.kickoff, rows: [row] });
  }
  const finished = rows.filter((x) => x.state === 'finished').length;
  return {
    title: roundTitle(r),
    leagueId: r.league.id ?? undefined,
    played: `сыграно ${finished} из ${rows.length}`,
    live: rows.filter((x) => x.state === 'live' || x.state === 'halftime').length,
    days,
  };
}

/* ---------- кто победит? ---------- */

export type Outcome1x2 = 'home' | 'draw' | 'away';

export interface PollRowView {
  key: 'ours' | 'fotmob';
  label: string;
  /** «124 прогноза», «263 тыс. голосов» */
  sub: string;
  parts: Array<{ k: Outcome1x2; pct: number; leader: boolean }>;
}

export interface PollView {
  rows: PollRowView[];
  /** у нас прогнозов меньше порога: сколько ещё нужно (строка «Мадридисты» без распределения) */
  need: number | null;
  /** сколько прогнозов уже есть и порог, с которого показываем распределение («уже 4 из 10») */
  have: number;
  of: number;
  /** ссылка «Сделай прогноз»: приём открыт и прогноза у пользователя нет */
  cta: boolean;
  /** прогноз пользователя «2:1», если есть */
  mine: string | null;
}

/** Проценты, в сумме ровно 100 (метод наибольших остатков). */
export function percents(o: ApiOutcomes): Record<Outcome1x2, number> {
  const keys: Outcome1x2[] = ['home', 'draw', 'away'];
  const total = o.home + o.draw + o.away;
  if (!total) return { home: 0, draw: 0, away: 0 };
  const raw = keys.map((k) => (o[k] / total) * 100);
  const out = raw.map(Math.floor);
  let rest = 100 - out.reduce((a, b) => a + b, 0);
  const order = raw.map((v, i) => [v - Math.floor(v), i] as const).sort((a, b) => b[0] - a[0]);
  for (const [, i] of order) {
    if (rest <= 0) break;
    out[i] += 1;
    rest -= 1;
  }
  return { home: out[0], draw: out[1], away: out[2] };
}

/** 963 → «963 голоса», 263 128 → «263 тыс. голосов», 1 240 000 → «1,2 млн голосов» */
export function votesText(n: number): string {
  if (n >= 1_000_000) return `${(Math.round(n / 100_000) / 10).toString().replace('.', ',')} млн голосов`;
  if (n >= 10_000) return `${Math.round(n / 1000)} тыс. голосов`;
  if (n >= 1000) return `${(Math.round(n / 100) / 10).toString().replace('.', ',')} тыс. голосов`;
  return `${n} ${plural(n, ['голос', 'голоса', 'голосов'])}`;
}

function parts(o: ApiOutcomes): PollRowView['parts'] {
  const p = percents(o);
  const max = Math.max(p.home, p.draw, p.away);
  return (['home', 'draw', 'away'] as Outcome1x2[]).map((k) => ({ k, pct: p[k], leader: max > 0 && p[k] === max }));
}

export interface PollContext {
  /** приём прогнозов на этот матч открыт */
  accepting?: boolean;
  /** прогноз пользователя на этот матч */
  mine?: { home: number; away: number } | null;
}

export function pollView(m: ApiMatch, ctx: PollContext = {}): PollView | null {
  const p = m.poll;
  if (!p || !has(m, 'poll')) return null;
  const rows: PollRowView[] = [];
  if (p.ours && p.ours.total > 0) {
    rows.push({ key: 'ours', label: 'Болельщики Мадридисты', sub: `${p.ours.total} ${plural(p.ours.total, ['прогноз', 'прогноза', 'прогнозов'])}`, parts: parts(p.ours) });
  }
  if (p.fotmob && p.fotmob.total > 0) {
    rows.push({ key: 'fotmob', label: 'FotMob', sub: votesText(p.fotmob.total), parts: parts(p.fotmob) });
  }
  const need = !p.ours && p.threshold > 0 ? Math.max(1, p.threshold - (p.ours_count || 0)) : null;
  const cta = !!ctx.accepting && !ctx.mine;
  // строки «Мадридисты» ещё нет и звать некуда — без голосов FotMob карточка пустая
  if (!rows.length && !cta) return null;
  return { rows, need: rows.some((r) => r.key === 'ours') ? null : need, have: p.ours_count || 0, of: p.threshold, cta, mine: ctx.mine ? `${ctx.mine.home}:${ctx.mine.away}` : null };
}
