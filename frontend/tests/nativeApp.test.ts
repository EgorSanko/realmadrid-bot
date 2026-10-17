import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isNativeAppUa } from '../src/lib/shell.ts';
import { descriptionFor } from '../src/lib/seo.ts';

const APP_UA =
  'Mozilla/5.0 (Linux; Android 15; sdk_gphone64_x86_64 Build/AP3A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.6367.219 Mobile Safari/537.36 MadridistaApp/1.0 (Android; RuStore)';

test('приложение из RuStore узнаётся по User-Agent', () => {
  assert.equal(isNativeAppUa(APP_UA), true);
  assert.equal(isNativeAppUa('MadridistaApp/2.3.1'), true);
});

test('обычные браузеры, WebView Telegram и пустой UA — не приложение', () => {
  for (const ua of [
    'Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 14; wv) AppleWebKit/537.36 Version/4.0 Chrome/124.0 Mobile Safari/537.36 Telegram-Android/11.2',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1',
    'NotMadridistaApp/1.0',
    'MadridistaApp/',
    '',
    null,
    undefined,
  ]) {
    assert.equal(isNativeAppUa(ua), false, String(ua));
  }
});

test('у политики и условий свои описания', () => {
  const p = descriptionFor('/privacy');
  const t = descriptionFor('/terms');
  assert.notEqual(p, t);
  assert.notEqual(p, descriptionFor('/'));
  for (const d of [p, t]) assert.ok(d.length > 50 && d.length < 200, d);
});
