// plan.html → PDF A4; любые внешние запросы блокируются и печатаются
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const external = [];
  await page.route('**/*', (r) => {
    const u = r.request().url();
    if (u.startsWith('file:') || u.startsWith('data:')) return r.continue();
    external.push(u); return r.abort();
  });
  await page.goto('file:///' + path.join(__dirname, 'plan.html').replace(/\\/g, '/'));
  await page.evaluate(() => document.fonts.ready);
  const out = path.join(__dirname, 'Мадридиста — исследование и план.pdf');
  await page.pdf({ path: out, format: 'A4', printBackground: true });
  console.log('внешние запросы:', external.length ? external : 'НЕТ');
  console.log('PDF:', out, Math.round(fs.statSync(out).size / 1024), 'КБ');
  await browser.close();
})();
