import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  DEVICE_KEY,
  SENT_KEY,
  _resetVisit,
  detectPlatform,
  deviceId,
  isDeviceId,
  localDay,
  reportVisit,
  shouldSend,
} from '../src/lib/visit.ts';
import type { KV } from '../src/lib/visit.ts';

class Mem implements KV {
  m = new Map<string, string>();
  getItem(k: string) {
    return this.m.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.m.set(k, v);
  }
}

class Broken implements KV {
  getItem(): string | null {
    throw new Error('SecurityError');
  }
  setItem(): void {
    throw new Error('SecurityError');
  }
}

function okFetch(calls: { url: string; body: unknown; headers: Record<string, string> }[], status = 200) {
  return (async (url: string, init: RequestInit) => {
    calls.push({ url, body: JSON.parse(String(init.body)), headers: init.headers as Record<string, string> });
    return new Response('{"ok":true}', { status });
  }) as unknown as typeof fetch;
}

beforeEach(() => _resetVisit());

test('платформа: initData → tg, приложение RuStore → android, иначе web', () => {
  assert.equal(detectPlatform(true, false), 'tg');
  assert.equal(detectPlatform(true, true), 'tg');
  assert.equal(detectPlatform(false, true), 'android');
  assert.equal(detectPlatform(false, false), 'web');
});

test('местная дата и правило «раз в день»', () => {
  assert.equal(localDay(new Date(2026, 0, 5, 23, 59)), '2026-01-05');
  assert.equal(shouldSend(null, '2026-10-20'), true);
  assert.equal(shouldSend('2026-10-19', '2026-10-20'), true);
  assert.equal(shouldSend('2026-10-20', '2026-10-20'), false);
});

test('id устройства: создаётся один раз и подходит серверу', () => {
  const s = new Mem();
  const a = deviceId(s);
  assert.ok(isDeviceId(a));
  assert.equal(deviceId(s), a);
  assert.equal(s.getItem(DEVICE_KEY), a);
  s.setItem(DEVICE_KEY, '<bad>');
  assert.notEqual(deviceId(s), '<bad>');
});

test('без хранилища — id в памяти, один на сессию', () => {
  const a = deviceId(new Broken());
  assert.ok(isDeviceId(a));
  assert.equal(deviceId(null), a);
});

test('отметка уходит раз в день и одна за открытие', async () => {
  const s = new Mem();
  const calls: { url: string; body: unknown; headers: Record<string, string> }[] = [];
  const now = new Date(2026, 9, 20, 12);
  assert.equal(await reportVisit('web', { Authorization: 'Session x' }, { store: s, now, fetchFn: okFetch(calls) }), true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/visit');
  assert.deepEqual(calls[0].body, { device: s.getItem(DEVICE_KEY), platform: 'web' });
  assert.equal(calls[0].headers.Authorization, 'Session x');
  assert.equal(s.getItem(SENT_KEY), '2026-10-20');

  _resetVisit(); // «новое открытие» в тот же день — не шлём
  assert.equal(await reportVisit('web', {}, { store: s, now, fetchFn: okFetch(calls) }), false);
  assert.equal(calls.length, 1);

  _resetVisit(); // на следующий день — снова
  const next = new Date(2026, 9, 21, 0, 5);
  assert.equal(await reportVisit('web', {}, { store: s, now: next, fetchFn: okFetch(calls) }), true);
  assert.equal(calls.length, 2);
});

test('ошибка сети или сервера — без повторов в этой сессии и без исключений', async () => {
  const s = new Mem();
  const calls: { url: string; body: unknown; headers: Record<string, string> }[] = [];
  const now = new Date(2026, 9, 20, 12);
  const failing = (async () => {
    throw new TypeError('Failed to fetch');
  }) as unknown as typeof fetch;
  assert.equal(await reportVisit('tg', {}, { store: s, now, fetchFn: failing }), false);
  assert.equal(s.getItem(SENT_KEY), null);
  assert.equal(await reportVisit('tg', {}, { store: s, now, fetchFn: okFetch(calls) }), false); // та же сессия
  assert.equal(calls.length, 0);

  _resetVisit();
  assert.equal(await reportVisit('tg', {}, { store: s, now, fetchFn: okFetch(calls, 429) }), false);
  assert.equal(s.getItem(SENT_KEY), null);
});

test('хранилище недоступно — запрос всё равно уходит и не падает', async () => {
  const calls: { url: string; body: unknown; headers: Record<string, string> }[] = [];
  const ok = await reportVisit('android', {}, { store: new Broken(), now: new Date(), fetchFn: okFetch(calls) });
  assert.equal(ok, true);
  assert.equal(calls.length, 1);
  assert.ok(isDeviceId((calls[0].body as { device: string }).device));
});
