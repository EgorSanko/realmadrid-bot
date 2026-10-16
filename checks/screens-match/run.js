// Проверка экрана матча против настоящего сервера.
// Сборка — своя (frontend/dist, подкладывается через route), /api/* и /img/* — с сервера.
// Запуск: NODE_PATH=C:/Users/egor3/node_modules node checks/screens-match/run.js
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const OUT = __dirname;
const ROOT = path.resolve(__dirname, '..', '..');
const DIST = path.join(ROOT, 'frontend', 'dist');
const FIX = path.join(ROOT, 'frontend', 'src', '__fixtures__');
const HOST = 'realmadridfan.ru';
// с 17.10 сервер отдаёт 301 http → https; схему можно переопределить: SCHEME=http
const ORIGIN = `${process.env.SCHEME || 'https'}://${HOST}`;
const MIME = { '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.png': 'image/png', '.html': 'text/html' };

const log = (...a) => console.log(...a);
const results = [];
const check = (name, ok, extra = '') => {
  results.push({ name, ok });
  log(`${ok ? 'OK  ' : 'FAIL'} ${name}${extra ? ' — ' + extra : ''}`);
};

function serveDist(route) {
  const u = new URL(route.request().url());
  let file = path.join(DIST, decodeURIComponent(u.pathname));
  if (!u.pathname.startsWith('/assets/') || !file.startsWith(DIST) || !fs.existsSync(file)) file = path.join(DIST, 'index.html');
  return route.fulfill({
    status: 200,
    body: fs.readFileSync(file),
    headers: { 'content-type': MIME[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' },
  });
}

/* ---------- снимки для лайва: из реального ответа 6106274 ---------- */
const FULL = JSON.parse(fs.readFileSync(path.join(FIX, 'match_6106274.json'), 'utf8'));
function liveSnap(minute, state = 'live') {
  const events = FULL.events.filter((e) => (e.minute ?? 0) <= minute && e.type !== 'period' && e.type !== 'added_time');
  if (minute > 45) events.splice(events.findIndex((e) => (e.minute ?? 0) > 45), 0, FULL.events.find((e) => e.type === 'period' && e.label === 'HT'));
  const goals = events.filter((e) => e.type === 'goal');
  const sc = goals.length ? goals[goals.length - 1].score : [0, 0];
  return {
    ...FULL,
    status: { state, live: true, finished: false, minute: state === 'halftime' ? null : minute, added: null, label: `${minute}'` },
    home: { ...FULL.home, score: sc[0] },
    away: { ...FULL.away, score: sc[1] },
    events,
    highlights: null,
    potm: null,
    shots: FULL.shots.filter((s) => (s.minute ?? 0) <= minute),
    momentum: FULL.momentum.filter((p) => p.minute <= minute),
    available: FULL.available.filter((k) => k !== 'highlights' && k !== 'potm'),
    age_s: 2,
    stale: false,
  };
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ args: [`--host-resolver-rules=MAP ${HOST} 81.17.154.4`] });
  // часовой пояс устройства — не Москва: время на экране всё равно должно быть МСК
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: 'ru-RU', timezoneId: 'Europe/London' });

  const external = new Map();
  const consoleErrors = [];
  const imgStatus = new Map();
  await ctx.route('**/*', (route) => {
    const u = new URL(route.request().url());
    if (u.host !== HOST) {
      external.set(u.host, (external.get(u.host) || 0) + 1);
      return route.abort();
    }
    if (u.pathname.startsWith('/api/') || u.pathname.startsWith('/img/')) return route.continue();
    return serveDist(route);
  });
  ctx.on('response', (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith('/img/')) imgStatus.set(u.pathname, r.status());
  });
  const watch = (p, name) => {
    p.on('console', (m) => {
      if (m.type() !== 'error') return;
      const t = m.text();
      // 404 картинки — ожидаемо (компонент прячет её); остальное — ошибка
      if (/Failed to load resource.*404/.test(t)) return;
      // 503 — подстроенный в проверке ответ «сборщик пуст»
      if (name === 'states' && /Failed to load resource.*503/.test(t)) return;
      consoleErrors.push(`[${name}] ${t}`);
    });
    p.on('pageerror', (e) => consoleErrors.push(`[${name}] pageerror: ${e.message}`));
  };

  const page = await ctx.newPage();
  watch(page, 'main');
  const noHScroll = async (label) => {
    const r = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
    check(`нет горизонтальной прокрутки: ${label}`, r.sw <= r.cw, `${r.sw}/${r.cw}`);
  };
  const settle = async () => {
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(300);
  };

  for (const id of [6106274, 5868098]) {
    for (const [tab, suffix] of [['overview', ''], ['lineups', '/lineups'], ['stats', '/stats']]) {
      await page.goto(`${ORIGIN}/match/${id}${suffix}`);
      await page.waitForSelector('.mt-body, .mt-state', { timeout: 15000 });
      await settle();
      // для полноэкранного снимка нижнее меню ставим в конец страницы, иначе fixed-панель закрывает середину кадра
      const nav = await page.addStyleTag({ content: '.bottom-nav{position:static!important}' });
      await page.screenshot({ path: path.join(OUT, `${id}-${tab}.png`), fullPage: true });
      await nav.evaluate((n) => n.remove());
      await noHScroll(`${id} ${tab}`);
    }
  }

  /* ---------- содержимое 6106274 ---------- */
  await page.goto(`${ORIGIN}/match/6106274`);
  await page.waitForSelector('.mt-body');
  await settle();
  const ov = await page.evaluate(() => ({
    title: document.querySelector('.mt-top__title')?.textContent,
    score: document.querySelector('.ui-score-head__score')?.textContent,
    status: document.querySelector('.ui-score-head__status')?.textContent,
    scorers: [...document.querySelectorAll('.ui-score-head__scorers span')].map((s) => s.textContent),
    video: document.querySelector('.mt-video a')?.getAttribute('target'),
    thumb: document.querySelector('.mt-video img')?.getAttribute('src') ?? null,
    tl: document.querySelectorAll('.ui-tl__row').length,
    half: [...document.querySelectorAll('.ui-tl__half')].map((x) => x.textContent),
    about: [...document.querySelectorAll('.mt-about__row')].map((x) => x.textContent),
    stars: [...document.querySelectorAll('.mt-star')].map((x) => x.textContent),
    h2h: !!document.querySelector('.mt-h2h'),
  }));
  log('Обзор 6106274:', JSON.stringify(ov));
  check('шапка: турнир и тур', ov.title === 'Лига чемпионов · 2-й тур', ov.title);
  check('шапка: счёт 3 : 4, «Матч завершён · 14 окт»', ov.score === '3 : 4' && ov.status === 'Матч завершён · 14 окт');
  check('видеообзор открывается в новой вкладке', ov.video === '_blank');
  check('хронология: 24+ строк, перерыв 1:1', ov.tl >= 20 && ov.half[0] === 'Перерыв · 1:1', `${ov.tl} строк`);
  check('после матча нет личных встреч', !ov.h2h);

  // составы: оси поля
  await page.getByRole('tab', { name: 'Составы' }).click();
  await page.waitForFunction(() => location.pathname.endsWith('/lineups'));
  await page.waitForSelector('.ui-pitch');
  await settle();
  const pos = await page.evaluate(() => {
    const out = {};
    const box = document.querySelector('.ui-pitch').getBoundingClientRect();
    for (const li of document.querySelectorAll('.ui-pl')) {
      const r = li.querySelector('.ui-pl__shirt').getBoundingClientRect();
      out[li.querySelector('.ui-pl__nm').textContent] = {
        x: +(((r.left + r.width / 2 - box.left) / box.width) * 100).toFixed(1),
        y: +(((r.top + r.height / 2 - box.top) / box.height) * 100).toFixed(1),
      };
    }
    return { out, team: document.querySelector('.ui-tabs--pill .is-on')?.textContent };
  });
  log('Поле (Реал), % от левого/верхнего края:', JSON.stringify(pos));
  const P = pos.out;
  check('составы: Реал выбран первым', pos.team === 'Real Madrid');
  check('Pitch: вратарь внизу, нападающий вверху', P.Courtois.y > 80 && P['Mbappé'].y < 20);
  check('Pitch: Dumfries справа, Cucurella слева', P.Dumfries.x > 75 && P.Cucurella.x < 25);
  check('Pitch: Vinícius слева', P['Vinícius'].x < 25);

  // статистика: карта ударов
  await page.getByRole('tab', { name: 'Статистика' }).click();
  await page.waitForFunction(() => location.pathname.endsWith('/stats'));
  await page.waitForSelector('.ui-shots');
  const sm = await page.evaluate(() => {
    const c = [...document.querySelectorAll('.ui-shots circle')].map((e) => ({ cx: +e.getAttribute('cx'), cy: +e.getAttribute('cy'), r: +e.getAttribute('r'), goal: e.getAttribute('fill') !== 'none' }));
    return {
      c,
      summary: [...document.querySelectorAll('section[aria-label="Карта ударов"] .mt-small')].map((x) => x.textContent)[0],
      hi: [...document.querySelectorAll('.ui-st__v.is-hi')].map((e) => getComputedStyle(e).color)[0],
      periods: [...document.querySelectorAll('.mt-periods .ui-tabs__tab')].map((e) => e.textContent),
    };
  });
  log('Карта ударов:', sm.summary, '| голы:', JSON.stringify(sm.c.filter((x) => x.goal)));
  check('ShotMap: все удары в верхней (атакующей) части', sm.c.every((x) => x.cy < 130), `max cy ${Math.max(...sm.c.map((x) => x.cy))}`);
  const espi = sm.c.find((x) => x.r > 9);
  check('ShotMap: гол Espí (xG 0.45) — у ворот, x как в макете (173)', espi && espi.cy < 15 && Math.abs(espi.cx - 173) < 3, JSON.stringify(espi));
  check('подпись карты «16 ударов · xG 1.43»', sm.summary === '16 ударов · xG 1.43');
  check('лучшее значение — белым', sm.hi === 'rgb(238, 241, 247)', sm.hi);
  check('периоды Матч / 1-й тайм / 2-й тайм', sm.periods.join('/') === 'Матч/1-й тайм/2-й тайм');
  await page.getByRole('tab', { name: '2-й тайм' }).click();
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(OUT, '6106274-stats-2nd-half.png'), fullPage: true });

  // 6106274 завершён — без опроса
  let polls = 0;
  const countPolls = (r) => new URL(r.url()).pathname === '/api/match/6106274' && polls++;
  page.on('request', countPolls);
  await page.waitForTimeout(12000);
  page.off('request', countPolls);
  check('завершённый матч: без опроса за 12 с', polls === 0, `${polls} запросов`);

  // «назад» при прямом заходе — в календарь
  await page.goto(`${ORIGIN}/match/6106274/stats`);
  await page.waitForSelector('.mt-top__back');
  await page.click('.mt-top__back');
  await page.waitForFunction(() => location.pathname === '/matches');
  check('«назад» при прямом заходе → /matches', page.url().endsWith('/matches'));
  // «назад» после перехода внутри приложения — navigate(-1)
  await page.goto(`${ORIGIN}/matches`);
  await page.evaluate(() => {
    history.pushState({ usr: null, key: 'k1', idx: 1 }, '', '/match/5868098');
    dispatchEvent(new PopStateEvent('popstate', { state: history.state }));
  });
  await page.waitForSelector('.mt-top__back');
  await page.click('.mt-top__back');
  await page.waitForFunction(() => location.pathname === '/matches');
  check('«назад» после перехода → предыдущая страница', page.url().endsWith('/matches'));

  /* ---------- 5868098: до начала ---------- */
  await page.goto(`${ORIGIN}/match/5868098`);
  await page.waitForSelector('.mt-body');
  await settle();
  const up = await page.evaluate(() => ({
    status: document.querySelector('.ui-score-head__status')?.textContent,
    cd: document.querySelector('.ui-cd')?.getAttribute('aria-label'),
    h2h: document.querySelector('.mt-h2h')?.textContent,
    form: [...document.querySelectorAll('.mt-form')].map((x) => x.textContent),
    about: [...document.querySelectorAll('.mt-about__row')].map((x) => x.textContent),
  }));
  log('5868098:', JSON.stringify(up));
  check('до начала: «Вс, 18 окт · 22:00 МСК» при поясе устройства Europe/London', up.status === 'Вс, 18 окт · 22:00 МСК', up.status);
  check('до начала: отсчёт, личные встречи, форма', !!up.cd && !!up.h2h && up.form.length === 2);

  /* ---------- 503 / 404 / pending ---------- */
  const p2 = await ctx.newPage();
  watch(p2, 'states');
  await p2.route('**/api/match/111', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'no_data', available: [] }) }));
  await p2.goto(`${ORIGIN}/match/111`);
  await p2.waitForSelector('.mt-state');
  await p2.screenshot({ path: path.join(OUT, 'state-503.png') });
  check('503: «Данные ещё собираются»', (await p2.textContent('.mt-state')).includes('Данные ещё собираются'));
  await p2.goto(`${ORIGIN}/match/999999999`);
  await p2.waitForSelector('.mt-state');
  check('404 с сервера: «Матч не найден»', (await p2.textContent('.mt-state')).includes('Матч не найден'));

  const fx = JSON.parse(fs.readFileSync(path.join(OUT, 'fixtures-row.json'), 'utf8'));
  let pendingCalls = 0;
  await p2.route('**/api/match/5868105', (r) => {
    pendingCalls++;
    const body = pendingCalls === 1
      ? { ...fx, events: [], lineups: null, stats: null, shots: [], momentum: [], potm: null, highlights: null, h2h: null, form: null, venue: null, available: [], pending: true, source: 'fotmob', age_s: 3, stale: false }
      : { ...JSON.parse(fs.readFileSync(path.join(FIX, 'match_5868098.json'), 'utf8')), id: fx.id, kickoff: fx.kickoff, home: fx.home, away: fx.away, tournament: fx.tournament };
    return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body), headers: { 'cache-control': 'public, max-age=5' } });
  });
  await p2.goto(`${ORIGIN}/match/5868105`);
  await p2.waitForSelector('.mt-pending');
  await p2.evaluate(() => document.fonts.ready);
  await p2.screenshot({ path: path.join(OUT, 'state-pending.png') });
  check('pending: шапка и «Данные подгружаются»', !!(await p2.$('.ui-score-head')) && (await p2.textContent('.mt-pending')).includes('Данные подгружаются'));
  await p2.waitForSelector('.mt-body', { timeout: 15000 });
  check('pending: через ~10 с сам подгрузил данные', pendingCalls === 2, `${pendingCalls} запроса`);
  await p2.close();

  /* ---------- лайв: последовательность снимков ---------- */
  for (const anchorMode of ['native', 'fallback', 'control']) {
    const lp = await ctx.newPage();
    watch(lp, `live-${anchorMode}`);
    const seq = [liveSnap(44), liveSnap(45, 'halftime'), liveSnap(81), liveSnap(86)];
    let n = 0;
    const reqTimes = [];
    await lp.route('**/api/match/6106274', (r) => {
      reqTimes.push(Date.now());
      const body = seq[Math.min(n++, seq.length - 1)];
      return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body), headers: { 'cache-control': 'public, max-age=5' } });
    });
    if (anchorMode !== 'native') {
      // выключаем нативный scroll anchoring (как в WebKit) — должен сработать свой
      await lp.addInitScript(() => {
        const s = document.createElement('style');
        s.textContent = 'html, body { overflow-anchor: none !important; }';
        document.addEventListener('DOMContentLoaded', () => document.head.appendChild(s));
      });
    }
    // контроль: и нативный якорь, и свой выключены — сдвиг должен появиться (иначе проверка ничего не ловит)
    if (anchorMode === 'control') await lp.addInitScript(() => (window.scrollBy = () => {}));
    await lp.goto(`${ORIGIN}/match/6106274`);
    await lp.waitForSelector('.mt-body');
    await lp.evaluate(() => document.fonts.ready);
    await lp.evaluate(() => (window.__noReload = 1));
    const st0 = await lp.evaluate(() => ({ score: document.querySelector('.ui-score-head__score').textContent, min: document.querySelector('.ui-mc__minute')?.textContent, live: !!document.querySelector('.mt-top .ui-badge--live') }));
    if (anchorMode === 'native') await lp.screenshot({ path: path.join(OUT, 'live-44.png'), fullPage: true });
    // ждём перерыв
    await lp.waitForFunction(() => document.querySelector('.ui-score-head__status')?.textContent === 'Перерыв', null, { timeout: 15000 });
    if (anchorMode === 'native') await lp.screenshot({ path: path.join(OUT, 'live-halftime.png'), fullPage: true });
    await lp.waitForFunction(() => document.querySelector('.ui-mc__minute')?.textContent === '81′', null, { timeout: 15000 });
    const rows81 = await lp.evaluate(() => document.querySelectorAll('.ui-tl__row').length);
    // прокручиваем к «О матче» (ниже хронологии) — следим, чтобы блок не уехал, когда в хронологию добавятся строки
    await lp.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await lp.waitForTimeout(300);
    // что человек сейчас читает: строка хронологии у верхнего края экрана
    const before = await lp.evaluate(() => {
      const el = document.elementFromPoint(195, 120).closest('li, section, div');
      el.setAttribute('data-probe', '1');
      return { top: el.getBoundingClientRect().top, y: scrollY, text: el.textContent.slice(0, 40) };
    });
    await lp.waitForFunction(() => document.querySelector('.ui-score-head__score')?.textContent === '3 : 3', null, { timeout: 15000 });
    const hl = await lp.evaluate(() => [...document.querySelectorAll('.ui-tl__row.mt-new')].map((x) => x.textContent));
    await lp.waitForTimeout(100);
    const after = await lp.evaluate(() => ({ top: document.querySelector('[data-probe]').getBoundingClientRect().top, y: scrollY, rows: document.querySelectorAll('.ui-tl__row').length, flag: window.__noReload }));
    log(`Лайв (${anchorMode}): 44′ ${JSON.stringify(st0)}; 81′ → 86′: строк ${rows81}→${after.rows}, верхний видимый блок «${before.text}» top ${before.top.toFixed(0)}→${after.top.toFixed(0)}, scrollY ${before.y}→${after.y}`);
    check(`лайв (${anchorMode}): LIVE и минута`, st0.live && st0.min === '44′' && st0.score === '1 : 1');
    check(`лайв (${anchorMode}): строки добавились без перезагрузки`, after.rows > rows81 && rows81 > 3 && after.flag === 1);
    if (anchorMode === 'control') {
      check('лайв (контроль, без якоря): сдвиг есть — проверка чувствительна', Math.abs(after.top - before.top) > 5, `сдвиг ${(after.top - before.top).toFixed(1)} px`);
      await lp.close();
      continue;
    }
    check(`лайв (${anchorMode}): прокрутка не прыгнула`, before.y > 0 && Math.abs(after.top - before.top) < 2, `сдвиг ${(after.top - before.top).toFixed(1)} px при scrollY ${before.y}→${after.y}`);
    check(`лайв (${anchorMode}): новые голы подсвечены`, hl.length === 2 && hl.some((t) => t.includes('Endrick')), JSON.stringify(hl));
    if (anchorMode === 'native') {
      // кадр с подсветкой: возвращаем 3:2 → 3:3 ещё раз нельзя, поэтому снимаем сразу, пока идёт анимация
      await lp.evaluate(() => document.querySelector('.ui-tl__row.mt-new')?.scrollIntoView({ block: 'center' }));
      await lp.screenshot({ path: path.join(OUT, 'live-new-goal.png') });
    }
    const gaps = reqTimes.slice(1).map((t, i) => ((t - reqTimes[i]) / 1000).toFixed(1));
    check(`лайв (${anchorMode}): опрос раз в ~10 с`, gaps.every((g) => g >= 9.5 && g <= 12), gaps.join(', '));

    // возврат на вкладку — сразу запрос
    if (anchorMode === 'native') {
      const k = reqTimes.length;
      await lp.evaluate(() => {
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
        document.dispatchEvent(new Event('visibilitychange'));
      });
      await lp.waitForTimeout(400);
      await lp.evaluate(() => {
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
        document.dispatchEvent(new Event('visibilitychange'));
      });
      await lp.waitForTimeout(700);
      check('лайв: при возврате на вкладку — сразу запрос', reqTimes.length === k + 1, `${reqTimes.length - k}`);
    }
    await lp.close();
  }

  log('Картинки /img:', JSON.stringify([...imgStatus.entries()].reduce((a, [p, s]) => ((a[s] = (a[s] || 0) + 1), a), {})));
  const yt = [...imgStatus.entries()].filter(([p]) => p.startsWith('/img/yt/'));
  log('Превью YouTube:', JSON.stringify(yt));
  check('внешних хостов — 0', external.size === 0, JSON.stringify([...external.entries()]));
  check('ошибок консоли — 0', consoleErrors.length === 0, consoleErrors.join(' | '));

  await browser.close();
  const fail = results.filter((r) => !r.ok).length;
  log(`\nИтого: ${results.length - fail}/${results.length} OK`);
  process.exit(fail ? 1 : 0);
})().catch((e) => {
  console.error(e);
  process.exit(2);
});
