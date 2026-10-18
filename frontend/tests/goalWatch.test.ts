// Праздник гола: что считается новым голом, а что уже показано. Запуск: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SEEN_KEY, createGoalWatcher, observeScore, scoreKeys, sessionSeen } from '../src/lib/goalWatch.ts';

function memStorage() {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
}

test('ключи голов — по счёту: матч, сторона, номер', () => {
  assert.deepEqual(
    scoreKeys(7, [2, 1]).map((g) => g.key),
    ['7:home:1', '7:home:2', '7:away:1'],
  );
});

test('открыли экран с уже забитыми голами — без праздника', () => {
  const w = createGoalWatcher(sessionSeen(memStorage()));
  assert.deepEqual(w({ id: 1, score: [2, 1], live: true }), []);
  // повторный ответ с тем же счётом — тоже ничего
  assert.deepEqual(w({ id: 1, score: [2, 1], live: true }), []);
});

test('новый гол во время лайва — один праздник', () => {
  const w = createGoalWatcher(sessionSeen(memStorage()));
  w({ id: 1, score: [0, 0], live: true });
  assert.deepEqual(w({ id: 1, score: [1, 0], live: true }), [{ key: '1:home:1', side: 'home', n: 1 }]);
  assert.deepEqual(w({ id: 1, score: [1, 0], live: true }), []);
  assert.deepEqual(w({ id: 1, score: [1, 1], live: true }), [{ key: '1:away:1', side: 'away', n: 1 }]);
});

test('до начала счёта нет — первый взгляд наступает со стартом матча', () => {
  const w = createGoalWatcher(sessionSeen(memStorage()));
  assert.deepEqual(w({ id: 1, score: null, live: false }), []);
  assert.deepEqual(w({ id: 1, score: [0, 0], live: true }), []);
  assert.equal(w({ id: 1, score: [0, 1], live: true }).length, 1);
});

test('после свистка и при пачке голов (вкладка спала) — не празднуем', () => {
  const w = createGoalWatcher(sessionSeen(memStorage()));
  w({ id: 1, score: [0, 0], live: true });
  assert.deepEqual(w({ id: 1, score: [3, 0], live: true }), []);
  assert.deepEqual(w({ id: 1, score: [3, 1], live: false }), []);
});

test('показанный гол не повторяется на другом экране той же сессии', () => {
  const st = memStorage();
  const home = createGoalWatcher(sessionSeen(st));
  home({ id: 5, score: [0, 0], live: true });
  assert.equal(home({ id: 5, score: [1, 0], live: true }).length, 1);
  assert.ok(JSON.parse(st.m.get(SEEN_KEY)!).includes('5:home:1'));
  // экран матча открылся позже и видит уже следующий опрос
  const match = createGoalWatcher(sessionSeen(st));
  assert.deepEqual(match({ id: 5, score: [1, 0], live: true }), []);
  assert.deepEqual(observeScore({ id: 5, score: [1, 0], live: true }, sessionSeen(st), false), []);
});

test('VAR отменил гол — перебитый гол снова праздник', () => {
  const w = createGoalWatcher(sessionSeen(memStorage()));
  w({ id: 1, score: [0, 0], live: true });
  assert.equal(w({ id: 1, score: [1, 0], live: true }).length, 1);
  assert.deepEqual(w({ id: 1, score: [0, 0], live: true }), []);
  assert.equal(w({ id: 1, score: [1, 0], live: true }).length, 1);
});

test('без sessionStorage (приватный режим) — работает в памяти', () => {
  const w = createGoalWatcher(sessionSeen(null));
  w({ id: 1, score: [0, 0], live: true });
  assert.equal(w({ id: 1, score: [0, 1], live: true }).length, 1);
  assert.deepEqual(w({ id: 1, score: [0, 1], live: true }), []);
});
