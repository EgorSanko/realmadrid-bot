// Пенальти: позы Куртуа (мяч в перчатке — в центре зоны), каркас, исходы и надписи.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  DIVE,
  GOAL,
  GOAL_LINE,
  catchPoint,
  divePoint,
  goalPoint,
  keeperPose,
  outcomeText,
  reboundPoint,
  rivalFrom,
  shotOutcome,
  woodPoint,
  zonePoint,
} from '../src/lib/penalty.ts';

const near = (a: number, b: number, eps = 1e-6) => Math.abs(a - b) < eps;

test('сейв: мяч в перчатках — в центре зоны для углов, у груди/живота по центру', () => {
  for (const z of [1, 3, 4, 6]) {
    const pose = keeperPose(z);
    assert.equal(pose.kind, 'dive');
    const c = catchPoint(pose);
    const p = zonePoint(z);
    assert.ok(near(c.x, p.x) && near(c.y, p.y), `зона ${z}`);
  }
  for (const z of [2, 5]) {
    const pose = keeperPose(z);
    assert.equal(pose.kind, 'idle');
    const c = catchPoint(pose);
    assert.ok(Math.abs(c.x - 200) < 2);
    assert.ok(c.y > GOAL.y && c.y < GOAL_LINE);
  }
  // вверх по центру — выше, чем внизу
  assert.ok(catchPoint(keeperPose(2)).y < catchPoint(keeperPose(5)).y);
});

test('прыжок: влево — зеркально вправо, таз в воротах, ступни не под газоном', () => {
  for (const [l, r] of [
    [1, 3],
    [4, 6],
  ]) {
    const a = keeperPose(l);
    const b = keeperPose(r);
    if (a.kind !== 'dive' || b.kind !== 'dive') throw new Error('ожидался прыжок');
    assert.equal(a.flip, -1);
    assert.equal(b.flip, 1);
    assert.ok(near(a.hip.x, 400 - b.hip.x) && near(a.hip.y, b.hip.y) && near(a.rot, -b.rot));
    for (const pose of [a, b]) {
      assert.ok(pose.hip.x > GOAL.x && pose.hip.x < GOAL.x + GOAL.w && pose.hip.y < GOAL_LINE);
      for (const f of DIVE.feet) assert.ok(divePoint(f, pose.hip, pose.rot, pose.flip).y < GOAL_LINE + 6);
    }
  }
  // верхний угол — таз выше, чем в нижнем
  const top = keeperPose(3);
  const low = keeperPose(6);
  if (top.kind === 'dive' && low.kind === 'dive') assert.ok(top.hip.y < low.hip.y);
});

test('гол: точка в воротах, не ближе 12 px к каркасу', () => {
  for (let z = 1; z <= 6; z += 1)
    for (const r of [-1, 0, 1]) {
      const p = goalPoint(z, r, r);
      assert.ok(p.x >= GOAL.x + 12 && p.x <= GOAL.x + GOAL.w - 12 && p.y >= GOAL.y + 12 && p.y <= GOAL_LINE - 10);
    }
});

test('каркас: штанга — у своего края, перекладина — сверху; отскок — из ворот', () => {
  assert.ok(woodPoint(1, 'post').x < GOAL.x && woodPoint(6, 'post').x > GOAL.x + GOAL.w);
  assert.ok(woodPoint(3, 'bar').y < GOAL.y);
  assert.ok(reboundPoint(4, 'post').x < GOAL.x && reboundPoint(3, 'bar').y > GOAL_LINE);
});

test('исход: с сервера, а без поля outcome — из goal и прыжка', () => {
  assert.equal(shotOutcome({ outcome: 'bar', goal: false, zone: 1, keeper: 2 }), 'bar');
  assert.equal(shotOutcome({ goal: true, zone: 1, keeper: 2 }), 'goal');
  assert.equal(shotOutcome({ goal: false, zone: 2, keeper: 2 }), 'save');
  assert.equal(shotOutcome({ outcome: 'что-то', goal: false, zone: 4, keeper: 1 }), 'post');
  assert.deepEqual(outcomeText('goal'), { title: 'ГОЛ!', sub: 'Красота!' });
  assert.equal(outcomeText('save').sub, 'Куртуа угадал!');
  assert.equal(outcomeText('bar').title, 'ПЕРЕКЛАДИНА!');
});

test('соперник на табло: из ближайшего матча, Реал — не соперник, без данных — null', () => {
  type Home = NonNullable<Parameters<typeof rivalFrom>[0]>;
  const team = (id: number | null, name: string | null, short?: string) => ({ id, name, short });
  const fx = (home: ReturnType<typeof team>, away: ReturnType<typeof team>) => ({ home, away }) as unknown as Home['next'];
  assert.deepEqual(rivalFrom({ next: fx(team(8633, 'Real Madrid'), team(8302, 'Sevilla')), last: null }), { id: 8302, name: 'Sevilla' });
  assert.deepEqual(rivalFrom({ next: fx(team(9906, 'Atletico Madrid', 'Atlético'), team(8633, 'Real Madrid')), last: null }), {
    id: 9906,
    name: 'Atlético',
  });
  assert.deepEqual(rivalFrom({ next: null, last: fx(team(8633, 'Real Madrid'), team(8634, 'Barcelona')) }), { id: 8634, name: 'Barcelona' });
  assert.equal(rivalFrom({ next: fx(team(8633, 'Real Madrid'), team(null, 'TBD')), last: null }), null);
  assert.equal(rivalFrom(null), null);
});
