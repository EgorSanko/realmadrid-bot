// Проверка UI-кита на /dev/ui против локального vite preview.
// В обычной прод-сборке /dev/ui нет — preview собирать с флагом:
//   cd frontend && VITE_UIKIT=1 npx vite build && npx vite preview
// (или смотреть на dev-сервере `npm run dev`, там маршрут есть всегда).
// Запуск (preview уже поднят):
//   NODE_PATH=C:/Users/egor3/node_modules MODE=noimg BASE=http://127.0.0.1:4173 node checks/ui-kit/run.js
//   NODE_PATH=C:/Users/egor3/node_modules MODE=img   BASE=http://127.0.0.1:4174 node checks/ui-kit/run.js
// MODE=noimg — /img проксируется на недоступный адрес; MODE=img — preview с DEV_IMG=1.
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const MODE = process.env.MODE || 'noimg';
const BASE = process.env.BASE || 'http://127.0.0.1:4173';
const OUT = path.join(__dirname, MODE);
const CMP = path.join(__dirname, 'compare');
const DESIGN = path.resolve(__dirname, '../../design/screens');
// Countdown: «1 день 22 часа 15 минут» до Вс 18.10 22:00 МСК, как в макете
const NOW = new Date('2026-10-16T20:45:00Z');

const PAIRS = [
  ['match-upcoming', 'a-home.html', 'section[aria-label="Ближайший матч"]'],
  ['match-live', 'a-live.html', 'section[aria-label="Счёт"]'],
  ['match-finished', 'a-home.html', 'a[href="a-match-events.html"]'],
  ['score-header', 'a-match-events.html', 'section[aria-label="Счёт"]'],
  ['timeline', 'a-match-events.html', 'section[aria-label="Хронология"]'],
  ['standings', 'a-fixtures.html', 'section[aria-label="Таблица Ла Лиги"]'],
  ['pitch', 'a-match-lineup.html', 'section.pitch'],
  ['momentum', 'a-match-stats.html', 'section[aria-label="Давление по ходу матча"]'],
  ['statrow', 'a-match-stats.html', 'section[aria-label="Статистика"]'],
  ['shotmap', 'a-match-stats.html', 'section[aria-label="Карта ударов"]'],
];

fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(CMP, { recursive: true });

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: 'ru-RU' });
  await ctx.clock.setFixedTime(NOW);
  // накопленный CLS — сдвиги вёрстки за всё время жизни страницы
  await ctx.addInitScript(() => {
    window.__cls = 0;
    window.__shifts = [];
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) {
        window.__cls += e.value;
        window.__shifts.push({ v: +e.value.toFixed(4), src: (e.sources || []).map((s) => s.node?.className || s.node?.nodeName || '?').join(',') });
      }
    }).observe({ type: 'layout-shift', buffered: true });
  });
  const page = await ctx.newPage();

  const hosts = new Map();
  const consoleErrors = [];
  const imgResponses = new Map();
  page.on('request', (req) => {
    const u = new URL(req.url());
    const key = u.protocol === 'data:' ? 'data:' : u.host;
    hosts.set(key, (hosts.get(key) || 0) + 1);
  });
  page.on('response', (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith('/img/')) imgResponses.set(u.pathname, r.status());
  });
  page.on('requestfailed', (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith('/img/')) imgResponses.set(u.pathname, 'failed: ' + r.failure()?.errorText);
  });
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text() + (m.location()?.url ? ' @ ' + new URL(m.location().url).pathname : ''));
  });
  page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message));

  await page.goto(BASE + '/dev/ui', { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  // прокрутить до конца, чтобы сработали loading="lazy"
  const full = await page.evaluate(() => document.documentElement.scrollHeight);
  for (let y = 0; y < full; y += 600) {
    await page.evaluate((y) => window.scrollTo(0, y), y);
    await page.waitForTimeout(60);
  }
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(300);
  await page.evaluate(() => window.scrollTo(0, 0));

  // /dev/ui не должен быть в нижнем меню; само меню (fixed) прячем, чтобы не перекрывало скриншоты
  const navLinks = await page.$$eval('nav.bottom-nav a', (as) => as.map((a) => a.getAttribute('href')));
  await page.addStyleTag({ content: 'nav.bottom-nav{display:none!important}' });

  // скриншоты секций
  const ids = await page.$$eval('[data-demo]', (els) => els.map((e) => e.dataset.demo));
  for (const id of ids) {
    await page.locator(`[data-demo="${id}"]`).screenshot({ path: path.join(OUT, `${id}.png`) });
  }

  // состояние картинок и рамок
  const imgs = await page.$$eval('img.ui-img', (els) =>
    els.map((img) => {
      const cs = getComputedStyle(img);
      const r = img.getBoundingClientRect();
      return {
        src: new URL(img.src).pathname,
        failed: img.classList.contains('is-failed'),
        visibility: cs.visibility,
        natural: `${img.naturalWidth}x${img.naturalHeight}`,
        box: `${Math.round(r.width)}x${Math.round(r.height)}`,
        attr: `${img.getAttribute('width')}x${img.getAttribute('height')}`,
        loading: img.loading,
        decoding: img.decoding,
        alt: img.getAttribute('alt'),
        frame: cs.borderTopWidth !== '0px' || cs.backgroundColor !== 'rgba(0, 0, 0, 0)' || cs.boxShadow !== 'none',
      };
    }),
  );
  const silhouettes = await page.$$eval('.ui-photo__sil', (e) => e.length);
  const layout = await page.$$eval('[data-demo]', (els) => els.map((e) => ({ id: e.dataset.demo, h: Math.round(e.getBoundingClientRect().height) })));
  const cls = await page.evaluate(() => ({ cls: +window.__cls.toFixed(4), shifts: window.__shifts }));
  const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
  const countdown = await page.$eval('[data-cmp="match-upcoming"] .ui-cd', (e) => e.getAttribute('aria-label'));

  // пары «макет | компонент»
  const pairs = [];
  if (MODE === 'img' || process.env.COMPARE === '1') {
    const dctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
    const dpage = await dctx.newPage();
    for (const [name, file, sel] of PAIRS) {
      await dpage.goto('file:///' + path.join(DESIGN, file).replace(/\\/g, '/'));
      await dpage.evaluate(() => document.fonts.ready);
      const dl = dpage.locator(sel).first();
      const ours = page.locator(`[data-cmp="${name}"] > *`).first();
      await ours.scrollIntoViewIfNeeded();
      const a = await dl.screenshot();
      const b = await ours.screenshot();
      const da = await dl.boundingBox();
      const db = await ours.boundingBox();
      pairs.push({ name, mock: `${Math.round(da.width)}x${Math.round(da.height)}`, ours: `${Math.round(db.width)}x${Math.round(db.height)}` });
      const html = `<!doctype html><html><body style="margin:0;background:#05070d;font:600 22px system-ui;color:#9AA4BC">
        <div style="display:flex;gap:24px;padding:20px;align-items:flex-start">
          <figure style="margin:0"><figcaption style="margin-bottom:10px">Макет · ${file} · ${pairs.at(-1).mock}</figcaption><img src="data:image/png;base64,${a.toString('base64')}" style="width:${da.width}px;display:block"></figure>
          <figure style="margin:0"><figcaption style="margin-bottom:10px">Компонент · ${name} · ${pairs.at(-1).ours}</figcaption><img src="data:image/png;base64,${b.toString('base64')}" style="width:${db.width}px;display:block"></figure>
        </div></body></html>`;
      const cpage = await dctx.newPage();
      await cpage.setViewportSize({ width: Math.ceil(da.width + db.width + 64), height: 400 });
      await cpage.setContent(html);
      await cpage.waitForLoadState('load');
      await cpage.screenshot({ path: path.join(CMP, `${name}.png`), fullPage: true });
      await cpage.close();
    }
    await dctx.close();
  }

  await browser.close();

  const own = new Set([new URL(BASE).host, 'data:']);
  const foreign = [...hosts.keys()].filter((h) => !own.has(h));
  const failedImgs = imgs.filter((i) => i.failed);
  const report = {
    mode: MODE,
    hosts: Object.fromEntries(hosts),
    foreignHosts: foreign,
    consoleErrors,
    consoleErrorsNotImg: consoleErrors.filter((e) => !/Failed to load resource/.test(e)),
    imgResponses: Object.fromEntries(imgResponses),
    images: { total: imgs.length, failed: failedImgs.length, loaded: imgs.length - failedImgs.length },
    failedVisible: failedImgs.filter((i) => i.visibility !== 'hidden').map((i) => i.src),
    withFrame: imgs.filter((i) => i.frame).map((i) => i.src),
    sizeMismatch: imgs.filter((i) => i.box !== i.attr && !i.src.includes('/player/')).map((i) => `${i.src} ${i.box} vs ${i.attr}`),
    notLazy: imgs.filter((i) => i.loading !== 'lazy' || i.decoding !== 'async').map((i) => i.src),
    noAlt: imgs.filter((i) => i.alt == null).map((i) => i.src),
    silhouettes,
    cls,
    scrollW,
    countdown,
    navHasDev: navLinks.some((h) => h && h.includes('/dev')),
    layout,
    pairs,
  };
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  const brief = { ...report, layout: undefined, imgResponses: undefined };
  console.log(JSON.stringify(brief, null, 2));
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
