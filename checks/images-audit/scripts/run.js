// Ревизия картинок: каждый экран — счёт картинок, битые, внешние хосты, ошибки консоли,
// горизонтальная прокрутка; для изменённых мест — скриншоты элемента.
// Запуск: node run.js <before|after> <distDir> [localApiDir]
const fs = require('fs');
const path = require('path');
const { open, settle, imageStats, hscroll, SITE } = require('./harness');

const [, , label, distDir, localDir] = process.argv;
const OUT = path.resolve(__dirname, '..');
const SHOTS = path.join(OUT, label);

// экран → путь, места (селектор → имя скриншота), подготовка
const SCREENS = [
  {
    name: 'home', url: '/',
    places: [
      ['.home-predict', 'home-predict'],
      ['[aria-label="Таблица Ла Лиги"]', 'home-laliga-tile'],
      ['[aria-label="Форма"]', 'home-form'],
      ['.ui-mc-past', 'home-last-match'],
    ],
  },
  {
    // «Следующий матч» (CalendarRow) виден, только когда сверху итог только что сыгранного матча:
    // подставляем ответу /api/home last.kickoff = 2 ч назад
    name: 'home-just-finished', url: '/', homeJustFinished: true,
    places: [['.home-next', 'home-next-calendar-row']],
  },
  {
    name: 'matches-tables', url: '/matches', click: 'role=tab[name="Таблица"]',
    places: [
      ['[aria-label="Таблица: Ла Лига"]', 'matches-table-laliga'],
      ['[aria-label="Таблица: Лига чемпионов"]', 'matches-table-ucl'],
    ],
  },
  { name: 'matches-calendar', url: '/matches', places: [] },
  {
    name: 'match-finished-overview', url: '/match/6106274',
    places: [
      ['[aria-label="Хронология"]', 'match-timeline'],
      ['.mt-about', 'match-about'],
    ],
  },
  {
    name: 'match-finished-lineups', url: '/match/6106274/lineups',
    places: [
      ['.mt-lu-head', 'match-lineups-head'],
      ['[aria-label="Замены"]', 'match-lineups-subs-bench'],
      ['[aria-label="Не играли"]', 'match-lineups-coach'],
    ],
  },
  {
    name: 'match-finished-stats', url: '/match/6106274/stats',
    places: [['[aria-label="Статистика"]', 'match-stats-head', { height: 200 }]],
  },
  {
    name: 'match-upcoming-overview', url: '/match/5868098',
    places: [
      ['[aria-label="Форма команд"]', 'match-upcoming-form'],
      ['.mt-about', 'match-upcoming-about'],
      ['[aria-label="Личные встречи"]', 'match-upcoming-h2h'],
    ],
  },
  {
    name: 'match-upcoming-lineups', url: '/match/5868098/lineups',
    places: [['[aria-label="Не сыграют"]', 'match-upcoming-coach']],
  },
  {
    name: 'team', url: '/team',
    places: [
      ['[aria-label="Состав"]', 'team-squad-coach', { height: 330 }],
      ['[aria-label="Трансферы"]', 'team-transfers', { height: 420 }],
    ],
  },
  { name: 'player-mbappe', url: '/player/701154', places: [] },
  { name: 'player-mbappe-career', url: '/player/701154', click: 'role=tab[name="Карьера"]', places: [] },
  { name: 'media', url: '/media', places: [] },
  { name: 'media-video', url: '/media?tab=video', places: [] },
  { name: 'admin', url: '/admin', places: [] },
];

async function homeJustFinished(context) {
  await context.route(`${SITE}/api/home`, async (route) => {
    const r = await route.fetch();
    const b = await r.json();
    if (b.last) b.last.kickoff = new Date(Date.now() - 2 * 3600_000).toISOString();
    return route.fulfill({ status: 200, headers: { 'content-type': 'application/json' }, body: JSON.stringify(b) });
  });
}

(async () => {
  const report = { label, dist: distDir, localApi: localDir || null, screens: {} };
  for (const s of SCREENS) {
    const { browser, context, page, log } = await open(distDir, { localDir });
    if (s.homeJustFinished) await homeJustFinished(context);
    await page.goto(SITE + s.url, { waitUntil: 'domcontentloaded' });
    await settle(page);
    if (s.click) {
      await page.locator(s.click).first().click().catch((e) => log.errors.push('click: ' + e.message));
      await settle(page);
    }
    const stats = await imageStats(page);
    const hs = await hscroll(page);
    // обрезанные многоточием имена: ширина текста (Range) больше ширины элемента
    const ellipsis = await page.evaluate(() =>
      [...document.querySelectorAll('.ui-tl__line .ui-pin__name, .ui-table__nm, .cal-row__nm, .mt-bench__who .ui-pin__name, .mt-coach__name')]
        .filter((e) => {
          const r = document.createRange();
          r.selectNodeContents(e);
          return r.getBoundingClientRect().width > e.getBoundingClientRect().width + 0.05;
        })
        .map((e) => e.textContent),
    );
    const shots = [];
    // для скриншотов мест — без нижней навигации поверх длинных карточек
    // и без заставки #splash (она уходит анимацией и на полностраничном снимке ещё видна)
    await page.addStyleTag({ content: '#splash{display:none!important}' + (s.places.length ? '.bottom-nav{display:none!important}' : '') });
    for (const [sel, name, opt] of s.places) {
      const loc = page.locator(sel).first();
      if (!(await loc.count())) {
        shots.push(name + ': нет на экране');
        continue;
      }
      const file = path.join(SHOTS, name + '.png');
      // кадр из полностраничного снимка по координатам документа: фиксированные шапка и
      // затемнения поверх прокрученной карточки не попадают в кадр
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(200);
      const r = await loc.evaluate((el) => {
        const b = el.getBoundingClientRect();
        return { x: b.left + window.scrollX, y: b.top + window.scrollY, width: b.width, height: b.height };
      });
      fs.mkdirSync(SHOTS, { recursive: true });
      const h = opt && opt.height ? Math.min(r.height, opt.height) : r.height;
      await page.screenshot({ path: file, fullPage: true, clip: { x: Math.max(0, r.x - 4), y: Math.max(0, r.y - 4), width: Math.min(390, r.width + 8), height: h + 8 } });
      shots.push(name);
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    fs.mkdirSync(SHOTS, { recursive: true });
    // полностраничные снимки — только по FULL=1 (тяжёлые, в репозиторий не кладём)
    if (process.env.FULL) await page.screenshot({ path: path.join(SHOTS, 'full-' + s.name + '.png'), fullPage: true });
    report.screens[s.name] = {
      url: s.url,
      images: stats.visible,
      byKind: stats.by,
      broken: stats.broken,
      hiddenFailed: stats.failedHidden,
      hscroll: hs,
      truncated: ellipsis,
      external: [...log.external],
      consoleErrors: log.errors,
      failedRequests: log.failed.filter((f) => !/ERR_ABORTED/.test(f)),
      merged: log.merged,
      shots,
    };
    console.log(`${s.name}: img=${stats.visible} ${JSON.stringify(stats.by)} broken=${stats.broken.length} hidden=${stats.failedHidden} hscroll=${hs} ext=${log.external.size} err=${log.errors.length} trunc=${JSON.stringify(ellipsis)}`);
    await browser.close();
  }
  fs.writeFileSync(path.join(OUT, `report-${label}.json`), JSON.stringify(report, null, 1));
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
