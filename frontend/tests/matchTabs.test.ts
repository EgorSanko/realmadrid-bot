// Вкладки экрана матча и их адрес (?tab= на компьютере, хвост пути на телефоне). Запуск: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MOBILE_TABS, deskTabHref, mobileTabHref, pickTab, tabFromLocation } from '../src/screens/match/matchTabs.ts';

test('вкладка из адреса: ?tab= важнее пути, неизвестное — обзор', () => {
  assert.equal(tabFromLocation('/match/1', ''), 'overview');
  assert.equal(tabFromLocation('/match/1', '?tab=stats'), 'stats');
  assert.equal(tabFromLocation('/match/1', '?tab=table'), 'table');
  assert.equal(tabFromLocation('/match/1', '?tab=h2h'), 'h2h');
  assert.equal(tabFromLocation('/match/1/lineups', ''), 'lineups');
  assert.equal(tabFromLocation('/match/1/online/', ''), 'online');
  assert.equal(tabFromLocation('/match/1/lineups', '?tab=stats'), 'stats');
  assert.equal(tabFromLocation('/match/1', '?tab=nope'), 'overview');
  assert.equal(tabFromLocation('/match/1/table', ''), 'overview');
});

test('адрес вкладки: компьютер — ?tab=, телефон — путь; прочие параметры остаются', () => {
  assert.equal(deskTabHref('42', 'stats'), '/match/42?tab=stats');
  assert.equal(deskTabHref('42', 'overview', '?tab=stats'), '/match/42');
  assert.equal(deskTabHref('42', 'table', '?utm=x'), '/match/42?utm=x&tab=table');
  assert.equal(mobileTabHref('42', 'online', '?tab=stats'), '/match/42/online');
  assert.equal(mobileTabHref('42', 'overview'), '/match/42');
  // «Турнир» на телефоне — часть обзора
  assert.equal(mobileTabHref('42', 'table'), '/match/42');
  for (const t of ['overview', 'lineups', 'stats', 'online', 'table', 'h2h'] as const) {
    const u = new URL(deskTabHref('42', t), 'https://x');
    assert.equal(tabFromLocation(u.pathname, u.search), t);
  }
});

test('вкладка без данных не выбирается', () => {
  assert.equal(pickTab('h2h', ['overview', 'stats']), 'overview');
  assert.equal(pickTab('stats', ['overview', 'stats']), 'stats');
  assert.equal(pickTab('table', MOBILE_TABS), 'overview');
});
