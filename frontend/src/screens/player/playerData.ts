// Ответ /api/player/{id} и чистые функции карточки игрока. Рантайм-импорт — только lib/i18n (без зависимостей): их гоняет node --test.

import { isEn, pluralEn, t } from '../../lib/i18n';

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
  const en = pluralEn(n, forms);
  if (en != null) return en;
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

/** По-английски — привычные сокращения, сгруппированные так же, как русские (LM и LW — обе «LW»). */
const POS_EN: Record<string, string> = {
  GK: 'GK',
  CB: 'CB',
  RB: 'RB',
  RWB: 'RB',
  LB: 'LB',
  LWB: 'LB',
  DM: 'DM',
  CDM: 'DM',
  CM: 'CM',
  AM: 'AM',
  CAM: 'AM',
  LM: 'LW',
  RM: 'RW',
  LW: 'LW',
  RW: 'RW',
  ST: 'ST',
  CF: 'ST',
};

const ROLE_RU: Record<string, string> = { GK: 'Вратарь', DF: 'Защитник', MF: 'Полузащитник', FW: 'Нападающий', COACH: 'Тренер' };
const ROLE_EN: Record<string, string> = { GK: 'Goalkeeper', DF: 'Defender', MF: 'Midfielder', FW: 'Forward', COACH: 'Coach' };

export function positionShort(code: string | null | undefined): string | null {
  return (isEn() ? POS_EN : POS_RU)[(code ?? '').toUpperCase()] ?? null;
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
  return (isEn() ? ROLE_EN : ROLE_RU)[role ?? ''] ?? null;
}

/* ---------- био ---------- */

export function ageText(age: number | null | undefined): string | null {
  if (age == null || !Number.isFinite(age)) return null;
  return `${age} ${plural(age, ['год', 'года', 'лет'])}`;
}

const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const MONTHS_EN = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const MONTHS_SHORT_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const ymd = (s: string | null | undefined) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s ?? '');
  return m ? { y: +m[1], m: +m[2], d: +m[3] } : null;
};

/** '1998-12-20' → «20 декабря 1998» */
export function dateLong(s: string | null | undefined): string | null {
  const v = ymd(s);
  return v ? `${v.d} ${(isEn() ? MONTHS_EN : MONTHS_GEN)[v.m - 1]} ${v.y}` : null;
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
  const ru = ({ right: 'правая', left: 'левая', both: 'обе' } as Record<string, string>)[f ?? ''];
  return ru ? t(ru) : null;
}

/** €120 694 930 → «€120,7 млн»; 2 326 109 → «€2,3 млн»; 800 000 → «€800 тыс.» */
export function moneyText(v: number | null | undefined): string | null {
  if (v == null || !Number.isFinite(v) || v <= 0) return null;
  if (v >= 1e6) {
    const s = (Math.round(v / 1e5) / 10).toString();
    return t('€{s} млн', { s: isEn() ? s : s.replace('.', ',') });
  }
  return t('€{s} тыс.', { s: Math.round(v / 1e3) });
}

const MONTHS_NOM = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];

/** '2029-06-30' → «июнь 2029» (подпись плитки — «Контракт до») */
export function contractText(s: string | null | undefined): string | null {
  const v = ymd(s);
  return v ? `${(isEn() ? MONTHS_EN : MONTHS_NOM)[v.m - 1]} ${v.y}` : null;
}

const HOME_NATIONS: Record<string, string> = { 'gb-eng': 'Англия', 'gb-sct': 'Шотландия', 'gb-wls': 'Уэльс', 'gb-nir': 'Северная Ирландия' };

/** Название страны по-русски по коду флага; не вышло — как у источника. По-английски — как у источника (он английский). */
export function countryRu(iso2: string | null | undefined, fallback: string | null | undefined): string | null {
  const c = (iso2 ?? '').toLowerCase();
  if (isEn()) {
    if (fallback) return fallback;
    if (HOME_NATIONS[c]) return t(HOME_NATIONS[c]);
    if (/^[a-z]{2}$/.test(c)) {
      try {
        return new Intl.DisplayNames(['en'], { type: 'region' }).of(c.toUpperCase()) ?? null;
      } catch {
        return null;
      }
    }
    return null;
  }
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

/** Травма по-русски по названию у источника; по-английски — название источника как есть. */
export function injuryNameRu(name: string | null | undefined): string | null {
  const n = name ?? '';
  if (isEn()) return n.trim() || null;
  for (const [re, ru] of INJURY_RU) if (re.test(n)) return ru;
  return null;
}

export function statusTitle(s: PlayerStatus): string {
  return /suspen|ban|red card/i.test(s.type) ? t('Дисквалификация') : t('Травма');
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

/** Турнир по-русски; по-английски — название источника (оно английское), без него — перевод русского. */
export function tournamentRu(tn: { id: number | null; name: string | null } | null | undefined): string {
  if (!tn) return '';
  if (isEn() && tn.name) return tn.name;
  if (tn.id != null && TOURNAMENT_RU[tn.id]) return t(TOURNAMENT_RU[tn.id]);
  return tn.name ?? '';
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
  const s = p.season?.totals;
  if (!s) return [];
  const rating: KeyStat = { label: t('Оценка'), value: s.rating != null ? s.rating.toFixed(1) : '—', gold: s.rating != null && s.rating >= 7.5 };
  const matches: KeyStat = { label: t('Матчи'), value: n0(s.matches) };
  if (p.role === 'GK') {
    return [matches, { label: t('Сухие'), value: n0(s.clean_sheets) }, { label: t('Пропущено'), value: n0(s.conceded) }, rating];
  }
  return [matches, { label: t('Голы'), value: n0(s.goals) }, { label: isEn() ? 'Assists' : 'Передачи', value: n0(s.assists) }, rating];
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

/** Однобуквенные «Г»/«П» в общем словаре заняты таблицей (П — поражения), поэтому английские шапки — здесь. */
export function seasonHead(p: ApiPlayer): string[] {
  if (isEn()) return p.role === 'GK' ? ['Apps', 'Min', 'CS', 'GA', 'Rtg'] : ['Apps', 'Min', 'G', 'A', 'Rtg'];
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
      r.yellow ? t('ЖК {n}', { n: r.yellow }) : null,
      r.red ? t('КК {n}', { n: r.red }) : null,
      gk && r.saves != null ? t('сейвы {n}', { n: r.saves }) : null,
      r.started != null && r.matches != null && r.started !== r.matches ? t('в старте {n}', { n: r.started }) : null,
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
  return `${d.getUTCDate()} ${(isEn() ? MONTHS_SHORT_EN : MONTHS_SHORT)[d.getUTCMonth()]}`;
}

export function deedsText(m: Pick<RecentMatch, 'goals' | 'assists' | 'yellow' | 'red' | 'minutes'>): string {
  const parts: string[] = [];
  if (m.goals) parts.push(m.goals === 1 ? t('гол') : `${m.goals} ${plural(m.goals, ['гол', 'гола', 'голов'])}`);
  if (m.assists) parts.push(m.assists === 1 ? t('пас') : `${m.assists} ${plural(m.assists, ['пас', 'паса', 'пасов'])}`);
  if (m.red) parts.push(t('удалён'));
  else if (m.yellow) parts.push(t('жёлтая'));
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
      venue: m.home ? t('дома') : t('в гостях'),
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
    const to = c.active || !c.end ? t('н. в.') : year(c.end);
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
