// Проверка экранов «Команда» и «Медиа» (этапы 8–9) в Chromium, 390×844 @2x.
//
//   cd frontend && npm run build && cd ..
//   NODE_PATH=C:/Users/egor3/node_modules node checks/screens-team-media/run.js
//
// Страница и /assets/* — из своей сборки frontend/dist (через page.route).
// /api/team и прочие /api/*, /img/team|player|flag|league — с настоящего сервера (host-resolver-rules).
// /api/news и /api/videos на сервере ещё нет — ответы своего бэкенда, сгенерированные локально
// на реальных RSS (mock/*.json, см. отчёт). /img/yt/* и /img/news/* на сервере тоже ещё нет —
// их отдаёт этот скрипт так же, как будет отдавать nginx (тот же хост и путь), чтобы видеть картинки.
const fs = require('fs');
const path = require('path');
const https = require('https');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '../..');
const DIST = path.join(ROOT, 'frontend', 'dist');
const DESIGN = path.join(ROOT, 'design', 'screens');
const OUT = __dirname;
const MOCK = path.join(__dirname, 'mock');
const ORIGIN = 'https://realmadridfan.ru';
const MIME = { '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.html': 'text/html', '.svg': 'image/svg+xml', '.png': 'image/png' };
const BLANK = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64');

// как nginx: /img/yt/{id}.jpg → i.ytimg.com, /img/news/<ключ>/<путь> → известный хост
function upstream(p) {
  let m = /^\/img\/yt\/([A-Za-z0-9_-]{11})\.jpg$/.exec(p);
  if (m) return `https://i.ytimg.com/vi/${m[1]}/hqdefault.jpg`;
  m = /^\/img\/news\/championat\/([A-Za-z0-9._~/-]{1,400}\.(?:jpe?g|png|webp))$/.exec(p);
  if (m) return `https://img.championat.com/${m[1]}`;
  m = /^\/img\/news\/sportsru\/(dynamic_images\/[A-Za-z0-9._~/-]{1,400}\.(?:jpe?g|png|webp))$/.exec(p);
  if (m) return `https://www.sports.ru/${m[1]}`;
  return null;
}
function fetchBuf(url) {
  return new Promise((resolve) => {
    https
      .get(url, { headers: { 'User-Agent': 'Mozilla/5.0' }, timeout: 10000 }, (r) => {
        const chunks = [];
        r.on('data', (c) => chunks.push(c));
        r.on('end', () => resolve(r.statusCode === 200 ? { body: Buffer.concat(chunks), type: r.headers['content-type'] } : null));
      })
      .on('error', () => resolve(null))
      .on('timeout', function () { this.destroy(); resolve(null); });
  });
}

const SCENARIOS = [
  { name: 'team', url: '/team', full: true },
  { name: 'media-all', url: '/media', full: true },
  { name: 'media-news', url: '/media?tab=news', full: true },
  { name: 'media-video', url: '/media?tab=video', full: true },
  { name: 'team-loading', url: '/team', delayApi: true },
  { name: 'media-loading', url: '/media', delayApi: true },
  { name: 'team-error', url: '/team', failApi: /\/api\/team/ },
  { name: 'media-error', url: '/media', failApi: /\/api\/(news|videos)/ },
];

(async () => {
  const browser = await chromium.launch({ args: ['--host-resolver-rules=MAP realmadridfan.ru 81.17.154.4'] });
  const report = { scenarios: {}, externalHosts: {}, consoleErrors: [], pageErrors: [] };
  const imgCache = new Map();

  for (const sc of SCENARIOS) {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: 'ru-RU' });
    const page = await ctx.newPage();
    const stats = { requests: 0, api: {}, img: { ok: 0, fail: 0 }, hosts: {} };
    page.on('request', (req) => {
      const u = new URL(req.url());
      const host = u.protocol === 'data:' ? 'data:' : u.host;
      stats.hosts[host] = (stats.hosts[host] || 0) + 1;
      stats.requests++;
      if (host !== 'realmadridfan.ru' && host !== 'data:') report.externalHosts[host] = (report.externalHosts[host] || 0) + 1;
    });
    page.on('console', (m) => {
      if (m.type() === 'error') report.consoleErrors.push(`${sc.name}: ${m.text()}`);
    });
    page.on('pageerror', (e) => report.pageErrors.push(`${sc.name}: ${e.message}`));
    page.on('response', (r) => {
      const u = new URL(r.url());
      if (u.pathname.startsWith('/api/')) stats.api[u.pathname + u.search] = r.status();
      if (u.pathname.startsWith('/img/')) r.status() === 200 ? stats.img.ok++ : stats.img.fail++;
    });

    await page.route(`${ORIGIN}/**`, async (route) => {
      const u = new URL(route.request().url());
      const p = u.pathname;
      if (p.startsWith('/api/')) {
        if (sc.failApi && sc.failApi.test(p)) return route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"internal"}' });
        if (sc.delayApi) await new Promise((r) => setTimeout(r, 60000));
        if (p === '/api/news') {
          const f = u.searchParams.get('limit') === '2' ? 'news2' : 'news50';
          return route.fulfill({ status: 200, contentType: 'application/json', body: fs.readFileSync(path.join(MOCK, `${f}.json`)) });
        }
        if (p === '/api/videos') {
          return route.fulfill({ status: 200, contentType: 'application/json', body: fs.readFileSync(path.join(MOCK, 'videos30.json')) });
        }
        return route.continue();
      }
      if (p.startsWith('/img/')) {
        const up = upstream(p);
        if (!up) return route.continue();
        if (!imgCache.has(up)) imgCache.set(up, await fetchBuf(up));
        const got = imgCache.get(up);
        return route.fulfill(got ? { status: 200, contentType: got.type || 'image/jpeg', body: got.body } : { status: 200, contentType: 'image/png', body: BLANK });
      }
      const file = path.join(DIST, decodeURIComponent(p));
      if (p !== '/' && file.startsWith(DIST) && fs.existsSync(file) && fs.statSync(file).isFile()) {
        return route.fulfill({ status: 200, contentType: MIME[path.extname(file)] || 'application/octet-stream', body: fs.readFileSync(file) });
      }
      return route.fulfill({ status: 200, contentType: 'text/html', body: fs.readFileSync(path.join(DIST, 'index.html')) });
    });

    await page.goto(ORIGIN + sc.url, { waitUntil: sc.delayApi ? 'domcontentloaded' : 'networkidle', timeout: 60000 });
    if (sc.delayApi) await page.waitForTimeout(1200);
    else {
      await page.waitForTimeout(800);
      // ленивые картинки ниже экрана: прокрутить, дождаться, вернуться
      await page.evaluate(async () => {
        for (let y = 0; y < document.body.scrollHeight; y += 600) {
          window.scrollTo(0, y);
          await new Promise((r) => setTimeout(r, 120));
        }
        window.scrollTo(0, 0);
      });
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(500);
    }
    const dom = await page.evaluate(() => ({
      overflowX: document.documentElement.scrollWidth > window.innerWidth,
      height: document.documentElement.scrollHeight,
      extLinks: [...document.querySelectorAll('a.ext-link')].length,
      extLinksBlank: [...document.querySelectorAll('a.ext-link')].every((a) => a.target === '_blank' && /noopener/.test(a.rel)),
      players: document.querySelectorAll('.tm-player').length,
      injuryBadges: document.querySelectorAll('.tm-player .ui-badge--injury').length,
      flags: document.querySelectorAll('.tm-player .ui-flag:not(.is-failed)').length,
      photosFailed: document.querySelectorAll('.ui-photo .is-failed').length,
      leaders: [...document.querySelectorAll('.tm-leader')].map((e) => e.innerText.replace(/\s+/g, ' ')),
      lazaret: [...document.querySelectorAll('.tm-inj')].map((e) => e.innerText.replace(/\s+/g, ' ')),
      subs: [...document.querySelectorAll('.tm-player .tm-sub')].slice(0, 6).map((e) => e.innerText),
      news: document.querySelectorAll('.ui-news').length,
      newsImgs: document.querySelectorAll('.ui-news__img').length,
      tiles: document.querySelectorAll('.ui-vtile').length,
      shorts: document.querySelectorAll('.mx-short-tag').length,
      heroVideo: document.querySelector('.ui-video__title')?.innerText ?? null,
      heroSub: document.querySelector('.ui-video__sub')?.innerText ?? null,
      states: [...document.querySelectorAll('.ui-state__title')].map((e) => e.innerText),
      skeletons: document.querySelectorAll('.ui-skel').length,
      title: document.title,
    }));
    await page.screenshot({ path: path.join(OUT, `${sc.name}.png`), fullPage: !!sc.full });
    if (sc.full) await page.screenshot({ path: path.join(OUT, `${sc.name}-viewport.png`) });
    report.scenarios[sc.name] = { ...dom, requests: stats.requests, hosts: stats.hosts, api: stats.api, img: stats.img };
    await ctx.close();
  }

  // макеты: тот же размер, для сравнения
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.route('**/*', (route) => (route.request().url().startsWith('file:') ? route.continue() : route.abort()));
  for (const [n, f] of [['design-team', 'a-team.html'], ['design-media', 'a-media.html']]) {
    await page.goto('file:///' + path.join(DESIGN, f).replace(/\\/g, '/'));
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(OUT, `${n}.png`), fullPage: true });
  }
  // пары «макет | сборка» (первый экран)
  for (const [n, a, b] of [['compare-team', 'design-team.png', 'team-viewport.png'], ['compare-media', 'design-media.png', 'media-all-viewport.png']]) {
    const img = (f) => 'data:image/png;base64,' + fs.readFileSync(path.join(OUT, f)).toString('base64');
    await page.setViewportSize({ width: 800, height: 900 });
    await page.setContent(
      `<body style="margin:0;background:#222;display:flex;gap:20px;padding:10px;font:14px sans-serif;color:#ccc">
        <div><div>макет</div><img src="${img(a)}" style="width:390px;height:844px;object-fit:cover;object-position:top"></div>
        <div><div>сборка</div><img src="${img(b)}" style="width:390px"></div></body>`,
    );
    await page.screenshot({ path: path.join(OUT, `${n}.png`), fullPage: true });
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1));
  console.log(JSON.stringify({ externalHosts: report.externalHosts, consoleErrors: report.consoleErrors, pageErrors: report.pageErrors }, null, 1));
  for (const [k, v] of Object.entries(report.scenarios)) {
    console.log(k, JSON.stringify({ ...v, hosts: undefined }).slice(0, 900));
  }
})();
