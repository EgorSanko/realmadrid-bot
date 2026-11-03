// Праздник гола: что считается новым голом, а что уже показано. Запуск: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SCORER_MAX_MS, SCORER_STEP_MS, SEEN_KEY, createGoalWatcher, observeScore, scoreKeys, storedSeen, waitScorer, type ScorerProbe } from '../src/lib/goalWatch.ts';
import { shortName } from '../src/screens/match/view.ts';

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

test('впервые открыли на 35-й минуте при 1:0 — гол празднуем, повтор того же счёта — нет', () => {
  const w = createGoalWatcher(storedSeen(memStorage()));
  assert.deepEqual(w({ id: 1, score: [1, 0], live: true }), [{ key: '1:home:1', side: 'home', n: 1 }]);
  assert.deepEqual(w({ id: 1, score: [1, 0], live: true }), []);
});

test('смотрел при 0:0, закрыл, открыл снова после гола — праздник пропущенного гола', () => {
  const st = memStorage();
  createGoalWatcher(storedSeen(st))({ id: 9, score: [0, 0], live: true });
  // новое открытие приложения: новый экран, то же хранилище
  const again = createGoalWatcher(storedSeen(st));
  assert.deepEqual(again({ id: 9, score: [1, 0], live: true }), [{ key: '9:home:1', side: 'home', n: 1 }]);
  // и ещё одно открытие — уже показанный гол не повторяется
  assert.deepEqual(createGoalWatcher(storedSeen(st))({ id: 9, score: [1, 0], live: true }), []);
});

test('новый гол во время лайва — один праздник', () => {
  const w = createGoalWatcher(storedSeen(memStorage()));
  w({ id: 1, score: [0, 0], live: true });
  assert.deepEqual(w({ id: 1, score: [1, 0], live: true }), [{ key: '1:home:1', side: 'home', n: 1 }]);
  assert.deepEqual(w({ id: 1, score: [1, 0], live: true }), []);
  assert.deepEqual(w({ id: 1, score: [1, 1], live: true }), [{ key: '1:away:1', side: 'away', n: 1 }]);
});

test('пропустил несколько голов — все непоказанные по порядку (экран берёт последний)', () => {
  const w = createGoalWatcher(storedSeen(memStorage()));
  w({ id: 1, score: [0, 0], live: true });
  assert.deepEqual(
    w({ id: 1, score: [2, 1], live: true }).map((g) => g.key),
    ['1:home:1', '1:home:2', '1:away:1'],
  );
});

test('до начала счёта нет; после свистка — не празднуем, но помечаем', () => {
  const st = memStorage();
  const w = createGoalWatcher(storedSeen(st));
  assert.deepEqual(w({ id: 1, score: null, live: false }), []);
  assert.deepEqual(w({ id: 1, score: [0, 0], live: true }), []);
  assert.deepEqual(w({ id: 1, score: [2, 0], live: false }), []);
  assert.ok(JSON.parse(st.m.get(SEEN_KEY)!).includes('1:home:2'));
});

test('показанный гол не повторяется на другом экране', () => {
  const st = memStorage();
  const home = createGoalWatcher(storedSeen(st));
  home({ id: 5, score: [0, 0], live: true });
  assert.equal(home({ id: 5, score: [1, 0], live: true }).length, 1);
  assert.ok(JSON.parse(st.m.get(SEEN_KEY)!).includes('5:home:1'));
  // экран матча открылся позже и видит уже следующий опрос
  const match = createGoalWatcher(storedSeen(st));
  assert.deepEqual(match({ id: 5, score: [1, 0], live: true }), []);
  assert.deepEqual(observeScore({ id: 5, score: [1, 0], live: true }, storedSeen(st)), []);
});

test('VAR отменил гол — перебитый гол снова праздник', () => {
  const w = createGoalWatcher(storedSeen(memStorage()));
  w({ id: 1, score: [0, 0], live: true });
  assert.equal(w({ id: 1, score: [1, 0], live: true }).length, 1);
  assert.deepEqual(w({ id: 1, score: [0, 0], live: true }), []);
  assert.equal(w({ id: 1, score: [1, 0], live: true }).length, 1);
});

test('без хранилища (приватный режим) — работает в памяти', () => {
  const w = createGoalWatcher(storedSeen(null));
  w({ id: 1, score: [0, 0], live: true });
  assert.equal(w({ id: 1, score: [0, 1], live: true }).length, 1);
  assert.deepEqual(w({ id: 1, score: [0, 1], live: true }), []);
});

test('пачка пропущенных голов — по ходу матча, не больше трёх последних', async () => {
  const { orderBatch } = await import('../src/lib/goalWatch.ts');
  // лента: гость 1-й, хозяева 1-й, хозяева 2-й, гость 2-й
  const tl = [{ side: 'away' as const }, { side: 'home' as const }, { side: 'home' as const }, { side: 'away' as const }];
  const batch = [
    { side: 'home' as const, n: 2 },
    { side: 'away' as const, n: 2 },
    { side: 'home' as const, n: 1 },
  ];
  assert.deepEqual(orderBatch(batch, tl).map((g) => `${g.side}${g.n}`), ['home1', 'home2', 'away2']);
  const all = [...batch, { side: 'away' as const, n: 1 }];
  assert.deepEqual(orderBatch(all, tl).map((g) => `${g.side}${g.n}`), ['home1', 'home2', 'away2']);
  // ленты нет — порядок прихода, последние три
  assert.deepEqual(orderBatch(all, null).map((g) => `${g.side}${g.n}`), ['away2', 'home1', 'away1']);
});

function scripted(answers: ScorerProbe[]) {
  let clock = 0;
  let calls = 0;
  return {
    probe: async () => answers[Math.min(calls++, answers.length - 1)],
    opts: { sleep: async (ms: number) => void (clock += ms), now: () => clock },
    calls: () => calls,
    clock: () => clock,
  };
}

test('плашка ждёт автора: сначала счёт без имени, потом имя и минута', async () => {
  const s = scripted([{ state: 'wait' }, { state: 'wait' }, { state: 'known', scorer: { id: 7, name: 'Mbappé' }, minute: "67'" }]);
  assert.deepEqual(await waitScorer(s.probe, s.opts), { scorer: { id: 7, name: 'Mbappé' }, minute: "67'" });
  assert.equal(s.calls(), 3);
});

test('автор уже известен — без ожидания', async () => {
  const s = scripted([{ state: 'known', scorer: { name: 'Vini' } }]);
  await waitScorer(s.probe, s.opts);
  assert.equal(s.clock(), 0);
});

test('автора так и нет — через 2 минуты плашка без имени; матч окончен — сразу', async () => {
  const s = scripted([{ state: 'wait' }]);
  assert.deepEqual(await waitScorer(s.probe, s.opts), { scorer: null });
  assert.equal(s.clock(), SCORER_MAX_MS);
  assert.equal(s.calls(), SCORER_MAX_MS / SCORER_STEP_MS + 1);
  const f = scripted([{ state: 'final' }]);
  assert.deepEqual(await waitScorer(f.probe, f.opts), { scorer: null });
  assert.equal(f.clock(), 0);
});

test('гол отменили, пока ждали автора, — плашки нет; один устаревший ответ гол не отменяет', async () => {
  const s = scripted([{ state: 'wait' }, { state: 'gone' }, { state: 'gone' }]);
  assert.equal(await waitScorer(s.probe, s.opts), null);
  const once = scripted([{ state: 'gone' }, { state: 'wait' }, { state: 'known', scorer: { name: 'Vini' } }]);
  assert.deepEqual(await waitScorer(once.probe, once.opts), { scorer: { name: 'Vini' }, minute: undefined });
});

test('<TBD> вместо имени — автор неизвестен', () => {
  assert.equal(shortName('<TBD>'), '');
  assert.equal(shortName('TBD'), '');
  assert.equal(shortName('Kylian Mbappé'), 'Mbappé');
});
