/**
 * Ответы API → пропсы компонентов главной и «Матчей». Чистые функции без React и DOM:
 * их гоняют тесты (node --test) на сохранённых реальных ответах из src/__fixtures__.
 * Поэтому здесь только `import type` — рантайм-импортов из src нет.
 */
import type { ApiFetchError, ApiFixture, ApiHome, ApiMeta, ApiStatus, ApiTable, ApiTableRow, ApiTeam, ApiTournament } from './api';
import type { CompetitionRef, MatchStatus, Outcome, StandingRow, StandingZone, TeamRef } from '../ui/match';

export const RM_ID = 8633;
export const LALIGA_ID = 87;
export const UCL_ID = 42;

export const matchHref = (id: number | string) => `/match/${id}`;

/* ---------- турниры ---------- */

export interface Competition extends CompetitionRef {
  /** показывать логотип в календаре (Кубок, Суперкубок — у них нет привычного сокращения) */
  withLogo?: boolean;
}

const COMP_BY_ID: Record<number, Omit<Competition, 'id'>> = {
  87: { name: 'Ла Лига', short: 'ЛЛ', tone: 'gold' },
  42: { name: 'Лига чемпионов', short: 'ЛЧ', tone: 'ucl' },
  138: { name: 'Кубок Испании', short: 'Кубок', withLogo: true },
  139: { name: 'Суперкубок Испании', short: 'Суперкубок', withLogo: true },
};

const COMP_BY_NAME: Record<string, Omit<Competition, 'id'>> = {
  laliga: COMP_BY_ID[87],
  'champions league': COMP_BY_ID[42],
  'copa del rey': COMP_BY_ID[138],
  'super cup': COMP_BY_ID[139],
  supercopa: COMP_BY_ID[139],
  'uefa super cup': { name: 'Суперкубок УЕФА', short: 'Суперкубок УЕФА', withLogo: true },
  'fifa club world cup': { name: 'Клубный чемпионат мира', short: 'КЧМ', withLogo: true },
  'club friendlies': { name: 'Товарищеский матч', short: 'Товарищеский' },
};

export function competitionOf(t: ApiTournament | null | undefined): Competition {
  const id = t?.id ?? undefined;
  const known = (id != null ? COMP_BY_ID[id] : undefined) ?? COMP_BY_NAME[(t?.name ?? '').trim().toLowerCase()];
  if (known) return { id, ...known };
  const name = t?.name || 'Матч';
  return { id, name, short: name, withLogo: id != null };
}

/* ---------- команды и статус ---------- */

export function teamRef(t: ApiTeam | null | undefined): TeamRef {
  return { id: t?.id ?? undefined, name: t?.name || '—' };
}

export function matchStatusOf(s: ApiStatus | null | undefined): MatchStatus {
  if (s?.live || s?.state === 'live' || s?.state === 'halftime') return 'live';
  if (s?.finished || s?.state === 'finished') return 'finished';
  return 'upcoming';
}

export function scoreOf(f: Pick<ApiFixture, 'home' | 'away'>): [number, number] | undefined {
  const h = f.home?.score;
  const a = f.away?.score;
  if (h == null || a == null) return undefined;
  return [h, a];
}

/** «67′», «45+2′», «Перерыв» */
export function minuteText(s: ApiStatus): string | undefined {
  if (s.state === 'halftime') return 'Перерыв';
  if (s.minute == null) return undefined;
  return s.added ? `${s.minute}+${s.added}′` : `${s.minute}′`;
}

/** «1-й тайм», «2-й тайм», «Перерыв», «Доп. время» */
export function periodText(s: ApiStatus): string {
  if (s.state === 'halftime') return 'Перерыв';
  const m = s.minute;
  if (m == null) return 'Идёт матч';
  if (m <= 45) return '1-й тайм';
  if (m <= 90 || s.added) return '2-й тайм';
  return 'Доп. время';
}

/** Итог для Реала: из поля result, а нет его — по счёту и стороне. */
export function outcomeOf(f: ApiFixture, teamId = RM_ID): Outcome | undefined {
  if (f.result) return f.result;
  const sc = scoreOf(f);
  if (!sc) return undefined;
  if (sc[0] === sc[1]) return 'D';
  const weHome = f.is_home ?? f.home?.id === teamId;
  return sc[0] > sc[1] === weHome ? 'W' : 'L';
}

export function venueText(f: ApiFixture): string | undefined {
  const v = f.venue;
  if (!v) return undefined;
  const parts = [v.name, v.city].filter((x): x is string => !!x);
  // «Estadio Bernabéu, Madrid»; город не повторяем, если он уже в названии
  if (parts.length === 2 && parts[0].includes(parts[1])) parts.pop();
  return parts.length ? parts.join(', ') : undefined;
}

/* ---------- главная ---------- */

/** Сколько показываем итог только что сыгранного матча вместо следующего (от начала матча). */
export const JUST_FINISHED_MS = 4 * 3600_000;

export interface HeroCard {
  status: MatchStatus;
  id: number;
  href: string;
  competition: Competition;
  kickoff: string;
  home: TeamRef;
  away: TeamRef;
  score?: [number, number];
  minute?: string;
  period?: string;
  venue?: string;
}

function hero(f: ApiFixture): HeroCard {
  const status = matchStatusOf(f.status);
  return {
    status,
    id: f.id,
    href: matchHref(f.id),
    competition: competitionOf(f.tournament),
    kickoff: f.kickoff,
    home: teamRef(f.home),
    away: teamRef(f.away),
    score: status === 'upcoming' ? undefined : (scoreOf(f) ?? (status === 'live' ? [0, 0] : undefined)),
    minute: status === 'live' ? minuteText(f.status) : undefined,
    period: status === 'live' ? periodText(f.status) : undefined,
    venue: venueText(f),
  };
}

/**
 * Что в большой карточке сверху:
 * идёт матч → live; матч только что закончился (API отдаёт его как last, с начала < 4 ч) → итог;
 * иначе ближайший матч с отсчётом.
 */
export function heroOf(h: ApiHome, now = Date.now()): HeroCard | null {
  if (h.next && matchStatusOf(h.next.status) === 'live') return hero(h.next);
  if (h.last && matchStatusOf(h.last.status) === 'finished') {
    const ko = Date.parse(h.last.kickoff);
    if (Number.isFinite(ko) && now - ko >= 0 && now - ko < JUST_FINISHED_MS) return hero(h.last);
  }
  return h.next ? hero(h.next) : null;
}

/** Форма для FormStrip: от старого к новому (API отдаёт от нового к старому). */
export function formResults(h: ApiHome): Outcome[] {
  return (h.form ?? [])
    .map((f) => f.result)
    .filter((r): r is Outcome => r === 'W' || r === 'D' || r === 'L')
    .slice(0, 5)
    .reverse();
}

/** Соперники к formResults — в том же порядке (для эмблем под буквами формы). */
export function formOpponents(h: ApiHome): Array<TeamRef | undefined> {
  return (h.form ?? [])
    .filter((f) => f.result === 'W' || f.result === 'D' || f.result === 'L')
    .slice(0, 5)
    .reverse()
    .map((f) => (f.opponent ? teamRef(f.opponent) : undefined));
}

export interface LeagueSummary {
  pos: number;
  /** «место · 18 очк.» */
  line: string;
  /** «−6 до лидера», «лидер», «делит первое место» */
  gap: string;
}

export function leagueSummary(h: ApiHome): LeagueSummary | null {
  const l = h.laliga;
  if (!l) return null;
  const diff = l.leader_pts != null ? l.leader_pts - l.pts : null;
  let gap = '';
  if (l.pos === 1) gap = 'лидер';
  else if (diff != null && diff > 0) gap = `−${diff} до лидера`;
  else if (diff === 0) gap = 'вровень с лидером';
  return { pos: l.pos, line: `место · ${l.pts} очк.`, gap };
}

/** Прошлый матч (для MatchCard status="finished"). */
export function lastMatchOf(h: ApiHome): HeroCard | null {
  return h.last && matchStatusOf(h.last.status) === 'finished' ? hero(h.last) : null;
}

/**
 * Интервал опроса /api/home: во время матча — 10 с; за 5 мин до начала и до 3 ч после —
 * тоже 10 с (сборщик может отметить старт с задержкой); иначе 30 с.
 */
export function homePollMs(h: ApiHome | null, now = Date.now()): number {
  const n = h?.next;
  if (!n) return 30_000;
  if (n.status?.live) return 10_000;
  const ko = Date.parse(n.kickoff);
  if (Number.isFinite(ko) && now >= ko - 5 * 60_000 && now <= ko + 3 * 3600_000 && !n.status?.finished) return 10_000;
  return 30_000;
}

const STALE_NOTE_AFTER_S = 15 * 60;

/** «обновлено 17 мин назад», если данные помечены stale и старше 15 минут; иначе null. */
export function staleNote(meta: ApiMeta | null | undefined, extraS = 0): string | null {
  if (!meta?.stale || meta.age_s == null) return null;
  const age = meta.age_s + Math.max(0, extraS);
  if (age <= STALE_NOTE_AFTER_S) return null;
  const min = Math.floor(age / 60);
  if (min < 60) return `обновлено ${min} мин назад`;
  const hr = Math.floor(min / 60);
  if (hr < 48) return `обновлено ${hr} ч назад`;
  return `обновлено ${Math.floor(hr / 24)} дн назад`;
}

/* ---------- «Матчи» ---------- */

export type CompTab = 'all' | 'laliga' | 'ucl';

export const COMP_TABS: Array<{ id: CompTab; label: string; aside: string }> = [
  { id: 'all', label: 'Все', aside: 'все турниры' },
  { id: 'laliga', label: 'Ла Лига', aside: 'Ла Лига' },
  { id: 'ucl', label: 'Лига чемпионов', aside: 'Лига чемпионов' },
];

export function inTab(f: ApiFixture, tab: CompTab): boolean {
  if (tab === 'all') return true;
  return f.tournament?.id === (tab === 'laliga' ? LALIGA_ID : UCL_ID);
}

export interface CalendarItem {
  id: number;
  href: string;
  kickoff: string;
  home: TeamRef;
  away: TeamRef;
  competition: Competition;
  note?: string;
  /** идёт: «67′» */
  live?: string;
  highlighted?: boolean;
}

export interface ResultItem {
  id: number;
  href: string;
  kickoff: string;
  home: TeamRef;
  away: TeamRef;
  score: [number, number];
  result?: Outcome;
  competition: Competition;
}

function noteOf(f: ApiFixture): string | undefined {
  if (f.status?.state === 'postponed') return 'перенесён';
  const v = venueText(f);
  if (v) return v;
  if (f.is_home === true) return 'дома';
  if (f.is_home === false) return 'в гостях';
  return undefined;
}

/** Ближайшие (по времени, идущий — первым и в рамке) и результаты (свежие сверху). */
export function splitFixtures(matches: ApiFixture[], tab: CompTab): { upcoming: CalendarItem[]; results: ResultItem[] } {
  const list = (matches ?? []).filter((f) => inTab(f, tab));
  const byKo = (a: ApiFixture, b: ApiFixture) => Date.parse(a.kickoff) - Date.parse(b.kickoff);

  const upcoming = list
    .filter((f) => !f.status?.finished && f.status?.state !== 'cancelled' && f.status?.state !== 'abandoned')
    .sort(byKo)
    .map<CalendarItem>((f, i) => {
      const live = matchStatusOf(f.status) === 'live';
      return {
        id: f.id,
        href: matchHref(f.id),
        kickoff: f.kickoff,
        home: teamRef(f.home),
        away: teamRef(f.away),
        competition: competitionOf(f.tournament),
        note: noteOf(f),
        live: live ? (minuteText(f.status) ?? 'идёт') : undefined,
        highlighted: i === 0,
      };
    });

  const results = list
    .filter((f) => f.status?.finished && scoreOf(f))
    .sort((a, b) => byKo(b, a))
    .map<ResultItem>((f) => ({
      id: f.id,
      href: matchHref(f.id),
      kickoff: f.kickoff,
      home: teamRef(f.home),
      away: teamRef(f.away),
      score: scoreOf(f)!,
      result: outcomeOf(f),
      competition: competitionOf(f.tournament),
    }));

  return { upcoming, results };
}

/* ---------- таблицы ---------- */

export function tableFor(tables: ApiTable[] | null | undefined, leagueId: number): ApiTable | null {
  return (tables ?? []).find((t) => t.league?.id === leagueId && t.rows?.length > 0) ?? null;
}

export function standingRows(t: ApiTable): StandingRow[] {
  return t.rows.map((r) => ({
    pos: r.pos,
    team: teamRef(r.team),
    played: r.played,
    goalsFor: r.gf,
    goalsAgainst: r.ga,
    points: r.pts,
  }));
}

export function usRow(t: ApiTable): ApiTableRow | null {
  return t.rows.find((r) => r.is_us) ?? t.rows.find((r) => r.team?.id === RM_ID) ?? null;
}

/** Подписи и цвета зон: зона ЛЧ — золотом, как в макете; остальное — спокойными тонами. */
const ZONE_STYLE: Record<string, { label: string; color: string }> = {
  'champions league': { label: 'зона Лиги чемпионов', color: 'var(--gold)' },
  'europa league': { label: 'Лига Европы', color: '#5B7BD6' },
  'conference league qualification': { label: 'Лига конференций', color: '#4FA3B8' },
  'conference league': { label: 'Лига конференций', color: '#4FA3B8' },
  relegation: { label: 'зона вылета', color: '#C2453D' },
  'qualification to 1/8 finals': { label: 'выход в 1/8 финала', color: 'var(--gold)' },
  'qualification to 1/16 finals': { label: 'стыковые матчи', color: '#5B7BD6' },
};

export function zoneStyle(z: { label: string; color: string }): { label: string; color: string } {
  return ZONE_STYLE[z.label.trim().toLowerCase()] ?? { label: z.label, color: z.color };
}

/** Зоны таблицы — непрерывные диапазоны позиций с одной подписью; только те, что видны. */
export function zonesFor(t: ApiTable, visible?: StandingRow[]): StandingZone[] {
  const zones: StandingZone[] = [];
  for (const r of [...t.rows].sort((a, b) => a.pos - b.pos)) {
    if (!r.zone) continue;
    const st = zoneStyle(r.zone);
    const lastZ = zones[zones.length - 1];
    if (lastZ && lastZ.label === st.label && lastZ.to === r.pos - 1) lastZ.to = r.pos;
    else zones.push({ from: r.pos, to: r.pos, color: st.color, label: st.label });
  }
  if (!visible) return zones;
  const shown = new Set(visible.map((r) => r.pos));
  return zones.filter((z) => [...shown].some((p) => p >= z.from && p <= z.to));
}

/**
 * Свёрнутая таблица: топ-4 и ±3 строки вокруг Реала.
 * Если свёрнутая почти не короче полной (скрыто ≤ 2 строк) — показываем целиком.
 */
export function compactRows(rows: StandingRow[], usPos: number | null, top = 4, around = 3): { rows: StandingRow[]; collapsed: boolean } {
  const keep = (p: number) => p <= top || (usPos != null && Math.abs(p - usPos) <= around);
  const short = rows.filter((r) => keep(r.pos));
  if (rows.length - short.length <= 2) return { rows, collapsed: false };
  return { rows: short, collapsed: true };
}

/** «после 8 туров» — по сыгранным матчам Реала. */
export function roundsAside(t: ApiTable): string | undefined {
  const us = usRow(t);
  const n = us?.played ?? Math.max(0, ...t.rows.map((r) => r.played));
  if (!n) return undefined;
  const a = n % 100;
  const b = n % 10;
  const w = a > 10 && a < 20 ? 'туров' : b === 1 ? 'тура' : 'туров';
  return `после ${n} ${w}`;
}

/* ---------- ошибки ---------- */

export function errorText(e: Pick<ApiFetchError, 'status'> | null | undefined): { title: string; text: string } {
  if (e?.status === 503)
    return { title: 'Данные ещё собираются', text: 'Сервер пока не получил расписание. Попробуй через минуту' };
  if (e?.status === 0) return { title: 'Нет соединения', text: 'Проверь интернет и попробуй ещё раз' };
  return { title: 'Не удалось загрузить', text: 'Попробуй ещё раз чуть позже' };
}
