// Ответ /api/team и чистые функции для экрана «Команда». Без импортов — их гоняет node --test.

export interface Country {
  code: string | null;
  name: string | null;
  flag: string | null; // /img/flag/{iso2}.svg
}

export interface SquadPlayer {
  id: number;
  name: string;
  number: number | null;
  position: string | null; // FotMob: «CB,RB», «CAM,CM,LM»
  age: number | null;
  birth: string | null;
  height: number | null;
  country: Country | null;
  photo: string | null;
  rating: number | null;
  goals: number | null;
  assists: number | null;
  injured: boolean;
}

export type LineKey = 'goalkeepers' | 'defenders' | 'midfielders' | 'attackers';

export interface Injury {
  id: number;
  name: string;
  photo: string | null;
  type: 'injury' | 'suspension' | string;
  expected_return: string | null; // «Late October 2026», «Back in training»
}

export interface Leader {
  id: number;
  name: string;
  value: number;
  photo: string | null;
}

export interface TransferTeam {
  id: number | null;
  name: string;
  logo: string | null;
}

export interface Transfer {
  player: { id: number; name: string; photo: string | null };
  position: string | null;
  date: string | null;
  from: TransferTeam;
  to: TransferTeam;
  fee_text: string | null; // fee | free transfer | on loan | null
  fee_eur: number | null;
  loan: boolean;
}

export interface TeamResponse {
  team: { id: number; name: string; logo: string };
  venue: { name: string; city: string } | null;
  coach: { id: number; name: string; photo: string | null; country: Country | null } | null;
  squad: Partial<Record<LineKey, SquadPlayer[]>> | null;
  injuries: Injury[] | null;
  leaders: { goals?: Leader[]; assists?: Leader[]; rating?: Leader[] } | null;
  transfers: { in?: Transfer[]; out?: Transfer[] } | null;
  source: string;
  available: string[];
  updated_at: string;
  age_s: number;
  stale: boolean;
}

export const LINES: { key: LineKey; title: string }[] = [
  { key: 'goalkeepers', title: 'Вратари' },
  { key: 'defenders', title: 'Защитники' },
  { key: 'midfielders', title: 'Полузащитники' },
  { key: 'attackers', title: 'Нападающие' },
];

/** plural(5, ['год', 'года', 'лет']) → «лет» */
export function plural(n: number, forms: [string, string, string]): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b > 1 && b < 5) return forms[1];
  if (b === 1) return forms[0];
  return forms[2];
}

export function ageText(age: number | null | undefined): string | null {
  if (age == null || !Number.isFinite(age)) return null;
  return `${age} ${plural(age, ['год', 'года', 'лет'])}`;
}

const POS_RU: Record<string, string> = {
  GK: 'ВРТ',
  CB: 'ЦЗ',
  RB: 'ПЗ',
  RWB: 'ПЗ',
  LB: 'ЛЗ',
  LWB: 'ЛЗ',
  CDM: 'ОП',
  DM: 'ОП',
  CM: 'ЦП',
  CAM: 'АП',
  AM: 'АП',
  LM: 'ЛВ',
  RM: 'ПВ',
  LW: 'ЛВ',
  RW: 'ПВ',
  ST: 'НАП',
  CF: 'НАП',
  SS: 'НАП',
};

const LINE_CODES: Record<LineKey, string[]> = {
  goalkeepers: ['GK'],
  defenders: ['CB', 'RB', 'LB', 'RWB', 'LWB'],
  midfielders: ['CDM', 'DM', 'CM', 'CAM', 'AM', 'LM', 'RM'],
  attackers: ['LW', 'RW', 'ST', 'CF', 'SS'],
};

/** Основная позиция по-русски: первый код из списка, подходящий линии игрока («CB,RB» → «ЦЗ»). */
export function positionRu(position: string | null | undefined, line?: LineKey): string | null {
  const codes = (position ?? '')
    .split(',')
    .map((c) => c.trim().toUpperCase())
    .filter(Boolean);
  if (!codes.length) return null;
  // полузащитнику сначала ищем центральную позицию: «RB,RM,CDM,CM» у Вальверде → ОП, а не ПВ
  const central = line === 'midfielders' ? codes.find((c) => ['CDM', 'DM', 'CM', 'CAM', 'AM'].includes(c)) : undefined;
  const fit = central ?? (line ? codes.find((c) => LINE_CODES[line].includes(c)) : undefined);
  const code = fit ?? codes[0];
  return POS_RU[code] ?? null;
}

const MONTHS_EN = [
  'january', 'february', 'march', 'april', 'may', 'june',
  'july', 'august', 'september', 'october', 'november', 'december',
];
const MONTHS_GEN = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
];

export interface ReturnInfo {
  /** «конец октября», «вернулся в общую группу» */
  text: string;
  /** вернулся в общую группу — выделяем отдельно */
  back: boolean;
  /** примерная дата (для сортировки и «уже прошло»), UTC */
  date: Date | null;
  /** примерный срок уже прошёл (данные источника могли не обновиться) */
  past: boolean;
}

function parseReturn(raw: string | null | undefined, now: Date): Omit<ReturnInfo, 'past'> {
  const s = (raw ?? '').trim();
  if (!s) return { text: 'срок неизвестен', back: false, date: null };
  const low = s.toLowerCase();
  if (/back in training|returned to training|in training/.test(low)) {
    return { text: 'вернулся в общую группу', back: true, date: null };
  }
  if (/doubtful|questionable|50%/.test(low)) return { text: 'под вопросом', back: false, date: null };
  if (/unknown|indefinite/.test(low)) return { text: 'срок неизвестен', back: false, date: null };
  if (/season|end of season/.test(low)) return { text: 'до конца сезона', back: false, date: null };

  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (iso) {
    const d = new Date(Date.UTC(+iso[1], +iso[2] - 1, +iso[3]));
    return { text: `до ${d.getUTCDate()} ${MONTHS_GEN[d.getUTCMonth()]}${yearSuffix(d, now)}`, back: false, date: d };
  }
  const m = /^(early|mid|middle of|late|end of|beginning of)?\s*([a-z]+)\s+(\d{4})$/.exec(low);
  if (m) {
    const mi = MONTHS_EN.indexOf(m[2]);
    if (mi >= 0) {
      const part = m[1] ?? '';
      const day = /early|beginning/.test(part) ? 5 : /mid/.test(part) ? 15 : /late|end/.test(part) ? 25 : 15;
      const word = /early|beginning/.test(part) ? 'начало' : /mid/.test(part) ? 'середина' : /late|end/.test(part) ? 'конец' : '';
      const d = new Date(Date.UTC(+m[3], mi, day));
      const text = word ? `${word} ${MONTHS_GEN[mi]}${yearSuffix(d, now)}` : `${MONTHS_GEN[mi]}${yearSuffix(d, now)}`;
      return { text, back: false, date: d };
    }
  }
  return { text: 'срок уточняется', back: false, date: null };
}

/** FotMob «Early/Mid/Late October 2026», «Back in training», ISO-дата → по-русски. */
export function returnInfo(raw: string | null | undefined, now: Date = new Date()): ReturnInfo {
  const r = parseReturn(raw, now);
  // «начало октября» при сегодняшнем 17 октября: срок прошёл (с запасом 3 дня)
  const past = r.date != null && r.date.getTime() < now.getTime() - 3 * 86400e3;
  return { ...r, past };
}

/** Год пишем, только если возвращение дальше чем через 10 месяцев («начало января» — без года). */
function yearSuffix(d: Date, now: Date): string {
  return d.getTime() - now.getTime() > 300 * 86400e3 ? ` ${d.getUTCFullYear()}` : '';
}

/** «€125 млн», «€2,5 млн», «€500 тыс.», «аренда», «бесплатно», null — сумма неизвестна. */
export function feeText(t: Pick<Transfer, 'fee_text' | 'fee_eur' | 'loan'>): string | null {
  if (t.loan || /loan/i.test(t.fee_text ?? '')) return 'аренда';
  if (/free/i.test(t.fee_text ?? '')) return 'бесплатно';
  const v = t.fee_eur;
  if (v == null || !Number.isFinite(v) || v <= 0) return null;
  if (v >= 1e6) {
    const m = v / 1e6;
    const s = m >= 10 ? Math.round(m).toString() : (Math.round(m * 10) / 10).toString().replace('.', ',');
    return `€${s} млн`;
  }
  return `€${Math.round(v / 1e3)} тыс.`;
}

/** Сезон по МСК: с июля — «2026/27». */
export function seasonLabel(now: Date = new Date()): string {
  const msk = new Date(now.getTime() + 3 * 3600e3);
  const y = msk.getUTCFullYear();
  const start = msk.getUTCMonth() >= 6 ? y : y - 1;
  return `${start}/${String((start + 1) % 100).padStart(2, '0')}`;
}

/** /img/flag/gb-eng.svg → «gb-eng» (для компонента Flag) */
export function flagIso(flag: string | null | undefined): string | null {
  const m = /\/img\/flag\/([a-z]{2}(?:-[a-z]{3})?)\.svg$/.exec(flag ?? '');
  return m ? m[1] : null;
}
