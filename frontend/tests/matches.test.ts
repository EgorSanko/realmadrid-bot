// «Матчи»: реальные ответы /api/fixtures и /api/tables → пропсы CalendarRow / FixtureRow / StandingsTable.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import type { ApiFixtures, ApiTables } from '../src/lib/api.ts';
import {
  LALIGA_ID,
  UCL_ID,
  compactRows,
  competitionOf,
  roundsAside,
  splitFixtures,
  standingRows,
  tableFor,
  usRow,
  zonesFor,
} from '../src/lib/mapMatches.ts';

const load = <T>(name: string): T => JSON.parse(readFileSync(new URL(`../src/__fixtures__/${name}`, import.meta.url), 'utf8')) as T;
const FX = load<ApiFixtures>('fixtures.json');
const TB = load<ApiTables>('tables.json');

test('все турниры: ближайшие по времени, первый в рамке; результаты — свежие сверху', () => {
  const { upcoming, results } = splitFixtures(FX.matches, 'all');
  assert.equal(upcoming.length + results.length, FX.matches.length);
  assert.equal(results.length, 10);
  assert.equal(upcoming.length, 37);

  const first = upcoming[0];
  assert.equal(first.highlighted, true);
  assert.equal(first.href, '/match/5868098');
  assert.deepEqual(first.home, { id: 8633, name: 'Real Madrid' });
  assert.deepEqual(first.away, { id: 8302, name: 'Sevilla' });
  assert.equal(first.competition.short, 'ЛЛ');
  assert.equal(first.note, 'дома');
  assert.equal(first.live, undefined);
  assert.ok(upcoming.slice(1).every((m) => !m.highlighted));
  assert.equal(upcoming[1].competition.short, 'ЛЧ');
  assert.equal(upcoming[1].competition.tone, 'ucl');
  assert.equal(upcoming[2].note, 'в гостях'); // Barcelona — Real Madrid

  const r = results[0];
  assert.equal(r.href, '/match/6106274');
  assert.deepEqual(r.score, [3, 4]);
  assert.equal(r.result, 'W');
  assert.equal(results[2].result, 'L'); // Atlético Madrid 2:1
  for (let i = 1; i < results.length; i++) assert.ok(Date.parse(results[i - 1].kickoff) > Date.parse(results[i].kickoff));
});

test('Суперкубок — во «Все», с логотипом; во вкладках лиг его нет', () => {
  const all = splitFixtures(FX.matches, 'all').upcoming;
  const sc = all.find((m) => m.competition.id === 139)!;
  assert.ok(sc);
  assert.equal(sc.competition.name, 'Суперкубок Испании');
  assert.equal(sc.competition.withLogo, true);
  assert.deepEqual(competitionOf({ id: 138, name: 'Copa del Rey' }).withLogo, true);
  assert.ok(!splitFixtures(FX.matches, 'laliga').upcoming.some((m) => m.competition.id === 139));
  assert.ok(!splitFixtures(FX.matches, 'ucl').upcoming.some((m) => m.competition.id === 139));
});

test('вкладки Ла Лига / Лига чемпионов', () => {
  const ll = splitFixtures(FX.matches, 'laliga');
  const ucl = splitFixtures(FX.matches, 'ucl');
  assert.ok(ll.upcoming.every((m) => m.competition.id === LALIGA_ID));
  assert.ok(ucl.upcoming.every((m) => m.competition.id === UCL_ID));
  assert.equal(ll.upcoming.length + ll.results.length, 38);
  assert.equal(ucl.upcoming.length + ucl.results.length, 8);
  assert.equal(ucl.upcoming[0].highlighted, true);
  assert.equal(ucl.upcoming[0].away.name, 'RB Leipzig');
});

test('идущий матч в «Ближайших»: первым, в рамке, с минутой', () => {
  const m = structuredClone(FX.matches);
  const sev = m.find((x) => x.id === 5868098)!;
  sev.status = { state: 'live', live: true, finished: false, minute: 67, added: null };
  sev.home.score = 2;
  sev.away.score = 1;
  const { upcoming, results } = splitFixtures(m, 'all');
  assert.equal(upcoming[0].id, 5868098);
  assert.equal(upcoming[0].live, '67′');
  assert.equal(upcoming[0].highlighted, true);
  assert.ok(!results.some((r) => r.id === 5868098));
});

test('таблица Ла Лиги: строки, Реал, зоны', () => {
  const t = tableFor(TB.tables, LALIGA_ID)!;
  const rows = standingRows(t);
  assert.equal(rows.length, 20);
  assert.deepEqual(rows[3], { pos: 4, team: { id: 8633, name: 'Real Madrid' }, played: 8, goalsFor: 19, goalsAgainst: 8, points: 18 });
  assert.equal(usRow(t)!.team.id, 8633);
  assert.equal(roundsAside(t), 'после 8 туров');

  const zones = zonesFor(t);
  assert.deepEqual(zones[0], { from: 1, to: 4, color: 'var(--gold)', label: 'зона Лиги чемпионов' });
  assert.deepEqual(
    zones.map((z) => [z.from, z.to, z.label]),
    [
      [1, 4, 'зона Лиги чемпионов'],
      [5, 5, 'Лига Европы'],
      [6, 6, 'Лига конференций'],
      [18, 20, 'зона вылета'],
    ],
  );
});

test('длинная таблица: топ-4 и ±3 вокруг Реала, зоны — только видимые', () => {
  const t = tableFor(TB.tables, LALIGA_ID)!;
  const { rows, collapsed } = compactRows(standingRows(t), 4);
  assert.equal(collapsed, true);
  assert.deepEqual(rows.map((r) => r.pos), [1, 2, 3, 4, 5, 6, 7]);
  assert.ok(!zonesFor(t, rows).some((z) => z.label === 'зона вылета'));

  // Реал внизу — разрыв между топ-4 и окрестностью
  const far = compactRows(standingRows(t), 15);
  assert.deepEqual(far.rows.map((r) => r.pos), [1, 2, 3, 4, 12, 13, 14, 15, 16, 17, 18]);

  // короткая таблица не сворачивается
  assert.equal(compactRows(standingRows(t).slice(0, 8), 4).collapsed, false);
});

test('таблица ЛЧ есть в ответе — общий этап, 36 команд', () => {
  const t = tableFor(TB.tables, UCL_ID)!;
  assert.ok(t);
  assert.equal(t.rows.length, 36);
  assert.equal(usRow(t)!.pos, 8);
  const { rows, collapsed } = compactRows(standingRows(t), 8);
  assert.equal(collapsed, true);
  assert.deepEqual(rows.map((r) => r.pos), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
  assert.equal(zonesFor(t)[0].label, 'выход в 1/8 финала');
  assert.equal(tableFor([], UCL_ID), null);
});

test('идущий матч в календаре: LIVE, «Перерыв» в перерыве и текущий счёт', () => {
  const live = structuredClone(FX.matches);
  const f = live.find((m) => m.id === 5868098)!;
  f.status = { state: 'halftime', live: true, finished: false, minute: 45, added: null, label: 'HT' };
  f.home = { ...f.home, score: 2 };
  f.away = { ...f.away, score: 0 };
  const first = splitFixtures(live, 'all').upcoming[0];
  assert.equal(first.live, 'Перерыв');
  assert.deepEqual(first.score, [2, 0]);
  f.status = { state: 'live', live: true, finished: false, minute: 67, added: null, label: "67'" };
  assert.equal(splitFixtures(live, 'all').upcoming[0].live, '67′');
  // будущие — без счёта
  assert.equal(splitFixtures(live, 'all').upcoming[1].score, undefined);
});
