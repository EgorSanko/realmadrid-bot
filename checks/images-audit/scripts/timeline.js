// Хронология /match/6106274: какие фамилии режутся многоточием (до / после).
// Запуск: node timeline.js <distDir>
const { open, settle, SITE } = require('./harness');

(async () => {
  const { browser, page } = await open(process.argv[2]);
  await page.goto(SITE + '/match/6106274', { waitUntil: 'domcontentloaded' });
  await settle(page);
  await page.evaluate(() => document.fonts.ready);
  await page.locator('[aria-label="Хронология"]').screenshot({ path: require('path').join(require('os').tmpdir(), 'tl.png') });
  const rows = await page.evaluate(() =>
    [...document.querySelectorAll('.ui-tl .ui-pin__name')].map((e) => {
      const r = document.createRange();
      r.selectNodeContents(e);
      const text = r.getBoundingClientRect().width;
      const box = e.getBoundingClientRect().width;
      return { name: e.textContent, text: Math.round(text * 10) / 10, box: Math.round(box * 10) / 10, cut: text > box + 0.05 }; // дробная нехватка даже в 0.4 px уже рисует «…»
    }),
  );
  console.log(JSON.stringify(rows.filter((r) => /Roon|Rüdiger/.test(r.name))));
  const cut = rows.filter((r) => r.cut);
  console.log('имён в хронологии:', rows.length, '| обрезано:', cut.length, JSON.stringify(cut));
  await browser.close();
})();
