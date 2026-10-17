// Ответ /api/player/{id} и чистые функции карточки игрока. Без рантайм-импортов — их гоняет node --test.

export interface PlayerTeam {
  id: number | null;
  name: string | null;
  logo: string | null;
  on_loan?: boolean;
}

export interface PlayerCountry {
  code: string | null; // alpha-3 FotMob: FRA, ENG
  name: string | null;
  flag: string | null; // /img/flag/{iso2}.svg
  team_id: number | null;
}

export interface PlayerLeague {
  id: number | null;
  name: string | null;
  logo: string | null;
}

export interface SeasonRow {
  league: PlayerLeague;
  matches: number | null;
  started: number | null;
  minutes: number | null;
  goals: number | null;
  assists: number | null;
  rating: number | null;
  yellow: number | null;
  red: number | null;
  clean_sheets: number | null;
  conceded: number | null;
  saves: number | null;
}

export interface SeasonTotals {
  matches: number | null;
  minutes: number | null;
  goals: number | null;
  assists: number | null;
  yellow: number | null;
  red: number | null;
  rating: number | null;
  clean_sheets?: number | null;
  conceded?: number | null;
  saves?: number | null;
}

export interface RecentMatch {
  match_id: number | null;
  kickoff: string | null;
  tournament: PlayerLeague;
  team: PlayerTeam | null;
  opponent: PlayerTeam | null;
  home: boolean;
  score: [number | null, number | null];
  result: 'W' | 'D' | 'L' | null;
  minutes: number | null;
  goals: number;
  assists: number;
  yellow: number;
  red: number;
  rating: number | null;
  potm: boolean;
}

export interface CareerEntry {
  team: PlayerTeam | null;
  start: string | null;
  end: string | null;
  active: boolean;
  loan: boolean;
  apps: number | null;
  goals: number | null;
  assists: number | null;
}

export interface PlayerStatus {
  type: 'injury' | 'suspension' | string;
  name: string | null;
  expected_return: string | null;
  updated: string | null;
}

export interface ApiPlayer {
  id: number;
  pending?: boolean;
  name: string | null;
  short_name?: string | null;
  photo: string | null;
  number: number | null;
  position: string | null;
  positions: string[];
  role: 'GK' | 'DF' | 'MF' | 'FW' | 'COACH' | null;
  team: PlayerTeam | null;
  country: PlayerCountry | null;
  birth: string | null;
  age: number | null;
  height: number | null;
  foot: 'right' | 'left' | 'both' | null;
  value_eur: number | null;
  contract_until: string | null;
  status: PlayerStatus | null;
  season: { name: string | null; team: PlayerTeam | null; totals: SeasonTotals; tournaments: SeasonRow[]; partial?: boolean } | null;
  recent: RecentMatch[];
  career: CareerEntry[];
  national: CareerEntry[];
  source: string | null;
  updated_at: string | null;
  age_s: number | null;
  stale: boolean;
  available: string[];
}

export function plural(n: number, forms: [string, string, string]): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b > 1 && b < 5) return forms[1];
  if (b === 1) return forms[0];
  return forms[2];
}

/* ---------- позиции ---------- */

const POS_RU: Record<string, string> = {
  GK: 'ВРТ',
  CB: 'ЦЗ',
  RB: 'ПЗ',
  RWB: 'ПЗ',
  LB: 'ЛЗ',
  LWB: 'ЛЗ',
  DM: 'ОП',
  CDM: 'ОП',
  CM: 'ЦП',
  AM: 'АП',
  CAM: 'АП',
  LM: 'ЛВ',
  RM: 'ПВ',
  LW: 'ЛВ',
  RW: 'ПВ',
  ST: 'НАП',
  CF: 'НАП',
};

const ROLE_RU: Record<string, string> = { GK: 'Вратарь', DF: 'Защитник', MF: 'Полузащитник', FW: 'Нападающий', COACH: 'Тренер' };

export function positionShort(code: string | null | undefined): string | null {
  return POS_RU[(code ?? '').toUpperCase()] ?? null;
}

/** Все позиции по-русски, основная первой, без повторов (LW и LM — обе «ЛВ»). */
export function positionsRu(codes: string[] | null | undefined): string[] {
  const out: string[] = [];
  for (const c of codes ?? []) {
    const r = positionShort(c);
    if (r && !out.includes(r)) out.push(r);
  }
  return out;
}

export function roleRu(role: string | null | undefined): string | null {
  return ROLE_RU[role ?? ''] ?? null;
}

/* ---------- био ---------- */

export function ageText(age: number | null | undefined): string | null {
  if (age == null || !Number.isFinite(age)) return null;
  return `${age} ${plural(age, ['год', 'года', 'лет'])}`;
}

const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

const ymd = (s: string | null | undefined) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s ?? '');
  return m ? { y: +m[1], m: +m[2], d: +m[3] } : null;
};

/** '1998-12-20' → «20 декабря 1998» */
export function dateLong(s: string | null | undefined): string | null {
  const v = ymd(s);
  return v ? `${v.d} ${MONTHS_GEN[v.m - 1]} ${v.y}` : null;
}

/** Полных лет — по дате рождения (снимок может быть суточной давности, а день рождения — сегодня). */
export function ageFromBirth(birth: string | null | undefined, now: Date = new Date()): number | null {
  const v = ymd(birth);
  if (!v) return null;
  const msk = new Date(now.getTime() + 3 * 3600e3);
  const y = msk.getUTCFullYear();
  const m = msk.getUTCMonth() + 1;
  const d = msk.getUTCDate();
  return y - v.y - (m < v.m || (m === v.m && d < v.d) ? 1 : 0);
}

export function footRu(f: string | null | undefined): string | null {
  return ({ right: 'правая', left: 'левая', both: 'обе' } as Record<string, string>)[f ?? ''] ?? null;
}

/** €120 694 930 → «€120,7 млн»; 2 326 109 → «€2,3 млн»; 800 000 → «€800 тыс.» */
export function moneyText(v: number | null | undefined): string | null {
  if (v == null || !Number.isFinite(v) || v <= 0) return null;
  if (v >= 1e6) {
    const s = (Math.round(v / 1e5) / 10).toString();
    return `€${s.replace('.', ',')} млн`;
  }
  return `€${Math.round(v / 1e3)} тыс.`;
}

const MONTHS_NOM = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];

/** '2029-06-30' → «июнь 2029» (подпись плитки — «Контракт до») */
export function contractText(s: string | null | undefined): string | null {
  const v = ymd(s);
  return v ? `${MONTHS_NOM[v.m - 1]} ${v.y}` : null;
}

const HOME_NATIONS: Record<string, string> = { 'gb-eng': 'Англия', 'gb-sct': 'Шотландия', 'gb-wls': 'Уэльс', 'gb-nir': 'Северная Ирландия' };

/** Название страны по-русски по коду флага; не вышло — как у источника. */
export function countryRu(iso2: string | null | undefined, fallback: string | null | undefined): string | null {
  const c = (iso2 ?? '').toLowerCase();
  if (HOME_NATIONS[c]) return HOME_NATIONS[c];
  if (/^[a-z]{2}$/.test(c)) {
    try {
      const n = new Intl.DisplayNames(['ru'], { type: 'region' }).of(c.toUpperCase());
      if (n && n.toUpperCase() !== c.toUpperCase()) return n;
    } catch {
      /* старый движок без Intl.DisplayNames */
    }
  }
  return fallback ?? null;
}

export function flagIso(flag: string | null | undefined): string | null {
  const m = /\/img\/flag\/([a-z]{2}(?:-[a-z]{3})?)\.svg$/.exec(flag ?? '');
  return m ? m[1] : null;
}

/* ---------- травма ---------- */

const INJURY_RU: Array<[RegExp, string]> = [
  [/cruciate|acl/i, 'разрыв крестообразной связки'],
  [/hamstring/i, 'травма задней поверхности бедра'],
  [/thigh|quadriceps/i, 'травма бедра'],
  [/calf/i, 'травма икроножной мышцы'],
  [/groin|adductor/i, 'травма паха'],
  [/ankle/i, 'травма голеностопа'],
  [/knee|meniscus/i, 'травма колена'],
  [/foot|toe/i, 'травма стопы'],
  [/shoulder/i, 'травма плеча'],
  [/back/i, 'травма спины'],
  [/hip/i, 'травма бедра'],
  [/achilles/i, 'травма ахиллова сухожилия'],
  [/muscle/i, 'мышечная травма'],
  [/ligament/i, 'травма связок'],
  [/fracture|broken/i, 'перелом'],
  [/concussion|head/i, 'травма головы'],
  [/ill|virus|flu/i, 'болезнь'],
];

export function injuryNameRu(name: string | null | undefined): string | null {
  const n = name ?? '';
  for (const [re, ru] of INJURY_RU) if (re.test(n)) return ru;
  return null;
}

export function statusTitle(s: PlayerStatus): string {
  return /suspen|ban|red card/i.test(s.type) ? 'Дисквалификация' : 'Травма';
}

/* ---------- турниры ---------- */

const TOURNAMENT_RU: Record<number, string> = {
  87: 'Ла Лига',
  42: 'Лига чемпионов',
  138: 'Кубок Испании',
  139: 'Суперкубок Испании',
  74: 'Суперкубок УЕФА',
  78: 'Клубный чемпионат мира',
  73: 'Лига Европы',
  10216: 'Лига конференций',
  47: 'Премьер-лига',
  54: 'Бундеслига',
  55: 'Серия А',
  53: 'Лига 1',
  77: 'Чемпионат мира',
  50: 'Чемпионат Европы',
  9806: 'Лига наций',
  10195: 'Отбор ЧМ',
  114: 'Товарищеский матч',
  489: 'Товарищеский матч',
};

export function tournamentRu(t: { id: number | null; name: string | null } | null | undefined): string {
  if (!t) return '';
  if (t.id != null && TOURNAMENT_RU[t.id]) return TOURNAMENT_RU[t.id];
  return t.name ?? '';
}

/** '2026/2027' → «2026/27» */
export function seasonShort(s: string | null | undefined): string | null {
  const m = /^(\d{4})\/(\d{2})(\d{2})$/.exec(s ?? '');
  return m ? `${m[1]}/${m[3]}` : (s ?? null);
}

/* ---------- ключевые цифры ---------- */

export interface KeyStat {
  label: string;
  value: string;
  gold?: boolean;
}

const n0 = (v: number | null | undefined) => (v == null ? '—' : String(v));

export function keyStats(p: ApiPlayer): KeyStat[] {
  const t = p.season?.totals;
  if (!t) return [];
  const rating: KeyStat = { label: 'Оценка', value: t.rating != null ? t.rating.toFixed(1) : '—', gold: t.rating != null && t.rating >= 7.5 };
  const matches: KeyStat = { label: 'Матчи', value: n0(t.matches) };
  if (p.role === 'GK') {
    return [matches, { label: 'Сухие', value: n0(t.clean_sheets) }, { label: 'Пропущено', value: n0(t.conceded) }, rating];
  }
  return [matches, { label: 'Голы', value: n0(t.goals) }, { label: 'Передачи', value: n0(t.assists) }, rating];
}

/* ---------- сезон по турнирам ---------- */

export interface SeasonView {
  key: string;
  league: PlayerLeague;
  name: string;
  cells: string[];
  /** «ЖК 2 · КК 1 · сейвы 25» */
  note: string | null;
}

export function seasonHead(p: ApiPlayer): string[] {
  return p.role === 'GK' ? ['И', 'Мин', 'Сух', 'Проп', 'Оц'] : ['И', 'Мин', 'Г', 'П', 'Оц'];
}

export function seasonView(p: ApiPlayer): { rows: SeasonView[]; total: string[] | null } | null {
  const s = p.season;
  if (!s || !s.tournaments.length) return null;
  const gk = p.role === 'GK';
  const cells = (r: SeasonRow | SeasonTotals) =>
    gk
      ? [n0(r.matches), n0(r.minutes), n0(r.clean_sheets), n0(r.conceded), r.rating != null ? r.rating.toFixed(1) : '—']
      : [n0(r.matches), n0(r.minutes), n0(r.goals), n0(r.assists), r.rating != null ? r.rating.toFixed(1) : '—'];
  const rows = s.tournaments.map((r, i) => {
    const note = [
      r.yellow ? `ЖК ${r.yellow}` : null,
      r.red ? `КК ${r.red}` : null,
      gk && r.saves != null ? `сейвы ${r.saves}` : null,
      r.started != null && r.matches != null && r.started !== r.matches ? `в старте ${r.started}` : null,
    ]
      .filter(Boolean)
      .join(' · ');
    return { key: `${r.league.id ?? r.league.name}-${i}`, league: r.league, name: tournamentRu(r.league), cells: cells(r), note: note || null };
  });
  return { rows, total: s.tournaments.length > 1 ? cells(s.totals) : null };
}

/* ---------- последние матчи ---------- */

export interface RecentView {
  key: string;
  href: string | null;
  date: string;
  tournament: PlayerLeague;
  tournamentName: string;
  opponent: PlayerTeam | null;
  /** «дома» / «в гостях» */
  venue: string;
  /** счёт с точки зрения команды игрока: «4 : 3» */
  score: string;
  result: 'W' | 'D' | 'L' | null;
  /** «гол · 90′», «2 гола, передача · 73′» */
  deeds: string;
  goals: number;
  rating: number | null;
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(Date.parse(iso) + 3 * 3600e3); // МСК
  return `${d.getUTCDate()} ${MONTHS_SHORT[d.getUTCMonth()]}`;
}

export function deedsText(m: Pick<RecentMatch, 'goals' | 'assists' | 'yellow' | 'red' | 'minutes'>): string {
  const parts: string[] = [];
  if (m.goals) parts.push(m.goals === 1 ? 'гол' : `${m.goals} ${plural(m.goals, ['гол', 'гола', 'голов'])}`);
  if (m.assists) parts.push(m.assists === 1 ? 'пас' : `${m.assists} ${plural(m.assists, ['пас', 'паса', 'пасов'])}`);
  if (m.red) parts.push('удалён');
  else if (m.yellow) parts.push('жёлтая');
  const what = parts.join(', ');
  const min = m.minutes != null ? `${m.minutes}′` : '';
  return [what, min].filter(Boolean).join(' · ');
}

export function recentView(p: ApiPlayer): RecentView[] {
  return (p.recent ?? []).map((m, i) => {
    const [h, a] = m.score;
    const ours = m.home ? h : a;
    const theirs = m.home ? a : h;
    return {
      key: `${m.match_id ?? i}-${m.kickoff}`,
      href: m.match_id != null ? `/match/${m.match_id}` : null,
      date: shortDate(m.kickoff),
      tournament: m.tournament,
      tournamentName: tournamentRu(m.tournament),
      opponent: m.opponent,
      venue: m.home ? 'дома' : 'в гостях',
      score: ours != null && theirs != null ? `${ours} : ${theirs}` : '– : –',
      result: m.result,
      deeds: deedsText(m),
      goals: m.goals,
      rating: m.rating,
    };
  });
}

/* ---------- карьера ---------- */

export interface CareerView {
  key: string;
  team: PlayerTeam | null;
  years: string;
  loan: boolean;
  active: boolean;
  /** «113 матчей · 95 голов» */
  stats: string | null;
}

const year = (s: string | null) => (s ? s.slice(0, 4) : null);

export function careerView(list: CareerEntry[] | null | undefined): CareerView[] {
  return (list ?? []).map((c, i) => {
    const from = year(c.start);
    const to = c.active || !c.end ? 'н. в.' : year(c.end);
    const years = from ? (from === to ? from : `${from} — ${to}`) : (to ?? '');
    const st = [
      c.apps != null ? `${c.apps} ${plural(c.apps, ['матч', 'матча', 'матчей'])}` : null,
      c.goals ? `${c.goals} ${plural(c.goals, ['гол', 'гола', 'голов'])}` : null,
    ]
      .filter(Boolean)
      .join(' · ');
    return { key: `${c.team?.id ?? c.team?.name}-${c.start}-${i}`, team: c.team, years, loan: c.loan, active: c.active, stats: st || null };
  });
}

/** «обновлено 14:20» по МСК */
export function updatedText(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return null;
  const d = new Date(t + 3 * 3600e3);
  return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
}
