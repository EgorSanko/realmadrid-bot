import { test } from 'node:test';
import assert from 'node:assert/strict';
import { applyLang, langFromCode, t } from '../src/lib/i18n.ts';
import { formatKickoff, plural } from '../src/ui/format.ts';
import en from '../src/i18n/en/index.ts';

test('язык по коду Telegram/браузера: русский для ru и близких, остальным — английский', () => {
  assert.deepEqual(['ru', 'uk-UA', 'kk', 'en-US', 'pt_BR', 'es', '', null].map(langFromCode), ['ru', 'ru', 'ru', 'en', 'en', 'en', null, null]);
});

test('t(): русский — как есть, английский — из словаря, нет строки — русский; подстановки', () => {
  applyLang('ru');
  assert.equal(t('Ты {n}-й', { n: 3 }), 'Ты 3-й');
  applyLang('en', { 'Ты {n}-й': 'You are #{n}', 'матч|матча|матчей': 'match|matches' });
  try {
    assert.equal(t('Ты {n}-й', { n: 3 }), 'You are #3');
    assert.equal(t('Нет перевода'), 'Нет перевода');
    assert.deepEqual([1, 2, 5].map((n) => plural(n, ['матч', 'матча', 'матчей'])), ['match', 'matches', 'matches']);
    assert.equal(formatKickoff('2026-10-25T20:00:00Z'), 'Sun, 25 October · 23:00 MSK');
  } finally {
    applyLang('ru');
  }
  assert.equal(formatKickoff('2026-10-25T20:00:00Z'), 'Вс, 25 октября · 23:00 МСК');
});

test('словарь: у каждой строки те же подстановки {имя}, что в русском ключе', () => {
  const names = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(',');
  const bad = Object.entries(en).filter(([ru, tr]) => !ru.includes('|') && names(ru) !== names(tr));
  assert.deepEqual(bad, []);
});
