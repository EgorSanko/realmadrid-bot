// Экран матча и «Матчи» по-английски: строки из view/info/extras/mapMatches идут через t()/plural(),
// а каждый ключ из этих файлов есть в английском словаре. Запуск: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { normalizeMatch, type ApiMatch } from '../src/api/match.ts';
import { applyLang } from '../src/lib/i18n.ts';
import en from '../src/i18n/en/index.ts';
import {
  aboutRows,
  headerView,
  keyFeed,
  lineupView,
  realSide,
  returnText,
  shotsView,
  statsView,
  timelineView,
  tournamentLine,
} from '../src/screens/match/view.ts';
import { refereeView, stadiumView, weatherView } from '../src/screens/match/info.ts';
import { roundTitle, votesText } from '../src/screens/match/extras.ts';
import { commentaryRows } from '../src/screens/match/feed.ts';
import { competitionOf, errorText, periodText, staleNote } from '../src/lib/mapMatches.ts';

const fx = (name: string): ApiMatch =>
  normalizeMatch(JSON.parse(readFileSync(new URL(`../src/__fixtures__/${name}.json`, import.meta.url), 'utf8')));

const FOTMOB = fx('match_6106274');
const LIVE = fx('match_5868098_live');

/** Выполнить fn по-английски и вернуть интерфейс на русский, даже если проверка упала. */
function inEnglish(fn: () => void) {
  applyLang('en', en);
  try {
    fn();
  } finally {
    applyLang('ru');
  }
}

const CYR = /[А-Яа-яЁё]/;

test('экран матча по-английски: шапка, хронология, статистика, составы', () => {
  const ruStats = statsView(FOTMOB, 'all');
  inEnglish(() => {
    assert.equal(headerView({ ...FOTMOB, status: { ...FOTMOB.status, state: 'halftime' } }).statusText, 'Half-time');
    assert.equal(headerView({ ...FOTMOB, status: { ...FOTMOB.status, state: 'postponed' } }).statusText, 'Match postponed');
    assert.match(tournamentLine(FOTMOB), /^Champions League/);
    assert.equal(tournamentLine({ ...FOTMOB, tournament: { ...FOTMOB.tournament, id: 87, round: '9' } }), 'LaLiga · Matchday 9');

    const stats = statsView(FOTMOB, 'all');
    assert.equal(stats.length, ruStats.length);
    assert.equal(stats[0].title, 'Top stats');
    const labels = stats.flatMap((g) => [g.title, ...g.rows.map((r) => r.label)]);
    assert.ok(labels.includes('Ball possession'));
    assert.ok(labels.every((l) => !CYR.test(l)), `русское в статистике: ${labels.filter((l) => CYR.test(l))}`);

    const tl = timelineView(FOTMOB).items;
    for (const it of tl) {
      const text = 'kind' in it && it.kind === 'divider' ? it.label : [it.detail, it.related?.prefix].filter(Boolean).join(' ');
      assert.ok(!CYR.test(text), `русское в хронологии: ${text}`);
    }

    const feed = keyFeed(FOTMOB);
    assert.ok(feed.some((x) => x.title === 'Goal!'));
    assert.ok(feed.some((x) => x.title === 'Kick-off'));
    assert.ok(feed.every((x) => !CYR.test(x.title + (x.text ?? '') + x.players.map((p) => p.role ?? '').join(''))));

    const shots = shotsView(FOTMOB, realSide(FOTMOB));
    if (shots) assert.match(shots.summary, /^\d+ shots?( ·|$)/);

    const lu = lineupView(FOTMOB, realSide(FOTMOB));
    assert.ok(lu);
    for (const s of lu!.subs) assert.match(s.detail, /^on \d+′/);
    assert.ok(lu!.unavailable.every((u) => !CYR.test(u.reason)));

    assert.equal(returnText('Late October 2026'), 'until late October');
    assert.equal(returnText('2026-12-31'), 'until 31 December');
    assert.ok(aboutRows(FOTMOB).every(([k]) => !CYR.test(k)));
  });
  // русский — как был
  assert.equal(statsView(FOTMOB, 'all')[0].title, 'Главное');
  assert.equal(returnText('Late October 2026'), 'до конца октября');
});

test('о матче, тур, опрос и комментарии по-английски', () => {
  inEnglish(() => {
    const st = stadiumView(LIVE);
    if (st?.surface) assert.ok(!CYR.test(st.surface));
    if (st?.country) assert.ok(!CYR.test(st.country));
    const w = weatherView(LIVE);
    if (w) assert.ok(!CYR.test(`${w.text ?? ''} ${w.details}`), w.details);
    const ref = refereeView(LIVE);
    if (ref?.matches) assert.match(ref.matches, /^\d+ match(es)? in /);
    assert.ok((ref?.tiles ?? []).every((x) => !CYR.test(x.label)));

    assert.equal(roundTitle({ league: { id: 87, name: 'LaLiga' }, round: '9' } as Parameters<typeof roundTitle>[0]), 'LaLiga · Matchday 9');
    assert.equal(votesText(1), '1 vote');
    assert.equal(votesText(963), '963 votes');
    assert.equal(votesText(263_128), '263K votes');
    assert.equal(votesText(1_240_000), '1.2M votes');

    const rows = commentaryRows([
      { id: 'a', type: 'goal', minute: 12, added: null, text: 'Goal!', side: 'home', players: [] },
      { id: 'b', type: 'comment', minute: 13, added: null, text: 'Hm', side: null, players: [] },
    ] as unknown as Parameters<typeof commentaryRows>[0]);
    assert.equal(rows[0].title, 'Goal!');
    assert.equal(rows[1].title, undefined);
  });
  assert.equal(votesText(1_240_000), '1,2 млн голосов');
});

test('«Матчи» по-английски: турниры, периоды, ошибки', () => {
  inEnglish(() => {
    assert.deepEqual(competitionOf({ id: 42, name: 'Champions League' } as Parameters<typeof competitionOf>[0]), {
      id: 42,
      name: 'Champions League',
      short: 'UCL',
      tone: 'ucl',
    });
    assert.equal(periodText({ state: 'live', minute: 30 } as Parameters<typeof periodText>[0]), '1st half');
    assert.equal(periodText({ state: 'halftime' } as Parameters<typeof periodText>[0]), 'Half-time');
    assert.equal(staleNote({ stale: true, age_s: 20 * 60 } as Parameters<typeof staleNote>[0]), 'updated 20 min ago');
    assert.equal(errorText({ status: 0 }).title, 'No connection');
  });
  assert.equal(competitionOf({ id: 42, name: 'Champions League' } as Parameters<typeof competitionOf>[0]).short, 'ЛЧ');
});

/* ---------- каждый ключ t()/plural() из этих файлов есть в словаре ---------- */

const SRC = new URL('../src/', import.meta.url);
const FILES = [
  ...readdirSync(new URL('screens/match/', SRC))
    .filter((f) => /\.tsx?$/.test(f))
    .map((f) => `screens/match/${f}`),
  'ui/match.tsx',
  'ui/matchExtra.tsx',
  'ui/stats.tsx',
  'lib/mapMatches.ts',
  'screens/MatchesScreen.tsx',
  'screens/LeagueTable.tsx',
];

test('все русские строки экрана матча и «Матчей» есть в английском словаре', () => {
  const missing: string[] = [];
  for (const f of FILES) {
    const code = readFileSync(new URL(f, SRC), 'utf8')
      .split('\n')
      .filter((l) => !/^\s*(\/\/|\*|\/\*|\{\/\*)/.test(l)) // комментарии
      .map((l) => l.replace(/\s\/\/ .*$/, ''))
      .join('\n');
    const keys = new Set<string>();
    const forms = new Set<string>();
    // формы plural(): ['гол', 'гола', 'голов'] → ключ 'гол|гола|голов'
    for (const m of code.matchAll(/\[\s*'([^'\n]*)',\s*'([^'\n]*)',\s*'([^'\n]*)'\s*\]/g)) {
      if (!CYR.test(m[0])) continue;
      keys.add(`${m[1]}|${m[2]}|${m[3]}`);
      [m[1], m[2], m[3]].forEach((x) => forms.add(x));
    }
    // t('…') и русские строки в таблицах (значения переводятся через t() при выводе)
    for (const m of code.matchAll(/\bt\(\s*'([^'\n]*)'/g)) keys.add(m[1]);
    for (const m of code.matchAll(/'([^'\n]*[А-Яа-яЁё][^'\n]*)'/g)) if (!forms.has(m[1])) keys.add(m[1]);
    for (const k of keys) if (!(k in en)) missing.push(`${f}: ${k}`);
  }
  assert.deepEqual(missing, []);
});
