/**
 * «О матче» (стадион, погода, судья) и зоны атак: ответ /api/match → данные карточек.
 * Только FotMob даёт вместимость, покрытие, погоду, статистику судьи и зоны (available: venue_details,
 * weather, referee_stats, zones); у резервов этих пунктов нет — карточки сводятся к строкам или прячутся.
 * Чистые функции без рантайм-импортов (только типы) — их проверяет `node --test`.
 */
import type { ApiMatch, ApiRefScale, ApiZone, AvailableKey } from '../../api/match';

type PeriodKey = 'all' | 'first_half' | 'second_half';

const has = (m: ApiMatch, k: AvailableKey) => m.available.includes(k);

/** 5.51 → «5,51»; целые — без дробной части */
export function decimalRu(v: number, digits = 2): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '').replace('.', ',');
}

export const thousandsRu = (n: number) => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');

/** '/img/flag/es.svg' → 'es' */
export function flagIsoOf(flag: string | null | undefined): string | null {
  const r = /\/img\/flag\/([a-z]{2}(?:-[a-z]{3})?)\.svg$/.exec(flag ?? '');
  return r ? r[1] : null;
}

const HOME_NATIONS: Record<string, string> = { 'gb-eng': 'Англия', 'gb-sct': 'Шотландия', 'gb-wls': 'Уэльс', 'gb-nir': 'Северная Ирландия' };

/** Страна по-русски по коду флага (как countryRu в карточке игрока); не вышло — null (английский не выводим). */
export function countryNameRu(iso2: string | null | undefined): string | null {
  const c = (iso2 ?? '').toLowerCase();
  if (HOME_NATIONS[c]) return HOME_NATIONS[c];
  if (!/^[a-z]{2}$/.test(c)) return null;
  try {
    const n = new Intl.DisplayNames(['ru'], { type: 'region' }).of(c.toUpperCase());
    return n && n.toUpperCase() !== c.toUpperCase() ? n : null;
  } catch {
    return null; // старый движок без Intl.DisplayNames
  }
}

const TOURNAMENT_RU: Record<number, string> = {
  87: 'Ла Лиге',
  42: 'Лиге чемпионов',
  138: 'Кубке Испании',
  139: 'Суперкубке Испании',
  47: 'АПЛ',
  55: 'Серии А',
  54: 'Бундеслиге',
  53: 'Лиге 1',
};

/* ---------- стадион и погода ---------- */

const SURFACE_RU: Record<string, string> = {
  grass: 'Трава',
  natural: 'Трава',
  artificial: 'Искусственный газон',
  artificial_turf: 'Искусственный газон',
  hybrid: 'Гибридный газон',
};

export interface StadiumView {
  name: string;
  city?: string;
  /** iso2 флага страны стадиона */
  iso?: string;
  country?: string;
  /** «83 186» */
  capacity?: string;
  /** «Трава» */
  surface?: string;
  attendance?: string;
}

export function stadiumView(m: ApiMatch): StadiumView | null {
  const v = m.venue;
  if (!v?.name || !has(m, 'venue')) return null;
  const iso = flagIsoOf(v.flag) ?? undefined;
  const details = has(m, 'venue_details');
  const city = v.city && !v.name.includes(v.city) ? v.city : undefined;
  return {
    name: v.name,
    city,
    iso,
    country: (iso && countryNameRu(iso)) || undefined,
    capacity: details && v.capacity ? thousandsRu(v.capacity) : undefined,
    surface: details && v.surface ? SURFACE_RU[v.surface.toLowerCase()] : undefined,
    attendance: m.attendance ? thousandsRu(m.attendance) : undefined,
  };
}

/** Словарь FotMob (translationFile ru): weather_condition_* */
const WEATHER_RU: Record<string, string> = {
  weather_condition_rain: 'Дождь',
  weather_condition_light_rain: 'Небольшой дождь',
  weather_condition_heavy_rain: 'Сильный дождь',
  weather_condition_thunderstorms: 'Грозы',
  weather_condition_snowy: 'Снег',
  weather_condition_foggy: 'Туман',
  weather_condition_windy: 'Ветрено',
  weather_condition_cloudy: 'Облачно',
  weather_condition_partly_cloudy: 'Переменная облачность',
  weather_condition_mostly_cloudy: 'Облачно с прояснениями',
  weather_condition_clear: 'Ясно',
  weather_condition_sunny: 'Солнечно',
  weather_condition_stormy: 'Шторм',
};

export type WeatherIcon = 'clear' | 'partly' | 'cloudy' | 'rain' | 'storm' | 'snow' | 'fog' | 'wind';

const ICON_BY_KEY: Array<[RegExp, WeatherIcon]> = [
  [/thunder|storm/, 'storm'],
  [/snow/, 'snow'],
  [/rain/, 'rain'],
  [/fog/, 'fog'],
  [/wind/, 'wind'],
  [/partly|mostly/, 'partly'],
  [/cloud/, 'cloudy'],
  [/clear|sunny/, 'clear'],
];

export interface WeatherView {
  /** «10 °C» */
  temp: string;
  /** «Облачно»; ключа нет в словаре — null (английский не выводим) */
  text: string | null;
  icon: WeatherIcon;
  /** «влажность 78% · облачность 92% · осадки 0 мм» */
  details: string;
}

export function weatherView(m: ApiMatch): WeatherView | null {
  const w = m.weather;
  if (!w || w.temp == null || !has(m, 'weather')) return null;
  const key = (w.key ?? '').toLowerCase();
  const icon = ICON_BY_KEY.find(([re]) => re.test(key))?.[1] ?? 'cloudy';
  const details = [
    w.humidity != null ? `влажность ${w.humidity}%` : null,
    w.cloud != null ? `облачность ${w.cloud}%` : null,
    w.precip != null ? `осадки ${decimalRu(w.precip, 1)} мм` : null,
  ]
    .filter(Boolean)
    .join(' · ');
  return { temp: `${Math.round(w.temp)} °C`, text: WEATHER_RU[key] ?? null, icon, details };
}

/* ---------- судья ---------- */

export type RefLevel = 'above' | 'average' | 'below';

const LEVEL_RU: Record<RefLevel, string> = { above: 'Выше среднего', average: 'Средний', below: 'Ниже среднего' };

export function refereeLevelText(level: RefLevel | null | undefined): string | null {
  return level ? LEVEL_RU[level] ?? null : null;
}

export interface RefScaleView {
  /** «5,51» */
  value: string;
  /** «4,46» — среднее по лиге */
  avg: string | null;
  level: RefLevel | null;
  /** «Выше среднего» */
  label: string | null;
  /** позиция значения и среднего на шкале, 0..100 */
  fill: number;
  avgFill: number | null;
}

const clamp = (v: number) => Math.max(0, Math.min(100, v));

function scaleView(s: ApiRefScale | null | undefined): RefScaleView | null {
  if (!s || s.per_match == null) return null;
  // FotMob даёт позиции сам; нет — считаем: среднее посередине шкалы, значение — относительно него
  const avgFill = s.avg_fill != null ? clamp(s.avg_fill) : s.avg ? 50 : null;
  const fill = s.fill != null ? clamp(s.fill) : s.avg ? clamp((s.per_match / s.avg) * 50) : 50;
  return {
    value: decimalRu(s.per_match),
    avg: s.avg != null ? decimalRu(s.avg) : null,
    level: s.level ?? null,
    label: refereeLevelText(s.level),
    fill,
    avgFill,
  };
}

export interface RefereeView {
  name: string;
  /** id FotMob — фото /img/player/{id}.png; нет — силуэт */
  id?: number;
  iso?: string;
  country?: string;
  /** «37 матчей в Ла Лиге» */
  matches?: string;
  yellow: RefScaleView | null;
  fouls: RefScaleView | null;
  tiles: Array<{ label: string; value: string }>;
}

const plural = (n: number, f: [string, string, string]) => {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return f[2];
  if (b > 1 && b < 5) return f[1];
  if (b === 1) return f[0];
  return f[2];
};

export function refereeView(m: ApiMatch): RefereeView | null {
  if (!m.referee || !has(m, 'referee')) return null;
  const iso = flagIsoOf(m.referee_country?.flag) ?? undefined;
  const base: RefereeView = { name: m.referee, iso, country: (iso && countryNameRu(iso)) || undefined, yellow: null, fouls: null, tiles: [] };
  const ri = has(m, 'referee_stats') ? m.referee_info : null;
  if (!ri) return base;
  const id = ri.id != null && ri.id > 0 && ri.photo ? ri.id : undefined;
  let matches: string | undefined;
  if (ri.matches != null) {
    const where = ri.league?.id != null && TOURNAMENT_RU[ri.league.id] ? ` в ${TOURNAMENT_RU[ri.league.id]}` : ' в лиге';
    matches = `${ri.matches} ${plural(ri.matches, ['матч', 'матча', 'матчей'])}${where}`;
  }
  const tiles: RefereeView['tiles'] = [];
  if (ri.yellow?.total != null) tiles.push({ label: 'Жёлтых всего', value: thousandsRu(ri.yellow.total) });
  if (ri.red != null) tiles.push({ label: 'Красных', value: String(ri.red) });
  if (ri.pens != null) tiles.push({ label: 'Пенальти', value: String(ri.pens) });
  return { ...base, id, matches, yellow: scaleView(ri.yellow), fouls: scaleView(ri.fouls), tiles };
}

/** Свёрнутая строка «О матче» в лайве: «Estadio Bernabéu · 10° · Mateo Busquets Ferrer». */
export function infoLine(m: ApiMatch): string | null {
  const st = stadiumView(m);
  const w = weatherView(m);
  const parts = [st?.name, w ? `${Math.round(m.weather!.temp)}°` : null, m.referee && has(m, 'referee') ? m.referee : null].filter(Boolean);
  return parts.length ? parts.join(' · ') : null;
}

/* ---------- зоны атак ---------- */

export interface ZonesView {
  home: ApiZone;
  away: ApiZone;
  /** самая «горячая» зона у каждой команды — подсветка золотом */
  hot: { home: keyof ApiZone; away: keyof ApiZone };
}

const hottest = (z: ApiZone): keyof ApiZone =>
  (['left', 'center', 'right'] as Array<keyof ApiZone>).reduce((a, b) => (z[b] > z[a] ? b : a), 'left');

export function zonesView(m: ApiMatch, period: PeriodKey = 'all'): ZonesView | null {
  if (!has(m, 'zones') || !m.zones) return null;
  const z = m.zones[period] ?? (period === 'all' ? null : m.zones.all);
  if (!z?.home || !z?.away) return null;
  return { home: z.home, away: z.away, hot: { home: hottest(z.home), away: hottest(z.away) } };
}

/** Доля зоны → прозрачность золотой заливки (0.08…0.6): чем больше атак, тем «горячее». */
export function zoneHeat(pct: number): number {
  return Math.round((0.08 + Math.max(0, Math.min(1, pct / 70)) * 0.52) * 100) / 100;
}

