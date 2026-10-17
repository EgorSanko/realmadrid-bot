// Почему фото в «Команде» на ПК иногда пустые: состояние <img> лидеров и лазарета.
//   NODE_PATH=C:/Users/egor3/node_modules node probe-img.js [width]
const { chromium } = require('playwright');
(async () => {
  const w = +(process.argv[2] || 1280);
  const b = await chromium.launch();
  const page = await b.newPage({ viewport: { width: w, height: 800 } });
  const reqs = [];
  page.on('requestfinished', async (r) => { if (r.url().includes('/img/player/')) reqs.push(r.url().split('/').pop()); });
  page.on('requestfailed', (r) => { if (r.url().includes('/img/player/')) reqs.push('FAILED ' + r.url().split('/').pop() + ' ' + r.failure().errorText); });
  await page.goto('https://realmadridfan.ru/team');
  await page.waitForTimeout(8000);
  const s = await page.evaluate(() => [...document.querySelectorAll('.tm-leader img, .tm-inj img, [class*="inj"] img, [class*="leader"] img')].slice(0, 12).map((i) => {
    const cs = getComputedStyle(i);
    const r = i.getBoundingClientRect();
    return `${i.getAttribute('src')} loading=${i.loading} complete=${i.complete} nw=${i.naturalWidth} op=${cs.opacity} vis=${cs.visibility} y=${Math.round(r.top)} ${i.className}`;
  }));
  console.log(s.join('\n'));
  console.log('requests', reqs.length, reqs.filter((x) => x.startsWith('FAILED')).join(' '));
  await page.screenshot({ path: process.env.TEMP + '/probe-team.png' });
  await b.close();
})();
