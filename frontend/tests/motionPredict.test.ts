// Праздник точного счёта: какие строки «Моих прогнозов» праздновать. Запуск: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { exactToCelebrate, type HistoryItem } from '../src/lib/predict.ts';

const item = (id: string, kickoff: string, tone: HistoryItem['tone']): HistoryItem => ({
  id, kickoff, tone, home: { id: 1, name: 'A' }, away: { id: 2, name: 'B' }, pick: '1:0', result: '1:0', scorerPick: null, note: '', points: 5,
});
const NOW = Date.parse('2026-10-18T12:00:00Z');

test('празднуем только свежий точный счёт, один раз', () => {
  const items = [
    item('a', '2026-10-14T19:00:00Z', 'exact'),
    item('b', '2026-10-14T19:00:00Z', 'hit'),
    item('c', '2026-09-01T19:00:00Z', 'exact'), // давно — не новость
    item('d', '2026-10-19T19:00:00Z', 'exact'), // в будущем — не бывает, но не празднуем
  ];
  assert.deepEqual(exactToCelebrate(items, [], NOW), ['a']);
  assert.deepEqual(exactToCelebrate(items, ['a'], NOW), []);
});
