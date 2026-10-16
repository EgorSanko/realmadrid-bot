// Снимки макетов экрана матча (design/screens/a-match-*.html) в том же размере, что и проверка: 390×844, scale 2.
// Запуск: NODE_PATH=C:/Users/egor3/node_modules node checks/screens-match/design.js
const path = require('path');
const { chromium } = require('playwright');

const DESIGN = path.resolve(__dirname, '..', '..', 'design', 'screens');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.route('**/*', (r) => (r.request().url().startsWith('file:') ? r.continue() : r.abort()));
  const page = await ctx.newPage();
  for (const f of ['a-match-events', 'a-match-lineup', 'a-match-stats', 'a-live']) {
    await page.goto('file:///' + path.join(DESIGN, `${f}.html`).replace(/\\/g, '/'));
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(__dirname, `design-${f}.png`), fullPage: true });
  }
  await browser.close();
})();
