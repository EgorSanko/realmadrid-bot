// Проверка этапа 0 против задеплоенной версии.
// Запуск: NODE_PATH=C:/Users/egor3/node_modules node checks/stage0/run.js
const path = require('path');
const { chromium } = require('playwright');

const DOMAIN = process.env.DOMAIN || 'realmadridfan.ru';
const IP = process.env.IP || '81.17.154.4';
const BASE = `http://${DOMAIN}`;
const OUT = __dirname;
const DESIGN = path.resolve(__dirname, '../../design/screens/a-home.html');

const TABS = [
  ['Главная', '/', 'home'],
  ['Матчи', '/matches', 'matches'],
  ['Команда', '/team', 'team'],
  ['Медиа', '/media', 'media'],
  ['Прогнозы', '/predict', 'predict'],
];

// метрики нижнего меню для сравнения с макетом
async function navMetrics(page, sel) {
  return page.evaluate((sel) => {
    const nav = document.querySelector(sel);
    const r = nav.getBoundingClientRect();
    const cs = getComputedStyle(nav);
    const links = [...nav.querySelectorAll('a')].map((a) => {
      const s = getComputedStyle(a);
      const svg = a.querySelector('svg').getBoundingClientRect();
      const ar = a.getBoundingClientRect();
      return {
        text: a.textContent.trim(),
        color: s.color,
        weight: s.fontWeight,
        size: s.fontSize,
        font: s.fontFamily.split(',')[0],
        x: Math.round(ar.x),
        w: Math.round(ar.width),
        svgY: Math.round(svg.y - r.y),
        svg: `${svg.width}x${svg.height}`,
        on: a.classList.contains('on') || a.getAttribute('aria-current') === 'page',
        paths: [...a.querySelectorAll('svg *')].map((p) => p.outerHTML.replace(/\s+/g, ' ')).join(''),
      };
    });
    return {
      top: Math.round(r.y),
      height: Math.round(r.height),
      bg: cs.backgroundColor,
      borderTop: cs.borderTopWidth + ' ' + cs.borderTopColor,
      bodyBg: getComputedStyle(document.body).backgroundColor,
      links,
    };
  }, sel);
}

(async () => {
  const browser = await chromium.launch({
    args: [`--host-resolver-rules=MAP ${DOMAIN} ${IP}`],
  });
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    locale: 'ru-RU',
  });
  const page = await ctx.newPage();

  const hosts = new Map();
  const consoleErrors = [];
  const failed = [];
  page.on('request', (req) => {
    const u = new URL(req.url());
    const key = u.protocol === 'data:' ? 'data:' : u.host;
    hosts.set(key, (hosts.get(key) || 0) + 1);
  });
  page.on('requestfailed', (r) => failed.push(r.url() + ' ' + r.failure()?.errorText));
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message));

  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);

  const results = [];
  for (const [label, route, name] of TABS) {
    await page.locator('nav.bottom-nav a', { hasText: label }).click();
    await page.waitForURL(BASE + route);
    await page.waitForFunction((l) => document.querySelector('nav.bottom-nav a.on')?.textContent.trim() === l && document.querySelector('h1'), label);
    await page.waitForFunction((l) => (document.querySelector('h1').textContent.trim() === l) || (l === 'Главная' && document.querySelector('h1').textContent.includes('МАДРИДИСТА')), label);
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => document.fonts.ready);
    const info = await page.evaluate(() => ({
      h1: document.querySelector('h1')?.textContent.trim(),
      empty: document.querySelector('.empty__title')?.textContent.trim(),
      active: document.querySelector('nav.bottom-nav a.on')?.textContent.trim(),
      activeColor: getComputedStyle(document.querySelector('nav.bottom-nav a.on')).color,
      title: document.title,
      scrollW: document.documentElement.scrollWidth,
    }));
    await page.screenshot({ path: path.join(OUT, `${name}.png`) });
    results.push({ route, ...info });
  }

  const fonts = await page.evaluate(async () => {
    await document.fonts.ready;
    return [...document.fonts]
      .map((f) => `${f.family.replace(/"/g, '')} ${f.weight} ${f.unicodeRange.startsWith('U+301') ? 'cyrillic' : 'latin'}: ${f.status}`);
  });

  const isTmaInBrowser = await page.evaluate(() => document.documentElement.classList.contains('tma'));
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  const appNav = await navMetrics(page, 'nav.bottom-nav');

  // макет — в отдельном контексте, его file:// запросы не смешиваем с проверкой хостов
  const dctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const dpage = await dctx.newPage();
  await dpage.goto('file:///' + DESIGN.replace(/\\/g, '/'));
  await dpage.evaluate(() => document.fonts.ready);
  const designNav = await navMetrics(dpage, 'nav');
  // макет: nav прибит к низу 844-высокого .phone-контейнера
  await browser.close();

  const own = new Set([DOMAIN, 'data:']);
  const foreign = [...hosts.keys()].filter((h) => !own.has(h));

  console.log('== Маршруты');
  for (const r of results) console.log(JSON.stringify(r));
  console.log('\n== Хосты запросов:', JSON.stringify(Object.fromEntries(hosts)));
  console.log('== Чужие хосты:', foreign.length ? foreign : '(нет)');
  console.log('== Неудачные запросы:', failed.length ? failed : '(нет)');
  console.log('== Ошибки консоли:', consoleErrors.length, consoleErrors);
  console.log('== Класс .tma в браузере:', isTmaInBrowser);
  console.log('\n== Загруженные шрифты (document.fonts: объявлены / loaded — реально скачаны браузером по требованию):');
  for (const f of fonts) console.log('  ' + f);

  console.log('\n== Нижнее меню: приложение vs макет a-home.html');
  const pick = (n) => ({ top: n.top, height: n.height, bg: n.bg, borderTop: n.borderTop, bodyBg: n.bodyBg });
  console.log('app   ', JSON.stringify(pick(appNav)));
  console.log('design', JSON.stringify(pick(designNav)));
  const diffs = [];
  for (const k of ['height', 'bg', 'borderTop']) if (appNav[k] !== designNav[k]) diffs.push(`${k}: ${appNav[k]} vs ${designNav[k]}`);
  appNav.links.forEach((a, i) => {
    const d = designNav.links[i];
    for (const k of ['text', 'color', 'weight', 'size', 'font', 'x', 'w', 'svgY', 'svg', 'on', 'paths'])
      if (a[k] !== d[k]) diffs.push(`${a.text}.${k}: ${k === 'paths' ? 'svg различается' : a[k] + ' vs ' + d[k]}`);
  });
  console.log('Расхождения:', diffs.length ? diffs : '(нет)');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
