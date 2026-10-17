// Проверки прогнозов (Playwright) против https://realmadridfan.ru.
//
//   NODE_PATH=C:/Users/egor3/node_modules node run.js <distDir> <dataDir> <localApi> <outDir>
//
// Страницы и /assets/* — из локальной сборки (distDir); /api/predict/*, /api/auth/* — локальный бэкенд
// (local_backend.py: фейковый токен бота, SnapshotProvider на копии снимков с сервера); /img/avatar/* — из
// dataDir/avatars (как nginx); остальное /api/* и /img/* — с сервера. В сценариях «матч идёт / завершён»
// /api/home и /api/match/* тоже берутся у локального бэкенда — там сдвинуто время матча.
const { chromium } = require('playwright');
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const path = require('path');

const [, , DIST, DATA, LOCAL, OUT] = process.argv;
const SITE = 'https://realmadridfan.ru';
const HOST = 'realmadridfan.ru';
const BOT_TOKEN = '123456:LOCAL-fake-bot-token';
const SILHOUETTE = path.resolve(__dirname, '../../../deploy/img/silhouette.svg');
const MIME = {
  '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.woff2': 'font/woff2', '.woff': 'font/woff',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.json': 'application/json', '.ico': 'image/x-icon',
};
const VIEWPORTS = [
  { name: '390', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  { name: '1366', viewport: { width: 1366, height: 768 }, deviceScaleFactor: 1 },
];
const ALEX = { id: 4242, first_name: 'Алексей', last_name: 'Морозов', username: 'madridista_alex', language_code: 'ru' };
const IVAN = { id: 5005, first_name: 'Иван', last_name: 'Друг', username: 'ivan_friend', language_code: 'ru' };
const MBAPPE = '701154';
fs.mkdirSync(OUT, { recursive: true });

// ---------- подписи Telegram с фейковым токеном ----------
const hmac = (key, msg) => crypto.createHmac('sha256', key).update(msg).digest();
function signInitData(user, startParam) {
  const f = {
    auth_date: String(Math.floor(Date.now() / 1000)),
    query_id: 'AAHtestQuery',
    user: JSON.stringify(user),
    signature: 'c3R1Yi1zaWduYXR1cmUtZm9yLWxvY2FsLWNoZWNrcw',
    ...(startParam ? { start_param: startParam, chat_type: 'sender', chat_instance: '-1' } : {}),
  };
  const dcs = Object.keys(f).sort().map((k) => `${k}=${f[k]}`).join('\n');
  f.hash = hmac(hmac('WebAppData', BOT_TOKEN), dcs).toString('hex');
  return new URLSearchParams(f).toString();
}
function tmaHash(initData, startParam) {
  const theme = { bg_color: '#06070b', secondary_bg_color: '#0b0d14', text_color: '#eef0f5', hint_color: '#8a90a1',
    link_color: '#d4af37', button_color: '#d4af37', button_text_color: '#1a1408', header_bg_color: '#06070b' };
  const p = new URLSearchParams({ tgWebAppData: initData, tgWebAppVersion: '8.0', tgWebAppPlatform: 'ios',
    tgWebAppThemeParams: JSON.stringify(theme), ...(startParam ? { tgWebAppStartParam: startParam } : {}) });
  return '#' + p.toString();
}

const TMA_MOCK = `
  window.__tgEvents = [];
  window.Telegram = { WebApp: { platform: 'ios', version: '8.0' } };
  window.TelegramWebviewProxy = {
    postEvent(name, data) {
      window.__tgEvents.push([name, data]);
      const reply = (ev, payload) => setTimeout(() => window.Telegram && window.Telegram.WebView && window.Telegram.WebView.receiveEvent(ev, payload), 0);
      if (name === 'web_app_request_viewport') reply('viewport_changed', { height: innerHeight, width: innerWidth, is_expanded: true, is_state_stable: true });
      if (name === 'web_app_request_theme') reply('theme_changed', { theme_params: { bg_color: '#06070b', text_color: '#eef0f5', hint_color: '#8a90a1', button_color: '#d4af37', button_text_color: '#1a1408', secondary_bg_color: '#0b0d14' } });
      if (name === 'web_app_request_safe_area') reply('safe_area_changed', { top: 0, bottom: 0, left: 0, right: 0 });
      if (name === 'web_app_request_content_safe_area') reply('content_safe_area_changed', { top: 0, bottom: 0, left: 0, right: 0 });
    },
  };
  window.TelegramWebviewProxy.postEvent.toString = () => 'function postEvent() { [native code] }';
`;

// ---------- локальный бэкенд ----------
function httpLocal(method, pathAndQuery, headers = {}, body = null) {
  const target = new URL(LOCAL);
  return new Promise((resolve, reject) => {
    const r = http.request({ hostname: target.hostname, port: target.port, path: pathAndQuery, method, headers }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    r.on('error', reject);
    if (body) r.write(body);
    r.end();
  });
}
const ctl = async (p) => JSON.parse((await httpLocal('POST', p)).body.toString() || 'null');

async function proxyLocal(route) {
  const req = route.request();
  const u = new URL(req.url());
  const hdrs = { ...(await req.allHeaders()), host: HOST };
  delete hdrs['accept-encoding'];
  try {
    const res = await httpLocal(req.method(), u.pathname + u.search, hdrs, req.postDataBuffer());
    const out = {};
    for (const [k, v] of Object.entries(res.headers)) {
      if (k === 'content-length' || k === 'transfer-encoding' || k === 'connection') continue;
      out[k] = Array.isArray(v) ? v.join('\n') : v;
    }
    return route.fulfill({ status: res.status, headers: out, body: res.body });
  } catch (e) {
    return route.fulfill({ status: 502, body: String(e) });
  }
}

async function open(browser, vp, { tma = false, localAll = false } = {}) {
  const context = await browser.newContext({ ...vp, locale: 'ru-RU', timezoneId: 'Europe/Moscow' });
  const log = { external: {}, errors: [], failed: [], api: [] };
  if (tma) await context.addInitScript(TMA_MOCK);
  await context.route('https://telegram.org/**', (route) => route.abort('blockedbyclient'));
  await context.route(`${SITE}/**`, async (route) => {
    const p = new URL(route.request().url()).pathname;
    if (p.startsWith('/api/auth/') || p.startsWith('/api/predict/')) return proxyLocal(route);
    if (localAll && (p === '/api/home' || p.startsWith('/api/match/') || p === '/api/fixtures')) return proxyLocal(route);
    const av = /^\/img\/avatar\/(\d+)\.jpg$/.exec(p);
    if (av) {
      const f = path.join(DATA, 'avatars', av[1] + '.jpg');
      if (fs.existsSync(f)) return route.fulfill({ status: 200, headers: { 'content-type': 'image/jpeg' }, body: fs.readFileSync(f) });
      return route.fulfill({ status: 200, headers: { 'content-type': 'image/svg+xml' }, body: fs.readFileSync(SILHOUETTE) });
    }
    if (p.startsWith('/api/') || p.startsWith('/img/')) return route.continue();
    const file = path.join(DIST, decodeURIComponent(p));
    if (p !== '/' && fs.existsSync(file) && fs.statSync(file).isFile())
      return route.fulfill({ status: 200, headers: { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' }, body: fs.readFileSync(file) });
    if (p.startsWith('/assets/')) return route.fulfill({ status: 404, body: '' });
    return route.fulfill({ status: 200, headers: { 'content-type': 'text/html' }, body: fs.readFileSync(path.join(DIST, 'index.html')) });
  });
  const page = await context.newPage();
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (u.protocol.startsWith('http') && u.host !== HOST) log.external[u.host] = (log.external[u.host] || 0) + 1;
  });
  page.on('response', (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith('/api/predict/')) log.api.push(`${r.request().method()} ${u.pathname}${u.search} → ${r.status()}`);
  });
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    // ответ 409 «приём закрыт» в сценарии (в) ожидаем: Chrome сам пишет его в консоль как ошибку загрузки
    if (/status of 409 \(Conflict\)/.test(m.text())) log.expected = (log.expected || []).concat(m.text());
    else log.errors.push(m.text());
  });
  page.on('pageerror', (e) => log.errors.push('pageerror: ' + e.message));
  page.on('requestfailed', (r) => log.failed.push(r.url() + ' ' + ((r.failure() || {}).errorText || '')));
  return { context, page, log };
}

async function shot(page, name, full = false) {
  // во весь рост нижнее меню (fixed) легло бы посреди страницы — на время такого снимка прячем его
  const h = full ? await page.addStyleTag({ content: '.bottom-nav{visibility:hidden!important}' }) : null;
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: full });
  if (h) await h.evaluate((n) => n.remove());
}
// снимок блока целиком: нижнее меню (position: fixed) на время снимка прячем, иначе оно ложится поверх
async function elShot(page, sel, name) {
  const h = await page.addStyleTag({ content: '.bottom-nav{visibility:hidden!important}' });
  await page.locator(sel).screenshot({ path: path.join(OUT, `${name}.png`) });
  await h.evaluate((n) => n.remove());
}
const hscroll = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
async function settle(page, ms = 600) {
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForSelector('#splash', { state: 'detached', timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(ms);
}
const text = (page, sel) => page.locator(sel).first().innerText().then((t) => t.replace(/\s+/g, ' ').trim()).catch(() => null);
const meta = async (page, log) => ({ external: log.external, errors: log.errors, expectedErrors: log.expected || [], hscroll: await hscroll(page) });

async function gotoTma(page, user, route = '/', startParam) {
  await page.goto(SITE + route + tmaHash(signInitData(user, startParam), startParam));
}
async function nav(page, href) {
  // переход внутри приложения (как по нижнему меню), без перезагрузки мини-аппа
  await page.evaluate((h) => { history.pushState({}, '', h); dispatchEvent(new PopStateEvent('popstate')); }, href);
}
async function setScore(page, root, home, away) {
  // счёт ставится кнопками «+»/«−» — как пальцем
  const steppers = page.locator(`${root} .ui-stepper`);
  for (const [i, want] of [[0, home], [1, away]]) {
    const st = steppers.nth(i);
    for (let k = 0; k < 25; k++) {
      const cur = Number(await st.locator('.ui-stepper__val').innerText());
      if (cur === want) break;
      await st.locator(cur < want ? '.ui-stepper__btn:not(.ui-stepper__btn--minus)' : '.ui-stepper__btn--minus').click();
    }
  }
}

// ---------- сценарии ----------

async function scenarioA(browser, vp) {
  // (а) мини-апп: вход сам → 2:1 и Мбаппе → сохранить → видно на главной и в профиле
  const { context, page, log } = await open(browser, vp, { tma: true });
  await gotoTma(page, ALEX, '/predict');
  await page.waitForSelector('.pd-match .ui-stepper');
  await page.waitForSelector('.pd-tile');
  await settle(page);
  await shot(page, `a-predict-empty-${vp.name}`);
  await setScore(page, '.pd-match', 2, 1);
  await page.locator('.pd-scorer[aria-label="Kylian Mbappé"]').click();
  const photo = await page.locator('.pd-scorer[aria-label="Kylian Mbappé"] img').evaluate((i) => ({ src: new URL(i.src).pathname, ok: i.complete && i.naturalWidth > 1 })).catch(() => null);
  await page.locator('.pd-save').click();
  await page.waitForFunction(() => document.querySelector('.pd-save')?.textContent?.includes('сохранён'));
  const saved = { button: await text(page, '.pd-save') };
  await page.locator('.pd-match').scrollIntoViewIfNeeded();
  await shot(page, `a-predict-saved-${vp.name}`);
  await shot(page, `a-predict-full-${vp.name}`, true);
  const scorers = await page.locator('.pd-scorer').count();
  const photos = await page.locator('.pd-scorer img').evaluateAll((ims) => ims.filter((i) => i.complete && i.naturalWidth > 1).length);
  await nav(page, '/');
  await page.waitForSelector('.hp-line');
  await settle(page);
  const home = await text(page, '.hp');
  await page.locator('.hp').scrollIntoViewIfNeeded();
  await shot(page, `a-home-${vp.name}`);
  await nav(page, '/profile');
  await page.waitForSelector('.pf-pred');
  await settle(page);
  const profile = await page.locator('.pf-pred').allInnerTexts();
  await shot(page, `a-profile-${vp.name}`, true);
  const r = { saved, photo, scorers, photosLoaded: photos, home, profile: profile.map((t) => t.replace(/\s+/g, ' ')), api: log.api, ...(await meta(page, log)) };
  await context.close();
  return r;
}

async function scenarioB(browser, vp) {
  // (б) изменить прогноз: на главной «изменить» → 3:1 → сохранить; на /predict — тот же счёт и Мбаппе
  const { context, page, log } = await open(browser, vp, { tma: true });
  await gotoTma(page, ALEX, '/');
  await page.waitForSelector('.hp-line');
  await settle(page);
  const before = await text(page, '.hp-line');
  await page.locator('.hp-link').click();
  await setScore(page, '.hp', 3, 1);
  await page.locator('.hp').scrollIntoViewIfNeeded();
  await shot(page, `b-home-edit-${vp.name}`);
  await page.locator('.hp-save').click();
  await page.waitForSelector('.hp-line');
  const after = await text(page, '.hp-line');
  await shot(page, `b-home-changed-${vp.name}`);
  await nav(page, '/predict');
  await page.waitForSelector('.pd-match .ui-stepper');
  await settle(page);
  const vals = await page.locator('.pd-match .ui-stepper__val').allInnerTexts();
  const picked = await page.locator('.pd-scorer.is-on').getAttribute('aria-label');
  const button = await text(page, '.pd-save');
  // и на самом /predict: поменять бомбардира
  await page.locator('.pd-scorer[aria-label="Jude Bellingham"]').click();
  const button2 = await text(page, '.pd-save');
  await page.locator('.pd-save').click();
  await page.waitForFunction(() => document.querySelector('.pd-save')?.textContent?.includes('сохранён'));
  await page.locator('.pd-scorer[aria-label="Kylian Mbappé"]').click();
  await page.locator('.pd-save').click();
  await page.waitForFunction(() => document.querySelector('.pd-save')?.textContent?.includes('сохранён'));
  const server = await page.evaluate(async (init) => (await (await fetch('/api/predict/me', { headers: { Authorization: 'tma ' + init } })).json()).history[0].prediction, signInitData(ALEX));
  await shot(page, `b-predict-changed-${vp.name}`);
  const r = { before, after, vals, picked, button, button2, server, api: log.api, ...(await meta(page, log)) };
  await context.close();
  return r;
}

async function scenarioC(browser, vp) {
  // (в) матч начался, пока открыта карточка → «Сохранить» → 409 → «Приём закрыт»; потом идёт со счётом 1:0
  const { context, page, log } = await open(browser, vp, { tma: true, localAll: true });
  await gotoTma(page, ALEX, '/predict');
  await page.waitForSelector('.pd-match .ui-stepper');
  await settle(page);
  await ctl('/__ctl/kickoff?min=-2');
  await setScore(page, '.pd-match', 4, 1);
  const resp = page.waitForResponse((r) => r.url().includes('/api/predict/matches/') && r.request().method() === 'PUT');
  await page.locator('.pd-save').click();
  const put = await resp;
  await page.waitForSelector('.pd-closed');
  await settle(page, 400);
  const closed = { status: put.status(), body: await put.json(), msg: await text(page, '.pd-msg'), card: await text(page, '.pd-closed') };
  await page.locator('.pd-match').scrollIntoViewIfNeeded();
  await shot(page, `c-closed-409-${vp.name}`);
  // идёт: 1:0, забил Мбаппе → «пока +N» по тем же правилам (прогноз 3:1 + Мбаппе: исход 2 + бомбардир 2)
  await ctl(`/__ctl/score?home=1&away=0&scorer=${MBAPPE}&minute=25`);
  await nav(page, '/');
  await page.waitForSelector('.hp-line');
  await settle(page);
  const home = await text(page, '.hp');
  await shot(page, `c-home-live-${vp.name}`);
  await nav(page, '/predict');
  await page.waitForSelector('.pd-closed');
  await settle(page);
  const live = await text(page, '.pd-closed');
  await page.locator('.pd-match').scrollIntoViewIfNeeded();
  await shot(page, `c-predict-live-${vp.name}`);
  const r = { closed, home, live, api: log.api, ...(await meta(page, log)) };
  await context.close();
  return r;
}

async function scenarioD(browser, vp) {
  // (г) матч завершён 3:1, первый гол — Мбаппе → settle (как сборщик) → очки в «Моих прогнозах» и в рейтинге
  await ctl(`/__ctl/finish?home=3&away=1&scorer=${MBAPPE}`);
  const settled = await ctl('/__ctl/settle');
  const again = await ctl('/__ctl/settle');
  const { context, page, log } = await open(browser, vp, { tma: true, localAll: true });
  await gotoTma(page, ALEX, '/predict');
  await page.waitForSelector('.pd-hist__row');
  await page.waitForSelector('.pd-board__rows');
  await settle(page, 900);
  const hist = (await page.locator('.pd-hist__row').allInnerTexts()).slice(0, 3).map((t) => t.replace(/\s+/g, ' '));
  const tiles = (await page.locator('.pd-tile').allInnerTexts()).map((t) => t.replace(/\s+/g, ' '));
  const nextMatch = await text(page, '.pd-teams');
  await page.locator('.pd-mine').scrollIntoViewIfNeeded();
  await shot(page, `d-my-predictions-${vp.name}`);
  await page.locator('.pd-board').scrollIntoViewIfNeeded();
  await shot(page, `d-rating-${vp.name}`);
  const me = await text(page, '.pd-board .ui-lb.is-me');
  await shot(page, `d-predict-full-${vp.name}`, true);
  const r = { settled, again, hist, tiles, nextMatch, me, api: log.api, ...(await meta(page, log)) };
  await context.close();
  return r;
}

async function boardRows(page) {
  await page.waitForFunction(() => !document.querySelector('.pd-board .ui-skel') && document.querySelector('.pd-board .ui-lb, .pd-board__msg'));
  await page.waitForFunction(() => [...document.querySelectorAll('.pd-board .ui-lb img')].every((i) => i.complete), null, { timeout: 5000 }).catch(() => {});
  return page.evaluate(() => [...document.querySelectorAll('.pd-board .ui-lb')].map((r) => ({
    text: r.innerText.replace(/\s+/g, ' '), me: r.classList.contains('is-me'), sep: r.classList.contains('pd-board__me'),
    avatar: r.querySelector('img') ? new URL(r.querySelector('img').src).pathname : (r.querySelector('.ui-lb__sil') ? 'silhouette' : 'letter'),
    imgOk: r.querySelector('img') ? r.querySelector('img').complete && r.querySelector('img').naturalWidth > 1 : null,
  })));
}

async function scenarioE(browser, vp, mode) {
  // (д) рейтинг «Сезон / Месяц / Лиги», моя строка. mode=before — до расчёта Севильи (я ниже топа-10)
  const { context, page, log } = await open(browser, vp, { tma: true });
  await gotoTma(page, ALEX, '/predict');
  await page.waitForSelector('.pd-board__rows, .pd-board__msg');
  await settle(page);
  const out = {};
  for (const [tab, label] of [['season', 'Сезон'], ['month', 'Месяц'], ['leagues', 'Лиги']]) {
    await page.locator('.pd-board__tabs .ui-tabs__tab', { hasText: label }).click();
    out[tab] = await boardRows(page);
    out[tab + '_msg'] = await text(page, '.pd-board__msg');
    await page.locator('.pd-board').scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await elShot(page, '.pd-board', `e-rating-${mode}-${tab}-${vp.name}`);
  }
  const r = { ...out, api: log.api, ...(await meta(page, log)) };
  await context.close();
  return r;
}

async function scenarioF(browser, vp) {
  // (е) создать лигу → ссылка → «Поделиться» (shareURL) → второй пользователь по startapp → рейтинг лиги
  const { context, page, log } = await open(browser, vp, { tma: true });
  await gotoTma(page, ALEX, '/predict');
  await page.waitForSelector('.pd-invite__form');
  await settle(page);
  await page.locator('#pd-league-name').fill(`Пенья ${vp.name}`);
  await page.locator('.pd-invite__btn').click();
  await page.waitForSelector('.pd-league__link');
  const link = (await page.locator('.pd-league__link').first().innerText()).trim();
  await page.locator('.pd-league__share').first().click();
  await page.waitForTimeout(300);
  const tgShare = await page.evaluate(() => window.__tgEvents.filter(([n]) => n === 'web_app_open_tg_link' || n === 'web_app_open_link').map(([n, d]) => [n, d]));
  await page.locator('.pd-invite').scrollIntoViewIfNeeded();
  await shot(page, `f-league-created-${vp.name}`);
  const code = /startapp=league_([A-Z0-9]+)/.exec(link)[1];
  // второй пользователь открывает ссылку в Telegram
  const b = await open(browser, vp, { tma: true });
  const joins = [];
  b.page.on('response', async (r) => { if (r.url().endsWith('/api/predict/leagues/join')) joins.push({ status: r.status(), body: await r.json().catch(() => null) }); });
  await gotoTma(b.page, IVAN, '/', `league_${code}`);
  await b.page.waitForURL('**/profile', { timeout: 15000 });
  await b.page.waitForSelector('.pf-flash');
  await settle(b.page);
  const flash = await text(b.page, '.pf-flash');
  await shot(b.page, `f-friend-joined-${vp.name}`);
  await nav(b.page, '/predict');
  await b.page.waitForSelector('.pd-board__tabs');
  await settle(b.page);
  await b.page.locator('.pd-board__tabs .ui-tabs__tab', { hasText: 'Лиги' }).click();
  await b.page.locator('.pd-board__leagues .ui-tabs__tab', { hasText: `Пенья ${vp.name}` }).click();
  const friendRows = await boardRows(b.page);
  await b.page.locator('.pd-board').scrollIntoViewIfNeeded();
  await elShot(b.page, '.pd-board', `f-league-rating-friend-${vp.name}`);
  const friendMeta = await meta(b.page, b.log);
  await b.context.close();
  // и у создателя — оба в рейтинге лиги
  await page.reload();
  await page.waitForSelector('.pd-board__tabs');
  await settle(page);
  await page.locator('.pd-board__tabs .ui-tabs__tab', { hasText: 'Лиги' }).click();
  await page.locator('.pd-board__leagues .ui-tabs__tab', { hasText: `Пенья ${vp.name}` }).click();
  const ownerRows = await boardRows(page);
  await elShot(page, '.pd-board', `f-league-rating-owner-${vp.name}`);
  const r = { link, tgShare, joins: joins.map((j) => ({ status: j.status, joined: j.body && j.body.joined, name: j.body && j.body.name })),
    flash, friendRows, ownerRows, friend: friendMeta, api: log.api, ...(await meta(page, log)) };
  await context.close();
  return r;
}

async function scenarioG(browser, vp) {
  // (ж) сайт без входа: на /predict и на главной — кнопка «Войти через Telegram»
  const { context, page, log } = await open(browser, vp);
  await page.goto(SITE + '/predict');
  await page.waitForSelector('.pd-match');
  await settle(page);
  const buttons = await page.locator('.tg-login__btn').allInnerTexts();
  await shot(page, `g-site-anon-predict-${vp.name}`);
  await shot(page, `g-site-anon-predict-full-${vp.name}`, true);
  await page.goto(SITE + '/');
  await page.waitForSelector('.hp');
  await settle(page);
  const home = await text(page, '.hp');
  await page.locator('.hp').scrollIntoViewIfNeeded();
  await shot(page, `g-site-anon-home-${vp.name}`);
  const r = { buttons, home, telegramRequested: Object.keys(log.external).includes('telegram.org'), api: log.api, ...(await meta(page, log)) };
  await context.close();
  return r;
}

(async () => {
  const browser = await chromium.launch();
  const report = {};
  try {
    for (const vp of VIEWPORTS) {
      const r = (report[vp.name] = {});
      r.reset = await ctl('/__ctl/reset');
      r.g = await scenarioG(browser, vp);
      r.e_before = await scenarioE(browser, vp, 'before');
      r.a = await scenarioA(browser, vp);
      r.b = await scenarioB(browser, vp);
      r.c = await scenarioC(browser, vp);
      r.d = await scenarioD(browser, vp);
      r.e_after = await scenarioE(browser, vp, 'after');
      r.f = await scenarioF(browser, vp);
      console.log(`viewport ${vp.name}: ok`);
    }
  } catch (e) {
    report.fatal = String((e && e.stack) || e);
    console.error(e);
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  }
})();
