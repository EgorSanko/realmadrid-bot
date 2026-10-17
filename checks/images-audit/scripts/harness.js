// Обвязка Playwright для ревизии картинок.
// Сайт https://realmadridfan.ru: страницы и /assets/* — из локального dist (до/после),
// /api/* и /img/* — с сервера. В режиме «после» в ответы /api/match/{id} подмешиваются
// новые поля локального бэкенда (venue.flag, referee_country, form[*].opponent) — их на
// сервере ещё нет; берутся из checks/images-audit/local-api/*.json (scripts/local_api.py).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const SITE = 'https://realmadridfan.ru';
const HOST = 'realmadridfan.ru';
const MIME = {
  '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.woff2': 'font/woff2', '.woff': 'font/woff',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json', '.ico': 'image/x-icon',
  '.webmanifest': 'application/manifest+json',
};

function localPart(localDir, p) {
  if (!localDir) return null;
  let f = null;
  const m = /^\/api\/match\/(\d+)$/.exec(p);
  if (m) f = path.join(localDir, `match_${m[1]}.json`);
  if (!f || !fs.existsSync(f)) return null;
  return JSON.parse(fs.readFileSync(f, 'utf8'));
}

async function open(distDir, { localDir = null } = {}) {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: 'ru-RU', timezoneId: 'Europe/Moscow',
  });
  const log = { external: new Set(), errors: [], failed: [], merged: [] };
  await context.route(`${SITE}/**`, async (route) => {
    const req = route.request();
    const u = new URL(req.url());
    const p = u.pathname;
    if (p.startsWith('/api/')) {
      const part = localPart(localDir, p);
      if (!part) return route.continue();
      const r = await route.fetch();
      const body = await r.json();
      Object.assign(body, part);
      log.merged.push(p);
      return route.fulfill({ status: r.status(), headers: { 'content-type': 'application/json', 'cache-control': 'no-store' }, body: JSON.stringify(body) });
    }
    if (p.startsWith('/img/')) return route.continue();
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

/** Прокрутить страницу целиком, чтобы lazy-картинки загрузились, и дождаться их. */
async function settle(page, ms = 800) {
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.evaluate(async () => {
    const step = window.innerHeight * 0.8;
    for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 120));
    }
    window.scrollTo(0, 0);
  });
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.evaluate(async () => {
    const imgs = [...document.images].filter((i) => !i.complete);
    await Promise.race([
      Promise.all(imgs.map((i) => new Promise((r) => { i.onload = i.onerror = r; }))),
      new Promise((r) => setTimeout(r, 5000)),
    ]);
  });
  await page.waitForTimeout(ms);
}

/** Картинки на экране: сколько видимых, сколько битых (naturalWidth = 0), по типам. */
async function imageStats(page) {
  return page.evaluate(() => {
    const vis = (el) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0 && !el.classList.contains('is-failed');
    };
    const all = [...document.images];
    const visible = all.filter(vis);
    const broken = visible.filter((i) => i.complete && i.naturalWidth === 0).map((i) => i.currentSrc || i.src);
    const kind = (src) => {
      const m = /\/img\/(team|player|league|flag|yt|news)\//.exec(src);
      return m ? m[1] : 'other';
    };
    const by = {};
    for (const i of visible) {
      const k = kind(i.currentSrc || i.src);
      by[k] = (by[k] || 0) + 1;
    }
    const failedHidden = all.filter((i) => i.classList.contains('is-failed')).length;
    return { visible: visible.length, broken, by, failedHidden };
  });
}

async function hscroll(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

async function shotEl(page, locator, file) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  await locator.scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  await locator.screenshot({ path: file });
}

module.exports = { open, settle, imageStats, hscroll, shotEl, SITE };
