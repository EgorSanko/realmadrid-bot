// Карточка игрока: разбор ответа /api/player (фикстуры — ответы локального бэкенда на реальных данных FotMob).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  ageFromBirth,
  ageText,
  careerView,
  contractText,
  countryRu,
  deedsText,
  injuryNameRu,
  keyStats,
  moneyText,
  positionShort,
  positionsRu,
  recentView,
  seasonHead,
  seasonShort,
  seasonView,
  statusTitle,
  type ApiPlayer,
} from '../src/screens/player/playerData.ts';

const load = (n: string) => JSON.parse(readFileSync(new URL(`../src/__fixtures__/${n}`, import.meta.url), 'utf8')) as ApiPlayer;
const MBAPPE = load('player_701154.json');
const COURTOIS = load('player_170323.json');
const RODRYGO = load('player_895362.json');

test('позиции по-русски', () => {
  assert.equal(positionShort('ST'), 'НАП');
  assert.equal(positionShort('GK'), 'ВРТ');
  assert.equal(positionShort('DM'), 'ОП');
  assert.equal(positionShort('AM'), 'АП');
  assert.deepEqual(positionsRu(['ST', 'LW']), ['НАП', 'ЛВ']);
  assert.deepEqual(positionsRu(['LW', 'LM', 'RW']), ['ЛВ', 'ПВ']); // без повторов
  for (const c of ['GK', 'CB', 'RB', 'LB', 'DM', 'CM', 'AM', 'LW', 'RW', 'ST']) assert.ok(positionShort(c));
});

test('возраст со склонением и по дате рождения', () => {
  assert.equal(ageText(21), '21 год');
  assert.equal(ageText(22), '22 года');
  assert.equal(ageText(27), '27 лет');
  assert.equal(ageText(34), '34 года');
  assert.equal(ageFromBirth('1998-12-20', new Date('2026-10-17T00:00:00Z')), 27);
  assert.equal(ageFromBirth('1998-12-20', new Date('2026-12-20T00:00:00Z')), 28); // день рождения по МСК
});

test('деньги, контракт, страна', () => {
  assert.equal(moneyText(120694930), '€120,7 млн');
  assert.equal(moneyText(39970483), '€40 млн');
  assert.equal(moneyText(800000), '€800 тыс.');
  assert.equal(moneyText(null), null);
  assert.equal(contractText('2029-06-30'), 'до июня 2029');
  assert.equal(countryRu('gb-eng', 'England'), 'Англия');
  assert.equal(countryRu('fr', 'France'), 'Франция');
  assert.equal(countryRu(null, 'Kosovo'), 'Kosovo');
});

test('Mbappé: ключевые цифры и сезон по турнирам', () => {
  assert.equal(MBAPPE.name, 'Kylian Mbappé');
  const k = keyStats(MBAPPE);
  assert.deepEqual(k.map((x) => x.label), ['Матчи', 'Голы', 'Передачи', 'Оценка']);
  assert.equal(k[0].value, '10');
  assert.equal(k[1].value, '9');
  const s = seasonView(MBAPPE)!;
  assert.deepEqual(seasonHead(MBAPPE), ['И', 'Мин', 'Г', 'П', 'Оц']);
  assert.equal(s.rows[0].name, 'Ла Лига');
  assert.deepEqual(s.rows[0].cells, ['8', '720', '7', '2', '8.1']);
  assert.equal(s.rows[1].name, 'Лига чемпионов');
  assert.ok(s.total);
  assert.equal(seasonShort(MBAPPE.season!.name), '2026/27');
});

test('Mbappé: последние матчи — ссылка, счёт своей команды первым', () => {
  const r = recentView(MBAPPE);
  assert.ok(r.length >= 5 && r.length <= 10);
  const roma = r[0];
  assert.equal(roma.href, '/match/6106274');
  assert.equal(roma.opponent?.name, 'Roma');
  assert.equal(roma.venue, 'в гостях');
  assert.equal(roma.score, '4 : 3'); // Реал в гостях выиграл 4:3
  assert.equal(roma.result, 'W');
  assert.equal(roma.deeds, 'гол · 90′');
  assert.equal(deedsText({ goals: 2, assists: 1, yellow: 1, red: 0, minutes: 73 }), '2 гола, передача, жёлтая · 73′');
});

test('карьера: годы, аренда, матчи', () => {
  const c = careerView(MBAPPE.career);
  assert.equal(c[0].team?.name, 'Real Madrid');
  assert.equal(c[0].years, '2024 — н. в.');
  assert.ok(c[0].active);
  assert.match(c[0].stats ?? '', /^113 матчей · 95 голов$/);
  assert.ok(c.some((x) => x.loan));
});

test('вратарь: сухие и пропущенные вместо голов', () => {
  assert.deepEqual(keyStats(COURTOIS).map((x) => x.label), ['Матчи', 'Сухие', 'Пропущено', 'Оценка']);
  assert.deepEqual(seasonHead(COURTOIS), ['И', 'Мин', 'Сух', 'Проп', 'Оц']);
  const ll = seasonView(COURTOIS)!.rows[0];
  assert.equal(ll.cells[2], '2');
  assert.match(ll.note ?? '', /сейвы 25/);
});

test('травма: заголовок и название по-русски', () => {
  assert.ok(RODRYGO.status);
  assert.equal(statusTitle(RODRYGO.status!), 'Травма');
  assert.equal(injuryNameRu(RODRYGO.status!.name), 'разрыв крестообразной связки');
  assert.equal(statusTitle({ type: 'suspension', name: null, expected_return: null, updated: null }), 'Дисквалификация');
  assert.equal(injuryNameRu('Something odd'), null);
});
