import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { applyLang } from '../src/lib/i18n.ts';
import { descriptionFor } from '../src/lib/seo.ts';
import { describeExpiry } from '../src/lib/linkExpiry.ts';
import { linkError } from '../src/lib/linkCheck.ts';
import { joinedMessage } from '../src/lib/startParam.ts';
import en from '../src/i18n/en/index.ts';

const SRC = join(import.meta.dirname, '..', 'src');

/** Ссылка поставщика с exp в токене (как в linkExpiry.test.ts). */
function linkWithExp(exp: number): string {
  const head = Buffer.from(JSON.stringify({ exp })).toString('base64url');
  return `https://cdn.example/live/chunks.m3u8?nimblesessionid=1&token=${head}.sig`;
}

test('оболочка по-английски: SEO, срок ссылки, проверка ссылки, лиги', () => {
  const ruHome = descriptionFor('/');
  applyLang('en', en);
  try {
    assert.match(descriptionFor('/'), /^Madridista — a Real Madrid fan app/);
    assert.match(descriptionFor('/matches'), /fixtures and results/);
    assert.equal(descriptionFor('/неизвестно'), descriptionFor('/'));
    const paths = ['/', '/matches', '/match/1', '/team', '/player/1', '/media', '/news/a', '/video/b', '/predict', '/profile', '/privacy', '/terms', '/games', '/games/penalty'];
    for (const p of paths) assert.doesNotMatch(descriptionFor(p), /[А-Яа-яЁё]/, p);

    const now = new Date('2026-10-25T12:00:00Z');
    const info = describeExpiry(linkWithExp(now.getTime() / 1000 + 3 * 3600), now);
    assert.equal(info?.text, 'The link is valid until 18:00 (MSK)');
    assert.equal(describeExpiry(linkWithExp(now.getTime() / 1000 - 60), now)?.text, 'The link expired at 14:59 (MSK)');

    assert.equal(linkError(''), 'Paste the stream link');
    assert.equal(linkError('ftp://x'), 'The link must start with https://');
    assert.equal(joinedMessage('Ультрас', true), 'You joined the league “Ультрас”');
  } finally {
    applyLang('ru');
  }
  assert.equal(descriptionFor('/'), ruHome);
  assert.equal(linkError(''), 'Вставьте ссылку на трансляцию');
});

const FILES = [
  'App.tsx',
  'sections.tsx',
  'boot.tsx',
  ...['BottomNav', 'GoalBurst', 'GoalLayer', 'Player', 'PullToRefresh', 'RouteMeta', 'ScreenHeader', 'SiteFooter', 'SiteHeader', 'StartParamHandler', 'StreamBlock', 'Toaster', 'UserAvatar'].map(
    (n) => `components/${n}.tsx`,
  ),
  'components/goalOrder.ts',
  ...readdirSync(join(SRC, 'lib'))
    .filter((f) => !/^(predict|profile|games|penalty|codeLogin|codeFormat|mapMatches|i18n|mediaNav|playerNav)\.ts$/.test(f))
    .map((f) => `lib/${f}`),
  ...['base.tsx', 'countUp.tsx', 'flip.tsx', 'images.tsx', 'index.ts', 'media.tsx', 'playerLink.tsx', 'reveal.ts'].map((f) => `ui/${f}`),
  'screens/HomeScreen.tsx',
  ...readdirSync(join(SRC, 'screens/home'))
    .filter((f) => f.endsWith('.tsx'))
    .map((f) => `screens/home/${f}`),
  'screens/NotFoundScreen.tsx',
  'screens/legal/LegalScreen.tsx',
];

test('оболочка: у каждой строки t() и plural() в своих файлах есть английский перевод', () => {
  const missing: string[] = [];
  for (const f of FILES) {
    const src = readFileSync(join(SRC, f), 'utf8');
    for (const m of src.matchAll(/\bt\(\s*'((?:[^'\\]|\\.)*)'/g)) if (!(m[1] in en)) missing.push(`${f}: ${m[1]}`);
    for (const m of src.matchAll(/plural\([^,]+,\s*\[\s*'([^']+)',\s*'([^']+)',\s*'([^']+)'\s*\]/g)) {
      const key = `${m[1]}|${m[2]}|${m[3]}`;
      if (!(key in en)) missing.push(`${f}: ${key}`);
    }
  }
  assert.deepEqual(missing, []);
});
