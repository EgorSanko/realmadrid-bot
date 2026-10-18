/**
 * Ответ /api/match → пропсы компонентов экрана матча.
 * Чистые функции без рантайм-импортов (только типы) — их проверяет `node --test`.
 * Даты здесь не форматируются: это делают компоненты (по МСК, ui/format.ts).
 */
import type {
  ApiEvent,
  ApiGoal,
  ApiLineupPlayer,
  ApiLineupSide,
  ApiMatch,
  ApiPerson,
  ApiStat,
  AvailableKey,
  Side,
} from '../../api/match';
import type {
  MatchStatus,
  Outcome,
  PitchPlayer,
  ScorerLine,
  Shot,
  TeamRef,
  TimelineItem,
} from '../../ui';

export const REAL_ID = 8633;

export const has = (m: ApiMatch, k: AvailableKey) => m.available.includes(k);

const other = (s: Side): Side => (s === 'home' ? 'away' : 'home');

/** На чьей стороне Реал; если его нет в матче — хозяева. */
export function realSide(m: ApiMatch): Side {
  if (m.away.id === REAL_ID) return 'away';
  if (m.home.id === REAL_ID) return 'home';
  if (/real madrid/i.test(m.away.name ?? '') && !/real madrid/i.test(m.home.name ?? '')) return 'away';
  return 'home';
}

export function teamRef(m: ApiMatch, side: Side): TeamRef {
  const t = m[side];
  // только настоящая эмблема с нашего сервера; без logo — место пустое
  return { id: t.logo && t.id != null ? Number(t.id) : undefined, name: t.name ?? '' };
}

/* ---------- имена ---------- */

const SUFFIX = new Set(['junior', 'júnior', 'jr', 'jr.', 'filho', 'neto', 'ii', 'iii']);
const PARTICLE = new Set(['de', 'da', 'do', 'dos', 'das', 'del', 'della', 'di', 'van', 'von', 'der', 'den', 'la', 'le', 'ten', 'ter', 'el', 'al', 'mac']);

/** Фамилия латиницей, как в API: «Marten de Roon» → «de Roon», «Vinícius Júnior» → «Vinícius». */
export function shortName(full: string | null | undefined): string {
  const name = (full ?? '').trim();
  if (!name) return '';
  let w = name.split(/\s+/);
  while (w.length > 1 && SUFFIX.has(w[w.length - 1].toLowerCase())) w = w.slice(0, -1);
  if (w.length === 1) return w[0];
  let i = w.length - 1;
  while (i > 1 && PARTICLE.has(w[i - 1].toLowerCase())) i--;
  return w.slice(i).join(' ');
}

/** Ключ для сравнения имён между источниками: без диакритики и регистра. */
export function nameKey(s: string | null | undefined): string {
  return (s ?? '')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z]/g, '');
}

function samePerson(p: ApiPerson | null | undefined, id: number | string | null | undefined, name: string | null | undefined) {
  if (!p) return false;
  if (p.id != null && id != null && String(p.id) === String(id)) return true;
  const a = nameKey(p.name);
  const b = nameKey(name);
  return !!a && !!b && (a === b || (a.length > 5 && b.length > 5 && (a.includes(b) || b.includes(a))));
}

const photoId = (p: { id: number | string | null; photo: string | null } | null | undefined): number | undefined => {
  if (!p || !p.photo || p.id == null) return undefined;
  const n = Number(p.id);
  return Number.isFinite(n) && n > 0 ? n : undefined;
};

/* ---------- склонения ---------- */

export function plural(n: number, forms: [string, string, string]): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b > 1 && b < 5) return forms[1];
  if (b === 1) return forms[0];
  return forms[2];
}

export const minuteText = (minute: number | null | undefined, added?: number | null) =>
  minute == null ? '' : added ? `${minute}+${added}′` : `${minute}′`;

/* ---------- турнир ---------- */

const TOURNAMENT_RU: Record<number, string> = {
  87: 'Ла Лига',
  42: 'Лига чемпионов',
  138: 'Кубок Испании',
  139: 'Суперкубок Испании',
  77: 'Чемпионат мира по клубам',
  73: 'Лига Европы',
  10611: 'Лига чемпионов',
};

export function tournamentName(m: ApiMatch): string {
  const t = m.tournament;
  if (t.id != null && TOURNAMENT_RU[t.id]) return TOURNAMENT_RU[t.id];
  return t.name ?? '';
}

const ROUND_RU: Array<[RegExp, string]> = [
  [/^final$/i, 'Финал'],
  [/semi/i, 'Полуфинал'],
  [/quarter/i, 'Четвертьфинал'],
  [/round of 16|1\/8/i, '1/8 финала'],
  [/round of 32|1\/16/i, '1/16 финала'],
  [/play-?off/i, 'Плей-офф'],
];

export function roundName(round: string | null | undefined): string | null {
  const r = (round ?? '').trim();
  if (!r) return null;
  if (/^\d+$/.test(r)) return `${r}-й тур`;
  for (const [re, ru] of ROUND_RU) if (re.test(r)) return ru;
  return null; // «League Stage» и прочее — без подписи, чем по-английски
}

/** «Лига чемпионов · 2-й тур» */
export function tournamentLine(m: ApiMatch): string {
  return [tournamentName(m), roundName(m.tournament.round)].filter(Boolean).join(' · ');
}

/* ---------- шапка ---------- */

export type Phase = 'pending' | 'scheduled' | 'live' | 'halftime' | 'finished' | 'postponed' | 'cancelled' | 'abandoned';

export interface HeaderView {
  phase: Phase;
  /** для ScoreHeader */
  status: MatchStatus;
  score?: [number, number];
  /** live: «67′», «45+2′» */
  minute?: string;
  /** своя подпись под счётом; нет — ScoreHeader пишет дату сам */
  statusText?: string;
  live: boolean;
  /** показывать обратный отсчёт */
  countdown: boolean;
  scorers: { home: ScorerLine[]; away: ScorerLine[] };
}

const scoreOf = (m: ApiMatch): [number, number] | undefined =>
  m.home.score != null && m.away.score != null ? [m.home.score, m.away.score] : undefined;

export function headerView(m: ApiMatch, now: number = Date.now()): HeaderView {
  const st = m.status.state;
  const scorers = scorerLines(m);
  const score = scoreOf(m);
  const kick = m.kickoff ? Date.parse(m.kickoff) : NaN;
  if (m.pending) {
    // строка календаря: статус может быть любым, но подробностей ещё нет
    const base = headerView({ ...m, pending: false }, now);
    return { ...base, phase: 'pending' };
  }
  switch (st) {
    case 'live':
      return {
        phase: 'live',
        status: 'live',
        score: score ?? [0, 0],
        minute: m.status.minute != null ? minuteText(m.status.minute, m.status.added) : undefined,
        statusText: m.status.minute == null ? 'Идёт матч' : undefined,
        live: true,
        countdown: false,
        scorers,
      };
    case 'halftime':
      return { phase: 'halftime', status: 'live', score: score ?? [0, 0], statusText: 'Перерыв', live: true, countdown: false, scorers };
    case 'finished': {
      const label = (m.status.label ?? '').toUpperCase();
      const statusText = label === 'AET' ? 'Завершён после доп. времени' : label.startsWith('PEN') ? 'Завершён по пенальти' : undefined;
      return { phase: 'finished', status: 'finished', score, statusText, live: false, countdown: false, scorers };
    }
    case 'abandoned':
      return { phase: 'abandoned', status: score ? 'finished' : 'upcoming', score, statusText: 'Матч прерван', live: false, countdown: false, scorers };
    case 'postponed':
      return { phase: 'postponed', status: 'upcoming', statusText: 'Матч перенесён', live: false, countdown: false, scorers };
    case 'cancelled':
      return { phase: 'cancelled', status: 'upcoming', statusText: 'Матч отменён', live: false, countdown: false, scorers };
    default:
      return {
        phase: 'scheduled',
        status: 'upcoming',
        // без времени начала ScoreHeader не напишет подпись — пишем сами
        statusText: m.kickoff ? undefined : 'Время уточняется',
        live: false,
        countdown: Number.isFinite(kick) && kick > now,
        scorers,
      };
  }
}

/** «Roma 3 : 4 Real Madrid» / «Real Madrid — Sevilla» — заголовок на вкладках без большой шапки. */
export function compactTitle(m: ApiMatch): string {
  const s = scoreOf(m);
  const started = ['live', 'halftime', 'finished', 'abandoned'].includes(m.status.state);
  return s && started ? `${m.home.name} ${s[0]} : ${s[1]} ${m.away.name}` : `${m.home.name} — ${m.away.name}`;
}

/* ---------- голы ---------- */

interface GoalInfo {
  ev: ApiGoal;
  /** кому засчитан (по изменению счёта, иначе по side) */
  side: Side;
  score?: [number, number];
}

/** Голы основного и доп. времени по порядку; серия пенальти — отдельно, сюда не входит. */
export function goals(m: ApiMatch): GoalInfo[] {
  const out: GoalInfo[] = [];
  let prev: [number, number] = [0, 0];
  for (const e of m.events) {
    if (e.type !== 'goal' || e.shootout) continue;
    const sc = e.score && e.score[0] != null && e.score[1] != null ? ([e.score[0], e.score[1]] as [number, number]) : undefined;
    let side: Side | null = null;
    if (sc) {
      if (sc[0] > prev[0] && sc[1] === prev[1]) side = 'home';
      else if (sc[1] > prev[1] && sc[0] === prev[0]) side = 'away';
      prev = sc;
    }
    if (!side) side = e.own_goal && e.side ? other(e.side) : (e.side ?? 'home');
    out.push({ ev: e, side, score: sc });
  }
  return out;
}

export function goalKey(g: ApiGoal): string {
  return `g:${g.minute}:${g.added ?? 0}:${nameKey(g.player?.name)}`;
}

export function scorerLines(m: ApiMatch): { home: ScorerLine[]; away: ScorerLine[] } {
  const res: { home: ScorerLine[]; away: ScorerLine[] } = { home: [], away: [] };
  for (const g of goals(m)) {
    const nm = shortName(g.ev.player?.name) || 'Гол';
    const tag = g.ev.own_goal ? ' (авт.)' : g.ev.penalty ? ' (пен.)' : '';
    const list = res[g.side];
    const key = nm + (g.ev.own_goal ? '#og' : '');
    const found = list.find((s) => (s as ScorerLine & { k?: string }).k === key);
    const min = minuteText(g.ev.minute, g.ev.added) + tag;
    if (found) found.minutes.push(min);
    else list.push(Object.assign({ name: nm, minutes: [min] }, { k: key }));
  }
  // служебный ключ в пропсы не отдаём
  const clean = (l: ScorerLine[]) => l.map(({ name, minutes }) => ({ name, minutes }));
  return { home: clean(res.home), away: clean(res.away) };
}

/* ---------- хронология ---------- */

const VAR_RU: Array<[RegExp, string]> = [
  [/goal.*(cancel|disallow|overturn)|no goal/i, 'гол отменён'],
  [/penalty.*(cancel|overturn)|no penalty/i, 'пенальти отменён'],
  [/red card.*(cancel|overturn)|no red/i, 'красная отменена'],
  [/penalty/i, 'назначен пенальти'],
  [/red card/i, 'красная карточка'],
  [/goal/i, 'гол засчитан'],
];

function varText(e: Extract<ApiEvent, { type: 'var' }>): string {
  const t = `${e.decision ?? ''} ${e.text ?? ''}`.trim();
  for (const [re, ru] of VAR_RU) if (re.test(t)) return ru;
  return 'проверка VAR';
}

const PERIOD_RU: Record<string, string> = { HT: 'Перерыв', FT: 'Основное время', AET: 'Дополнительное время', ET: 'Дополнительное время' };

export interface TimelineView {
  items: TimelineItem[];
  /** ключ гола для каждой строки (или null) — для подсветки нового гола */
  goalKeys: Array<string | null>;
}

export function timelineView(m: ApiMatch): TimelineView {
  const items: TimelineItem[] = [];
  const goalKeys: Array<string | null> = [];
  const goalSide = new Map<ApiGoal, GoalInfo>();
  for (const g of goals(m)) goalSide.set(g.ev, g);
  const evs = m.events;
  const push = (it: TimelineItem, key: string | null = null) => {
    items.push(it);
    goalKeys.push(key);
  };
  evs.forEach((e, idx) => {
    const minute = e.minute ?? 0;
    const addedTime = e.added ?? undefined;
    switch (e.type) {
      case 'goal': {
        const g = goalSide.get(e);
        if (!g) return; // серия пенальти
        const detail = [e.own_goal ? 'автогол' : null, e.penalty ? 'пенальти' : null].filter(Boolean).join(' · ');
        push(
          {
            minute,
            addedTime,
            side: g.side,
            type: e.own_goal ? 'own-goal' : 'goal',
            player: shortName(e.player?.name) || 'Гол',
            playerId: photoId(e.player),
            related: e.assist?.name ? { id: photoId(e.assist), name: shortName(e.assist.name), prefix: 'пас' } : undefined,
            detail: detail || undefined,
            score: g.score,
          },
          goalKey(e),
        );
        return;
      }
      case 'card':
        if (!e.side) return;
        push({
          minute,
          addedTime,
          side: e.side,
          type: e.card === 'red' ? 'red' : e.card === 'second_yellow' ? 'second-yellow' : 'yellow',
          player: shortName(e.player?.name) || 'Карточка',
          playerId: photoId(e.player),
          detail: e.card === 'second_yellow' ? 'вторая жёлтая' : undefined,
        });
        return;
      case 'sub':
        if (!e.side) return;
        push({
          minute,
          addedTime,
          side: e.side,
          type: 'sub',
          player: shortName(e.player_in?.name) || 'Замена',
          playerId: photoId(e.player_in),
          related: e.player_out?.name ? { id: photoId(e.player_out), name: shortName(e.player_out.name), prefix: 'ушёл' } : undefined,
          detail: e.injury ? 'травма' : undefined,
        });
        return;
      case 'var':
        if (!e.side) return;
        push({ minute, addedTime, side: e.side, type: 'var', player: shortName(e.player?.name) || 'VAR', playerId: photoId(e.player), detail: varText(e) });
        return;
      case 'penalty_missed':
        if (!e.side) return;
        push({
          minute,
          addedTime,
          side: e.side,
          type: 'penalty-missed',
          player: shortName(e.player?.name) || 'Пенальти',
          playerId: photoId(e.player),
          detail: 'не забил пенальти',
        });
        return;
      case 'period': {
        const label = (e.label ?? '').toUpperCase();
        // конец матча в хронологии не нужен — он в шапке; конец основного времени — только если было продолжение
        const rest = evs.slice(idx + 1).some((x) => x.type !== 'period' && x.type !== 'added_time');
        if (label !== 'HT' && !rest) return;
        const sc = e.score && e.score[0] != null && e.score[1] != null ? ` · ${e.score[0]}:${e.score[1]}` : '';
        push({ kind: 'divider', label: `${PERIOD_RU[label] ?? 'Перерыв'}${sc}` });
        return;
      }
      default:
        return; // added_time — не показываем
    }
  });
  return { items, goalKeys };
}

/* ---------- лучшие игроки ---------- */

export interface StarView {
  id?: number;
  name: string;
  rating: number;
}

export function bestOfSide(m: ApiMatch, side: Side): StarView | null {
  const lu = m.lineups?.[side];
  if (!lu || !has(m, 'ratings')) return null;
  let best: ApiLineupPlayer | null = null;
  for (const p of [...lu.starters, ...lu.subs]) if (p.rating != null && (!best || p.rating > (best.rating ?? 0))) best = p;
  return best && best.rating != null ? { id: photoId(best), name: shortName(best.name), rating: best.rating } : null;
}

export function potmView(m: ApiMatch): StarView | null {
  const p = m.potm;
  if (!p || !p.name || !has(m, 'potm')) return null;
  let rating = p.rating;
  if (rating == null && m.lineups && p.side) {
    const lp = [...m.lineups[p.side].starters, ...m.lineups[p.side].subs].find((x) => samePerson(p, x.id, x.name));
    rating = lp?.rating ?? null;
  }
  if (rating == null) return null;
  return { id: photoId(p), name: shortName(p.name), rating };
}

/* ---------- о матче ---------- */

/** '/img/flag/it.svg' → 'it' (и 'gb-eng'); иначе null — флага не будет. */
export function flagIso(flag: string | null | undefined): string | null {
  const r = /\/img\/flag\/([a-z]{2}(?:-[a-z]{3})?)\.svg$/.exec(flag ?? '');
  return r ? r[1] : null;
}

/** Строки «О матче»: [подпись, значение, iso2 флага?] — флаг, если источник дал страну. */
export type AboutRow = [string, string] | [string, string, string];

export function aboutRows(m: ApiMatch): AboutRow[] {
  const rows: AboutRow[] = [];
  const row = (k: string, v: string, flag?: string | null): AboutRow => {
    const iso = flagIso(flag);
    return iso ? [k, v, iso] : [k, v];
  };
  if (m.venue?.name) {
    const city = m.venue.city && !m.venue.name.includes(m.venue.city) ? `, ${m.venue.city}` : '';
    rows.push(row('Стадион', `${m.venue.name}${city}`, m.venue.flag));
  }
  if (m.attendance) rows.push(['Зрители', groupThousands(m.attendance)]);
  if (m.referee) rows.push(row('Судья', m.referee, m.referee_country?.flag));
  return rows;
}

export const groupThousands = (n: number) => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');

/* ---------- видеообзор ---------- */

export function youtubeId(url: string | null | undefined): string | null {
  const m = /(?:youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/|live\/)|youtu\.be\/)([\w-]{11})/.exec(url ?? '');
  return m ? m[1] : null;
}

export interface HighlightView {
  href: string;
  /** превью с нашего сервера; нет id YouTube — без картинки */
  thumb?: string;
  title: string;
  provider?: string;
}

export function highlightView(m: ApiMatch): HighlightView | null {
  const h = m.highlights;
  if (!h?.url || !has(m, 'highlights') || !/^https?:\/\//i.test(h.url)) return null;
  const id = youtubeId(h.url);
  const s = scoreOf(m);
  return {
    href: h.url,
    thumb: id ? `/img/yt/${id}.jpg` : undefined,
    title: `Видеообзор: ${m.home.name} ${s ? `${s[0]}:${s[1]}` : '—'} ${m.away.name}`,
    provider: id || /youtu/i.test(h.source ?? h.url) ? 'YouTube' : undefined,
  };
}

/* ---------- личные встречи и форма ---------- */

export interface H2HView {
  home: { id?: number; name: string; wins: number };
  away: { id?: number; name: string; wins: number };
  draws: number;
  matches: Array<{ kickoff: string; home: TeamRef; away: TeamRef; score: [number, number]; result?: Outcome }>;
}

export const parseScore = (s: string | null | undefined): [number, number] | null => {
  const r = /^\s*(\d+)\s*[-:–]\s*(\d+)/.exec(s ?? '');
  return r ? [Number(r[1]), Number(r[2])] : null;
};

export function h2hView(m: ApiMatch, limit = 5): H2HView | null {
  const h = m.h2h;
  if (!h || !has(m, 'h2h')) return null;
  const matches: H2HView['matches'] = [];
  for (const x of h.matches) {
    const sc = parseScore(x.score);
    if (!x.finished || !sc || !x.kickoff) continue;
    const realHome = x.home.id === REAL_ID;
    const realAway = x.away.id === REAL_ID;
    let result: Outcome | undefined;
    if (realHome || realAway) {
      const [us, them] = realHome ? sc : [sc[1], sc[0]];
      result = us > them ? 'W' : us < them ? 'L' : 'D';
    }
    matches.push({
      kickoff: x.kickoff,
      home: { id: x.home.id ?? undefined, name: x.home.name ?? '' },
      away: { id: x.away.id ?? undefined, name: x.away.name ?? '' },
      score: sc,
      result,
    });
    if (matches.length >= limit) break;
  }
  const s = h.summary ?? { home_wins: null, draws: null, away_wins: null };
  if (s.home_wins == null && s.draws == null && s.away_wins == null && matches.length === 0) return null;
  return {
    home: { id: teamRef(m, 'home').id, name: m.home.name ?? '', wins: s.home_wins ?? 0 },
    away: { id: teamRef(m, 'away').id, name: m.away.name ?? '', wins: s.away_wins ?? 0 },
    draws: s.draws ?? 0,
    matches,
  };
}

export function formView(
  m: ApiMatch,
): Array<{ side: Side; team: TeamRef; results: Outcome[]; opponents: Array<TeamRef | undefined> }> | null {
  if (!m.form || !has(m, 'form')) return null;
  const rows = (['home', 'away'] as Side[]).map((side) => {
    const list = [...(m.form?.[side] ?? [])]
      .sort((a, b) => (a.kickoff ?? '').localeCompare(b.kickoff ?? ''))
      .filter((f) => f.result === 'W' || f.result === 'D' || f.result === 'L');
    return {
      side,
      team: teamRef(m, side),
      results: list.map((f) => f.result as Outcome),
      // соперник — эмблема под буквой (FotMob даёт id; у других источников нет)
      opponents: list.map((f) =>
        f.opponent ? { id: f.opponent.id ?? undefined, name: f.opponent.name ?? '' } : undefined,
      ),
    };
  });
  if (rows.every((r) => r.results.length === 0)) return null;
  // Реал первым
  const rs = realSide(m);
  return rows.sort((a, b) => Number(b.side === rs) - Number(a.side === rs));
}

/* ---------- составы ---------- */

export interface SubView {
  key: string;
  id?: number;
  number?: number;
  name: string;
  /** «вышел на 59′ вместо Vinícius · гол, 2 передачи» */
  detail: string;
  rating?: number;
  scored: boolean;
}

export interface StarterRow {
  key: string;
  id?: number;
  number?: number;
  name: string;
  position?: string;
  rating?: number;
}

export interface LineupView {
  side: Side;
  team: TeamRef;
  confirmed: boolean;
  formation?: string;
  avgRating?: number;
  /** есть координаты — поле; нет — список стартового состава */
  pitch: PitchPlayer[] | null;
  starters: StarterRow[];
  subs: SubView[];
  /** запасные, что не вышли: фото — если есть id */
  bench: Array<{ key: string; id?: number; name: string }>;
  unavailable: Array<{ key: string; id?: number; name: string; reason: string }>;
  /** id FotMob у тренера — фото с /img/player/{id}.png */
  coach?: { id?: number; name: string };
}

const MONTH_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const MONTH_EN = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];

/** «Late October 2026» → «до конца октября»; ISO-дата → «до 31 декабря». */
export function returnText(s: string | null | undefined): string | null {
  const v = (s ?? '').trim();
  if (!v) return null;
  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(v);
  if (iso) return `до ${Number(iso[3])} ${MONTH_GEN[Number(iso[2]) - 1]}`;
  const m = /^(early|mid|late)?\s*([a-z]+)\s+\d{4}$/i.exec(v);
  if (m) {
    const i = MONTH_EN.indexOf(m[2].toLowerCase());
    if (i >= 0) {
      const when = { early: 'до начала ', mid: 'до середины ', late: 'до конца ' }[(m[1] ?? '').toLowerCase() as 'early'] ?? 'до ';
      return `${when}${MONTH_GEN[i]}`;
    }
  }
  if (/back in training/i.test(v)) return 'вернулся к тренировкам';
  if (/doubt/i.test(v)) return 'под вопросом';
  if (/unknown/i.test(v)) return 'срок неизвестен';
  return null;
}

export function absenceReason(type: string | null | undefined): string {
  const t = (type ?? '').toLowerCase();
  if (/suspen|red card|ban/.test(t)) return 'дисквалификация';
  if (/injur|knock|ill|ligament|muscle|surgery/.test(t)) return 'травма';
  return 'не сыграет';
}

function countFor(m: ApiMatch, p: ApiLineupPlayer) {
  let g = 0;
  let a = 0;
  let yellow = 0;
  let red = 0;
  for (const e of m.events) {
    if (e.type === 'goal' && !e.shootout && !e.own_goal) {
      if (samePerson(e.player, p.id, p.name)) g++;
      if (samePerson(e.assist, p.id, p.name)) a++;
    } else if (e.type === 'card' && samePerson(e.player, p.id, p.name)) {
      if (e.card === 'yellow') yellow++;
      else red++;
    }
  }
  return { g, a, yellow, red };
}

function deedsText(c: { g: number; a: number; yellow: number; red: number }): string[] {
  const out: string[] = [];
  if (c.g) out.push(c.g === 1 ? 'гол' : `${c.g} ${plural(c.g, ['гол', 'гола', 'голов'])}`);
  if (c.a) out.push(c.a === 1 ? 'голевая передача' : `${c.a} ${plural(c.a, ['голевая передача', 'голевые передачи', 'голевых передач'])}`);
  if (c.red) out.push('удалён');
  else if (c.yellow) out.push('жёлтая');
  return out;
}

export function lineupView(m: ApiMatch, side: Side): LineupView | null {
  const lu: ApiLineupSide | undefined = m.lineups?.[side];
  if (!lu || !lu.starters?.length) return null;
  const ratings = has(m, 'ratings');
  const positions = has(m, 'lineup_positions') && lu.starters.every((p) => p.x != null && p.y != null);
  const ratingOf = (p: ApiLineupPlayer) => (ratings && p.rating != null ? p.rating : undefined);

  const rated = lu.starters.map((p) => p.rating).filter((r): r is number => r != null);
  const avg = lu.rating ?? (ratings && rated.length ? Math.round((rated.reduce((s, r) => s + r, 0) / rated.length) * 10) / 10 : null);

  const subEvents = m.events.filter((e): e is Extract<ApiEvent, { type: 'sub' }> => e.type === 'sub' && e.side === side);
  const subs: SubView[] = lu.subs
    .filter((p) => p.sub_in != null)
    .sort((a, b) => (a.sub_in ?? 0) - (b.sub_in ?? 0))
    .map((p, i) => {
      const ev = subEvents.find((e) => samePerson(e.player_in, p.id, p.name));
      const parts = [`вышел на ${p.sub_in}′${ev?.player_out?.name ? ` вместо ${shortName(ev.player_out.name)}` : ''}`];
      const c = countFor(m, p);
      parts.push(...deedsText(c));
      return {
        key: `${p.id ?? p.name}-${i}`,
        id: photoId(p),
        number: p.number ?? undefined,
        name: p.name,
        detail: parts.join(' · '),
        rating: ratingOf(p),
        scored: c.g > 0,
      };
    });

  return {
    side,
    team: teamRef(m, side),
    confirmed: m.lineups?.confirmed !== false,
    formation: lu.formation ?? undefined,
    avgRating: avg != null && ratings ? avg : undefined,
    pitch: positions
      ? lu.starters.map((p) => ({
          id: photoId(p),
          name: shortName(p.name),
          number: p.number ?? undefined,
          rating: ratingOf(p),
          x: p.x as number,
          y: p.y as number,
        }))
      : null,
    starters: lu.starters.map((p, i) => ({
      key: `${p.id ?? p.name}-${i}`,
      id: photoId(p),
      number: p.number ?? undefined,
      name: p.name,
      position: p.position ?? undefined,
      rating: ratingOf(p),
    })),
    subs,
    bench: lu.subs
      .filter((p) => p.sub_in == null)
      .map((p, i) => ({ key: `${p.id ?? p.name}-${i}`, id: photoId(p), name: p.name })),
    unavailable: (lu.unavailable ?? []).map((u, i) => ({
      key: `${u.id ?? u.name}-${i}`,
      id: photoId(u),
      name: u.name,
      reason: [absenceReason(u.type), returnText(u.expected_return)].filter(Boolean).join(', '),
    })),
    // тренера отдаёт только FotMob, id — FotMob: фото с /img/player/{id}.png (нет фото — сервер даст силуэт)
    coach: lu.coach?.name
      ? { id: lu.coach.id != null && Number(lu.coach.id) > 0 ? Number(lu.coach.id) : undefined, name: lu.coach.name }
      : undefined,
  };
}

/* ---------- статистика ---------- */

export type PeriodKey = 'all' | 'first_half' | 'second_half';

const STAT_LABEL: Record<string, string> = {
  possession: 'Владение',
  xg: 'Ожидаемые голы (xG)',
  shots_total: 'Удары',
  shots_on_target: 'В створ',
  big_chances: 'Голевые моменты',
  big_chances_missed: 'Упущенные голевые',
  corners: 'Угловые',
  xg_open_play: 'xG с игры',
  xg_set_play: 'xG со стандартов',
  xg_non_penalty: 'xG без пенальти',
  shots_off_target: 'Мимо ворот',
  shots_blocked: 'Заблокированные',
  shots_woodwork: 'В каркас ворот',
  shots_inside_box: 'Из штрафной',
  shots_outside_box: 'Из-за штрафной',
  xg_on_target: 'xG в створ (xGOT)',
  passes_total: 'Передачи',
  passes_accurate: 'Точные передачи',
  passes_own_half: 'На своей половине',
  passes_opp_half: 'На чужой половине',
  long_balls_accurate: 'Точные длинные',
  crosses_accurate: 'Точные навесы',
  throws: 'Вбрасывания',
  touches_opp_box: 'Касания в штрафной',
  tackles: 'Отборы',
  interceptions: 'Перехваты',
  blocks: 'Блоки',
  clearances: 'Выносы',
  saves: 'Сейвы',
  duels_won: 'Выиграно единоборств',
  ground_duels_won: 'На земле',
  aerials_won: 'Верховые',
  dribbles: 'Удачные обводки',
  fouls: 'Фолы',
  offsides: 'Офсайды',
  yellow_cards: 'Жёлтые карточки',
  red_cards: 'Красные карточки',
};

/** Все показатели, которые умеет экран (37 у FotMob): подпись по-русски есть у каждого. */
export const STAT_KEYS = Object.keys(STAT_LABEL);
export const statLabel = (key: string): string => STAT_LABEL[key] ?? key;

/** порядок «Главного» — как в a-match-stats.html */
const MAIN = ['possession', 'xg', 'shots_total', 'shots_on_target', 'big_chances', 'touches_opp_box', 'passes_accurate', 'corners', 'yellow_cards'];
/** детали xG есть только у FotMob: тогда — своя группа «xG», иначе xGOT и упущенные — в «Ударах» */
const XG_DETAIL = ['xg_open_play', 'xg_set_play', 'xg_non_penalty'];
const XG_GROUP = ['xg', 'xg_open_play', 'xg_set_play', 'xg_non_penalty', 'xg_on_target', 'big_chances_missed'];
const SHOTS = ['shots_off_target', 'shots_blocked', 'shots_woodwork', 'shots_inside_box', 'shots_outside_box'];

function statGroups(by: Map<string, ApiStat>): Array<[string, string[]]> {
  const xg = XG_DETAIL.some((k) => by.has(k));
  return [
    ['Главное', MAIN],
    ...(xg ? ([['xG', XG_GROUP]] as Array<[string, string[]]>) : []),
    ['Удары', xg ? SHOTS : [...SHOTS, 'xg_on_target', 'big_chances_missed']],
    ['Передачи', ['passes_total', 'passes_accurate', 'passes_own_half', 'passes_opp_half', 'long_balls_accurate', 'crosses_accurate', 'throws']],
    ['Единоборства', ['duels_won', 'ground_duels_won', 'aerials_won', 'dribbles']],
    ['Оборона', ['tackles', 'interceptions', 'blocks', 'clearances', 'saves']],
    ['Дисциплина', ['fouls', 'offsides', 'red_cards']],
  ];
}
const NO_COMPARE = new Set(['yellow_cards', 'red_cards', 'fouls', 'offsides', 'throws']);
/** «меньше — лучше»: упущенные моменты */
const LOWER_BETTER = new Set(['big_chances_missed']);
/** полоса под строкой: владение и всё, где есть точность / единоборства */
const BAR = new Set(['possession', 'duels_won']);

export interface StatRowView {
  key: string;
  label: string;
  home: string;
  away: string;
  homeValue?: number;
  awayValue?: number;
  better: 'higher' | 'lower' | 'none';
  bar?: boolean;
}

export function statPeriods(m: ApiMatch): PeriodKey[] {
  if (!m.stats?.all?.length || !has(m, 'stats')) return [];
  const out: PeriodKey[] = ['all'];
  if (has(m, 'stats_periods')) {
    if (m.stats.first_half?.length) out.push('first_half');
    if (m.stats.second_half?.length) out.push('second_half');
  }
  return out;
}

const fmtNum = (v: number, key: string) => (key.startsWith('xg') ? v.toFixed(2) : String(v));

export function statsView(m: ApiMatch, period: PeriodKey): Array<{ title: string; rows: StatRowView[] }> {
  const list: ApiStat[] = (m.stats?.[period] as ApiStat[] | undefined) ?? [];
  const by = new Map(list.map((s) => [s.key, s]));
  const row = (key: string, main: boolean): StatRowView | null => {
    const s = by.get(key);
    if (!s || (s.home == null && s.away == null)) return null;
    const h = s.home ?? 0;
    const a = s.away ?? 0;
    let home = fmtNum(h, key);
    let away = fmtNum(a, key);
    const withPct = s.home_pct != null || s.away_pct != null;
    if (key === 'possession') {
      home = `${h}%`;
      away = `${a}%`;
    } else if (withPct) {
      // точность — как у источника: «17 (52%)»
      if (s.home_pct != null) home = `${h} (${s.home_pct}%)`;
      if (s.away_pct != null) away = `${a} (${s.away_pct}%)`;
    } else if (key === 'passes_accurate') {
      const tot = by.get('passes_total');
      if (tot?.home) home = `${h} (${Math.round((h / tot.home) * 100)}%)`;
      if (tot?.away) away = `${a} (${Math.round((a / tot.away) * 100)}%)`;
    }
    return {
      key,
      label: statLabel(key),
      home,
      away,
      homeValue: h,
      awayValue: a,
      better: NO_COMPARE.has(key) ? 'none' : LOWER_BETTER.has(key) ? 'lower' : 'higher',
      // в «Главном» полоса только у владения — как раньше; в группах — у всех строк с точностью
      bar: BAR.has(key) || (withPct && !main) || undefined,
    };
  };
  return statGroups(by)
    .map(([title, keys], i) => ({ title, rows: keys.map((k) => row(k, i === 0)).filter((r): r is StatRowView => r != null) }))
    .filter((g) => g.rows.length > 0);
}

/* ---------- удары и давление ---------- */

export interface ShotsView {
  shots: Shot[];
  summary: string;
  team: string;
  opponent: string;
}

const OUTCOME: Record<string, Shot['outcome']> = { goal: 'goal', saved: 'saved', miss: 'missed', post: 'post', blocked: 'blocked' };

/** Удары Реала: API даёт 0..100, ShotMap ждёт метры FotMob (105 × 68). */
export function shotsView(m: ApiMatch, side: Side = realSide(m)): ShotsView | null {
  if (!has(m, 'shotmap')) return null;
  const withXg = has(m, 'shot_xg');
  const own = m.shots.filter((s) => s.side === side && !s.own_goal);
  if (!own.length) return null;
  const shots = own.map((s) => ({
    x: Math.round(s.x * 1.05 * 10) / 10,
    y: Math.round(s.y * 0.68 * 10) / 10,
    xg: withXg && s.xg != null ? s.xg : 0.04,
    outcome: OUTCOME[s.outcome] ?? 'missed',
  }));
  const n = shots.length;
  const words = `${n} ${plural(n, ['удар', 'удара', 'ударов'])}`;
  // xG команды — из статистики матча (как у источника); сумма по ударам расходится на округлениях
  const statXg = m.stats?.all?.find((x) => x.key === 'xg')?.[side];
  const xg = statXg ?? own.reduce((t, s) => t + (s.xg ?? 0), 0);
  return {
    shots,
    summary: withXg ? `${words} · xG ${xg.toFixed(2)}` : words,
    team: m[side].name ?? '',
    opponent: m[other(side)].name ?? '',
  };
}

export function momentumView(m: ApiMatch) {
  if (!has(m, 'momentum') || m.momentum.length < 2) return null;
  const rs = realSide(m);
  const last = Math.round(m.momentum[m.momentum.length - 1].minute);
  const end = last > 100 ? 120 : 90; // доп. время — до 120′
  return {
    data: m.momentum.map((p) => ({ minute: p.minute, value: p.value })),
    homeColor: rs === 'home' ? 'var(--gold)' : 'var(--ui-opp)',
    awayColor: rs === 'away' ? 'var(--gold)' : 'var(--ui-opp)',
    ticks: m.status.finished || last >= 90 ? ['0′', `${Math.round(end / 2)}′`, `${end}′`] : ['0′', `${last}′`],
    caption: `вверх — ${shortTeam(m.home.name)}, вниз — ${shortTeam(m.away.name)}`,
  };
}

/** «Real Madrid» → «Real», остальные как есть: подпись под графиком короткая. */
export const shortTeam = (n: string | null | undefined) => (/^real madrid$/i.test(n ?? '') ? 'Real' : (n ?? ''));
