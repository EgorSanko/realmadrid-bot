// Вход по коду: формат кода и отсчёта, генератор QR (структура; декодирование проверено OpenCV — см. отчёт).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { countdown, spacedCode } from '../src/lib/codeFormat.ts';
import { encodeQr, qrPath } from '../src/lib/qr.ts';

const LINK = 'https://t.me/Real_Madrid_football_bot?start=login_Ab3_-xYz9QwErTy0UiOpLk';

test('код показывается группами по три цифры', () => {
  assert.equal(spacedCode('012345'), '012 345');
  assert.equal(spacedCode('12'), '12');
});

test('обратный отсчёт м:сс, не уходит в минус', () => {
  assert.equal(countdown(300_000), '5:00');
  assert.equal(countdown(61_500), '1:02');
  assert.equal(countdown(999), '0:01');
  assert.equal(countdown(-5000), '0:00');
});

function finderAt(m: boolean[][], x0: number, y0: number): boolean {
  for (let y = 0; y < 7; y++)
    for (let x = 0; x < 7; x++) {
      const ring = Math.max(Math.abs(x - 3), Math.abs(y - 3));
      if (m[y0 + y][x0 + x] !== (ring !== 2)) return false;
    }
  return true;
}

test('QR ссылки входа: версия 5 (37×37), три поисковых узора, тайминг', () => {
  const q = encodeQr(LINK);
  assert.equal(q.size, 37);
  assert.equal(q.modules.length, 37);
  assert.ok(finderAt(q.modules, 0, 0));
  assert.ok(finderAt(q.modules, q.size - 7, 0));
  assert.ok(finderAt(q.modules, 0, q.size - 7));
  for (let i = 8; i < q.size - 8; i++) {
    assert.equal(q.modules[6][i], i % 2 === 0);
    assert.equal(q.modules[i][6], i % 2 === 0);
  }
  assert.equal(q.modules[q.size - 8][8], true); // «тёмный модуль»
});

test('QR детерминирован и растёт с длиной; слишком длинный текст — ошибка', () => {
  assert.deepEqual(encodeQr(LINK), encodeQr(LINK));
  assert.equal(encodeQr('hi').size, 21);
  assert.equal(encodeQr('x'.repeat(150)).size, 49);
  assert.throws(() => encodeQr('x'.repeat(300)));
});

test('SVG-путь — по квадрату на тёмный модуль, с полем', () => {
  const q = encodeQr('hi');
  const dark = q.modules.flat().filter(Boolean).length;
  const d = qrPath(q);
  assert.equal((d.match(/M/g) ?? []).length, dark);
  assert.ok(d.startsWith('M4 4h1v1h-1z'));
});
