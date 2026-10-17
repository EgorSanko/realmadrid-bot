// Проверки входа через Telegram и профиля (Playwright) против https://realmadridfan.ru.
//
//   NODE_PATH=C:/Users/egor3/node_modules node run.js <distDir> <dataDir> <localApi> <outDir>
//
// Страницы и /assets/* — из локальной сборки (distDir); /api/auth/* и /api/predict/* — локальный
// бэкенд (local_backend.py, фейковый токен бота); /img/avatar/* — из dataDir/avatars (как nginx);
// остальное /api/* и /img/* — с сервера. telegram.org: в (б) подменён стабом виджета, в (в) — недоступен.
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
const seed = JSON.parse(fs.readFileSync(path.join(DATA, 'seed.json'), 'utf8'));
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
function signWidget(user) {
  const d = { ...user, auth_date: Math.floor(Date.now() / 1000) };
  const dcs = Object.keys(d).sort().map((k) => `${k}=${d[k]}`).join('\n');
  d.hash = hmac(crypto.createHash('sha256').update(BOT_TOKEN).digest(), dcs).toString('hex');
  return d;
}
function tmaHash(initData, startParam) {
  const theme = { bg_color: '#06070b', secondary_bg_color: '#0b0d14', text_color: '#eef0f5', hint_color: '#8a90a1',
    link_color: '#d4af37', button_color: '#d4af37', button_text_color: '#1a1408', header_bg_color: '#06070b' };
  const p = new URLSearchParams({ tgWebAppData: initData, tgWebAppVersion: '8.0', tgWebAppPlatform: 'ios',
    tgWebAppThemeParams: JSON.stringify(theme), ...(startParam ? { tgWebAppStartParam: startParam } : {}) });
  return '#' + p.toString();
}

// окружение Telegram: мост postEvent и ответы на запросы SDK (viewport, тема, safe area)
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

// ---------- прокси к локальному бэкенду (Host — как у nginx, чтобы проверка Origin работала) ----------
function proxyLocal(route) {
  const req = route.request();
  const u = new URL(req.url());
  const target = new URL(LOCAL);
  return req.allHeaders().then((hdrs) => new Promise((resolve) => {
    const headers = { ...hdrs, host: HOST };
    delete headers['accept-encoding'];
    const body = req.postDataBuffer();
    const r = http.request({ hostname: target.hostname, port: target.port, path: u.pathname + u.search,
      method: req.method(), headers }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const out = {};
        for (const [k, v] of Object.entries(res.headers)) {
          if (k === 'content-length' || k === 'transfer-encoding' || k === 'connection') continue;
          out[k] = Array.isArray(v) ? v.join('\n') : v;
        }
        resolve(route.fulfill({ status: res.statusCode, headers: out, body: Buffer.concat(chunks) }));
      });
    });
    r.on('error', (e) => resolve(route.fulfill({ status: 502, body: String(e) })));
    if (body) r.write(body);
    r.end();
  }));
}

const widgetStub = (user) => `/* стаб telegram-widget.js для проверки: кнопка вызывает data-onauth с подписанными тестовыми данными */
(function () {
  var s = document.currentScript;
  var expr = s.getAttribute('data-onauth');
  window.__stubWidget = { bot: s.getAttribute('data-telegram-login'), onauth: expr, size: s.getAttribute('data-size'), requestAccess: s.getAttribute('data-request-access') };
  var b = document.createElement('button');
  b.type = 'button'; b.id = 'tg-stub-login'; b.textContent = 'Log in with Telegram';
  b.style.cssText = 'height:40px;padding:0 21px;border-radius:14px;border:0;background:#54a9eb;color:#fff;font:500 16px/40px sans-serif;cursor:pointer';
  b.onclick = function () { (new Function('user', expr))(${JSON.stringify(user)}); };
  s.parentNode.insertBefore(b, s);
})();`;

async function open(browser, vp, { tma = null, telegram = 'none', widgetUser = null } = {}) {
  const context = await browser.newContext({ ...vp, locale: 'ru-RU', timezoneId: 'Europe/Moscow' });
  const log = { external: {}, errors: [], failed: [], telegramReq: [] };
  if (tma) await context.addInitScript(TMA_MOCK);
  await context.route('https://telegram.org/**', async (route) => {
    log.telegramReq.push({ url: route.request().url(), t: Date.now() });
    if (telegram === 'stub') return route.fulfill({ status: 200, headers: { 'content-type': 'application/javascript' }, body: widgetStub(widgetUser) });
    if (telegram === 'abort') return route.abort('connectionrefused');
    if (telegram === 'hang') return; // не отвечаем никогда — как блокировка без ответа
    return route.abort('blockedbyclient');
  });
  await context.route(`${SITE}/**`, async (route) => {
    const p = new URL(route.request().url()).pathname;
    if (p.startsWith('/api/auth/') || p.startsWith('/api/predict/') || p.startsWith('/api/admin/')) return proxyLocal(route);
    const av = /^\/img\/avatar\/(\d+)\.jpg$/.exec(p);
    if (av) {
      for (const ext of ['.jpg', '.png']) {
        const f = path.join(DATA, 'avatars', av[1] + ext);
        if (fs.existsSync(f)) return route.fulfill({ status: 200, headers: { 'content-type': MIME[ext], 'cache-control': 'public, max-age=604800' }, body: fs.readFileSync(f) });
      }
      return route.fulfill({ status: 200, headers: { 'content-type': 'image/svg+xml', 'x-img-fallback': 'silhouette' }, body: fs.readFileSync(SILHOUETTE) });
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
  page.on('console', (m) => { if (m.type() === 'error') log.errors.push(m.text()); });
  page.on('pageerror', (e) => log.errors.push('pageerror: ' + e.message));
  page.on('requestfailed', (r) => log.failed.push(r.url() + ' ' + ((r.failure() || {}).errorText || '')));
  return { context, page, log };
}

const shot = (page, name, full = false) => page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: full });
const hscroll = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
async function settle(page, ms = 600) {
  await page.waitForLoadState('networkidle').catch(() => {});
  // заставка index.html держится не меньше 2,9 с при первом открытии вкладки
  await page.waitForSelector('#splash', { state: 'detached', timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(ms);
}
const cookieOf = async (context) => (await context.cookies(SITE)).find((c) => c.name === 'rm_session') || null;

// ---------- сценарии ----------

async function scenarioA(browser, vp) {
  // (а) мини-апп: тихий вход по initData → аватар в шапке → профиль
  const user = { id: 4242, first_name: 'Алексей', last_name: 'Морозов', username: 'madridista_alex', language_code: 'ru',
    photo_url: 'https://t.me/i/userpic/320/madridista_alex.jpg' };
  const { context, page, log } = await open(browser, vp, { tma: true });
  const authCalls = [];
  page.on('request', (r) => { if (r.url().includes('/api/auth/')) authCalls.push(`${r.method()} ${new URL(r.url()).pathname}`); });
  await page.goto(SITE + '/' + tmaHash(signInitData(user)));
  await page.waitForSelector('.avatar-btn');
  const silent = await page.evaluate(() => ({ tma: document.documentElement.classList.contains('tma'), buttons: [...document.querySelectorAll('button')].filter((b) => /Войти/.test(b.textContent)).length }));
  // аватар: при первом входе его качает «сборщик», клиент перечитывает /me через 5 с
  await page.waitForSelector('.avatar-btn img', { timeout: 25000 });
  await settle(page);
  const header = page.locator('.brandbar');
  await header.screenshot({ path: path.join(OUT, `a-tma-header-${vp.name}.png`) });
  await shot(page, `a-tma-home-${vp.name}`);
  const avatarSrc = await page.locator('.avatar-btn img').getAttribute('src');
  await page.locator('.avatar-btn').click();
  await page.waitForURL('**/profile');
  await page.waitForSelector('.pf-tile__value');
  await page.waitForSelector('.pf-pred, .pf-empty');
  await settle(page, 900);
  await shot(page, `a-tma-profile-${vp.name}`, true);
  const view = await page.evaluate(() => ({
    name: document.querySelector('.pf-hero__name')?.textContent,
    username: document.querySelector('.pf-hero__sub')?.textContent,
    tiles: [...document.querySelectorAll('.pf-tile')].map((t) => t.innerText.replace(/\n/g, ' | ')),
    preds: [...document.querySelectorAll('.pf-pred')].map((r) => r.innerText.replace(/\n/g, ' ')),
    crests: [...document.querySelectorAll('.pf-pred img')].map((i) => ({ src: new URL(i.src).pathname, ok: i.complete && i.naturalWidth > 1 })),
    leagues: [...document.querySelectorAll('.pf-league__name')].map((x) => x.textContent),
    invite: document.querySelector('.pf-league__link')?.textContent,
    admin: !!document.querySelector('a[href="/admin"]'),
    logout: [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Выйти'),
    backNative: !document.querySelector('.pf-top__back'),
  }));
  // «Поделиться» в Telegram → shareURL SDK (событие моста)
  await page.locator('.pf-league__actions button', { hasText: 'Поделиться' }).first().click();
  await page.waitForTimeout(300);
  const tgEvents = await page.evaluate(() => window.__tgEvents.map((e) => e[0]));
  const shareEvent = await page.evaluate(() => (window.__tgEvents.find((e) => /tg_link|share/.test(e[0])) || null));
  // админка по сессии
  await page.locator('a[href="/admin"]').click();
  await page.waitForURL('**/admin');
  await page.waitForSelector('.admin-status, .admin-msg', { timeout: 10000 });
  await settle(page);
  await shot(page, `a-tma-admin-${vp.name}`);
  const adminOk = await page.locator('.admin-status').count();
  const adminText = adminOk ? (await page.locator('.admin-status').innerText()).replace(/\n/g, ' ') : null;
  const cookie = await cookieOf(context);
  const res = { silent, authCalls, avatarSrc, view, shareEvent, tgEventsSample: [...new Set(tgEvents)].slice(0, 20), adminOk: adminOk > 0, adminText,
    cookie: cookie && { httpOnly: cookie.httpOnly, secure: cookie.secure, sameSite: cookie.sameSite, path: cookie.path, days: Math.round((cookie.expires - Date.now() / 1000) / 86400) },
    hscroll: await hscroll(page), ...log };
  await context.close();
  return res;
}

async function scenarioB(browser, vp) {
  // (б) сайт: «Войти через Telegram» → стаб виджета → вход → профиль → «Выйти»
  const user = { id: 777, first_name: 'Ирина', last_name: 'Соколова', username: 'irina_rm', photo_url: 'https://t.me/i/userpic/320/irina_rm.jpg' };
  const { context, page, log } = await open(browser, vp, { telegram: 'stub', widgetUser: signWidget(user) });
  await page.goto(SITE + '/');
  await page.waitForSelector('.avatar-btn');
  await settle(page);
  const beforeClickTelegram = log.telegramReq.length;
  await page.locator('.brandbar').screenshot({ path: path.join(OUT, `b-site-header-anon-${vp.name}.png`) });
  await page.locator('.avatar-btn').click();
  await page.waitForURL('**/profile');
  await page.waitForSelector('.tg-login__btn');
  await settle(page);
  const stillNoTelegram = log.telegramReq.length;
  await shot(page, `b-site-profile-anon-${vp.name}`);
  await page.locator('.tg-login__btn').click();
  await page.waitForSelector('#tg-stub-login');
  await shot(page, `b-site-widget-${vp.name}`);
  const widgetAttrs = await page.evaluate(() => window.__stubWidget);
  await page.locator('#tg-stub-login').click();
  await page.waitForSelector('.pf-hero__sub');
  await page.waitForSelector('.pf-tile__value');
  await settle(page, 900);
  await shot(page, `b-site-profile-${vp.name}`, true);
  const cookie = await cookieOf(context);
  const view = await page.evaluate(() => ({
    name: document.querySelector('.pf-hero__name')?.textContent,
    username: document.querySelector('.pf-hero__sub')?.textContent,
    tiles: [...document.querySelectorAll('.pf-tile')].map((t) => t.innerText.replace(/\n/g, ' | ')),
    emptyPreds: document.querySelector('.pf-empty__title')?.textContent,
    cta: [...document.querySelectorAll('.pf-empty a')].map((a) => `${a.textContent} → ${a.getAttribute('href')}`),
    admin: !!document.querySelector('a[href="/admin"]'),
  }));
  // перезагрузка: вход держится на cookie
  await page.reload();
  await page.waitForSelector('.pf-hero__sub');
  const afterReload = await page.locator('.pf-hero__sub').textContent();
  // аватар появляется после скачивания «сборщиком»
  await page.goto(SITE + '/');
  await page.waitForSelector('.avatar-btn img', { timeout: 25000 }).catch(() => {});
  await settle(page);
  await page.locator('.brandbar').screenshot({ path: path.join(OUT, `b-site-header-user-${vp.name}.png`) });
  const headerAvatar = await page.locator('.avatar-btn img').count();
  await page.locator('.avatar-btn').click();
  await page.waitForSelector('.pf-logout button');
  await page.locator('.pf-logout button').click();
  await page.waitForSelector('.tg-login__btn');
  await settle(page);
  await shot(page, `b-site-after-logout-${vp.name}`);
  const cookieAfter = await cookieOf(context);
  const meAfter = await page.evaluate(() => fetch('/api/auth/me').then((r) => r.json()));
  const res = { beforeClickTelegram, stillNoTelegram, telegramReq: log.telegramReq.map((r) => r.url), widgetAttrs, view, afterReload,
    headerAvatar, cookie: cookie && { httpOnly: cookie.httpOnly, secure: cookie.secure, sameSite: cookie.sameSite, path: cookie.path },
    cookieAfterLogout: !!cookieAfter, meAfter, hscroll: await hscroll(page), external: log.external, errors: log.errors, failed: log.failed };
  await context.close();
  return res;
}

async function scenarioC(browser, vp, mode) {
  // (в) сайт, telegram.org недоступен: abort — ошибка сразу; hang — ответа нет, ждём 8 с
  const { context, page, log } = await open(browser, vp, { telegram: mode });
  await page.goto(SITE + '/profile');
  await page.waitForSelector('.tg-login__btn');
  await settle(page);
  await page.evaluate(() => {
    window.__failAt = null;
    new MutationObserver(() => {
      if (!window.__failAt && document.querySelector('.tg-login__fail')) window.__failAt = Date.now();
    }).observe(document.body, { childList: true, subtree: true });
  });
  const t0 = await page.evaluate(() => Date.now());
  await page.locator('.tg-login__btn').click();
  await shot(page, `c-${mode}-loading-${vp.name}`);
  await page.waitForSelector('.tg-login__fail', { timeout: 15000 });
  const failAt = await page.evaluate(() => window.__failAt);
  // от нажатия (включая ожидание клика Playwright и скриншот) и от запроса скрипта (таймер виджета)
  const waited = { fromClickMs: failAt - t0, fromScriptRequestMs: log.telegramReq[0] ? failAt - log.telegramReq[0].t : null };
  await settle(page, 300);
  await shot(page, `c-${mode}-failed-${vp.name}`);
  const fail = await page.evaluate(() => ({
    text: document.querySelector('.tg-login__fail .tg-login__err')?.textContent,
    open: [...document.querySelectorAll('.tg-login__fail a')].map((a) => `${a.textContent.trim()} → ${a.getAttribute('href')}`),
  }));
  // ошибки консоли о заблокированном telegram.org — ожидаемые; считаем остальные
  const errors = log.errors.filter((e) => !/telegram\.org|ERR_CONNECTION_REFUSED|net::ERR_FAILED/.test(e));
  const res = { mode, waitedMs: waited, fail, telegramReq: log.telegramReq.map((r) => r.url), external: log.external,
    errors, errorsAboutTelegram: log.errors.length - errors.length, hscroll: await hscroll(page) };
  await context.close();
  return res;
}

async function scenarioD(browser, vp, uid) {
  // (г) мини-апп по ссылке startapp=league_<код>: вступление и профиль с сообщением
  const sp = `league_${seed.office_code}`;
  const user = { id: uid, first_name: 'Хави', last_name: null, username: `xavi_${uid}`, language_code: 'ru' };
  delete user.last_name;
  const { context, page, log } = await open(browser, vp, { tma: true });
  const joins = [];
  page.on('response', async (r) => { if (r.url().endsWith('/api/predict/leagues/join')) joins.push({ status: r.status(), body: await r.json().catch(() => null) }); });
  await page.goto(SITE + '/' + tmaHash(signInitData(user, sp), sp));
  await page.waitForURL('**/profile', { timeout: 15000 });
  await page.waitForSelector('.pf-flash');
  await page.waitForSelector('.pf-league__name');
  await settle(page, 800);
  await shot(page, `d-league-joined-${vp.name}`, true);
  const view = await page.evaluate(() => ({ flash: document.querySelector('.pf-flash')?.textContent,
    leagues: [...document.querySelectorAll('.pf-league')].map((l) => l.innerText.replace(/\n/g, ' | ')) }));
  // перезагрузка не вступает повторно и не уводит со страницы
  await page.goto(SITE + '/');
  await settle(page);
  const url = page.url();
  // match_<id> и profile
  const res = { startParam: sp, joins: joins.map((j) => ({ status: j.status, joined: j.body && j.body.joined, name: j.body && j.body.name })),
    view, afterHome: url, external: log.external, errors: log.errors, hscroll: await hscroll(page) };
  await context.close();
  return res;
}

async function scenarioE(browser, vp) {
  // сайт: админ входит через виджет → /admin работает по сессии, без токена
  const user = { id: 4242, first_name: 'Алексей', last_name: 'Морозов', username: 'madridista_alex' };
  const { context, page, log } = await open(browser, vp, { telegram: 'stub', widgetUser: signWidget(user) });
  await page.goto(SITE + '/admin');
  await page.waitForSelector('.tg-login__btn');
  await settle(page);
  await shot(page, `e-site-admin-login-${vp.name}`);
  await page.locator('.tg-login__btn').click();
  await page.locator('#tg-stub-login').click();
  await page.waitForSelector('.admin-status', { timeout: 10000 });
  await settle(page);
  await shot(page, `e-site-admin-session-${vp.name}`);
  const r = { adminStatus: await page.locator('.admin-status').innerText(),
    tokenStored: await page.evaluate(() => sessionStorage.getItem('rm-admin-token')),
    external: log.external, errors: log.errors, hscroll: await hscroll(page) };
  await context.close();
  return r;
}

async function scenarioMatch(browser, vp) {
  const user = { id: 9100, first_name: 'Тест' };
  const { context, page, log } = await open(browser, vp, { tma: true });
  await page.goto(SITE + '/' + tmaHash(signInitData(user, 'match_5868098'), 'match_5868098'));
  await page.waitForURL('**/match/5868098', { timeout: 15000 });
  await settle(page);
  await shot(page, `d-startapp-match-${vp.name}`);
  const r = { url: page.url(), external: log.external, errors: log.errors };
  await context.close();
  return r;
}

(async () => {
  const browser = await chromium.launch();
  const report = {};
  try {
    for (const vp of VIEWPORTS) {
      const r = (report[vp.name] = {});
      r.a = await scenarioA(browser, vp);
      r.b = await scenarioB(browser, vp);
      r.c_abort = await scenarioC(browser, vp, 'abort');
      r.c_hang = await scenarioC(browser, vp, 'hang');
      r.d = await scenarioD(browser, vp, vp.name === '390' ? 5555 : 5556);
      r.d_match = await scenarioMatch(browser, vp);
      r.e = await scenarioE(browser, vp);
      console.log(`viewport ${vp.name}: ok`);
    }
  } catch (e) {
    report.fatal = String(e && e.stack || e);
    console.error(e);
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  }
})();
