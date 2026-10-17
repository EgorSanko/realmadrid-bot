// Игры: множитель, кольцо таймера, клавиши, зоны ворот и свайп, полёт мяча, рекорды на устройстве.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  answerFromKey,
  ballFrame,
  bestFor,
  gameError,
  mergeLocalBest,
  moveZone,
  multiplierFor,
  parseLocalBest,
  penaltyHeadline,
  plural,
  ringOffset,
  shareText,
  shotMarks,
  zoneCell,
  zoneFromSwipe,
  zoneOf,
} from '../src/lib/games.ts';
import type { GameResult, GamesMe } from '../src/lib/games.ts';
import { parseStartParam } from '../src/lib/startParam.ts';

test('множитель серии как на сервере: 1–2 ×1, 3–5 ×2, 6+ ×3', () => {
  assert.deepEqual([0, 1, 2, 3, 5, 6, 9].map(multiplierFor), [1, 1, 1, 2, 2, 3, 3]);
});

test('кольцо таймера: полное в начале, пустое в конце, без выхода за пределы', () => {
  assert.equal(ringOffset(15, 15, 100), 0);
  assert.equal(ringOffset(0, 15, 100), 100);
  assert.equal(ringOffset(7.5, 15, 100), 50);
  assert.equal(ringOffset(-3, 15, 100), 100);
  assert.equal(ringOffset(20, 15, 100), 0);
});

test('клавиши ответа: 1–4, A–D, по коду клавиши — и в русской раскладке', () => {
  assert.equal(answerFromKey('1'), 0);
  assert.equal(answerFromKey('4'), 3);
  assert.equal(answerFromKey('b'), 1);
  assert.equal(answerFromKey('D'), 3);
  assert.equal(answerFromKey('с', 'KeyC'), 2);
  assert.equal(answerFromKey('5'), null);
  assert.equal(answerFromKey('Enter'), null);
});

test('зоны ворот: 1–3 верх, 4–6 низ; стрелки двигают прицел и не выходят за ворота', () => {
  assert.deepEqual(zoneCell(1), { col: 0, row: 0 });
  assert.deepEqual(zoneCell(6), { col: 2, row: 1 });
  for (let z = 1; z <= 6; z += 1) {
    const { col, row } = zoneCell(z);
    assert.equal(zoneOf(col, row), z);
  }
  assert.equal(moveZone(5, 'ArrowLeft'), 4);
  assert.equal(moveZone(4, 'ArrowLeft'), 4);
  assert.equal(moveZone(5, 'ArrowUp'), 2);
  assert.equal(moveZone(2, 'ArrowUp'), 2);
  assert.equal(moveZone(3, 'ArrowDown'), 6);
  assert.equal(moveZone(6, 'ArrowRight'), 6);
});

test('свайп от мяча: направление и длина → зона; короткий или вниз — не удар', () => {
  const w = 360;
  assert.equal(zoneFromSwipe(-120, -200, w), 1);
  assert.equal(zoneFromSwipe(0, -200, w), 2);
  assert.equal(zoneFromSwipe(130, -60, w), 6);
  assert.equal(zoneFromSwipe(-100, -60, w), 4);
  assert.equal(zoneFromSwipe(0, -60, w), 5);
  assert.equal(zoneFromSwipe(5, -10, w), null);
  assert.equal(zoneFromSwipe(0, 80, w), null);
});

test('полёт мяча: от точки к цели, уменьшается, в середине — над прямой', () => {
  const from = { x: 200, y: 280 };
  const to = { x: 100, y: 100 };
  const a = ballFrame(0, from, to, 40);
  const b = ballFrame(1, from, to, 40);
  assert.deepEqual([a.x, a.y, a.scale], [200, 280, 1]);
  assert.ok(Math.abs(b.x - 100) < 1e-9 && Math.abs(b.y - 100) < 1e-6 && b.scale < 0.5);
  const m = ballFrame(0.3, from, to, 40);
  const straightY = from.y + (to.y - from.y) * (1 - 0.7 ** 3);
  assert.ok(m.y < straightY);
});

test('отметки серии: 5 кружков, в серии до промаха — больше', () => {
  assert.deepEqual(shotMarks([true, false]), ['goal', 'miss', 'pending', 'pending', 'pending']);
  assert.equal(shotMarks([true, true, true, true, true, true, false]).length, 7);
});

test('рекорды на устройстве: только больше прежнего, мусор в хранилище отбрасывается', () => {
  let r = mergeLocalBest({}, 'quiz', 'easy', 900);
  assert.equal(r.record, true);
  r = mergeLocalBest(r.store, 'quiz', 'easy', 500);
  assert.equal(r.record, false);
  assert.equal(r.store['quiz:easy'], 900);
  assert.equal(mergeLocalBest({}, 'penalty', 'easy', 0).record, false); // ноль — не рекорд
  assert.deepEqual(parseLocalBest('{"quiz:hard":1200,"x":5,"quiz:easy":-1,"penalty:legend":"7"}'), { 'quiz:hard': 1200 });
  assert.deepEqual(parseLocalBest('не json'), {});
  assert.deepEqual(parseLocalBest(null), {});
});

test('лучший результат уровня: максимум из сервера и устройства', () => {
  const me: GamesMe = { best: { quiz: { easy: { best: 1500, played: 2 } }, penalty: {} }, week: { quiz: null, penalty: null } };
  assert.equal(bestFor('quiz', 'easy', { 'quiz:easy': 900 }, me), 1500);
  assert.equal(bestFor('quiz', 'easy', { 'quiz:easy': 2000 }, me), 2000);
  assert.equal(bestFor('penalty', 'easy', {}, me), null);
  assert.equal(bestFor('quiz', 'hard', { 'quiz:hard': 10 }, null), 10);
});

test('тексты: итог серии, «поделиться», склонения, ошибки', () => {
  const win: GameResult = { game: 'penalty', level: 'hard', score: 2400, saved: false, best: null, record: null, goals: 5, rival: 3, won: true, sudden: false };
  assert.equal(penaltyHeadline(win), 'Победа!');
  assert.equal(penaltyHeadline({ ...win, won: false, sudden: true }), 'Проиграли в серии до промаха');
  assert.match(shareText('penalty', 'hard', win), /Пенальти «Мадридиста», уровень «Сложный»: 5:3, 2400 очков/);
  const quiz: GameResult = { game: 'quiz', level: 'easy', score: 1, saved: true, best: 1, record: true, correct: 1, total: 10 };
  assert.match(shareText('quiz', 'easy', quiz), /1 очко, 1 из 10 верных/);
  assert.deepEqual([1, 2, 5, 11, 21, 22].map((n) => plural(n, ['игра', 'игры', 'игр'])), ['игра', 'игры', 'игр', 'игр', 'игра', 'игры']);
  assert.equal(gameError(0), 'Нет соединения — проверьте интернет');
  assert.equal(gameError(404, 'x'), 'Игра устарела — начните заново');
  assert.equal(gameError(429, 'Слишком быстро'), 'Слишком быстро');
});

test('startapp: quiz и penalty ведут в игры', () => {
  assert.deepEqual(parseStartParam('quiz'), { kind: 'game', game: 'quiz' });
  assert.deepEqual(parseStartParam('penalty'), { kind: 'game', game: 'penalty' });
  assert.equal(parseStartParam('quiz2'), null);
});
