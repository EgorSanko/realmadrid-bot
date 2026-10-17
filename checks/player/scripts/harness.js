// Общая обвязка Playwright: сайт realmadridfan.ru, страницы и /assets — из локального dist,
// /api/* и /img/* — с сервера, /api/player/* — из локального бэкенда (его на сервере ещё нет).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const SITE = 'https://realmadridfan.ru';
const HOST = 'realmadridfan.ru';
const LOCAL_API = process.env.LOCAL_API || 'http://127.0.0.1:8765';
const MIME = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json', '.ico': 'image/x-icon', '.webmanifest': 'application/manifest+json' };

async function open(distDir) {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: 'ru-RU', timezoneId: 'Europe/Moscow' });
  const log = { external: new Set(), errors: [], playerCalls: [], failed: [] };
  await context.route(`${SITE}/**`, async (route) => {
    const req = route.request();
    const u = new URL(req.url());
    const p = u.pathname;
    if (p.startsWith('/api/player/')) {
      log.playerCalls.push(p);
      try {
        const r = await fetch(LOCAL_API + p + u.search);
        const body = Buffer.from(await r.arrayBuffer());
        return route.fulfill({ status: r.status, headers: { 'content-type': r.headers.get('content-type') || 'application/json', 'cache-control': r.headers.get('cache-control') || 'no-store' }, body });
      } catch (e) {
        return route.fulfill({ status: 502, body: String(e) });
      }
    }
    if (p.startsWith('/api/') || p.startsWith('/img/')) return route.continue();
    const file = path.join(distDir, decodeURIComponent(p));
    if (p !== '/' && fs.existsSync(file) && fs.statSync(file).isFile()) {
      return route.fulfill({ status: 200, headers: { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' }, body: fs.readFileSync(file) });
    }
    if (p.startsWith('/assets/')) return route.fulfill({ status: 404, body: '' });
    return route.fulfill({ status: 200, headers: { 'content-type': 'text/html' }, body: fs.readFileSync(path.join(distDir, 'index.html')) });
  });
  const page = await context.newPage();
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (u.protocol.startsWith('http') && u.host !== HOST) log.external.add(u.host);
  });
  page.on('console', (m) => { if (m.type() === 'error') log.errors.push(m.text()); });
  page.on('pageerror', (e) => log.errors.push('pageerror: ' + e.message));
  page.on('requestfailed', (r) => log.failed.push(r.url() + ' ' + (r.failure() || {}).errorText));
  return { browser, context, page, log };
}

async function settle(page, ms = 1200) {
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(ms);
}

async function hscroll(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

async function shot(page, out, name, full = true) {
  fs.mkdirSync(out, { recursive: true });
  const f = path.join(out, name + '.png');
  await page.screenshot({ path: f, fullPage: full });
  return f;
}

module.exports = { open, settle, hscroll, shot, SITE };
