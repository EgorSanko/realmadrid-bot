// Экран матча, этап 3: вкладка «Онлайн» — лента «Ключевое» из наших событий и текстовая трансляция (EN).
// Запуск: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { normalizeMatch, type ApiCommentary, type ApiMatch } from '../src/api/match.ts';
import { commentaryRows, freshKeys, LONG_TEXT } from '../src/screens/match/feed.ts';
import { keyFeed } from '../src/screens/match/view.ts';

const read = (name: string) => JSON.parse(readFileSync(new URL(`../src/__fixtures__/${name}.json`, import.meta.url), 'utf8'));
const fx = (name: string): ApiMatch => normalizeMatch(read(name));

const LIVE = fx('match_5868098_live'); // 46′, 2:0, перерыв позади
const FIN = fx('match_6106274'); // Roma 3:4 Real Madrid
const UPCOMING = fx('match_5868098');
const CM: ApiCommentary = read('commentary_5868098');

test('ключевое: новые сверху, второй тайм после перерыва, начало матча внизу', () => {
  const f = keyFeed(LIVE);
  assert.deepEqual(
    f.map((x) => [x.kind, x.minute ?? '', x.title]),
    [
      ['sub', '46′', 'Замена'],
      ['second', '46′', 'Начался второй тайм'],
      ['half', '', 'Перерыв'],
      ['goal', '37′', 'Гол!'],
      ['goal', '30′', 'Гол!'],
      ['yellow', '23′', 'Жёлтая карточка'],
      ['yellow', '23′', 'Жёлтая карточка'],
      ['start', '1′', 'Начало матча'],
    ],
  );
  const g = f[3];
  assert.deepEqual(g.players.map((p) => [p.name, p.role ?? '']), [['Mbappé', ''], ['Bellingham', 'пас']]);
  assert.ok(Number.isInteger(g.players[0].id)); // фото — /img/player/{id}.png
  assert.equal(g.text, 'Real Madrid ведёт 2:0');
  assert.equal(g.side, 'home');
  assert.equal(g.team?.name, 'Real Madrid');
  assert.equal(f[2].text, 'Real Madrid 2:0 Sevilla');
  assert.equal(f[2].divider, true);
  assert.deepEqual(f[0].players.map((p) => [p.name, p.role]), [['Ejuke', 'вышел'], ['Vargas', 'ушёл']]);
  // ключи стабильны между опросами — иначе «новые» записи мигали бы
  assert.deepEqual(keyFeed(structuredClone(LIVE)).map((x) => x.key), f.map((x) => x.key));
});

test('ключевое: завершённый матч — «Матч завершён» сверху, счёт и автогол / сравнял', () => {
  const f = keyFeed(FIN);
  assert.equal(f[0].kind, 'end');
  assert.equal(f[0].text, 'Roma 3:4 Real Madrid');
  assert.equal(f[f.length - 1].kind, 'start');
  assert.ok(f.some((x) => x.kind === 'second'));
  const goals = f.filter((x) => x.kind === 'goal' || x.kind === 'own-goal');
  assert.equal(goals.length, 7);
  assert.ok(goals.some((x) => /^Счёт сравнялся/.test(x.text ?? '')) || goals.some((x) => /снова впереди/.test(x.text ?? '')));
  // ни одной английской подписи в заголовках
  for (const x of f) assert.match(x.title, /[А-ЯЁа-яё]/, x.title);
});

test('ключевое: до начала — пусто, в перерыве — без «второго тайма»', () => {
  assert.deepEqual(keyFeed(UPCOMING), []);
  const ht = structuredClone(LIVE);
  ht.status = { ...ht.status, state: 'halftime', minute: 45 };
  ht.events = ht.events.filter((e) => (e.minute ?? 0) <= 45);
  const f = keyFeed(ht);
  assert.equal(f[0].kind, 'half');
  assert.ok(!f.some((x) => x.kind === 'second'));
});

test('трансляция EN: заголовки по-русски, минуты, длинные тексты сворачиваются', () => {
  const rows = commentaryRows(CM.items);
  assert.equal(rows.length, 50);
  assert.equal(CM.attribution, 'Opta via FotMob');
  const goal = rows.find((r) => r.type === 'goal')!;
  assert.deepEqual([goal.title, goal.minute, goal.goal, goal.players[0].name], ['Гол!', '37′', true, 'Kylian Mbappé']);
  const chance = rows.find((r) => r.type === 'chance')!;
  assert.equal(chance.title, 'Опасный момент');
  const comment = rows.find((r) => r.type === 'comment' && r.minute)!;
  assert.equal(comment.title, undefined);
  const added = rows.find((r) => r.minute?.includes('+'))!;
  assert.equal(added.minute, '45+4′');
  assert.equal(rows.find((r) => r.type === 'summary')!.minute, undefined);
  assert.ok(rows.some((r) => r.long) && rows.every((r) => r.long === r.text.length > LONG_TEXT));
  assert.equal(rows[0].type, 'sub'); // новые первыми — как отдаёт сервер
});

test('новые записи: первый показ — без анимации, потом — только пришедшие', () => {
  const a = freshKeys(null, ['b', 'a']);
  assert.equal(a.fresh.size, 0);
  const b = freshKeys(a.seen, ['c', 'b', 'a']);
  assert.deepEqual([...b.fresh], ['c']);
  assert.equal(freshKeys(b.seen, ['c', 'b', 'a']).fresh.size, 0);
});
