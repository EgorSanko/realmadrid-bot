// Главная и «Матчи» — своя сборка (frontend/dist) на живых данных боевого сервера, ничего не выкладывая.
// Запуск (после `npm run build` в frontend/):
//   NODE_PATH=C:/Users/egor3/node_modules node checks/screens-home/run.js
// realmadridfan.ru резолвится в 81.17.154.4; страница и /assets/* — из локального dist,
// /api/* и /img/* уходят на сервер. Любой другой хост — блокируется и считается внешним.
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const ORIGIN = 'http://realmadridfan.ru';
const HOST = 'realmadridfan.ru';
const DIST = path.resolve(__dirname, '../../frontend/dist');
const OUT = __dirname;
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json', '.ico': 'image/x-icon',
};

const results = [];
const check = (name, ok, extra = '') => {
  results.push({ name, ok: !!ok, extra });
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${name}${extra ? ' — ' + extra : ''}`);
};

(async () => {
  const browser = await chromium.launch({ args: [`--host-resolver-rules=MAP ${HOST} 81.17.154.4`] });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: 'ru-RU' });

  const hosts = new Map();
  const external = [];
  const consoleErrors = [];
  const expected503 = [];
  const apiHits = [];
  const imgStatus = new Map();
  /** подмена /api/home: null — как есть с сервера; иначе (route) => Promise */
  let homeOverride = null;

  await ctx.route('**/*', async (route) => {
    const req = route.request();
    const u = new URL(req.url());
    hosts.set(u.host, (hosts.get(u.host) || 0) + 1);
    if (u.host !== HOST) {
      external.push(req.url());
      return route.abort('blockedbyclient');
    }
    if (u.pathname.startsWith('/api/')) {
      apiHits.push({ path: u.pathname, t: Date.now() });
      if (u.pathname === '/api/home' && homeOverride) return homeOverride(route);
      return route.continue();
    }
    if (u.pathname.startsWith('/img/')) return route.continue();
    // своя сборка: файл из dist, иначе index.html (маршруты SPA)
    let file = path.join(DIST, decodeURIComponent(u.pathname));
    if (!file.startsWith(DIST) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(DIST, 'index.html');
    return route.fulfill({
      status: 200,
      body: fs.readFileSync(file),
      headers: { 'content-type': MIME[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' },
    });
  });

  const page = await ctx.newPage();
  let phase = 'live-data';
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    // в сценарии 503 браузер сам пишет «Failed to load resource: 503» — это ожидаемо и считается отдельно
    if (phase === '503' && /status of 503/.test(m.text())) return expected503.push(m.text());
    consoleErrors.push(`[${phase}] ${m.text()}`);
  });
  page.on('pageerror', (e) => consoleErrors.push(`[${phase}] pageerror: ${e.message}`));
  page.on('response', (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith('/img/')) imgStatus.set(u.pathname, r.status());
  });

  const settle = async () => {
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => document.fonts.ready);
    const h = await page.evaluate(() => document.documentElement.scrollHeight);
    for (let y = 0; y < h; y += 500) await page.evaluate((y) => window.scrollTo(0, y), y);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(250);
  };
  const noHScroll = async (label) => {
    const [sw, cw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    check(`нет горизонтальной прокрутки: ${label}`, sw <= cw, `${sw}/${cw}`);
  };
  // во весь рост фиксированное меню легло бы поверх середины страницы — переносим его в конец документа
  const shot = async (name) => {
    const h = await page.addStyleTag({ content: 'html{position:relative}.bottom-nav{position:absolute!important;bottom:0!important}' });
    await page.screenshot({ path: path.join(OUT, name), fullPage: true });
    await h.evaluate((el) => el.remove());
  };
  const text = () => page.evaluate(() => document.body.innerText);
  // тот же путь, что у приложения: через браузер и host-resolver-rules
  const getJson = (p) => page.evaluate((p) => fetch(p, { cache: 'no-store' }).then((r) => r.json()).catch(() => null), p);

  // ---------- 1. главная на живых данных ----------
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.hero-mc, .ui-state', { timeout: 15000 });
  await settle();
  await shot('01-home.png');
  await noHScroll('главная');
  const home = await getJson('/api/home');
  const t1 = await text();
  check('главная: карточка ближайшего матча', await page.locator('.hero-mc').count() === 1);
  if (home?.next) {
    check('главная: команды латиницей из API', t1.includes(home.next.home.name) && t1.includes(home.next.away.name),
      `${home.next.home.name} — ${home.next.away.name}`);
    check('главная: ссылка карточки на /match/:id', await page.locator(`a.hero-mc[href="/match/${home.next.id}"]`).count() === 1);
  }
  check('главная: время МСК', /МСК/.test(t1));
  check('главная: отсчёт', await page.locator('.hero-mc .ui-cd').count() === 1);
  check('главная: логотип турнира', await page.locator('.hero-mc .ui-chip img[src^="/img/league/"]').count() === 1);
  check('главная: эмблемы команд', await page.locator('.hero-mc img[src^="/img/team/"]').count() === 2);
  check('главная: блок трансляции на месте', await page.locator('section[aria-label="Трансляция"]').count() === 1);
  check('главная: прогноз → /predict', await page.locator('a.home-predict[href="/predict"]').count() === 1);
  check('главная: форма 5 матчей', await page.locator('.home-tile .ui-form__item').count() === (home?.form?.length >= 5 ? 5 : home?.form?.length ?? 0));
  if (home?.laliga) check('главная: место в Ла Лиге', t1.includes(`место · ${home.laliga.pts} очк.`), `${home.laliga.pos} место`);
  if (home?.last) check('главная: прошлый матч → /match/:id', await page.locator(`a.ui-mc-past[href="/match/${home.last.id}"]`).count() === 1);
  check('главная: новостей нет (их подключит «Медиа»)', !/Новости/.test(t1));
  // переход по прошлому матчу — через роутер, без перезагрузки
  if (home?.last) {
    const navs = [];
    page.on('framenavigated', (f) => f === page.mainFrame() && navs.push(f.url()));
    await page.evaluate(() => (window.__alive = 1));
    await page.locator('a.ui-mc-past').click();
    await page.waitForTimeout(300);
    const alive = await page.evaluate(() => window.__alive === 1);
    check('клик по прошлому матчу — SPA-переход без перезагрузки', alive);
    // /match/:id ещё не подключён (экран делает другой агент) — роутер вернёт на главную
    await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.hero-mc');
  }

  // ---------- 2. опрос и visibilitychange ----------
  apiHits.length = 0;
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await page.waitForTimeout(800);
  check('visibilitychange → сразу запрос /api/home', apiHits.some((h) => h.path === '/api/home'));

  // ---------- 3. «Матчи»: все вкладки ----------
  await page.goto(ORIGIN + '/matches', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.cal-row, .ui-state', { timeout: 15000 });
  await settle();
  await shot('02-matches-all.png');
  await noHScroll('матчи / все');
  const fx = await getJson('/api/fixtures');
  const tb = await getJson('/api/tables');
  check('матчи: первый ближайший в золотой рамке', await page.locator('.cal-row.ui-fx--next').count() === 1);
  check('матчи: строки ведут на /match/:id', await page.locator('.cal-row[href^="/match/"]').count() >= 1 &&
    await page.locator('a.ui-fx[href^="/match/"]').count() >= 2);
  check('матчи: результаты с В/Н/П', await page.locator('.ui-fx .ui-form__item').count() >= 1);
  check('матчи: таблица Ла Лиги с Реалом', await page.locator('section[aria-label="Таблица: Ла Лига"] tr.is-me').count() === 1);
  const hasUcl = (tb?.tables || []).some((t) => t.league.id === 42 && t.rows.length);
  check('матчи: таблица ЛЧ, если API её отдаёт', (await page.locator('section[aria-label="Таблица: Лига чемпионов"]').count() === 1) === hasUcl, `в API: ${hasUcl}`);
  const llRowsCollapsed = await page.locator('section[aria-label="Таблица: Ла Лига"] tbody tr').count();
  // «Весь календарь» раскрывает список
  const calBtn = page.locator('section[aria-label="Ближайшие матчи"] button.screen-more');
  if (await calBtn.count()) {
    const before = await page.locator('.cal-row').count();
    await calBtn.click();
    check('матчи: «Весь календарь» раскрывает список', (await page.locator('.cal-row').count()) > before);
    await calBtn.click();
  }
  await page.locator('section[aria-label="Таблица: Ла Лига"] button.screen-more').click();
  const llRowsFull = await page.locator('section[aria-label="Таблица: Ла Лига"] tbody tr').count();
  check('матчи: «Вся таблица» раскрывает таблицу целиком', llRowsFull > llRowsCollapsed, `${llRowsCollapsed} → ${llRowsFull}`);
  await settle();
  await shot('03-matches-all-full-table.png');
  await page.locator('section[aria-label="Таблица: Ла Лига"] button.screen-more').click();

  // кубковые матчи во «Все» с логотипом
  const cups = (fx?.matches || []).filter((m) => ![87, 42].includes(m.tournament.id) && !m.status.finished);
  if (cups.length) {
    await calBtn.click();
    const n = await page.locator(`.cal-row .ui-chip img[src="/img/league/${cups[0].tournament.id}.png"]`).count();
    check('матчи: Кубок/Суперкубок во «Все» с логотипом', n >= 1, cups[0].tournament.name);
    await calBtn.click();
  }

  await page.getByRole('tab', { name: 'Ла Лига' }).click();
  await settle();
  await shot('04-matches-laliga.png');
  await noHScroll('матчи / Ла Лига');
  check('вкладка Ла Лига: только ЛЛ, без таблицы ЛЧ',
    (await page.locator('.cal-row .ui-chip--ucl').count()) === 0 &&
    (await page.locator('section[aria-label="Таблица: Лига чемпионов"]').count()) === 0);

  await page.getByRole('tab', { name: 'Лига чемпионов' }).click();
  await settle();
  await shot('05-matches-ucl.png');
  await noHScroll('матчи / Лига чемпионов');
  check('вкладка ЛЧ: только ЛЧ, без таблицы Ла Лиги',
    (await page.locator('.cal-row .ui-chip:not(.ui-chip--ucl)').count()) === 0 &&
    (await page.locator('section[aria-label="Таблица: Ла Лига"]').count()) === 0);

  // ---------- 4. подмены /api/home ----------
  // основа подмен — живой ответ сервера, снятый через браузер (route.fetch идёт из Node, мимо host-resolver-rules)
  const baseHome = await getJson('/api/home');
  const real = async () => structuredClone(baseHome);

  // live
  phase = 'mock-live';
  homeOverride = async (route) => {
    const j = await real();
    j.next.status = { state: 'live', live: true, finished: false, minute: 67, added: null, label: "67'" };
    j.next.home.score = 2;
    j.next.away.score = 1;
    return route.fulfill({ status: 200, json: j });
  };
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.hero-mc--live', { timeout: 15000 });
  await settle();
  await shot('06-home-live.png');
  await noHScroll('главная / live');
  const tl = await page.locator('.hero-mc').innerText();
  check('live: счёт 2 : 1', tl.includes('2 : 1'));
  check('live: минута 67′', tl.includes('67′'));
  check('live: бейдж LIVE', await page.locator('.hero-mc .ui-badge--live').count() === 1);
  check('live: ссылка на /match/:id', await page.locator('a.hero-mc--live[href^="/match/"]').count() === 1);
  apiHits.length = 0;
  await page.waitForTimeout(11_500);
  const homeHits = apiHits.filter((h) => h.path === '/api/home').length;
  check('live: опрос /api/home раз в 10 с', homeHits >= 1 && homeHits <= 2, `${homeHits} запроса за 11.5 с`);

  phase = 'mock-finished';
  // итог сразу после свистка (last начался 2 ч назад)
  homeOverride = async (route) => {
    const j = await real();
    j.last.kickoff = new Date(Date.now() - 2 * 3600_000).toISOString().replace(/\.\d+Z$/, 'Z');
    return route.fulfill({ status: 200, json: j });
  };
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.hero-mc--finished', { timeout: 15000 });
  await settle();
  await shot('07-home-finished.png');
  check('итог: карточка «Матч завершён» со счётом', /Матч завершён/.test(await page.locator('.hero-mc').innerText()));
  check('итог: ниже — следующий матч, а не тот же ещё раз', await page.locator('section[aria-label="Следующий матч"] .cal-row').count() === 1 &&
    await page.locator('a.ui-mc-past').count() === 0);

  // stale
  phase = 'mock-stale';
  homeOverride = async (route) => {
    const j = await real();
    j.stale = true;
    j.age_s = 1800;
    return route.fulfill({ status: 200, json: j });
  };
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.hero-mc', { timeout: 15000 });
  await settle();
  await shot('08-home-stale.png');
  check('stale: «обновлено 30 мин назад»', /обновлено 30 мин назад/.test(await text()));

  // 503 → «Повторить» → данные
  phase = '503';
  homeOverride = (route) =>
    route.fulfill({ status: 503, json: { error: 'no_data', detail: 'fixtures: сборщик ещё не получил данные', available: [] } });
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.ui-state', { timeout: 15000 });
  await settle();
  await shot('09-home-503.png');
  await noHScroll('главная / 503');
  const t503 = await text();
  check('503: ErrorState «Данные ещё собираются»', /Данные ещё собираются/.test(t503));
  check('503: блок трансляции остаётся', await page.locator('section[aria-label="Трансляция"]').count() === 1);
  homeOverride = null;
  await page.getByRole('button', { name: 'Повторить' }).click();
  phase = 'retry';
  await page.waitForSelector('.hero-mc', { timeout: 15000 });
  check('503: «Повторить» загружает данные', true);

  // первая загрузка — скелетоны
  phase = 'skeleton';
  homeOverride = async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    return route.continue();
  };
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.ui-skeleton', { timeout: 5000 });
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(OUT, '10-home-skeleton.png') });
  check('первая загрузка: скелетоны', await page.locator('.ui-skeleton, .ui-skel').count() >= 3);
  await page.waitForSelector('.hero-mc', { timeout: 15000 });
  homeOverride = null;

  // ---------- итог ----------
  const brokenImgs = [...imgStatus].filter(([, s]) => s !== 200);
  check('внешних хостов — 0', external.length === 0, external.slice(0, 5).join(', '));
  check('ошибок консоли — 0', consoleErrors.length === 0, consoleErrors.slice(0, 5).join(' | '));
  console.log('ожидаемые сообщения о 503:', expected503.length);
  console.log('хосты:', JSON.stringify(Object.fromEntries(hosts)));
  console.log('картинки:', imgStatus.size, 'шт.; не 200:', JSON.stringify(brokenImgs));
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify({ results, hosts: Object.fromEntries(hosts), external, consoleErrors, images: Object.fromEntries(imgStatus) }, null, 1));
  await browser.close();
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed}/${results.length} проверок прошли`);
  process.exit(failed ? 1 : 0);
})().catch((e) => {
  console.error(e);
  process.exit(2);
});
