// Главная: реальный ответ /api/home (src/__fixtures__/home.json) → пропсы компонентов.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import type { ApiFixture, ApiHome } from '../src/lib/api.ts';
import {
  JUST_FINISHED_MS,
  errorText,
  formResults,
  heroOf,
  homePollMs,
  lastMatchOf,
  leagueSummary,
  staleNote,
} from '../src/lib/mapMatches.ts';

const load = <T>(name: string): T => JSON.parse(readFileSync(new URL(`../src/__fixtures__/${name}`, import.meta.url), 'utf8')) as T;
const HOME = load<ApiHome>('home.json');
const clone = <T>(x: T): T => structuredClone(x);
// снимок сделан 16.10.2026 ~22:53 UTC: до Real Madrid — Sevilla (18.10 19:00 UTC) почти двое суток
const SNAP_NOW = Date.parse('2026-10-16T22:53:00Z');

test('ближайший матч до начала: турнир, команды, время, стадион', () => {
  const h = heroOf(HOME, SNAP_NOW)!;
  assert.equal(h.status, 'upcoming');
  assert.equal(h.id, 5868098);
  assert.equal(h.href, '/match/5868098');
  assert.deepEqual(h.competition, { id: 87, name: 'Ла Лига', short: 'ЛЛ', tone: 'gold' });
  assert.deepEqual(h.home, { id: 8633, name: 'Real Madrid' });
  assert.deepEqual(h.away, { id: 8302, name: 'Sevilla' });
  assert.equal(h.kickoff, '2026-10-18T19:00:00Z');
  assert.equal(h.score, undefined);
  assert.equal(h.minute, undefined);
  assert.equal(h.venue, 'Estadio Bernabéu, Madrid');
});

test('матч идёт: счёт, минута, тайм', () => {
  const d = clone(HOME);
  const n = d.next as ApiFixture;
  n.status = { state: 'live', live: true, finished: false, minute: 67, added: null, label: "67'" };
  n.home.score = 2;
  n.away.score = 1;
  const h = heroOf(d, SNAP_NOW)!;
  assert.equal(h.status, 'live');
  assert.deepEqual(h.score, [2, 1]);
  assert.equal(h.minute, '67′');
  assert.equal(h.period, '2-й тайм');
  assert.equal(homePollMs(d, SNAP_NOW), 10_000);

  n.status = { state: 'live', live: true, finished: false, minute: 45, added: 2, label: null };
  assert.equal(heroOf(d, SNAP_NOW)!.minute, '45+2′');
  assert.equal(heroOf(d, SNAP_NOW)!.period, '1-й тайм');

  n.status = { state: 'halftime', live: true, finished: false, minute: 45, added: null, label: 'HT' };
  assert.equal(heroOf(d, SNAP_NOW)!.minute, 'Перерыв');

  // счёт ещё не пришёл — 0 : 0, а не пусто
  n.home.score = null;
  n.away.score = null;
  assert.deepEqual(heroOf(d, SNAP_NOW)!.score, [0, 0]);
});

test('матч завершён: пока API отдаёт его как last — сверху итог, потом снова ближайший', () => {
  // last = Roma 3:4 Real Madrid, начало 14.10 19:00 UTC
  const ko = Date.parse(HOME.last!.kickoff);
  const justAfter = ko + 2 * 3600_000;
  const h = heroOf(HOME, justAfter)!;
  assert.equal(h.status, 'finished');
  assert.equal(h.id, 6106274);
  assert.deepEqual(h.score, [3, 4]);
  assert.deepEqual(h.competition, { id: 42, name: 'Лига чемпионов', short: 'ЛЧ', tone: 'ucl' });
  // через 4 ч после начала карточка возвращается к ближайшему матчу
  assert.equal(heroOf(HOME, ko + JUST_FINISHED_MS + 1)!.status, 'upcoming');
  // идущий матч важнее итога
  const d = clone(HOME);
  d.next!.status = { state: 'live', live: true, finished: false, minute: 3, added: null };
  assert.equal(heroOf(d, justAfter)!.status, 'live');
});

test('прошлый матч → MatchCard finished', () => {
  const l = lastMatchOf(HOME)!;
  assert.equal(l.status, 'finished');
  assert.equal(l.href, '/match/6106274');
  assert.deepEqual(l.home, { id: 8686, name: 'Roma' });
  assert.deepEqual(l.away, { id: 8633, name: 'Real Madrid' });
  assert.deepEqual(l.score, [3, 4]);
  assert.equal(l.competition.name, 'Лига чемпионов');
});

test('форма: 5 матчей, последний слева', () => {
  // API: от нового к старому — W(Roma) W(Villarreal) L(Atlético) W(Elche) W(Rayo)
  assert.deepEqual(formResults(HOME), ['W', 'W', 'L', 'W', 'W']);
  const d = clone(HOME);
  d.form[0].result = 'D';
  assert.deepEqual(formResults(d), ['D', 'W', 'L', 'W', 'W']);
});

test('место в Ла Лиге: «4 место · 18 очк., −6 до лидера»', () => {
  assert.deepEqual(leagueSummary(HOME), { pos: 4, line: 'место · 18 очк.', gap: '−6 до лидера' });
  const d = clone(HOME);
  d.laliga = { ...d.laliga!, pos: 1, pts: 24 };
  assert.equal(leagueSummary(d)!.gap, 'лидер');
  d.laliga = null;
  assert.equal(leagueSummary(d), null);
});

test('опрос: 30 с обычно, 10 с перед стартом и во время матча', () => {
  assert.equal(homePollMs(HOME, SNAP_NOW), 30_000);
  const ko = Date.parse(HOME.next!.kickoff);
  assert.equal(homePollMs(HOME, ko - 60_000), 10_000);
  assert.equal(homePollMs(HOME, ko + 3600_000), 10_000);
  assert.equal(homePollMs(null), 30_000);
});

test('stale: подпись только когда stale и старше 15 минут', () => {
  assert.equal(staleNote(HOME), null); // реальный снимок свежий: age 420 c, stale=false
  assert.equal(staleNote({ ...HOME, stale: true, age_s: 600 }), null);
  assert.equal(staleNote({ ...HOME, stale: true, age_s: 17 * 60 + 5 }), 'обновлено 17 мин назад');
  assert.equal(staleNote({ ...HOME, stale: true, age_s: 3 * 3600 }), 'обновлено 3 ч назад');
  assert.equal(staleNote({ ...HOME, stale: false, age_s: 3 * 3600 }), null);
  // возраст растёт, пока ответ лежит в клиенте
  assert.equal(staleNote({ ...HOME, stale: true, age_s: 14 * 60 }, 120), 'обновлено 16 мин назад');
});

test('нет данных (503) и нет сети — понятные тексты', () => {
  assert.equal(errorText({ status: 503 }).title, 'Данные ещё собираются');
  assert.equal(errorText({ status: 0 }).title, 'Нет соединения');
  assert.equal(errorText({ status: 500 }).title, 'Не удалось загрузить');
});

test('нет ни next, ни last — пустые карточки, без падений', () => {
  const d: ApiHome = { ...clone(HOME), next: null, last: null, form: [], laliga: null };
  assert.equal(heroOf(d, SNAP_NOW), null);
  assert.equal(lastMatchOf(d), null);
  assert.deepEqual(formResults(d), []);
});
