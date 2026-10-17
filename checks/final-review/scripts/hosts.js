// Внешние хосты при прямом заходе на страницу в чистом контексте (без «хвоста» предыдущей страницы).
//   NODE_PATH=C:/Users/egor3/node_modules node hosts.js predict media home
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  for (const p of process.argv.slice(2)) {
    const ctx = await b.newContext({ viewport: { width: 390, height: 844 } });
    const page = await ctx.newPage();
    const hosts = new Set();
    page.on('request', (r) => { const u = new URL(r.url()); if (u.host !== 'realmadridfan.ru') hosts.add(u.host); });
    await page.goto('https://realmadridfan.ru/' + (p === 'home' ? '' : p));
    await page.waitForTimeout(7000);
    console.log(p, [...hosts].join(',') || '—');
    await ctx.close();
  }
  await b.close();
})();
