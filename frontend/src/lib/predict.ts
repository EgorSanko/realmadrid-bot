/**
 * Прогнозы: ответы /api/predict/* (backend/app/predictions/service.py) → данные экрана.
 * Правила очков — копия backend/app/predictions/rules.py (единственный источник правды — сервер;
 * здесь только для подсказки «пока +N» во время матча). Чистые функции — проверяются node --test.
 */

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
  rank: number;
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
  { label: 'Точный счёт', points: RULES.exact, gold: true },
  { label: 'Угадана разница мячей', points: RULES.diff },
  { label: 'Угадан исход', points: RULES.outcome },
  { label: 'Автор первого гола Реала', points: RULES.scorer },
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

/** Статус и код ответа → понятное сообщение по-русски. */
export function predictError(status: number, code: string | null, serverMessage?: string): { kind: PredictErrorKind; message: string } {
  if (status === 0) return { kind: 'network', message: 'Нет соединения — проверьте интернет и попробуйте ещё раз' };
  if (status === 409 && code === 'match_cancelled') return { kind: 'closed', message: 'Матч отменён — прогнозы не принимаются' };
  if (status === 409) return { kind: 'closed', message: 'Приём закрыт: матч уже начался' };
  if (status === 401) return { kind: 'auth', message: 'Нужно войти через Telegram — тогда прогноз сохранится' };
  if (status === 429) return { kind: 'rate', message: 'Слишком часто — подождите минуту и сохраните ещё раз' };
  if (status === 422) {
    if (code === 'scorer_without_goal') return { kind: 'invalid', message: 'По вашему прогнозу Реал не забивает — автора первого гола выбрать нельзя' };
    if (code === 'scorer_not_in_squad') return { kind: 'invalid', message: 'Этого игрока нет в составе Реала на матч — выберите другого' };
    return { kind: 'invalid', message: serverMessage || 'Проверьте счёт: голы — от 0 до 20' };
  }
  if (status === 404) return { kind: 'other', message: serverMessage || 'Матч не найден' };
  if (status === 503) return { kind: 'unavailable', message: 'Прогнозы временно недоступны — попробуйте чуть позже' };
  return { kind: 'other', message: serverMessage || `Не удалось сохранить (ошибка ${status})` };
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
  exact: number;
  played: number;
}

export function summaryTiles(s: Summary | null): Array<{ label: string; value: string; gold?: boolean }> {
  return [
    { label: 'Очки', value: String(s?.points ?? 0), gold: true },
    { label: 'Место', value: s?.rank != null ? String(s.rank) : '—' },
    { label: 'Точных', value: String(s?.exact ?? 0) },
  ];
}

export interface BoardView {
  rows: LbRow[];
  /** моя строка отдельно внизу — если я есть в рейтинге, но не попал в показанный топ */
  meRow: LbRow | null;
  empty: boolean;
}

export function boardView(lb: Leaderboard, myName: string, myAvatar: string | null): BoardView {
  const rows = lb.top;
  const inTop = rows.some((r) => r.is_me);
  let meRow: LbRow | null = null;
  if (!inTop && lb.me && lb.me.rank != null) {
    meRow = {
      rank: lb.me.rank,
      name: myName,
      username: null,
      avatar: myAvatar,
      points: lb.me.points,
      exact: lb.me.exact,
      played: lb.me.played,
      is_me: true,
    };
  }
  return { rows, meRow, empty: rows.length === 0 };
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
    const parts = [h.points.score > 0 ? `${KIND_LABEL[h.points.kind]} +${h.points.score}` : KIND_LABEL[h.points.kind]];
    if (h.prediction?.first_scorer_id) parts.push(h.points.scorer > 0 ? `бомбардир +${h.points.scorer}` : 'бомбардир мимо');
    note = parts.join(' · ');
  } else if (h.state === 'open') note = 'можно изменить до начала';
  else if (h.state === 'void') note = 'матч не состоялся';
  else note = m.status === 'live' ? 'матч идёт' : 'считаем очки';
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
  if (m.accepting) return { pick, tail: 'изменить' };
  const live = livePoints(m);
  if (live) return { pick, tail: `пока +${live.total}` };
  if (m.my_points) return { pick, tail: `+${m.my_points.total}` };
  return { pick, tail: 'приём закрыт' };
}
