// Английский интерфейс «Команды», карточки игрока и «Медиа»: чистые функции и полнота словаря.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { applyLang } from '../src/lib/i18n.ts';
import en from '../src/i18n/en/index.ts';
import { ageText, feeText, positionRu, returnInfo } from '../src/screens/team/teamData.ts';
import {
  careerView,
  contractText,
  countryRu,
  dateLong,
  deedsText,
  footRu,
  injuryNameRu,
  keyStats,
  moneyText,
  positionsRu,
  roleRu,
  seasonHead,
  statusTitle,
  tournamentRu,
  type ApiPlayer,
} from '../src/screens/player/playerData.ts';
import { dayMonthRu, findVideo, highlightSubtitle, newsTime, readingTime, type VideosResponse } from '../src/screens/media/mediaData.ts';

const NOW = new Date('2026-10-17T00:00:00Z');

function inEnglish(fn: () => void) {
  applyLang('en', en);
  try {
    fn();
  } finally {
    applyLang('ru');
  }
}

test('«Команда» по-английски: возраст, позиции, сроки возвращения, суммы', () => {
  inEnglish(() => {
    assert.equal(ageText(21), '21 years');
    assert.equal(ageText(1), '1 year');
    assert.equal(positionRu('CB,RB', 'defenders'), 'CB');
    assert.equal(positionRu('RB,RM,CDM,CM,RW,CAM', 'midfielders'), 'DM');
    assert.equal(positionRu('LW,ST', 'attackers'), 'LW');
    assert.equal(returnInfo('Late November 2026', NOW).text, 'late November');
    assert.equal(returnInfo('Back in training', NOW).text, 'back in training');
    assert.equal(returnInfo('2026-11-12', NOW).text, 'until 12 November');
    assert.equal(returnInfo(null, NOW).text, 'return date unknown');
    assert.equal(feeText({ fee_text: null, fee_eur: 2_500_000, loan: false }), '€2.5m');
    assert.equal(feeText({ fee_text: null, fee_eur: 500_000, loan: false }), '€500k');
    assert.equal(feeText({ fee_text: 'on loan', fee_eur: null, loan: true }), 'loan');
  });
  // русский не изменился
  assert.equal(ageText(21), '21 год');
  assert.equal(feeText({ fee_text: null, fee_eur: 2_500_000, loan: false }), '€2,5 млн');
  assert.equal(returnInfo('Late November 2026', NOW).text, 'конец ноября');
});

test('карточка игрока по-английски: данные источника вместо русских подстановок', () => {
  const p = {
    role: 'FW',
    season: { totals: { matches: 10, goals: 7, assists: 3, rating: 7.8, minutes: 800, yellow: 1, red: 0 } },
  } as unknown as ApiPlayer;
  inEnglish(() => {
    assert.deepEqual(positionsRu(['LW', 'LM', 'ST']), ['LW', 'ST']);
    assert.equal(roleRu('FW'), 'Forward');
    assert.equal(dateLong('1998-12-20'), '20 December 1998');
    assert.equal(contractText('2029-06-30'), 'June 2029');
    assert.equal(footRu('left'), 'left');
    assert.equal(moneyText(120_694_930), '€120.7m');
    assert.equal(countryRu('fr', 'France'), 'France');
    assert.equal(countryRu('gb-eng', null), 'England');
    assert.equal(injuryNameRu('Hamstring Injury'), 'Hamstring Injury');
    assert.equal(statusTitle({ type: 'suspension', name: null, expected_return: null, updated: null }), 'Suspension');
    assert.equal(tournamentRu({ id: 87, name: 'LaLiga' }), 'LaLiga');
    assert.equal(tournamentRu({ id: 42, name: null }), 'Champions League');
    assert.deepEqual(keyStats(p).map((s) => s.label), ['Matches', 'Goals', 'Assists', 'Rating']);
    assert.deepEqual(seasonHead(p), ['Apps', 'Min', 'G', 'A', 'Rtg']);
    assert.equal(deedsText({ goals: 2, assists: 1, yellow: 1, red: 0, minutes: 90 }), '2 goals, assist, yellow card · 90′');
    assert.equal(careerView([{ team: null, start: '2018-07-01', end: null, active: true, loan: false, apps: 113, goals: 1 }])[0].stats, '113 matches · 1 goal');
  });
  assert.equal(roleRu('FW'), 'Нападающий');
  assert.equal(tournamentRu({ id: 87, name: 'LaLiga' }), 'Ла Лига');
  assert.deepEqual(keyStats(p).map((s) => s.label), ['Матчи', 'Голы', 'Передачи', 'Оценка']);
});

test('«Медиа» по-английски: время новости, подписи, обзор матча', () => {
  const vids = {
    items: [],
    highlights: [{ match_id: 1, video_id: 'abcdefghijk', title: 'Roma 3:4 Real Madrid', kickoff: '2026-10-14T19:00:00Z', tournament: { id: 42, name: 'Champions League' } }],
  } as unknown as VideosResponse;
  inEnglish(() => {
    assert.equal(newsTime('2026-10-16T23:59:30Z', NOW), 'just now');
    assert.equal(newsTime('2026-10-16T23:48:00Z', NOW), '12 min ago');
    assert.equal(newsTime('2026-10-16T21:00:00Z', NOW), '3h ago');
    assert.equal(newsTime('2026-10-16T15:40:00Z', NOW), 'yesterday, 18:40');
    assert.equal(newsTime('2026-10-14T15:30:00Z', NOW), '14 October, 18:30');
    assert.equal(readingTime(400), '2 min read');
    assert.equal(dayMonthRu('2026-10-14T19:00:00Z'), '14 October');
    assert.equal(highlightSubtitle({ tournament: { id: 42, name: 'Champions League' }, kickoff: '2026-10-14T19:00:00Z' }), 'Champions League · 14 October');
    assert.equal(findVideo(vids, 'abcdefghijk')?.title, 'Highlights: Roma 3:4 Real Madrid');
  });
  assert.equal(newsTime('2026-10-16T23:48:00Z', NOW), '12 мин назад');
  assert.equal(findVideo(vids, 'abcdefghijk')?.title, 'Обзор матча: Roma 3:4 Real Madrid');
});

/** Все файлы раздела: экраны team/player/media и их навигация. */
function sources(): string[] {
  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((n) => {
      const p = join(dir, n);
      return statSync(p).isDirectory() ? walk(p) : /\.tsx?$/.test(n) ? [p] : [];
    });
  const base = fileURLToPath(new URL('../src/', import.meta.url));
  return [
    ...walk(join(base, 'screens/team')),
    ...walk(join(base, 'screens/player')),
    ...walk(join(base, 'screens/media')),
    join(base, 'lib/mediaNav.ts'),
    join(base, 'lib/playerNav.ts'),
  ];
}

test('словарь: у каждой t(\'…\') и plural([…]) из team/player/media есть английская строка', () => {
  const missing: string[] = [];
  for (const f of sources()) {
    const src = readFileSync(f, 'utf8');
    for (const m of src.matchAll(/\bt\('((?:[^'\\]|\\.)*)'/g)) if (!(m[1] in en)) missing.push(`${f}: ${m[1]}`);
    for (const m of src.matchAll(/plural\([^,]+,\s*\['([^']+)',\s*'([^']+)',\s*'([^']+)'\]/g)) {
      const key = `${m[1]}|${m[2]}|${m[3]}`;
      if (!(key in en)) missing.push(`${f}: ${key}`);
    }
  }
  assert.deepEqual(missing, []);
});
