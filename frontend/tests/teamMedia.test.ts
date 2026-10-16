// Запуск: npm test (node --test, типы снимает сам Node ≥ 23)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ageText, feeText, flagIso, positionRu, returnInfo, seasonLabel } from '../src/screens/team/teamData.ts';
import { dayMonthRu, highlightSubtitle, newsTime, videoSubtitle } from '../src/screens/media/mediaData.ts';

const NOW = new Date('2026-10-17T00:00:00Z');

test('возраст с правильным склонением', () => {
  assert.equal(ageText(21), '21 год');
  assert.equal(ageText(23), '23 года');
  assert.equal(ageText(27), '27 лет');
  assert.equal(ageText(11), '11 лет');
  assert.equal(ageText(34), '34 года');
  assert.equal(ageText(null), null);
});

test('позиция по-русски с учётом линии', () => {
  assert.equal(positionRu('GK', 'goalkeepers'), 'ВРТ');
  assert.equal(positionRu('CB,RB', 'defenders'), 'ЦЗ');
  assert.equal(positionRu('LB,LM,LWB', 'defenders'), 'ЛЗ');
  assert.equal(positionRu('RB,RM', 'defenders'), 'ПЗ');
  assert.equal(positionRu('CAM,CM,LM', 'midfielders'), 'АП');
  assert.equal(positionRu('CDM,CM,LM,LB', 'midfielders'), 'ОП');
  assert.equal(positionRu('RB,RM,CDM,CM,RW,CAM', 'midfielders'), 'ОП');
  assert.equal(positionRu('LW,ST', 'attackers'), 'ЛВ');
  assert.equal(positionRu('ST,LW', 'attackers'), 'НАП');
  assert.equal(positionRu('RW,ST,RM,LM', 'attackers'), 'ПВ');
  assert.equal(positionRu(null), null);
});

test('срок возвращения из лазарета', () => {
  assert.deepEqual(
    { ...returnInfo('Late October 2026', NOW), date: undefined },
    { text: 'конец октября', back: false, past: false, date: undefined },
  );
  assert.equal(returnInfo('Early January 2027', NOW).text, 'начало января');
  assert.equal(returnInfo('Mid March 2028', NOW).text, 'середина марта 2028');
  const back = returnInfo('Back in training', NOW);
  assert.equal(back.back, true);
  assert.equal(back.text, 'вернулся в общую группу');
  assert.equal(returnInfo('Early October 2026', NOW).past, true);
  assert.equal(returnInfo('2026-11-02', NOW).text, 'до 2 ноября');
  assert.equal(returnInfo(null, NOW).text, 'срок неизвестен');
  assert.equal(returnInfo('Something odd', NOW).text, 'срок уточняется');
});

test('сумма трансфера', () => {
  assert.equal(feeText({ fee_text: 'fee', fee_eur: 125000000, loan: false }), '€125 млн');
  assert.equal(feeText({ fee_text: 'fee', fee_eur: 2500000, loan: false }), '€2,5 млн');
  assert.equal(feeText({ fee_text: 'fee', fee_eur: 500000, loan: false }), '€500 тыс.');
  assert.equal(feeText({ fee_text: 'on loan', fee_eur: null, loan: true }), 'аренда');
  assert.equal(feeText({ fee_text: 'free transfer', fee_eur: null, loan: false }), 'бесплатно');
  assert.equal(feeText({ fee_text: null, fee_eur: null, loan: false }), null);
});

test('сезон, флаг', () => {
  assert.equal(seasonLabel(NOW), '2026/27');
  assert.equal(seasonLabel(new Date('2027-03-01T00:00:00Z')), '2026/27');
  assert.equal(flagIso('/img/flag/gb-eng.svg'), 'gb-eng');
  assert.equal(flagIso('/img/flag/be.svg'), 'be');
  assert.equal(flagIso('https://evil/x.svg'), null);
});

test('время новостей и подписи видео по МСК', () => {
  assert.equal(newsTime('2026-10-16T23:59:30Z', NOW), 'только что');
  assert.equal(newsTime('2026-10-16T23:48:00Z', NOW), '12 мин назад');
  assert.equal(newsTime('2026-10-16T21:00:00Z', NOW), '3 ч назад');
  assert.equal(newsTime('2026-10-16T16:40:00Z', NOW), 'вчера, 19:40'); // NOW = 03:00 МСК 17-го
  assert.equal(newsTime('2026-10-14T15:30:00Z', NOW), '14 октября, 18:30');
  assert.equal(dayMonthRu('2026-10-14T21:30:00Z'), '15 октября'); // после полуночи по МСК
  assert.equal(videoSubtitle({ short: true, channel: 'Real Madrid' }), 'Shorts · Real Madrid');
  assert.equal(videoSubtitle({ short: false, channel: 'Real Madrid' }), 'Real Madrid · YouTube');
  assert.equal(
    highlightSubtitle({ tournament: { id: 42, name: 'Champions League' }, kickoff: '2026-10-14T19:00:00Z' }),
    'Лига чемпионов · 14 октября',
  );
});

test('фикстура /api/team разбирается', () => {
  const t = JSON.parse(readFileSync(new URL('../src/__fixtures__/team.json', import.meta.url), 'utf8'));
  assert.equal(t.coach.name, 'José Mourinho');
  assert.ok(t.available.includes('squad'));
  for (const p of t.squad.defenders) assert.ok(positionRu(p.position, 'defenders'));
});
