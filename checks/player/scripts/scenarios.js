// Сценарии карточки игрока. node scenarios.js <dist> <out>
const { open, settle, hscroll, shot, SITE } = require('./harness');

const report = [];
function check(name, ok, info = '') {
  report.push({ name, ok: !!ok, info });
}

async function cardShots(page, out, prefix) {
  // карточка — слой .pc со своей прокруткой: снимаем верх, потом каждую вкладку
  await shot(page, out, `${prefix}-top`, false);
  const tabs = await page.$$('.pc [role=tab]');
  for (let i = 0; i < tabs.length; i++) {
    const label = (await tabs[i].textContent()).trim();
    await tabs[i].click();
    await page.waitForTimeout(400);
    // разворачиваем слой на всю высоту содержимого, чтобы снять целиком
    const h = await page.evaluate(() => document.querySelector('.pc-in').scrollHeight);
    await page.setViewportSize({ width: 390, height: Math.max(844, Math.min(h, 4000)) });
    await page.waitForTimeout(300);
    await shot(page, out, `${prefix}-tab${i + 1}-${label.replace(/\s+/g, '_')}`, false);
    check(`${prefix}: вкладка «${label}» без горизонтальной прокрутки`,
      (await page.evaluate(() => { const e = document.querySelector('.pc'); return e.scrollWidth - e.clientWidth; })) === 0);
    await page.setViewportSize({ width: 390, height: 844 });
  }
  return tabs.length;
}

(async () => {
  const [dist, out] = process.argv.slice(2);
  const { browser, page, log } = await open(dist);

  // 1. Команда → Mbappé (строка состава); «назад» — к той же прокрутке
  await page.goto(SITE + '/team');
  await settle(page);
  const row = page.locator('.tm-list a[aria-label="Kylian Mbappé — карточка игрока"]');
  await row.scrollIntoViewIfNeeded();
  const scrollBefore = await page.evaluate(() => window.scrollY);
  await shot(page, out, '1-team-before-click', false);
  await row.click();
  await page.waitForSelector('.pc-hero__name');
  await settle(page, 800);
  check('1: URL /player/701154', page.url().endsWith('/player/701154'), page.url());
  check('1: имя Kylian Mbappé', (await page.textContent('.pc-hero__name')) === 'Kylian Mbappé');
  check('1: фон «Команда» остался под карточкой', await page.$('.tm-list') != null);
  check('1: фото, эмблема клуба, флаг — с /img/', await page.evaluate(() =>
    ['.pc-hero__photo img', '.pc-hero__row img.ui-crest', '.pc-hero__row img.ui-flag'].every((s) => {
      const i = document.querySelector(s); return i && new URL(i.src).pathname.startsWith('/img/'); })));
  const tabs1 = await cardShots(page, out, '1-mbappe');
  check('1: три вкладки', tabs1 === 3, String(tabs1));
  await page.click('.pc-top__back');
  await page.waitForSelector('.pc', { state: 'detached' });
  await page.waitForTimeout(300);
  const scrollAfter = await page.evaluate(() => window.scrollY);
  check('6: «назад» → /team, прокрутка та же', page.url().endsWith('/team') && Math.abs(scrollAfter - scrollBefore) < 2, `${scrollBefore} → ${scrollAfter}`);

  // 3. Команда → лазарет (Rodrygo, блок травмы)
  const inj = page.locator('section[aria-label="Лазарет"] a[aria-label="Rodrygo — карточка игрока"]');
  await inj.scrollIntoViewIfNeeded();
  await inj.click();
  await page.waitForSelector('.pc-hero__name');
  await settle(page, 600);
  check('3: блок травмы показан', await page.$('.pc-status') != null, await page.textContent('.pc-status').catch(() => ''));
  await shot(page, out, '3-rodrygo-injury', false);
  await page.goBack();
  await page.waitForSelector('.pc', { state: 'detached' });
  check('6: системный «назад» браузера тоже закрывает карточку', page.url().endsWith('/team'));

  // лидеры
  const lead = page.locator('.tm-leaders a').first();
  await page.evaluate(() => window.scrollTo(0, 0));
  await lead.click();
  await page.waitForSelector('.pc-hero__name');
  check('3: лидер сезона открывает карточку', /\/player\/\d+$/.test(page.url()), page.url());
  await page.keyboard.press('Escape');
  await page.waitForSelector('.pc', { state: 'detached' });

  // 2. Чужой игрок из состава Ромы: сначала pending, потом данные
  await page.goto(SITE + '/match/6106274/lineups');
  await settle(page);
  await page.click('.mt-lu-head [role=tab]:has-text("Roma")');
  await page.waitForTimeout(500);
  await shot(page, out, '2-roma-lineup', true);
  const dyb = page.locator('.ui-pitch a[aria-label="Dybala — карточка игрока"]');
  check('2: Dybala на поле — ссылка', (await dyb.count()) === 1);
  const before = log.playerCalls.length;
  await dyb.click();
  await page.waitForSelector('.pc-wait__title', { timeout: 5000 });
  const waitText = await page.textContent('.pc-wait__title');
  check('2: сначала «Загружаем данные игрока…»', waitText.includes('Загружаем данные игрока'), waitText);
  await shot(page, out, '2-dybala-pending', false);
  // во время ожидания в шапке уже стоит имя из ссылки («Dybala»); данные — когда пропал блок ожидания
  await page.waitForSelector('.pc-wait__title', { state: 'detached', timeout: 25000 });
  await settle(page, 800);
  const calls = log.playerCalls.slice(before);
  check('2: потом данные (повтор запроса)', (await page.textContent('.pc-hero__name')) === 'Paulo Dybala', `запросов: ${calls.length}`);
  await cardShots(page, out, '2-dybala');
  await page.click('.pc-top__back');
  await page.waitForSelector('.pc', { state: 'detached' });
  const selected = await page.textContent('.mt-lu-head [role=tab][aria-selected=true]');
  check('6: «назад» → составы, выбрана всё ещё Roma', page.url().endsWith('/match/6106274/lineups') && selected.trim() === 'Roma', selected);

  // замены и «Не играли»
  const sub = page.locator('section[aria-label="Замены"] a.mt-li').first();
  check('2: замены нажимаются', (await sub.count()) === 1);
  await shot(page, out, '2-roma-subs', true);
  // у матча с Ромой список «Не играли» пуст — проверяем на ближайшем матче (Севилья): «Не сыграют»
  await page.goto(SITE + '/match/5868098/lineups');
  await settle(page);
  const outLinks = await page.locator('.mt-out a.ui-ptap').count();
  check('2: «Не играли» — фото + ссылки', outLinks > 0, String(outLinks));
  await shot(page, out, '2-unavailable-sevilla', true);

  // 4. Автор гола в хронологии
  await page.goto(SITE + '/match/6106274');
  await settle(page);
  const goal = page.locator('.ui-tl a[aria-label="Mbappé — карточка игрока"]').first();
  await goal.scrollIntoViewIfNeeded();
  await shot(page, out, '4-timeline', true);
  await goal.click();
  await page.waitForSelector('.pc-hero__name');
  check('4: автор гола → карточка Mbappé', page.url().endsWith('/player/701154'));
  await page.click('.pc-top__back');
  await page.waitForSelector('.pc', { state: 'detached' });
  const assist = page.locator('.ui-tl .ui-tl__sub a.ui-ptap').first();
  const assistName = await assist.getAttribute('aria-label');
  await assist.click();
  await page.waitForSelector('.pc-hero__name, .pc-wait__title');
  check('4: ассистент тоже нажимается', /\/player\/\d+$/.test(page.url()), assistName);
  await page.click('.pc-top__back');
  await page.waitForSelector('.pc', { state: 'detached' });
  const star = page.locator('.mt-star a.ui-ptap');
  check('4: «Лучший у Реала» и «Игрок матча» — ссылки', (await star.count()) === 2, String(await star.count()));
  await star.first().click();
  await page.waitForSelector('.pc-hero__name, .pc-wait__title');
  check('4: «Лучший у Реала» открывает карточку', /\/player\/\d+$/.test(page.url()), page.url());
  // из карточки — на матч
  await page.waitForSelector('.pc-hero__name', { timeout: 20000 });
  const mtab = page.locator('.pc [role=tab]:has-text("Последние матчи")');
  await mtab.click();
  const firstMatch = page.locator('a.pc-rm').first();
  const mhref = await firstMatch.getAttribute('href');
  await firstMatch.click();
  await page.waitForSelector('.pc', { state: 'detached' });
  check('карточка → матч по нажатию строки', page.url().endsWith(mhref), `${mhref} → ${page.url()}`);

  // 5. Прямой заход
  const p2 = await page.context().newPage();
  p2.on('console', (m) => { if (m.type() === 'error') log.errors.push('p2: ' + m.text()); });
  p2.on('request', (r) => { const u = new URL(r.url()); if (u.protocol.startsWith('http') && u.host !== 'realmadridfan.ru') log.external.add(u.host); });
  await p2.goto(SITE + '/player/701154');
  await p2.waitForSelector('.pc-hero__name');
  await settle(p2, 800);
  check('5: прямой заход /player/701154', (await p2.textContent('.pc-hero__name')) === 'Kylian Mbappé');
  check('5: горизонтальной прокрутки нет', (await hscroll(p2)) === 0);
  await shot(p2, out, '5-direct', false);
  await p2.click('.pc-top__back');
  await p2.waitForURL(/\/team$/);
  check('6: «назад» при прямом заходе → /team (не из приложения)', p2.url().endsWith('/team'), p2.url());

  // несуществующий игрок → 404-экран
  await p2.goto(SITE + '/player/999999996');
  await p2.waitForSelector('.ui-state', { timeout: 25000 });
  await settle(p2, 300);
  await shot(p2, out, '7-not-found', false);
  check('7: неизвестный id → «Игрок не найден»', (await p2.textContent('.ui-state__title')).includes('не найден'), await p2.textContent('.ui-state__title'));

  check('внешних хостов — 0', log.external.size === 0, [...log.external].join(','));
  // 404 по /api/player/999999996 — ожидаемый ответ, браузер пишет его в консоль как ошибку ресурса
  const errs = log.errors.filter((e) => !/status of 404/.test(e));
  check('ошибок консоли — 0 (кроме ожидаемого 404 несуществующего игрока)', errs.length === 0, JSON.stringify(log.errors));
  console.log(JSON.stringify({ report, failed: log.failed, playerCalls: log.playerCalls.length }, null, 1));
  await browser.close();
})().catch((e) => { console.error('FATAL', e); console.log(JSON.stringify({ report }, null, 1)); process.exit(1); });
