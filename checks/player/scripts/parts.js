// Снимки отдельных блоков (без нижнего меню поверх). node parts.js <dist> <out> <prefix>
const { open, settle, SITE } = require('./harness');
const path = require('path');

(async () => {
  const [dist, out, prefix] = process.argv.slice(2);
  const { browser, page, log } = await open(dist);
  const parts = [
    ['/', '.home-grid', 'home-form'],
    ['/', '.ui-mc-past', 'home-last'],
    ['/match/5868098', 'section[aria-label="Личные встречи"]', 'h2h'],
    ['/match/5868098', 'section[aria-label="Форма команд"]', 'form'],
    ['/match/5868098/lineups', 'section[aria-label="Не сыграют"]', 'unavailable'],
    ['/match/6106274/stats', '.mt-top', 'topbar-stats'],
    ['/match/6106274', '.mt-stars', 'stars'],
    ['/team', 'section[aria-label="Трансферы"]', 'transfers'],
    ['/team', '.tm-leaders', 'leaders'],
  ];
  let last = '';
  for (const [url, sel, name] of parts) {
    if (url !== last) { await page.goto(SITE + url); await settle(page, 1500); last = url; }
    const el = await page.$(sel);
    if (!el) { console.log('нет блока', name); continue; }
    await page.evaluate(() => { const n = document.querySelector('nav'); if (n) n.style.visibility = 'hidden'; });
    await el.screenshot({ path: path.join(out, `${prefix}-part-${name}.png`) });
  }
  console.log(JSON.stringify({ external: [...log.external], errors: log.errors }));
  await browser.close();
})();
