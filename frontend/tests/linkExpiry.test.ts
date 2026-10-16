// Запуск: npm test (node --test, типы снимает сам Node ≥ 23)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { describeExpiry, formatMsk, linkExpiry } from '../src/lib/linkExpiry.ts';

const b64url = (o: object) =>
  Buffer.from(JSON.stringify(o)).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

const nimble = (payload: object) =>
  `https://edge1.hayuhi.online/hls/fut2/chunks.m3u8?nimblesessionid=160194540&token=${b64url(payload)}.SiGn_-x`;

const EXAMPLE = nimble({ ch: 'fut2', edge: 'bulbikjoe', sid: 'abc', exp: 1789521902 });

test('exp из token ссылки Nimble', () => {
  assert.equal(linkExpiry(EXAMPLE)?.toISOString(), '2026-09-16T01:25:02.000Z');
});

test('время по Москве', () => {
  const at = linkExpiry(EXAMPLE)!;
  assert.equal(formatMsk(at, at), '04:25');
  assert.equal(formatMsk(at, new Date('2026-09-14T12:00:00Z')), '16.09 04:25');
});

test('уровни предупреждения', () => {
  const at = new Date(1789521902 * 1000);
  assert.equal(describeExpiry(EXAMPLE, new Date(at.getTime() - 3 * 3600e3))?.level, 'ok');
  assert.equal(describeExpiry(EXAMPLE, new Date(at.getTime() - 3 * 3600e3))?.text, 'Ссылка действует до 04:25 (МСК)');
  assert.equal(describeExpiry(EXAMPLE, new Date(at.getTime() - 10 * 60e3))?.level, 'soon');
  assert.equal(describeExpiry(EXAMPLE, new Date(at.getTime() + 60e3))?.level, 'expired');
});

test('не разобрали — null', () => {
  for (const u of [
    'https://a.org/x.m3u8',
    'https://a.org/x.m3u8?token=abc.def',
    'https://a.org/x.m3u8?token=%%%',
    nimble({ ch: 'x' }),
    nimble({ exp: 'soon' }),
    'не ссылка',
    '',
  ]) {
    assert.equal(linkExpiry(u), null, u);
    assert.equal(describeExpiry(u), null, u);
  }
});
