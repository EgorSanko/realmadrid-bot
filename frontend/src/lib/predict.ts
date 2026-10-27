/**
 * Прогнозы: ответы /api/predict/* (backend/app/predictions/service.py) → данные экрана.
 * Правила очков — копия backend/app/predictions/rules.py (единственный источник правды — сервер;
 * здесь только для подсказки «пока +N» во время матча). Чистые функции — проверяются node --test.
 */
import { isEn, pluralEn, t } from './i18n';

export interface PTeam {
  id: string | number | null;
  name: string;
}

export interface SquadPlayer {
  id: string;
  name: string;
  position?: 'GK' | 'DF' | 'MF' | 'FW' | null;
  number?: number | null;
  starter?: boolean;
}

export interface PredictionView {
  home: number;
  away: number;
  first_scorer_id: string | null;
  updated_at?: string;
  revisions?: number;
}

export interface PointsView {
  total: number;
  score: number;
  scorer: number;
  kind: 'exact' | 'diff' | 'outcome' | 'miss';
}

export interface PMatch {
  id: string;
  kickoff_utc: string;
  home: PTeam;
  away: PTeam;
  rm_side: 'home' | 'away';
  status: 'scheduled' | 'live' | 'finished' | 'cancelled' | 'postponed';
  score: { home: number; away: number } | null;
  accepting: boolean;
  closes_at: string;
  first_rm_scorer_player_id?: string | null;
  tournament?: { id: number | null; name: string | null } | null;
}

export interface NextMatch extends PMatch {
  rm_squad: SquadPlayer[];
  my_prediction: PredictionView | null;
  my_points: PointsView | null;
}

export interface RecentMatch extends PMatch {
  my_prediction: PredictionView | null;
  my_points: PointsView | null;
  settled: boolean;
}

export interface MatchesResponse {
  server_time: string;
  next: NextMatch | null;
  recent: RecentMatch[];
}

export interface LbRow {
  /** порядковый номер строки — уникален */
  rank: number;
  /** место с учётом равенства очков и точных (1, 1, 3…); старый сервер — нет поля */
  place?: number;
  name: string;
  username: string | null;
  avatar: string | null;
  points: number;
  exact: number;
  played: number;
  is_me: boolean;
}

export interface LbMe {
  rank: number | null;
  place?: number | null;
  points: number;
  exact: number;
  played: number;
}

export interface Leaderboard {
  key: string;
  period: 'season' | 'month';
  label: string;
  league: { id: number; name: string } | null;
  total: number;
  top: LbRow[];
  me: LbMe | null;
}

/* ---------- правила (как rules.py) ---------- */

export const RULES = { exact: 5, diff: 3, outcome: 2, scorer: 2 } as const;

export const RULE_LINES: Array<{ label: string; points: number; gold?: boolean }> = [
  { label: t('Точный счёт'), points: RULES.exact, gold: true },
  { label: t('Угадана разница мячей'), points: RULES.diff },
  { label: t('Угадан исход'), points: RULES.outcome },
  { label: t('Автор первого гола Реала'), points: RULES.scorer },
];

const sign = (x: number) => (x > 0 ? 1 : x < 0 ? -1 : 0);

export function scorePoints(ph: number, pa: number, h: number, a: number): number {
  if (ph === h && pa === a) return RULES.exact;
  if (ph - pa === h - a) return RULES.diff;
  if (sign(ph - pa) === sign(h - a)) return RULES.outcome;
  return 0;
}

export function computePoints(
  pred: { home: number; away: number; first_scorer_id?: string | null },
  score: { home: number; away: number },
  actualScorer: string | null | undefined,
  rmHome: boolean,
): PointsView {
  const s = scorePoints(pred.home, pred.away, score.home, score.away);
  const rmGoals = rmHome ? score.home : score.away;
  const b =
    rmGoals > 0 && pred.first_scorer_id != null && actualScorer != null && String(pred.first_scorer_id) === String(actualScorer)
      ? RULES.scorer
      : 0;
  const kind = s === RULES.exact ? 'exact' : s === RULES.diff ? 'diff' : s === RULES.outcome ? 'outcome' : 'miss';
  return { total: s + b, score: s, scorer: b, kind };
}

/** «Пока +N» во время матча — по текущему счёту теми же правилами. null — не считаем. */
export function livePoints(m: PMatch & { my_prediction: PredictionView | null }): PointsView | null {
  if (m.status !== 'live' || !m.my_prediction || !m.score) return null;
  return computePoints(m.my_prediction, m.score, m.first_rm_scorer_player_id, m.rm_side === 'home');
}

/** Голы Реала по прогнозу: 0 — автора первого гола выбрать нельзя (сервер ответит 422). */
export function rmGoals(home: number, away: number, rmSide: 'home' | 'away'): number {
  return rmSide === 'home' ? home : away;
}

/* ---------- ошибки API ---------- */

export type PredictErrorKind = 'closed' | 'auth' | 'rate' | 'invalid' | 'network' | 'unavailable' | 'other';

/** Статус и код ответа → понятное сообщение (по-английски — свой текст вместо русского текста сервера). */
export function predictError(status: number, code: string | null, serverMessage?: string): { kind: PredictErrorKind; message: string } {
  const srv = isEn() ? undefined : serverMessage;
  if (status === 0) return { kind: 'network', message: t('Нет соединения — проверьте интернет и попробуйте ещё раз') };
  if (status === 409 && code === 'match_cancelled') return { kind: 'closed', message: t('Матч отменён — прогнозы не принимаются') };
  if (status === 409) return { kind: 'closed', message: t('Приём закрыт: матч уже начался') };
  if (status === 401) return { kind: 'auth', message: t('Нужно войти через Telegram — тогда прогноз сохранится') };
  if (status === 429) return { kind: 'rate', message: t('Слишком часто — подождите минуту и сохраните ещё раз') };
  if (status === 422) {
    if (code === 'scorer_without_goal') return { kind: 'invalid', message: t('По вашему прогнозу Реал не забивает — автора первого гола выбрать нельзя') };
    if (code === 'scorer_not_in_squad') return { kind: 'invalid', message: t('Этого игрока нет в составе Реала на матч — выберите другого') };
    return { kind: 'invalid', message: srv || t('Проверьте счёт: голы — от 0 до 20') };
  }
  if (status === 404) return { kind: 'other', message: srv || t('Матч не найден') };
  if (status === 503) return { kind: 'unavailable', message: t('Прогнозы временно недоступны — попробуйте чуть позже') };
  return { kind: 'other', message: srv || t('Не удалось сохранить (ошибка {status})', { status }) };
}

const LEAGUE_ERRORS: Record<string, string> = {
  league_not_found: 'Лига не найдена',
  not_member: 'Вы не состоите в этой лиге',
  not_owner: 'Это может только создатель лиги',
  owner_cannot_leave: 'Создатель не может выйти из лиги — её можно удалить',
  too_many_leagues: 'Достигнут предел числа лиг',
  invalid_code: 'Неверный код приглашения',
  validation: 'Проверьте название лиги: до 40 символов, без особых знаков',
};

/**
 * Ошибка действия с лигой по коду сервера — свой текст вместо русского текста сервера (для английского).
 * Неизвестный код — null (тогда общее сообщение predictError).
 */
export function leagueErrorText(code: string | null | undefined): string | null {
  const ru = code ? LEAGUE_ERRORS[code] : undefined;
  return ru ? t(ru) : null;
}

/* ---------- состав для выбора бомбардира ---------- */

const SUFFIX = /^(j[uú]nior|jr\.?|filho|neto)$/i;

/** Короткое имя для плитки: фамилия латиницей, как у источника («Kylian Mbappé» → «Mbappé»). */
export function shortName(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length < 2) return name.trim();
  const last = parts[parts.length - 1];
  return SUFFIX.test(last) ? parts.slice(-2).join(' ') : last;
}

export function scorerName(squad: SquadPlayer[], id: string | null | undefined): string | null {
  if (id == null) return null;
  return squad.find((p) => p.id === String(id))?.name ?? null;
}

/* ---------- итоги, рейтинг, мои прогнозы ---------- */

export interface Summary {
  points: number;
  rank: number | null;
  place?: number | null;
  exact: number;
  played: number;
}

export function summaryTiles(s: Summary | null): Array<{ label: string; value: string; gold?: boolean }> {
  return [
    { label: t('Очки'), value: String(s?.points ?? 0), gold: true },
    { label: t('Место'), value: s?.rank != null ? String(s.place ?? s.rank) : '—' },
    { label: t('Точных'), value: String(s?.exact ?? 0) },
  ];
}

function ru(n: number, forms: [string, string, string]): string {
  const en = pluralEn(n, forms);
  if (en != null) return en;
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b > 1 && b < 5) return forms[1];
  return b === 1 ? forms[0] : forms[2];
}

/** Подпись под именем в рейтинге: «3 прогноза · 1 точный». played — рассчитанные прогнозы. */
export function rowSub(r: { played: number; exact: number }): string {
  if (!r.played) return t('пока без прогнозов');
  return `${r.played} ${ru(r.played, ['прогноз', 'прогноза', 'прогнозов'])} · ${r.exact} ${ru(r.exact, ['точный', 'точных', 'точных'])}`;
}

export interface BoardRow extends LbRow {
  /** место для показа: равным очкам и точным — одно (1, 1, 3…) */
  place: number;
  sub: string;
}

/**
 * Места с учётом равенства. Сервер отдаёт place; без него (старый ответ) считаем по порядку строк:
 * те же очки и точные, что у строки выше, — её место, иначе — свой номер.
 */
export function withPlaces(rows: LbRow[]): BoardRow[] {
  const out: BoardRow[] = [];
  rows.forEach((r, i) => {
    const prev = out[i - 1];
    const place = r.place ?? (prev && prev.points === r.points && prev.exact === r.exact ? prev.place : r.rank);
    out.push({ ...r, place, sub: rowSub(r) });
  });
  return out;
}

export interface BoardView {
  rows: BoardRow[];
  /** моя строка отдельно внизу — если я есть в рейтинге, но не попал в показанный топ */
  meRow: BoardRow | null;
  empty: boolean;
  /** хоть у кого-то есть рассчитанный прогноз; нет — лига ещё не стартовала */
  started: boolean;
  /** моё место (с равенством) — для «ты N-й из M»; null — меня нет в рейтинге */
  myPlace: number | null;
}

export function boardView(lb: Leaderboard, myName: string, myAvatar: string | null): BoardView {
  const rows = withPlaces(lb.top);
  const mine = rows.find((r) => r.is_me);
  let meRow: BoardRow | null = null;
  if (!mine && lb.me && lb.me.rank != null) {
    const r: LbRow = {
      rank: lb.me.rank,
      name: myName,
      username: null,
      avatar: myAvatar,
      points: lb.me.points,
      exact: lb.me.exact,
      played: lb.me.played,
      is_me: true,
    };
    meRow = { ...r, place: lb.me.place ?? lb.me.rank, sub: rowSub(r) };
  }
  const started = rows.some((r) => r.played > 0) || (lb.me?.played ?? 0) > 0;
  const myPlace = mine?.place ?? meRow?.place ?? null;
  return { rows, meRow, empty: rows.length === 0, started, myPlace };
}

/* ---------- шапка лиги: GET /api/predict/leagues/{id} ---------- */

export interface LeaguePerson {
  name: string;
  avatar: string | null;
  is_me: boolean;
  is_owner: boolean;
  /** сделал ли прогноз на ближайший матч — только факт, без счёта */
  predicted_next: boolean;
}

export interface LeagueNextMatch {
  id: string;
  kickoff_utc: string;
  home: PTeam;
  away: PTeam;
  rm_side: 'home' | 'away';
}

export interface LeagueHeader {
  id: number;
  name: string;
  code: string;
  invite_link: string | null;
  is_owner: boolean;
  members: number;
  faces?: Array<{ name: string; avatar: string | null }>;
  people: LeaguePerson[];
  /** ближайший матч, на который ещё принимают прогнозы; нет — null */
  next_match: LeagueNextMatch | null;
  predicted_next_count: number;
}

/** «Реал — Севилья» / «Севилья — Реал»: Реал коротко, порядок — как в матче. */
export function matchTitle(m: { home: PTeam; away: PTeam; rm_side: 'home' | 'away' }): string {
  return m.rm_side === 'home' ? `${t('Реал')} — ${m.away.name}` : `${m.home.name} — ${t('Реал')}`;
}

/** «ты 2-й из 5»; в нестартовавшей лиге или без моего места — null (все пока первые). */
export function placeLine(v: Pick<BoardView, 'started' | 'myPlace'>, total: number): string | null {
  if (!v.started || v.myPlace == null) return null;
  return t('ты {place}-й из {total}', { place: v.myPlace, total });
}

/** «Прогнозы сделали 1 из 2» на ближайший матч; матча нет — null. */
export function nextLine(h: LeagueHeader): string | null {
  if (!h.next_match) return null;
  const k = h.predicted_next_count;
  const m = h.members;
  if (m > 1 && k === m) return t('Прогнозы сделали все');
  if (k === 0) return m > 1 ? t('Прогнозов пока нет ни у кого') : t('Прогноза пока нет');
  return t('Прогнозы сделали {k} из {m}', { k, m });
}

/** Участники нестартовавшей лиги: я первым, дальше — как пришли с сервера (создатель, по вступлению). */
export function waitingPeople(h: LeagueHeader): Array<LeaguePerson & { state: 'done' | 'wait' | 'none' }> {
  const ps = [...h.people].sort((a, b) => Number(b.is_me) - Number(a.is_me));
  return ps.map((p) => ({ ...p, state: !h.next_match ? 'none' : p.predicted_next ? 'done' : 'wait' }));
}

export interface HistoryItem {
  id: string;
  kickoff: string;
  home: { id: number | null; name: string };
  away: { id: number | null; name: string };
  pick: string;
  result: string | null;
  scorerPick: string | null;
  /** «счёт +3 · бомбардир +2» / «ждём итог» / … */
  note: string;
  points: number | null;
  tone: 'exact' | 'hit' | 'miss' | 'muted';
}

export interface MeHistoryEntry {
  match: PMatch & { first_rm_scorer_player_id?: string | null };
  prediction: PredictionView | null;
  points: PointsView | null;
  state: 'settled' | 'open' | 'waiting' | 'void';
}

const tid = (t: PTeam): number | null => {
  const n = Number(t.id);
  return Number.isFinite(n) && n > 0 ? n : null;
};

const KIND_LABEL: Record<PointsView['kind'], string> = {
  exact: 'точный счёт',
  diff: 'разница мячей',
  outcome: 'исход',
  miss: 'счёт мимо',
};

export function historyItem(h: MeHistoryEntry): HistoryItem {
  const m = h.match;
  const pick = h.prediction ? `${h.prediction.home}:${h.prediction.away}` : '—';
  const result = m.score ? `${m.score.home}:${m.score.away}` : null;
  let note: string;
  let tone: HistoryItem['tone'] = 'muted';
  let points: number | null = null;
  if (h.state === 'settled' && h.points) {
    points = h.points.total;
    tone = h.points.kind === 'exact' ? 'exact' : points > 0 ? 'hit' : 'miss';
    const kind = t(KIND_LABEL[h.points.kind]);
    const parts = [h.points.score > 0 ? `${kind} +${h.points.score}` : kind];
    if (h.prediction?.first_scorer_id)
      parts.push(h.points.scorer > 0 ? t('бомбардир +{n}', { n: h.points.scorer }) : t('бомбардир мимо'));
    note = parts.join(' · ');
  } else if (h.state === 'open') note = t('можно изменить до начала');
  else if (h.state === 'void') note = t('матч не состоялся');
  else note = m.status === 'live' ? t('матч идёт') : t('считаем очки');
  return {
    id: m.id,
    kickoff: m.kickoff_utc,
    home: { id: tid(m.home), name: m.home.name },
    away: { id: tid(m.away), name: m.away.name },
    pick,
    result,
    scorerPick: h.prediction?.first_scorer_id ?? null,
    note,
    points,
    tone,
  };
}

export const teamIdOf = tid;

/** Текст «Твой прогноз 2:1 · …» для главной. */
export function homeLine(m: NextMatch): { pick: string | null; tail: string | null } {
  const p = m.my_prediction;
  if (!p) return { pick: null, tail: null };
  const pick = `${p.home}:${p.away}`;
  if (m.accepting) return { pick, tail: t('изменить') };
  const live = livePoints(m);
  if (live) return { pick, tail: t('пока +{n}', { n: live.total }) };
  if (m.my_points) return { pick, tail: `+${m.my_points.total}` };
  return { pick, tail: t('приём закрыт') };
}

/* ---------- праздник точного счёта ---------- */

export const EXACT_SEEN_KEY = 'rmExactSeen';
const EXACT_FRESH_MS = 10 * 86400_000;

/**
 * Точные прогнозы, которые ещё не праздновали: рассчитанные «точный счёт» за последние 10 дней
 * (старые не празднуем — это не новость), без тех, что уже показаны (localStorage rmExactSeen).
 */
export function exactToCelebrate(items: HistoryItem[], seen: string[], now = Date.now()): string[] {
  return items
    .filter((h) => h.tone === 'exact' && !seen.includes(h.id))
    .filter((h) => {
      const k = Date.parse(h.kickoff);
      return Number.isFinite(k) && now - k >= 0 && now - k < EXACT_FRESH_MS;
    })
    .map((h) => h.id);
}
