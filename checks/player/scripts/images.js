// Скриншоты мест, где появляются картинки: до/после. node images.js <dist> <out> <prefix>
const { open, settle, hscroll, shot, SITE } = require('./harness');

(async () => {
  const [dist, out, prefix] = process.argv.slice(2);
  const { browser, page, log } = await open(dist);
  const pages = [
    ['home', '/'],
    ['match-overview', '/match/6106274'],
    ['match-lineups', '/match/6106274/lineups'],
    ['match-upcoming', '/match/5868098'],
    ['team', '/team'],
  ];
  const res = {};
  for (const [name, url] of pages) {
    await page.goto(SITE + url);
    await settle(page, 1800);
    res[name] = { hscroll: await hscroll(page) };
    await shot(page, out, `${prefix}-${name}`);
  }
  console.log(JSON.stringify({ res, external: [...log.external], errors: log.errors, failed: log.failed }, null, 1));
  await browser.close();
})();
