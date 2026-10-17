// Проверка входа по коду через бота — Playwright против https://realmadridfan.ru.
//
//   NODE_PATH=C:/Users/egor3/node_modules node run.js <distDir> <dataDir> <localApi> <outDir>
//
// Страницы и /assets/* — из локальной сборки (distDir); /api/auth/*, /api/predict/*, /api/games/* — локальный
// бэкенд (local_backend.py, фейковый токен бота); /img/avatar/* — из dataDir/avatars (как nginx);
// остальное /api/* и /img/* — с сервера. Внешние хосты (telegram.org, t.me и др.) блокируются и считаются.
// «Бот» — настоящий обработчик апдейта (app.bot.TelegramBot.handle_update) через POST /api/_test/bot_update.
const { chromium } = require('playwright');
const fs = require('fs');
const http = require('http');
const path = require('path');

const [, , DIST, DATA, LOCAL, OUT] = process.argv;
const SITE = 'https://realmadridfan.ru';
const HOST = 'realmadridfan.ru';
const SILHOUETTE = path.resolve(__dirname, '../../../deploy/img/silhouette.svg');
const MIME = {
  '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.woff2': 'font/woff2', '.woff': 'font/woff',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.json': 'application/json', '.ico': 'image/x-icon',
  '.webmanifest': 'application/manifest+json',
};
const VIEWPORTS = [
  { name: '390', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  { name: '1440', viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
];
const ALEX = { id: 4242, first_name: 'Алексей', last_name: 'Морозов', username: 'madridista_alex' };
// у бота лимит неверных кодов на человека (5 за 10 мин) — каждому сценарию своя «Мария»
let mariaSeq = 0;
const maria = () => ({ id: 100000 + Date.now() % 100000 * 10 + (mariaSeq++ % 10), first_name: 'Мария', username: 'maria_rm' });
const MSG_OK = 'Вход на сайт выполнен ✅ Можно вернуться в браузер.';
const MSG_BAD = 'Код не найден или устарел. Нажмите „Войти“ на сайте ещё раз.';
fs.mkdirSync(OUT, { recursive: true });
const report = { started: new Date().toISOString(), viewports: {} };
let ipSeq = 10;

// ---------- прокси к локальному бэкенду (X-Real-IP — как от nginx, у каждого сценария свой) ----------
function proxyLocal(route, ip) {
  const req = route.request();
  const u = new URL(req.url());
  const target = new URL(LOCAL);
  return req.allHeaders().then((hdrs) => new Promise((resolve) => {
    const headers = { ...hdrs, host: HOST, 'x-real-ip': ip };
    delete headers['accept-encoding'];
    const body = req.postDataBuffer();
    const r = http.request({ hostname: target.hostname, port: target.port, path: u.pathname + u.search, method: req.method(), headers }, (res) => {
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
function localPost(p, body) {
  const target = new URL(LOCAL);
  return new Promise((resolve, reject) => {
    const data = Buffer.from(JSON.stringify(body));
    const r = http.request({ hostname: target.hostname, port: target.port, path: p, method: 'POST',
      headers: { 'content-type': 'application/json', 'content-length': data.length } }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve(JSON.parse(Buffer.concat(chunks).toString() || 'null')));
    });
    r.on('error', reject);
    r.end(data);
  });
}
const botSays = (user, text) => localPost('/api/_test/bot_update', { user, text });
const setTtl = (seconds) => localPost('/api/_test/ttl', { seconds });

async function open(browser, vp) {
  const context = await browser.newContext({ ...vp, locale: 'ru-RU', timezoneId: 'Europe/Moscow' });
  const ip = `198.51.100.${ipSeq++}`;
  const log = { external: {}, errors: [], failed: [], authRequests: [] };
  await context.route(`${SITE}/**`, async (route) => {
    const p = new URL(route.request().url()).pathname;
    if (/^\/api\/(games|auth|predict)\//.test(p)) {
      if (p.startsWith('/api/auth/')) log.authRequests.push(`${route.request().method()} ${p}`);
      return proxyLocal(route, ip);
    }
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
    return route.fulfill({ status: 200, headers: { 'content-type': 'text/html' }, body: fs.readFileSync(path.join(DIST, 'index.html')) });
  });
  // всё, что не наш сайт, — блокируем и считаем
  await context.route((url) => url.host !== HOST, (route) => {
    const u = new URL(route.request().url());
    if (u.protocol.startsWith('http')) log.external[u.host] = (log.external[u.host] || 0) + 1;
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  page.on('console', (m) => { if (m.type() === 'error') log.errors.push(m.text()); });
  page.on('pageerror', (e) => log.errors.push('pageerror: ' + e.message));
  page.on('requestfailed', (r) => { if (new URL(r.url()).host === HOST) log.failed.push(r.url()); });
  return { context, page, log };
}

const hscroll = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
async function go(page, url) {
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => !document.getElementById('splash'), null, { timeout: 15000 });
}
async function shot(page, name, vp) {
  await page.screenshot({ path: path.join(OUT, `${name}-${vp.name}.png`) });
  const h = await hscroll(page);
  if (h > 0) throw new Error(`${name}-${vp.name}: горизонтальная прокрутка ${h}px`);
}
function check(cond, msg) {
  if (!cond) throw new Error('проверка не прошла: ' + msg);
}

// открыть вход по коду: на телефоне — «Профиль» → «Войти через Telegram», на ПК — панель в шапке
async function openCodeLogin(page, vp) {
  if (vp.name === '390') {
    await go(page, `${SITE}/profile`);
    await page.click('.tg-login__btn');
  } else {
    // не главная: там на ПК сам собой запускается эфир (HLS с чужого хоста) — к входу не относится
    await go(page, `${SITE}/matches`);
    await page.click('.sh-login__btn');
  }
  await page.waitForSelector('.code-login__digits');
  const digits = (await page.textContent('.code-login__digits')).replace(/\s/g, '');
  const link = await page.getAttribute('.code-login__open', 'href');
  const m = /^https:\/\/t\.me\/Real_Madrid_football_bot\?start=login_([A-Za-z0-9_-]{16,})$/.exec(link);
  check(/^\d{6}$/.test(digits), 'код — 6 цифр: ' + digits);
  check(m, 'deep link: ' + link);
  check(!link.includes(digits), '6 цифр не в ссылке');
  const cookies = await page.context().cookies(SITE + '/api/auth/code');
  const nonce = cookies.find((c) => c.name === 'rm_login');
  check(nonce && nonce.httpOnly && nonce.secure && nonce.path === '/api/auth/code', 'nonce в HttpOnly-cookie');
  check(!link.includes(nonce.value), 'nonce не в ссылке');
  check(await page.evaluate(() => !document.cookie.includes('rm_login')), 'nonce не виден JS');
  return { digits, token: m[1], link };
}

function onlySender(res, user) {
  const sends = res.calls.filter(([m]) => m === 'sendMessage');
  check(sends.length === 1, 'одно сообщение бота: ' + JSON.stringify(res.calls));
  check(sends.every(([, p]) => p.chat_id === user.id), 'бот пишет только отправителю');
  check(res.calls.every(([m]) => m === 'sendMessage' || m === 'getUserProfilePhotos'), 'другие методы: ' + JSON.stringify(res.calls));
  return sends[0][1].text;
}

async function loggedIn(page, vp, user) {
  await page.waitForSelector('.toast', { timeout: 6000 });
  const toast = await page.textContent('.toast');
  if (vp.name === '1440') {
    await page.waitForSelector('.sh__user', { timeout: 6000 });
    check(!(await page.$('.sh-login__panel')), 'панель входа закрылась');
  } else {
    await page.waitForFunction(() => !document.querySelector('.code-login'), null, { timeout: 6000 });
  }
  const me = await page.evaluate(() => fetch('/api/auth/me', { credentials: 'same-origin' }).then((r) => r.json()));
  check(me.user && me.user.id === user.id, '/api/auth/me после входа: ' + JSON.stringify(me));
  return toast;
}

async function scenarioDeepLink(browser, vp) {
  const { context, page, log } = await open(browser, vp);
  const r = {};
  const c = await openCodeLogin(page, vp);
  r.qr = !!(await page.$('.code-login__qrimg svg'));
  if (vp.name === '1440') {
    await page.waitForSelector('.code-login__qrimg svg');
    await page.locator('.code-login__qrimg').screenshot({ path: path.join(OUT, `qr-only-${vp.name}.png`) });
    fs.writeFileSync(path.join(OUT, `qr-only-${vp.name}.txt`), c.link);
  }
  r.status = await page.textContent('.code-login__status');
  await shot(page, 'a-code', vp);
  // пока бот не подтвердил — сессии нет
  const before = await page.evaluate(() => fetch('/api/auth/code/status').then((x) => x.json()));
  check(before.status === 'pending', 'до подтверждения — pending');
  const res = await botSays(ALEX, `/start login_${c.token}`);
  r.botReply = onlySender(res, ALEX);
  check(r.botReply === MSG_OK, 'ответ бота: ' + r.botReply);
  r.toast = await loggedIn(page, vp, ALEX);
  await shot(page, 'b-logged-in', vp);
  r.log = log;
  await context.close();
  return r;
}

async function scenarioExpired(browser, vp) {
  const { context, page, log } = await open(browser, vp);
  const r = {};
  const MARIA = maria();
  await setTtl(6);
  const c = await openCodeLogin(page, vp);
  await page.waitForSelector('.code-login__expired', { timeout: 15000 });
  r.expiredText = await page.textContent('.code-login__expired');
  await shot(page, 'c-expired', vp);
  const res = await botSays(MARIA, c.digits);
  r.botReplyOld = onlySender(res, MARIA);
  check(r.botReplyOld === MSG_BAD, 'просроченный код: ' + r.botReplyOld);
  await setTtl(300);
  await page.click('.code-login__expired .tg-login__btn');
  await page.waitForSelector('.code-login__digits');
  const fresh = (await page.textContent('.code-login__digits')).replace(/\s/g, '');
  r.renewed = fresh !== c.digits || (await page.getAttribute('.code-login__open', 'href')) !== c.link;
  check(r.renewed, 'новый код');
  await shot(page, 'c-renewed', vp);
  r.log = log;
  await context.close();
  return r;
}

async function scenarioDigits(browser, vp) {
  const { context, page, log } = await open(browser, vp);
  const r = {};
  const MARIA = maria();
  const c = await openCodeLogin(page, vp);
  await page.click('.code-login__copy');
  await page.waitForFunction(() => /Скопировано/.test(document.querySelector('.code-login__copy').textContent), null, { timeout: 3000 })
    .then(() => { r.copied = true; }, () => { r.copied = false; });
  await shot(page, 'd-code-copied', vp);
  const wrong = String((Number(c.digits) + 1) % 1e6).padStart(6, '0');
  r.botReplyWrong = onlySender(await botSays(MARIA, wrong), MARIA);
  check(r.botReplyWrong === MSG_BAD, 'неверный код: ' + r.botReplyWrong);
  const res = await botSays(MARIA, `${c.digits.slice(0, 3)} ${c.digits.slice(3)}`);
  r.botReply = onlySender(res, MARIA);
  check(r.botReply === MSG_OK, 'ответ бота: ' + r.botReply);
  r.toast = await loggedIn(page, vp, MARIA);
  await shot(page, 'd-digits-logged-in', vp);
  // тот же код второй раз не подтвердить
  const other = maria();
  r.botReplyRepeat = onlySender(await botSays(other, c.digits), other);
  check(r.botReplyRepeat === MSG_BAD, 'повторный код: ' + r.botReplyRepeat);
  r.log = log;
  await context.close();
  return r;
}

(async () => {
  const browser = await chromium.launch();
  let failed = false;
  try {
    for (const vp of VIEWPORTS) {
      const out = {};
      report.viewports[vp.name] = out;
      for (const [name, fn] of [['deep_link', scenarioDeepLink], ['expired', scenarioExpired], ['digits', scenarioDigits]]) {
        try {
          out[name] = await fn(browser, vp);
          out[name].ok = true;
        } catch (e) {
          failed = true;
          out[name] = { ok: false, error: String(e && e.stack || e) };
        }
        console.log(vp.name, name, out[name].ok ? 'ok' : out[name].error);
      }
    }
  } finally {
    await browser.close();
  }
  let external = 0;
  let errors = 0;
  for (const vp of Object.values(report.viewports))
    for (const s of Object.values(vp)) {
      if (!s.log) continue;
      external += Object.values(s.log.external).reduce((a, b) => a + b, 0);
      errors += s.log.errors.length;
    }
  report.summary = { external_requests: external, console_errors: errors, failed };
  report.finished = new Date().toISOString();
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report.summary));
  process.exit(failed || external || errors ? 1 : 0);
})();
