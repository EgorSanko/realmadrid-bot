// Откуда CLS на главной: сдвиги и их источники.
//   NODE_PATH=C:/Users/egor3/node_modules node cls.js [width] [height] [nginxBase]
const { chromium } = require('playwright');
(async () => {
  const w = +(process.argv[2] || 1440), h = +(process.argv[3] || 900);
  const NGX = process.argv[4];
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: w, height: h }, ...(w < 1024 ? { isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : {}) });
  if (NGX) await ctx.route('https://realmadridfan.ru/**', async (route) => {
    const u = new URL(route.request().url());
    if (u.pathname.startsWith('/api/') || u.pathname.startsWith('/img/')) return route.continue();
    const resp = await route.fetch({ url: NGX + u.pathname + u.search, headers: { ...route.request().headers(), host: new URL(NGX).host } });
    return route.fulfill({ response: resp });
  });
  const page = await ctx.newPage();
  await page.addInitScript(() => {
    window.__shifts = [];
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) {
        if (e.hadRecentInput) continue;
        window.__shifts.push({ t: Math.round(e.startTime), v: Math.round(e.value * 1000) / 1000,
          src: (e.sources || []).map((s) => {
            const n = s.node;
            const d = n && n.nodeType === 1 ? n.tagName.toLowerCase() + '.' + String(n.className).split(' ').slice(0, 2).join('.') : n ? '#text' : '?';
            return `${d} y${Math.round(s.previousRect.y)}→${Math.round(s.currentRect.y)} h${Math.round(s.previousRect.height)}→${Math.round(s.currentRect.height)}`;
          }) });
      }
    }).observe({ type: 'layout-shift', buffered: true });
  });
  await page.goto('https://realmadridfan.ru/');
  await page.waitForTimeout(9000);
  const s = await page.evaluate(() => window.__shifts);
  console.log('CLS', Math.round(s.reduce((a, x) => a + x.v, 0) * 1000) / 1000);
  for (const x of s) console.log(x.t, x.v, x.src.join(' | '));
  await b.close();
})();
