// Матч на компьютере вкладками (как FotMob) и телефон: скриншоты каждой вкладки, высота страницы, гориз. прокрутка.
//
//   NODE_PATH=C:/Users/egor3/node_modules node checks/match-tabs/run.js <distDir> <outDir> [prefix]
//
// Страницы и /assets/* — из локальной сборки distDir; /api/* и /img/* — только чтение с https://realmadridfan.ru.
// /api/auth/* подменён (аноним). Лайв-матч 5868098 — фикстура репозитория (match_5868098_live.json + commentary).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const [, , DIST, OUT, PREFIX = ''] = process.argv;
const HOST = 'realmadridfan.ru';
const SITE = 'https://' + HOST;
const FX = path.join(__dirname, '..', '..', 'frontend', 'src', '__fixtures__');
const MIME = {
  '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.woff2': 'font/woff2', '.woff': 'font/woff',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.json': 'application/json', '.ico': 'image/x-icon',
  '.webmanifest': 'application/manifest+json', '.txt': 'text/plain', '.xml': 'application/xml',
};
fs.mkdirSync(OUT, { recursive: true });

const LIVE = JSON.parse(fs.readFileSync(path.join(FX, 'match_5868098_live.json'), 'utf8'));
const LIVE_COMM = fs.readFileSync(path.join(FX, 'commentary_5868098.json'), 'utf8');

async function open(browser, viewport, mobile) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1, isMobile: mobile, hasTouch: mobile, locale: 'ru-RU', timezoneId: 'Europe/Moscow' });
  await context.addInitScript(() => { try { sessionStorage.setItem('rmSplash', '1'); localStorage.setItem('rmSplashAt', String(Date.now())); } catch (e) { /* */ } });
  const errors = [];
  await context.route('**/*', async (route) => {
    const u = new URL(route.request().url());
    if (u.host !== HOST) return route.abort('blockedbyclient');
    const p = u.pathname;
    const json = (body) => route.fulfill({ status: 200, headers: { 'content-type': 'application/json' }, body: typeof body === 'string' ? body : JSON.stringify(body) });
    if (p.startsWith('/api/auth/')) return json({ user: null, is_admin: false });
    if (p === '/api/match/5868098') return json(LIVE);
    if (p === '/api/match/5868098/commentary') return json(LIVE_COMM);
    if (p.startsWith('/api/') || p.startsWith('/img/')) {
      if (route.request().method() !== 'GET') return route.fulfill({ status: 405, body: '' });
      return route.continue();
    }
    const file = path.join(DIST, decodeURIComponent(p));
    if (p !== '/' && fs.existsSync(file) && fs.statSync(file).isFile())
      return route.fulfill({ status: 200, headers: { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' }, body: fs.readFileSync(file) });
    if (p.startsWith('/assets/') || /\.[a-z0-9]{2,12}$/i.test(p)) return route.fulfill({ status: 404, body: '' });
    return route.fulfill({ status: 200, headers: { 'content-type': 'text/html' }, body: fs.readFileSync(path.join(DIST, 'index.html')) });
  });
  const page = await context.newPage();
  page.on('response', (r) => { if (r.url().includes('/img/') && r.status() !== 200) errors.push('img ' + r.status() + ' ' + new URL(r.url()).pathname); });
  page.on('requestfailed', (r) => { if (r.url().includes('/img/')) errors.push('img failed ' + r.failure()?.errorText + ' ' + new URL(r.url()).pathname); });
  // общий баннер гола (данные прода) не относится к раскладке матча — прячем, чтобы не перекрывал кадры
  await page.addInitScript(() => { document.addEventListener('DOMContentLoaded', () => { const st = document.createElement('style'); st.textContent = '.gb{display:none!important}'; document.head.appendChild(st); }); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  return { context, page, errors };
}

async function settle(page) {
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  // ленивые картинки: проходим страницу сверху вниз, ждём загрузки и возвращаемся
  const y = await page.evaluate(() => window.scrollY);
  await page.evaluate(async () => {
    const h = document.documentElement.scrollHeight;
    for (let t = 0; t < h; t += 500) { window.scrollTo(0, t); await new Promise((r) => setTimeout(r, 60)); }
  });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForFunction(() => [...document.images].every((i) => i.complete), null, { timeout: 12000 }).catch(() => {});
  await page.evaluate(() => Promise.all([...document.images].map((i) => { i.loading = 'eager'; i.decoding = 'sync'; return i.decode().catch(() => {}); })));
  await page.evaluate((v) => window.scrollTo(0, v), y);
  await page.waitForTimeout(900);
}

/** Вся страница одним кадром: окно растягиваем на высоту страницы (fullPage у Chromium теряет картинки). */
async function shot(page, file) {
  const vp = page.viewportSize();
  const h = await page.evaluate(() => document.documentElement.scrollHeight);
  await page.setViewportSize({ width: vp.width, height: Math.min(h, 12000) });
  await page.waitForTimeout(400);
  await page.evaluate(() => Promise.all([...document.images].map((i) => i.decode().catch(() => {}))));
  await page.screenshot({ path: file });
  await page.setViewportSize(vp);
  await page.waitForTimeout(200);
}

async function measure(page) {
  return page.evaluate(() => ({
    height: document.documentElement.scrollHeight,
    hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    url: location.pathname + location.search,
    tabs: [...document.querySelectorAll('[aria-label="Разделы матча"] [role=tab]')].map((t) => t.textContent.trim()),
  }));
}

(async () => {
  const browser = await chromium.launch();
  const report = [];
  const matches = [
    ['fin', '6106244'],
    ['live', '5868098'],
  ];
  // компьютер: каждая вкладка отдельно
  for (const [tag, id] of matches) {
    const { context, page, errors } = await open(browser, { width: 1440, height: 900 }, false);
    await page.goto(`${SITE}/match/${id}`);
    await settle(page);
    const first = await measure(page);
    const tabs = first.tabs;
    for (let i = 0; i < tabs.length; i++) {
      const tab = page.locator('.mt-dock [role=tab]').nth(i);
      await tab.click();
      await settle(page);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(250);
      const m = await measure(page);
      const name = `${PREFIX}desk-${tag}-${i + 1}`;
      await shot(page, path.join(OUT, name + '.png'));
      report.push({ name, tab: tabs[i], ...m });
    }
    // свёрнутая шапка при прокрутке
    await page.locator('.mt-dock [role=tab]').nth(0).click();
    await settle(page);
    await page.evaluate(() => window.scrollTo(0, 600));
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(OUT, `${PREFIX}desk-${tag}-scrolled.png`) });
    // обновление страницы с ?tab=stats
    await page.goto(`${SITE}/match/${id}?tab=stats`);
    await settle(page);
    const sel = await page.evaluate(() => document.querySelector('.mt-dock [role=tab][aria-selected=true]')?.textContent?.trim());
    report.push({ name: `${PREFIX}desk-${tag}-reload-stats`, selected: sel, errors });
    await context.close();
  }
  // телефон
  for (const [tag, id] of matches) {
    const { context, page, errors } = await open(browser, { width: 390, height: 844 }, true);
    await page.goto(`${SITE}/match/${id}`);
    await settle(page);
    const tabs = (await measure(page)).tabs;
    for (let i = 0; i < tabs.length; i++) {
      await page.locator('[aria-label="Разделы матча"] [role=tab]').nth(i).click();
      await settle(page);
      const m = await measure(page);
      const name = `${PREFIX}m390-${tag}-${i + 1}`;
      await shot(page, path.join(OUT, name + '.png'));
      report.push({ name, tab: tabs[i], ...m });
    }
    report.push({ name: `${PREFIX}m390-${tag}-errors`, errors });
    await context.close();
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, `${PREFIX}report.json`), JSON.stringify(report, null, 2));
  for (const r of report) console.log(JSON.stringify(r));
})();
