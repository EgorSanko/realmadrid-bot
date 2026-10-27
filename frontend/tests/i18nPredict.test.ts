// Английский интерфейс прогнозов, игр, профиля и входа: чистые функции отдают английский, все ключи t() — в словаре.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { applyLang } from '../src/lib/i18n.ts';
import en from '../src/i18n/en/index.ts';
import { historyItem, homeLine, leagueErrorText, matchTitle, nextLine, placeLine, predictError, rowSub, summaryTiles } from '../src/lib/predict.ts';
import type { LeagueHeader, MeHistoryEntry, NextMatch } from '../src/lib/predict.ts';
import { gameError, levelTitle, penaltyHeadline, quizSummary, shareText } from '../src/lib/games.ts';
import { outcomeText } from '../src/lib/penalty.ts';
import { historyRow, monthLabel, pointsTiles } from '../src/lib/profile.ts';

function inEn(fn: () => void): void {
  applyLang('en', en);
  try {
    fn();
  } finally {
    applyLang('ru');
  }
}

const team = (id: number, name: string) => ({ id, name });

test('прогнозы по-английски: ошибки, подписи, история', () =>
  inEn(() => {
    assert.equal(predictError(409, 'closed').message, 'Predictions closed: the match has kicked off');
    // русский текст сервера по-английски не показываем
    assert.equal(predictError(404, null, 'Матч не найден').message, 'Match not found');
    assert.equal(predictError(500, null, 'Ошибка').message, 'Couldn’t save (error 500)');
    assert.equal(leagueErrorText('not_owner'), 'Only the league creator can do this');
    assert.equal(leagueErrorText('unknown'), null);
    assert.equal(rowSub({ played: 3, exact: 1 }), '3 predictions · 1 exact');
    assert.equal(rowSub({ played: 0, exact: 0 }), 'no predictions yet');
    assert.deepEqual(summaryTiles(null).map((x) => x.label), ['Points', 'Rank', 'Exact']);
    assert.equal(matchTitle({ home: team(541, 'Real Madrid'), away: team(536, 'Sevilla'), rm_side: 'home' }), 'Real Madrid — Sevilla');
    assert.equal(placeLine({ started: true, myPlace: 2 }, 5), 'you’re #2 of 5');
    const head = { next_match: { id: '1' }, predicted_next_count: 1, members: 2 } as unknown as LeagueHeader;
    assert.equal(nextLine(head), '1 of 2 have predicted');
    const entry = {
      match: { id: 'm1', kickoff_utc: '2026-10-01T19:00:00Z', home: team(541, 'Real Madrid'), away: team(536, 'Sevilla'), rm_side: 'home', status: 'finished', score: { home: 2, away: 1 } },
      prediction: { home: 2, away: 1, first_scorer_id: '7' },
      points: { total: 7, score: 5, scorer: 2, kind: 'exact' },
      state: 'settled',
    } as unknown as MeHistoryEntry;
    assert.equal(historyItem(entry).note, 'exact score +5 · scorer +2');
    const next = { my_prediction: { home: 1, away: 0 }, accepting: true } as unknown as NextMatch;
    assert.deepEqual(homeLine(next), { pick: '1:0', tail: 'edit' });
  }));

test('игры по-английски: уровни, итоги, поделиться, ошибки', () =>
  inEn(() => {
    assert.equal(levelTitle('quiz', 'expert'), 'Expert');
    assert.equal(quizSummary({ correct: 7, total: 10 } as never), '7 of 10 correct');
    assert.equal(penaltyHeadline({ won: true, sudden: true } as never), 'Won in sudden death!');
    assert.equal(outcomeText('save').title, 'SAVE!');
    assert.equal(gameError(429, 'Слишком часто'), 'Too fast — wait a moment');
    assert.equal(
      shareText('penalty', 'hard', { goals: 4, rival: 3, score: 1 } as never),
      'Madridista penalties, “Hard” level: 4:3, 1 point. Try to beat that!',
    );
  }));

test('профиль по-английски: плитки, месяц, история', () =>
  inEn(() => {
    assert.equal(monthLabel('2026-10'), 'October 2026');
    assert.deepEqual(pointsTiles(null).map((x) => x.label), ['Season points', 'This month', 'Rank', 'Exact scores']);
    const row = historyRow({
      match: { id: 'm1', kickoff_utc: '2026-10-01T19:00:00Z', home: team(541, 'Real'), away: team(536, 'Sevilla'), score: null },
      prediction: { home: 1, away: 0 },
      points: null,
      state: 'open',
    } as never);
    assert.equal(row.note, 'Can be changed until kick-off');
  }));

test('русский не изменился', () => {
  applyLang('ru');
  assert.equal(placeLine({ started: true, myPlace: 2 }, 5), 'ты 2-й из 5');
  assert.equal(predictError(404, null, 'Лига не найдена').message, 'Лига не найдена');
  assert.equal(rowSub({ played: 3, exact: 1 }), '3 прогноза · 1 точный');
});

/* ---------- все ключи t() из файлов прогнозов, игр, профиля и входа — в словаре ---------- */

const SRC = join(import.meta.dirname, '..', 'src');
function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : /\.tsx?$/.test(f) ? [p] : [];
  });
}
const FILES = [
  ...walk(join(SRC, 'screens', 'predict')),
  ...walk(join(SRC, 'screens', 'games')),
  ...walk(join(SRC, 'screens', 'profile')),
  ...['lib/predict.ts', 'lib/profile.ts', 'lib/games.ts', 'lib/penalty.ts', 'lib/codeLogin.ts', 'lib/codeFormat.ts'].map((p) => join(SRC, p)),
  ...['components/LoginButton.tsx', 'components/CodeLogin.tsx', 'components/GamesTabs.tsx'].map((p) => join(SRC, p)),
];

test('каждый t(\'…\') и plural([...]) в этих файлах есть в английском словаре', () => {
  const missing: string[] = [];
  let n = 0;
  for (const f of FILES) {
    const s = readFileSync(f, 'utf8');
    for (const m of s.matchAll(/\bt\('((?:[^'\\]|\\.)*)'/g)) {
      n++;
      if (!(m[1] in en)) missing.push(`${f}: ${m[1]}`);
    }
    for (const m of s.matchAll(/plural\([^,]+,\s*\['([^']*)',\s*'([^']*)',\s*'([^']*)'\]/g)) {
      const k = `${m[1]}|${m[2]}|${m[3]}`;
      if (!(k in en)) missing.push(`${f}: ${k}`);
    }
  }
  assert.ok(n > 200, `найдено ключей: ${n}`);
  assert.deepEqual(missing, []);
});
