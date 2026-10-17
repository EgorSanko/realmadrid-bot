/**
 * Профиль: ответы /api/predict/me и /api/predict/leagues (backend/app/predictions/service.py)
 * → данные для блоков экрана. Чистые функции — проверяются node --test.
 */

export interface PredTeam {
  id: string | number | null;
  name: string;
}

export interface PredHistoryItem {
  match: {
    id: string;
    kickoff_utc: string;
    home: PredTeam;
    away: PredTeam;
    rm_side: 'home' | 'away';
    status: string;
    score: { home: number; away: number } | null;
  };
  prediction: { home: number; away: number } | null;
  points: { total: number; score: number; scorer: number; kind: string } | null;
  /** settled — очки начислены; open — можно менять; waiting — ждём результат; void — матч не состоялся */
  state: 'settled' | 'open' | 'waiting' | 'void';
}

export interface PeriodStat {
  key: string;
  label: string;
  rank: number | null;
  points: number;
  exact: number;
  played: number;
}

export interface PredictMe {
  user: { id: number; name: string; username: string | null };
  season: PeriodStat;
  month: PeriodStat;
  points: number;
  rank: number | null;
  exact: number;
  predictions: number;
  history: PredHistoryItem[];
}

export interface League {
  id: number;
  name: string;
  code: string;
  invite_link: string | null;
  is_owner: boolean;
  members: number;
}

export interface Tile {
  label: string;
  value: string;
  sub?: string;
}

const MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];

/** «2026-10» → «октябрь 2026»; что не разобрали — как есть. */
export function monthLabel(label: string | undefined): string | undefined {
  const m = label ? /^(\d{4})-(\d{2})$/.exec(label) : null;
  if (!m) return label;
  const i = Number(m[2]) - 1;
  return MONTHS[i] ? `${MONTHS[i]} ${m[1]}` : label;
}

export function pointsTiles(me: PredictMe | null): Tile[] {
  const s = me?.season;
  const m = me?.month;
  return [
    { label: 'Очки за сезон', value: String(s?.points ?? 0), sub: s?.label },
    { label: 'За месяц', value: String(m?.points ?? 0), sub: monthLabel(m?.label) },
    { label: 'Место', value: s?.rank != null ? `${s.rank}` : '—', sub: s?.rank != null ? 'в сезоне' : 'нет прогнозов' },
    { label: 'Точных счетов', value: String(s?.exact ?? 0), sub: s ? `из ${s.played}` : undefined },
  ];
}

const teamId = (t: PredTeam): number | null => {
  const n = Number(t.id);
  return Number.isFinite(n) && n > 0 ? n : null;
};

export interface HistoryRow {
  id: string;
  href: string;
  kickoff: string;
  home: { id: number | null; name: string };
  away: { id: number | null; name: string };
  pick: string;
  result: string | null;
  note: string;
  points: number | null;
  tone: 'exact' | 'hit' | 'miss' | 'muted';
}

export function historyRow(h: PredHistoryItem): HistoryRow {
  const m = h.match;
  const pick = h.prediction ? `${h.prediction.home}:${h.prediction.away}` : '—';
  const result = m.score ? `${m.score.home}:${m.score.away}` : null;
  let note: string;
  let tone: HistoryRow['tone'] = 'muted';
  let points: number | null = null;
  switch (h.state) {
    case 'settled':
      points = h.points?.total ?? 0;
      tone = h.points?.kind === 'exact' ? 'exact' : points > 0 ? 'hit' : 'miss';
      note = result ? `Итог ${result}` : 'Очки начислены';
      break;
    case 'open':
      note = 'Можно изменить до начала';
      break;
    case 'void':
      note = 'Матч не состоялся';
      break;
    default:
      note = result ? `Итог ${result} · считаем очки` : 'Ждём результат';
  }
  return {
    id: m.id,
    href: `/match/${encodeURIComponent(m.id)}`,
    kickoff: m.kickoff_utc,
    home: { id: teamId(m.home), name: m.home.name },
    away: { id: teamId(m.away), name: m.away.name },
    pick,
    result,
    note,
    points,
    tone,
  };
}

/** Ошибка, которую профиль показывает пустым блоком, а не ошибкой (данные ещё не подключены). */
export function isSoftUnavailable(status: number): boolean {
  return status === 503 || status === 404;
}
