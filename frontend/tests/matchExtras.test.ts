// Экран матча, этап 2: «Интересные факты», «Матчи тура», «Кто победит?» (агрегат голосов).
// Фикстура match_5868098_live.json — настоящий ответ /api/match со снимками insights / round / poll.
// Запуск: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { normalizeMatch, type ApiMatch } from '../src/api/match.ts';
import { insightsView, percents, pollView, roundRows, roundTitle, roundView, votesText } from '../src/screens/match/extras.ts';

const fx = (name: string): ApiMatch =>
  normalizeMatch(JSON.parse(readFileSync(new URL(`../src/__fixtures__/${name}.json`, import.meta.url), 'utf8')));

const LIVE = fx('match_5868098_live');
const OLD = fx('match_6106274');

test('интересные факты: главный факт и по три на команду, Реал первым', () => {
  const v = insightsView(LIVE)!;
  assert.ok(v.main!.startsWith('Real Madrid выиграл 19 из 20'));
  assert.deepEqual(v.teams.map((t) => [t.id, t.name, t.side, t.items.length]), [
    [8633, 'Real Madrid', 'home', 3],
    [8302, 'Sevilla', 'away', 3],
  ]);
  assert.equal(v.count, 7);
  // Реал в гостях — всё равно первым
  const m = structuredClone(LIVE);
  m.insights!.teams.reverse();
  assert.equal(insightsView(m)!.teams[0].id, 8633);
  assert.equal(insightsView(OLD), null);
  m.insights = { lang: 'ru', main: null, teams: [] };
  assert.equal(insightsView(m), null);
});

test('матчи тура: по дням МСК, наш матч, live-минута, победитель', () => {
  const v = roundView(LIVE)!;
  assert.equal(v.title, 'Ла Лига · 9-й тур');
  assert.equal(v.leagueId, 87);
  assert.equal(v.played, 'сыграно 8 из 10');
  assert.equal(v.live, 1);
  assert.deepEqual(v.days.map((d) => d.rows.length), [1, 4, 4, 1]); // пт, сб, вс, пн
  const rows = v.days.flatMap((d) => d.rows);
  const ours = rows.filter((r) => r.ours);
  assert.equal(ours.length, 1);
  assert.deepEqual([ours[0].state, ours[0].label, ours[0].home.score, ours[0].away.score], ['live', '46′', 2, 0]);
  const betis = rows.find((r) => r.home.name === 'Real Betis')!;
  assert.deepEqual([betis.state, betis.label, betis.away.win, betis.home.win], ['finished', 'Завершён', true, false]);
  const getafe = rows[rows.length - 1];
  assert.deepEqual([getafe.state, getafe.home.score, getafe.label], ['scheduled', null, null]);
  assert.equal(roundView(OLD), null);
  assert.equal(roundTitle({ league: { id: 42, name: 'Champions League', logo: null }, round: 'League Stage' }), 'Лига чемпионов');
  // id нашего матча не совпал с туром (другой матч) — подсветки по id нет, по is_ours — есть
  assert.equal(roundRows(LIVE.round!, 1).filter((r) => r.ours).length, 0);
  assert.equal(roundRows(LIVE.round!).filter((r) => r.ours).length, 1);
});

test('проценты 1X2 в сумме 100, тысячи голосов', () => {
  assert.deepEqual(percents({ home: 176727, draw: 49376, away: 37025, total: 263128 }), { home: 67, draw: 19, away: 14 });
  assert.deepEqual(percents({ home: 1, draw: 1, away: 1, total: 3 }), { home: 34, draw: 33, away: 33 });
  assert.deepEqual(percents({ home: 0, draw: 0, away: 0, total: 0 }), { home: 0, draw: 0, away: 0 });
  assert.equal(votesText(263128), '263 тыс. голосов');
  assert.equal(votesText(9257), '9,3 тыс. голосов');
  assert.equal(votesText(1_240_000), '1,2 млн голосов');
  assert.equal(votesText(21), '21 голос');
  assert.equal(votesText(3), '3 голоса');
});

test('кто победит: наши прогнозы и голоса FotMob, лидер, порог', () => {
  const v = pollView(LIVE)!;
  assert.deepEqual(v.rows.map((r) => [r.key, r.label, r.sub]), [
    ['ours', 'Болельщики Мадридисты', '124 прогноза'],
    ['fotmob', 'FotMob', '263 тыс. голосов'],
  ]);
  assert.deepEqual(v.rows[0].parts.map((p) => [p.k, p.pct, p.leader]), [
    ['home', 68, true],
    ['draw', 18, false],
    ['away', 14, false],
  ]);
  assert.equal(v.need, null);
  assert.equal(v.cta, false);
  // ниже порога: строки «Мадридисты» нет, «ещё N», ссылка — если приём открыт и прогноза нет
  const m = structuredClone(LIVE);
  m.poll = { ...m.poll!, ours: null, ours_count: 7, threshold: 10 };
  const low = pollView(m, { accepting: true, mine: null })!;
  assert.deepEqual(low.rows.map((r) => r.key), ['fotmob']);
  assert.equal(low.need, 3);
  assert.deepEqual([low.have, low.of], [7, 10]);
  assert.equal(low.cta, true);
  const mine = pollView(m, { accepting: true, mine: { home: 2, away: 1 } })!;
  assert.equal(mine.cta, false);
  assert.equal(mine.mine, '2:1');
  // ни голосов FotMob, ни наших, и звать некуда — карточки нет
  m.poll = { fotmob: null, ours: null, ours_count: 3, threshold: 10 };
  assert.equal(pollView(m), null);
  assert.ok(pollView(m, { accepting: true, mine: null })!.cta);
  assert.equal(pollView(OLD), null);
});

test('кто победит: только исход 1X2 — никаких ставочных рынков', () => {
  const s = JSON.stringify(pollView(LIVE));
  for (const w of ['bts', 'тотал', 'обе забьют', 'двойной', 'коэфф']) assert.ok(!s.toLowerCase().includes(w), w);
  assert.deepEqual(Object.keys(LIVE.poll!.fotmob!).sort(), ['away', 'draw', 'home', 'total']);
});
