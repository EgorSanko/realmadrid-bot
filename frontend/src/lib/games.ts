/**
 * Мини-игры (/games): типы ответов /api/games/* (backend/app/games/service.py) и чистые функции экрана.
 * Без импортов SDK и React — проверяются node --test. Правила очков считает сервер; здесь — только показ.
 */

export type GameId = 'quiz' | 'penalty';
export type QuizLevel = 'easy' | 'medium' | 'hard' | 'expert';
export type PenaltyLevel = 'easy' | 'medium' | 'hard' | 'legend';

export interface QuizStart {
  session: string;
  level: QuizLevel;
  total: number;
  timer_s: number;
  saved: boolean;
}

export interface QuizMedia {
  type: 'player' | 'team' | 'league';
  id: number;
}

export interface QuizQuestion {
  index: number;
  total: number;
  q: string;
  a: string[];
  media: QuizMedia | null;
  timer_s: number;
  left_s: number;
  score: number;
  streak: number;
  /** множитель, который получит следующий верный ответ */
  multiplier: number;
}

export interface GameResult {
  game: GameId;
  level: string;
  score: number;
  saved: boolean;
  /** лучший результат на сервере (после этой партии); null — без входа */
  best: number | null;
  record: boolean | null;
  // викторина
  correct?: number;
  total?: number;
  best_streak?: number;
  timeouts?: number;
  // пенальти
  goals?: number;
  rival?: number;
  shots?: number;
  won?: boolean;
  sudden?: boolean;
}

export interface QuizAnswer {
  correct: boolean;
  timeout: boolean;
  correct_choice: number;
  points: number;
  score: number;
  streak: number;
  multiplier: number;
  elapsed_s: number;
  index: number;
  total: number;
  done: boolean;
  result?: GameResult;
}

export interface PenaltyStart {
  session: string;
  level: PenaltyLevel;
  shots: number;
  zones: number;
  saved: boolean;
}

export interface PenaltyShot {
  round: number;
  phase: 'regular' | 'sudden';
  zone: number;
  keeper: number;
  goal: boolean;
  rival_goal: boolean;
  goals: number;
  rival: number;
  done: boolean;
  sudden_next: boolean;
  result?: GameResult;
}

export interface WeekRow {
  rank: number;
  name: string;
  avatar: string | null;
  score: number;
  level: string;
  played: number;
  is_me: boolean;
}

export interface WeekBoard {
  game: GameId;
  week: { start: string; label: string };
  total: number;
  top: WeekRow[];
  me: { rank: number | null; score: number; played: number } | null;
}

export interface GamesMe {
  best: Record<GameId, Record<string, { best: number; played: number }>>;
  week: Record<GameId, { best: number; played: number } | null>;
}

/* ---------- уровни ---------- */

export interface LevelCard<L extends string> {
  id: L;
  title: string;
  /** 1–4 золотых деления */
  pips: number;
  text: string;
}

export const QUIZ_LEVELS: LevelCard<QuizLevel>[] = [
  { id: 'easy', title: 'Лёгкий', pips: 1, text: 'Стадион, легенды, главные трофеи' },
  { id: 'medium', title: 'Средний', pips: 2, text: 'Финалы, трансферы, тренеры' },
  { id: 'hard', title: 'Сложный', pips: 3, text: 'Рекорды, прозвища, детали матчей' },
  { id: 'expert', title: 'Эксперт', pips: 4, text: 'Для тех, кто помнит «Чамартин»' },
];

export const PENALTY_LEVELS: LevelCard<PenaltyLevel>[] = [
  { id: 'easy', title: 'Лёгкий', pips: 1, text: 'Соперник часто мажет · очки ×1' },
  { id: 'medium', title: 'Средний', pips: 2, text: 'Крепкий середняк · очки ×2' },
  { id: 'hard', title: 'Сложный', pips: 3, text: 'Бьют уверенно · очки ×3' },
  { id: 'legend', title: 'Легенда', pips: 4, text: 'Почти не промахиваются · очки ×4' },
];

export function levelTitle(game: GameId, level: string): string {
  const list: LevelCard<string>[] = game === 'quiz' ? QUIZ_LEVELS : PENALTY_LEVELS;
  return list.find((l) => l.id === level)?.title ?? level;
}

/* ---------- викторина ---------- */

/** Множитель за серию верных подряд (как multiplier() на сервере): 1–2 ×1, 3–5 ×2, 6+ ×3. */
export function multiplierFor(streak: number): number {
  return streak < 3 ? 1 : streak < 6 ? 2 : 3;
}

/** Длина дуги кольца таймера: доля оставшегося времени → stroke-dashoffset. */
export function ringOffset(left: number, total: number, circumference: number): number {
  const f = total > 0 ? Math.min(1, Math.max(0, left / total)) : 0;
  return circumference * (1 - f);
}

/** Буквы вариантов и клавиши: 1–4 или A–D (и русские Ф/И/С/В на тех же клавишах). */
export const ANSWER_LETTERS = ['A', 'B', 'C', 'D'];

export function answerFromKey(key: string, code?: string): number | null {
  if (/^[1-4]$/.test(key)) return Number(key) - 1;
  const k = key.toLowerCase();
  const i = ['a', 'b', 'c', 'd'].indexOf(k);
  if (i >= 0) return i;
  if (code) {
    const j = ['KeyA', 'KeyB', 'KeyC', 'KeyD'].indexOf(code);
    if (j >= 0) return j;
  }
  return null;
}

export function quizSummary(r: GameResult): string {
  const c = r.correct ?? 0;
  const t = r.total ?? 0;
  return `${c} из ${t} ${plural(t, ['верный', 'верных', 'верных'])}`;
}

/* ---------- пенальти ---------- */

/** Зоны ворот: 1–3 — верх (лево, центр, право), 4–6 — низ. */
export function zoneCell(zone: number): { col: 0 | 1 | 2; row: 0 | 1 } {
  const z = Math.min(6, Math.max(1, Math.round(zone))) - 1;
  return { col: (z % 3) as 0 | 1 | 2, row: (z < 3 ? 0 : 1) as 0 | 1 };
}

export function zoneOf(col: number, row: number): number {
  return Math.min(2, Math.max(0, col)) + 1 + (row > 0 ? 3 : 0);
}

/** Стрелки двигают прицел по зонам ворот. */
export function moveZone(zone: number, key: string): number {
  const { col, row } = zoneCell(zone);
  if (key === 'ArrowLeft') return zoneOf(col - 1, row);
  if (key === 'ArrowRight') return zoneOf(col + 1, row);
  if (key === 'ArrowUp') return zoneOf(col, 0);
  if (key === 'ArrowDown') return zoneOf(col, 1);
  return zone;
}

/**
 * Свайп по мячу → зона. dx, dy — смещение пальца в px (dy < 0 — вверх), w — ширина сцены.
 * Влево/вправо — по горизонтали, «длинный» свайп вверх — в верхний ярус. Короткий — null.
 */
export function zoneFromSwipe(dx: number, dy: number, w: number): number | null {
  const len = Math.hypot(dx, dy);
  if (len < 24 || dy > 10) return null;
  const side = dx / Math.max(1, Math.abs(dy) + Math.abs(dx));
  const col = side < -0.3 ? 0 : side > 0.3 ? 2 : 1;
  const row = -dy > w * 0.32 ? 0 : 1;
  return zoneOf(col, row);
}

/** Центр зоны в долях ворот (0..1 по ширине и высоте). */
export function zoneCenter(zone: number): { x: number; y: number } {
  const { col, row } = zoneCell(zone);
  return { x: (col + 0.5) / 3, y: row === 0 ? 0.28 : 0.74 };
}

export type ShotMark = 'goal' | 'miss' | 'pending';

/** Отметки серии: минимум 5 кружков, в серии до промаха — по числу ударов. */
export function shotMarks(results: boolean[], regular = 5): ShotMark[] {
  const n = Math.max(regular, results.length);
  return Array.from({ length: n }, (_, i) => (i < results.length ? (results[i] ? 'goal' : 'miss') : 'pending'));
}

export function penaltyHeadline(r: GameResult): string {
  if (r.won) return r.sudden ? 'Победа в серии до промаха!' : 'Победа!';
  return r.sudden ? 'Проиграли в серии до промаха' : 'Поражение';
}

/** Плавная кривая полёта мяча: easeOutCubic. */
export function easeOut(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return 1 - (1 - x) ** 3;
}

/** Положение мяча на кадре t∈[0,1]: дуга от точки до цели, с подъёмом и уменьшением (перспектива). */
export function ballFrame(
  t: number,
  from: { x: number; y: number },
  to: { x: number; y: number },
  lift: number,
): { x: number; y: number; scale: number; spin: number } {
  const e = easeOut(t);
  return {
    x: from.x + (to.x - from.x) * e,
    y: from.y + (to.y - from.y) * e - lift * Math.sin(Math.PI * e),
    scale: 1 - 0.55 * e,
    spin: 540 * e,
  };
}

/* ---------- рекорды на устройстве ---------- */

export type LocalBest = Record<string, number>;

export const LOCAL_KEY = 'rm-games-best';

export function bestKey(game: GameId, level: string): string {
  return `${game}:${level}`;
}

/** Обновить локальный рекорд; возвращает новый объект и был ли это рекорд. */
export function mergeLocalBest(store: LocalBest, game: GameId, level: string, score: number): { store: LocalBest; record: boolean } {
  const k = bestKey(game, level);
  const prev = store[k];
  if (prev != null && prev >= score) return { store, record: false };
  return { store: { ...store, [k]: score }, record: score > 0 && (prev == null || score > prev) };
}

export function parseLocalBest(raw: string | null): LocalBest {
  if (!raw) return {};
  try {
    const v = JSON.parse(raw) as unknown;
    if (!v || typeof v !== 'object' || Array.isArray(v)) return {};
    const out: LocalBest = {};
    for (const [k, n] of Object.entries(v as Record<string, unknown>)) {
      if (/^(quiz|penalty):[a-z]{2,10}$/.test(k) && typeof n === 'number' && Number.isFinite(n) && n >= 0) out[k] = Math.floor(n);
    }
    return out;
  } catch {
    return {};
  }
}

/** Лучший результат для карточки уровня: сервер (если вошёл) или устройство — что больше. */
export function bestFor(game: GameId, level: string, local: LocalBest, server: GamesMe | null): number | null {
  const s = server?.best?.[game]?.[level]?.best;
  const l = local[bestKey(game, level)];
  if (s == null && l == null) return null;
  return Math.max(s ?? 0, l ?? 0);
}

/* ---------- поделиться ---------- */

export function shareText(game: GameId, level: string, r: GameResult): string {
  const lv = levelTitle(game, level);
  if (game === 'quiz')
    return `Викторина «Мадридиста», уровень «${lv}»: ${r.score} ${plural(r.score, ['очко', 'очка', 'очков'])}, ${quizSummary(r)}. Сможешь больше?`;
  return `Пенальти «Мадридиста», уровень «${lv}»: ${r.goals ?? 0}:${r.rival ?? 0}, ${r.score} ${plural(r.score, ['очко', 'очка', 'очков'])}. Попробуй переиграть!`;
}

export function plural(n: number, forms: [string, string, string]): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b > 1 && b < 5) return forms[1];
  if (b === 1) return forms[0];
  return forms[2];
}

/** Ошибка API игр → понятный текст. */
export function gameError(status: number, serverMessage?: string): string {
  if (status === 0) return 'Нет соединения — проверьте интернет';
  if (status === 404) return 'Игра устарела — начните заново';
  if (status === 429) return serverMessage || 'Слишком часто — подождите немного';
  if (status >= 500) return 'Сервер игр недоступен — попробуйте позже';
  return serverMessage || 'Что-то пошло не так';
}
