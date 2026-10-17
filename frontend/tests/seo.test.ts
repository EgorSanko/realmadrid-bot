import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SITE_ORIGIN, canonicalFor, descriptionFor } from '../src/lib/seo.ts';

test('канонический адрес — домен без www, без вкладок матча и хвостового слэша', () => {
  assert.equal(SITE_ORIGIN, 'https://realmadridfan.ru');
  assert.equal(canonicalFor('/'), 'https://realmadridfan.ru/');
  assert.equal(canonicalFor('/matches/'), 'https://realmadridfan.ru/matches');
  assert.equal(canonicalFor('/match/6106274/lineups'), 'https://realmadridfan.ru/match/6106274');
  assert.equal(canonicalFor('/match/6106274/stats/'), 'https://realmadridfan.ru/match/6106274');
  assert.equal(canonicalFor('//news//abc'), 'https://realmadridfan.ru/news/abc');
});

test('у каждого раздела своё описание', () => {
  const paths = ['/', '/matches', '/match/1', '/team', '/player/1', '/media', '/news/a', '/video/b', '/predict', '/profile'];
  const all = paths.map(descriptionFor);
  assert.equal(new Set(all).size, paths.length);
  for (const d of all) assert.ok(d.length > 50 && d.length < 200, d);
  assert.equal(descriptionFor('/неизвестно'), descriptionFor('/'));
});
