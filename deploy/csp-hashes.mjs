// sha256 инлайн-скриптов собранной страницы для CSP (script-src 'sha256-…').
//   node deploy/csp-hashes.mjs frontend/dist/index.html   →   'sha256-AAA=' 'sha256-BBB='
// Инлайн-скрипт у нас один — заставка (tools/splash/inject.py). Хэш считается от байтов между
// <script> и </script> ровно так, как их видит браузер, поэтому берём уже собранный dist/index.html.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

const file = process.argv[2];
if (!file) {
  console.error('usage: node deploy/csp-hashes.mjs <dist/index.html>');
  process.exit(2);
}
const html = readFileSync(file, 'utf8');
const hashes = [];
for (const m of html.matchAll(/<script(\s[^>]*)?>([\s\S]*?)<\/script>/gi)) {
  const attrs = m[1] || '';
  if (/\ssrc\s*=/i.test(attrs)) continue; // внешние файлы разрешает 'self'
  // парсер HTML превращает CRLF/CR в LF до подсчёта хэша — так же и здесь (файл, собранный на Windows)
  const body = m[2].replace(/\r\n?/g, '\n');
  hashes.push(`'sha256-${createHash('sha256').update(body, 'utf8').digest('base64')}'`);
}
process.stdout.write(hashes.join(' '));
