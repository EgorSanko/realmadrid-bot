// Профиль и вход: разбор startapp, ответы /api/predict/me и /leagues → блоки экрана.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { inviteLink, joinedMessage, parseStartParam } from '../src/lib/startParam.ts';
import { historyRow, isSoftUnavailable, pointsTiles } from '../src/lib/profile.ts';
import type { PredHistoryItem, PredictMe } from '../src/lib/profile.ts';

test('startapp: profile, league_<код>, match_<id>; мусор — null', () => {
  assert.deepEqual(parseStartParam('profile'), { kind: 'profile' });
  assert.deepEqual(parseStartParam('league_ab23cdef9k'), { kind: 'league', code: 'AB23CDEF9K' });
  assert.deepEqual(parseStartParam('match_5868098'), { kind: 'match', id: '5868098' });
  for (const bad of [null, undefined, '', 'league_', 'league_a-b', 'match_0', 'match_12x', 'profile2', 'match_../admin', 'league_' + 'A'.repeat(40)])
    assert.equal(parseStartParam(bad), null, String(bad));
});

test('ссылка-приглашение: с сервера или собранная по имени бота', () => {
  assert.equal(inviteLink('ABC', 'https://t.me/x?startapp=league_ABC', 'bot'), 'https://t.me/x?startapp=league_ABC');
  assert.equal(inviteLink('ABC', null, 'Real_Madrid_football_bot'), 'https://t.me/Real_Madrid_football_bot?startapp=league_ABC');
  assert.equal(joinedMessage('Друзья', true), 'Вы вступили в лигу «Друзья»');
  assert.equal(joinedMessage('Друзья', false), 'Вы уже в лиге «Друзья»');
});

const ME: PredictMe = {
  user: { id: 7, name: 'Лука М.', username: 'lm10' },
  season: { key: 'S2026', label: '2026/27', rank: 3, points: 12, exact: 2, played: 4 },
  month: { key: 'M2026-10', label: '2026-10', rank: 1, points: 7, exact: 1, played: 2 },
  points: 12,
  rank: 3,
  exact: 2,
  predictions: 5,
  history: [],
};

test('«Мои очки»: сезон, месяц, место, точные счета', () => {
  assert.deepEqual(
    pointsTiles(ME).map((t) => [t.label, t.value]),
    [
      ['Очки за сезон', '12'],
      ['За месяц', '7'],
      ['Место', '3'],
      ['Точных счетов', '2'],
    ],
  );
  assert.equal(pointsTiles(ME)[1].sub, 'октябрь 2026');
  assert.equal(pointsTiles(ME)[0].sub, '2026/27');
  // нет данных (адаптер матчей не подключён) — нули и прочерк, не ошибка
  const empty = pointsTiles(null);
  assert.deepEqual(empty.map((t) => t.value), ['0', '0', '—', '0']);
  assert.equal(pointsTiles({ ...ME, season: { ...ME.season, rank: null } })[2].sub, 'нет прогнозов');
});

const item = (over: Partial<PredHistoryItem>): PredHistoryItem => ({
  match: {
    id: '5868098',
    kickoff_utc: '2026-10-18T19:00:00Z',
    home: { id: '8633', name: 'Реал Мадрид' },
    away: { id: '8302', name: 'Севилья' },
    rm_side: 'home',
    status: 'finished',
    score: { home: 2, away: 1 },
  },
  prediction: { home: 2, away: 1 },
  points: { total: 7, score: 5, scorer: 2, kind: 'exact' },
  state: 'settled',
  ...over,
});

test('«Мои прогнозы»: эмблемы по id, прогноз, итог, очки', () => {
  const r = historyRow(item({}));
  assert.equal(r.href, '/match/5868098');
  assert.deepEqual(r.home, { id: 8633, name: 'Реал Мадрид' });
  assert.deepEqual(r.away, { id: 8302, name: 'Севилья' });
  assert.equal(r.pick, '2:1');
  assert.equal(r.note, 'Итог 2:1');
  assert.equal(r.points, 7);
  assert.equal(r.tone, 'exact');
  assert.equal(historyRow(item({ points: { total: 0, score: 0, scorer: 0, kind: 'miss' } })).tone, 'miss');
  assert.equal(historyRow(item({ points: { total: 2, score: 2, scorer: 0, kind: 'outcome' } })).tone, 'hit');
  const open = historyRow(item({ state: 'open', points: null, match: { ...item({}).match, status: 'scheduled', score: null } }));
  assert.equal(open.note, 'Можно изменить до начала');
  assert.equal(open.points, null);
  assert.equal(historyRow(item({ state: 'void', points: null })).note, 'Матч не состоялся');
  assert.equal(historyRow(item({ state: 'waiting', points: null })).note, 'Итог 2:1 · считаем очки');
  const noId = historyRow(item({ match: { ...item({}).match, home: { id: null, name: 'Кто-то' } } }));
  assert.equal(noId.home.id, null);
});

test('503 «матчи не подключены» — пустой блок, не ошибка', () => {
  assert.equal(isSoftUnavailable(503), true);
  assert.equal(isSoftUnavailable(500), false);
  assert.equal(isSoftUnavailable(401), false);
});

test('скрипт виджета Telegram не в основном коде: только URL, грузится по нажатию', () => {
  const src = readFileSync(new URL('../src/lib/telegramWidget.ts', import.meta.url), 'utf8');
  assert.match(src, /https:\/\/telegram\.org\/js\/telegram-widget\.js\?22/);
  const main = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(main, /telegram-widget/);
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.doesNotMatch(html, /telegram\.org/);
});
