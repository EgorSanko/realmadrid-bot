import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isMixedContent, linkError } from '../src/lib/linkCheck.ts';

test('корректные ссылки', () => {
  assert.equal(linkError('https://edge.example.org/hls/a/chunks.m3u8?nimblesessionid=1&token=x.y'), null);
  assert.equal(linkError('  http://a.org/x.m3u8  '), null);
});

test('ошибки ссылки', () => {
  assert.equal(linkError(''), 'Вставьте ссылку на трансляцию');
  assert.equal(linkError('ftp://a.org/x'), 'Ссылка должна начинаться с https://');
  assert.equal(linkError('a.org/x.m3u8'), 'Ссылка должна начинаться с https://');
  assert.equal(linkError('https://a.org/a b'), 'В ссылке не должно быть пробелов');
  assert.equal(linkError('https://a.org/' + 'a'.repeat(2000)), 'Ссылка длиннее 2000 символов');
  assert.notEqual(linkError('https://'), null);
});

test('смешанный контент', () => {
  assert.equal(isMixedContent('http://a.org/x.m3u8', 'https:'), true);
  assert.equal(isMixedContent('http://a.org/x.m3u8', 'http:'), false);
  assert.equal(isMixedContent('https://a.org/x.m3u8', 'https:'), false);
});
