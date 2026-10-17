// Быстрая проба одной страницы: высота документа против низа подвала, занятость скелетонами.
//   NODE_PATH=C:/Users/egor3/node_modules node probe.js <path> [width] [height]
const { chromium } = require('playwright');
(async () => {
  const [, , p = '/', w = '1440', h = '900'] = process.argv;
  const b = await chromium.launch();
  const page = await b.newPage({ viewport: { width: +w, height: +h } });
  // путь без ведущего «/» (Git Bash переписывает /… в путь Windows): home → /
  await page.goto('https://realmadridfan.ru/' + (p === 'home' ? '' : p));
  await page.waitForSelector('#splash', { state: 'detached', timeout: 10000 }).catch(() => {});
  for (const t of [1000, 4000, 8000]) {
    await page.waitForTimeout(t === 1000 ? 1000 : t - 1000 * (t === 4000 ? 1 : 4));
    const r = await page.evaluate(() => {
      const f = document.querySelector('footer');
      const tall = [...document.querySelectorAll('body *')].map((e) => [e, e.getBoundingClientRect()]).filter(([, r]) => r.bottom + scrollY > document.documentElement.scrollHeight - 5 && r.height > 0)
        .map(([e, r]) => `${e.tagName.toLowerCase()}.${String(e.className).slice(0, 40)} top=${Math.round(r.top + scrollY)} h=${Math.round(r.height)} pos=${getComputedStyle(e).position}`).slice(0, 8);
      return { scrollH: document.documentElement.scrollHeight, bodyH: document.body.scrollHeight, footerBottom: f ? Math.round(f.getBoundingClientRect().bottom + scrollY) : null,
        busy: document.querySelectorAll('[aria-busy="true"]').length, imgsPending: [...document.images].filter((i) => !i.complete).length, tall };
    });
    console.log(t, JSON.stringify(r));
  }
  await b.close();
})();
