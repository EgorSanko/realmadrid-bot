// PDF «RuStore — инструкция и материалы» из шаблона rustore/guide.html (Playwright, локальные шрифты design/fonts).
//
//   NODE_PATH=C:/Users/egor3/node_modules node tools/rustore/make-guide.js [выходной.pdf]
//
// Строку комментария модератору с настоящим кодом берёт из файла вне репозитория
// (C:\Users\egor3\.keystores\realmadridfan-rustore-review.txt), нет файла — ставит заглушку.
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');
const OUT = process.argv[2] || 'C:/Users/egor3/Downloads/Мадридиста-RuStore/RuStore — инструкция и материалы.pdf';
const REVIEW = 'C:/Users/egor3/.keystores/realmadridfan-rustore-review.txt';
const KEYTXT = 'C:/Users/egor3/.keystores/realmadridfan-release.txt';
const url = (p) => 'file:///' + p.replace(/\\/g, '/');
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const card = JSON.parse(fs.readFileSync(path.join(ROOT, 'rustore/card.json'), 'utf8'));
const whats = fs.readFileSync(path.join(ROOT, 'rustore/whats-new.txt'), 'utf8').trim();
let moder = fs.readFileSync(path.join(ROOT, 'rustore/moderator-comment.txt'), 'utf8').match(/^moderInfo:\s*(.+)$/m)[1];
if (fs.existsSync(REVIEW)) moder = fs.readFileSync(REVIEW, 'utf8').match(/^moderInfo:\s*(.+)$/m)[1];
const sha = fs.existsSync(KEYTXT) ? (fs.readFileSync(KEYTXT, 'utf8').match(/SHA-256[^:]*:\s*([0-9A-F:]+)/) || [])[1] || '—' : '—';
let branch = '—';
try {
  branch = execFileSync('git', ['-C', ROOT, 'branch', '--show-current'], { encoding: 'utf8' }).trim();
} catch {}

const shotsDir = path.join(ROOT, 'rustore/screenshots');
const shots = fs
  .readdirSync(shotsDir)
  .filter((f) => /\.(png|jpe?g)$/i.test(f))
  .sort()
  .map((f, i) => `<figure><img src="${url(path.join(shotsDir, f))}"><figcaption>${i} · ${f}</figcaption></figure>`)
  .join('');

const now = new Date();
const date = now.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
let html = fs.readFileSync(path.join(ROOT, 'rustore/guide.html'), 'utf8');
const vars = {
  ROOT: url(ROOT),
  MODER: esc(moder),
  SHA256: sha,
  DATE: date,
  BRANCH: esc(branch),
  APPNAME: esc(card.appName),
  SHORT: esc(card.shortDescription),
  SHORT_LEN: String(card.shortDescription.length),
  FULL: esc(card.fullDescription),
  FULL_LEN: String(card.fullDescription.length),
  WHATSNEW: esc(whats),
  SHOTS: shots,
};
html = html.replace(/\{\{(\w+)\}\}/g, (m, k) => (k in vars ? vars[k] : m));

(async () => {
  const tmp = path.join(require('os').tmpdir(), 'madridista-guide.html');
  fs.writeFileSync(tmp, html);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(url(tmp), { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  await page.pdf({ path: OUT, format: 'A4', printBackground: true, preferCSSPageSize: true });
  await browser.close();
  fs.unlinkSync(tmp);
  console.log('PDF:', OUT, Math.round(fs.statSync(OUT).size / 1024) + ' КБ');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
