/*
 * Пенальти: геометрия сцены и исходы удара — чистые функции (без React и DOM), их проверяют тесты.
 *
 * Мир сцены — 400×320 условных px (вид от бьющего). Ворота — GOAL, линия ворот — GOAL.y + GOAL.h.
 * Вратарь — две картинки из старой игры (penalty.html): стойка (idle) и прыжок (dive).
 * Позы прыжка подобраны так, чтобы при сейве мяч в перчатке (DIVE.ball) оказался в центре зоны.
 */

import type { ApiHome } from './api';

export type PenaltyOutcome = 'goal' | 'save' | 'post' | 'bar';

export const REAL_ID = 8633;

/** Соперник на табло — из ближайшего матча (иначе — из прошедшего); null — показываем «Соперник». */
export function rivalFrom(home: Pick<ApiHome, 'next' | 'last'> | null | undefined): { id: number; name: string } | null {
  for (const m of [home?.next, home?.last]) {
    if (!m) continue;
    const t = m.home?.id === REAL_ID ? m.away : m.away?.id === REAL_ID ? m.home : null;
    const name = t?.short || t?.name;
    if (t && typeof t.id === 'number' && t.id !== REAL_ID && name) return { id: t.id, name };
  }
  return null;
}

export interface Pt {
  x: number;
  y: number;
}

export const WORLD = { w: 400, h: 320 };
export const GOAL = { x: 60, y: 80, w: 280, h: 112 };
export const GOAL_LINE = GOAL.y + GOAL.h;
export const SPOT: Pt = { x: 200, y: 284 };
export const BALL_SIZE = 28;
export const POST_W = 7;

/** Стойка: картинка 160×259, на сцене шириной IDLE.w; якорь — середина нижнего края. */
export const IDLE = {
  w: 58,
  h: (58 * 259) / 160,
  /** где стоит якорь: чуть ниже линии ворот — бёдра картинки уходят в тень */
  foot: { x: 200, y: GOAL_LINE + 3 } as Pt,
  /** точки «поймал» от якоря: грудь (прыжок вверх) и живот (низ по центру) */
  chest: { x: 0.7, y: -48.6 } as Pt,
  belly: { x: 0, y: -25 } as Pt,
};

const DIVE_SRC = { w: 300, h: 177 };
const DIVE_K = 170 / DIVE_SRC.w;
/** Прыжок: картинка 300×177 — Куртуа летит вправо, перчатка вверху справа. */
export const DIVE = {
  w: 170,
  h: DIVE_SRC.h * DIVE_K,
  /** таз — центр поворота */
  hip: { x: 115 * DIVE_K, y: 107 * DIVE_K } as Pt,
  /** где мяч в перчатке (там был мяч на исходной картинке) */
  ball: { x: 281 * DIVE_K, y: 18 * DIVE_K } as Pt,
  /** ступни — для проверки, что вратарь не «проваливается» под газон */
  feet: [
    { x: 10 * DIVE_K, y: 110 * DIVE_K },
    { x: 50 * DIVE_K, y: 170 * DIVE_K },
  ] as Pt[],
};

/** Зоны ворот: 1–3 — верх (лево, центр, право), 4–6 — низ. */
export function cell(zone: number): { col: 0 | 1 | 2; row: 0 | 1 } {
  const z = Math.min(6, Math.max(1, Math.round(zone))) - 1;
  return { col: (z % 3) as 0 | 1 | 2, row: (z < 3 ? 0 : 1) as 0 | 1 };
}

/** Центр зоны на сцене. */
export function zonePoint(zone: number): Pt {
  const { col, row } = cell(zone);
  return { x: GOAL.x + (GOAL.w * (col + 0.5)) / 3, y: GOAL.y + GOAL.h * (row === 0 ? 0.26 : 0.77) };
}

/** Куда летит мяч при голе: центр зоны с разбросом (r ∈ [-1, 1]), не ближе 12 px к каркасу. */
export function goalPoint(zone: number, rx: number, ry: number): Pt {
  const p = zonePoint(zone);
  return {
    x: Math.min(GOAL.x + GOAL.w - 12, Math.max(GOAL.x + 12, p.x + rx * 14)),
    // по вертикали — только «в угол»: верх — к перекладине, низ — к газону
    y: Math.min(GOAL_LINE - 10, Math.max(GOAL.y + 12, p.y + (cell(zone).row === 0 ? -1 : 0.75) * Math.abs(ry) * 8)),
  };
}

/** Куда летит мяч при штанге/перекладине: на внутренний край каркаса у зоны. */
export function woodPoint(zone: number, outcome: 'post' | 'bar'): Pt {
  const p = zonePoint(zone);
  const { col } = cell(zone);
  if (outcome === 'bar') return { x: p.x + (col === 0 ? -10 : col === 2 ? 10 : 0), y: GOAL.y - POST_W / 2 };
  return { x: col === 0 ? GOAL.x - POST_W / 2 : GOAL.x + GOAL.w + POST_W / 2, y: p.y };
}

/** Отскок от каркаса: от штанги — наружу и на газон, от перекладины — вверх и к бьющему. */
export function reboundPoint(zone: number, outcome: 'post' | 'bar'): Pt {
  const hit = woodPoint(zone, outcome);
  const side = cell(zone).col === 0 ? -1 : 1;
  return outcome === 'bar' ? { x: hit.x + side * 40, y: GOAL_LINE + 34 } : { x: hit.x + side * 58, y: GOAL_LINE + 46 };
}

/** Поза вратаря. kind: dive — картинка прыжка (повёрнута, при flip — зеркально), idle — стойка. */
export type KeeperPose =
  | { kind: 'dive'; hip: Pt; rot: number; flip: 1 | -1 }
  | { kind: 'idle'; dy: number; sy: number; catchAt: Pt };

const rad = (deg: number) => (deg * Math.PI) / 180;

/** Точка картинки прыжка (в px картинки на сцене) → координаты сцены для таза hip, угла rot и зеркала flip. */
export function divePoint(p: Pt, hip: Pt, rot: number, flip: 1 | -1): Pt {
  const vx = (p.x - DIVE.hip.x) * flip;
  const vy = p.y - DIVE.hip.y;
  const c = Math.cos(rad(rot));
  const s = Math.sin(rad(rot));
  return { x: hip.x + vx * c - vy * s, y: hip.y + vx * s + vy * c };
}

/** Наклон корпуса в прыжке: вверх — почти горизонтально, вниз — ниже к газону. Зеркально для левой стороны. */
const DIVE_ROT = { top: 10, low: 22 };

/** Поза вратаря в конце прыжка в зону: при сейве мяч в перчатках — ровно в центре зоны. */
export function keeperPose(zone: number): KeeperPose {
  const { col, row } = cell(zone);
  if (col === 1) {
    return row === 0
      ? { kind: 'idle', dy: -26, sy: 1.04, catchAt: { x: IDLE.foot.x + IDLE.chest.x, y: IDLE.foot.y - 26 + IDLE.chest.y * 1.04 } }
      : { kind: 'idle', dy: 0, sy: 0.8, catchAt: { x: IDLE.foot.x + IDLE.belly.x, y: IDLE.foot.y + IDLE.belly.y * 0.8 } };
  }
  const flip: 1 | -1 = col === 2 ? 1 : -1;
  const rot = (row === 0 ? DIVE_ROT.top : DIVE_ROT.low) * flip;
  const target = zonePoint(zone);
  // таз такой, чтобы мяч в перчатке попал в target
  const g = divePoint(DIVE.ball, { x: 0, y: 0 }, rot, flip);
  return { kind: 'dive', hip: { x: target.x - g.x, y: target.y - g.y }, rot, flip };
}

/** Где мяч у вратаря в позе (для сейва). */
export function catchPoint(pose: KeeperPose): Pt {
  return pose.kind === 'idle' ? pose.catchAt : divePoint(DIVE.ball, pose.hip, pose.rot, pose.flip);
}

/** CSS transform картинки прыжка (transform-origin 0 0, картинка DIVE.w × DIVE.h). */
export function diveTransform(hip: Pt, rot: number, flip: 1 | -1, scale = 1): string {
  return `translate(${hip.x.toFixed(2)}px, ${hip.y.toFixed(2)}px) rotate(${rot.toFixed(2)}deg) scale(${(flip * scale).toFixed(3)}, ${scale.toFixed(3)}) translate(${(-DIVE.hip.x).toFixed(2)}px, ${(-DIVE.hip.y).toFixed(2)}px)`;
}

/** Исход удара: с сервера (outcome), а у старого сервера — из goal/keeper. */
export function shotOutcome(r: { outcome?: string | null; goal: boolean; zone: number; keeper: number }): PenaltyOutcome {
  if (r.outcome === 'goal' || r.outcome === 'save' || r.outcome === 'post' || r.outcome === 'bar') return r.outcome;
  if (r.goal) return 'goal';
  return r.keeper === r.zone ? 'save' : 'post';
}

/** Надпись после удара — как в старой игре: «Красота!» и «Куртуа угадал!». */
export function outcomeText(o: PenaltyOutcome): { title: string; sub: string } {
  switch (o) {
    case 'goal':
      return { title: 'ГОЛ!', sub: 'Красота!' };
    case 'save':
      return { title: 'СЕЙВ!', sub: 'Куртуа угадал!' };
    case 'post':
      return { title: 'ШТАНГА!', sub: 'Чуть-чуть не хватило' };
    case 'bar':
      return { title: 'ПЕРЕКЛАДИНА!', sub: 'Чуть-чуть не хватило' };
  }
}

/** Плавные кривые. */
export const ease = {
  out: (t: number) => 1 - (1 - clamp01(t)) ** 3,
  in: (t: number) => clamp01(t) ** 2,
  inOut: (t: number) => {
    const x = clamp01(t);
    return x < 0.5 ? 2 * x * x : 1 - (-2 * x + 2) ** 2 / 2;
  },
};

export function clamp01(t: number): number {
  return Math.min(1, Math.max(0, t));
}

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
