// Проверка пенальти с Куртуа — Playwright против https://realmadridfan.ru.
//
//   NODE_PATH=C:/Users/egor3/node_modules node run.js <distDir> <localApi> <outDir>
//
// Страницы и /assets/* — из локальной сборки (distDir); /api/games/*, /api/auth/*, /api/predict/* — локальный
// бэкенд (local_backend.py: фейковый токен бота, сценарий ударов через /api/games/_test/script);
// остальное /api/* и /img/* — с сервера. Внешние хосты блокируются и считаются.
//
// Кадры снимаются «стоп-кадром»: window.__rmPkAt = мс от начала удара — сцена рисует этот момент и ждёт.
const { chromium } = require('playwright');
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const path = require('path');

const [, , DIST, LOCAL, OUT] = process.argv;
const SITE = 'https://realmadridfan.ru';
const HOST = 'realmadridfan.ru';
const BOT_TOKEN = '123456:LOCAL-fake-bot-token';
const MIME = {
  '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.woff2': 'font/woff2', '.woff': 'font/woff',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.json': 'application/json',
  '.ico': 'image/x-icon', '.webmanifest': 'application/manifest+json',
};
const VIEWPORTS = [
  { name: '390', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  { name: '1440', viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
];
const ME = { id: 4242, first_name: 'Алексей', last_name: 'Морозов', username: 'madridista_alex', language_code: 'ru' };
const FLIGHT = 520;
fs.mkdirSync(OUT, { recursive: true });
const report = { started: new Date().toISOString(), viewports: {} };

// ---------- Telegram (для проверки вибрации) ----------
const hmac = (key, msg) => crypto.createHmac('sha256', key).update(msg).digest();
function signInitData(user) {
  const f = { auth_date: String(Math.floor(Date.now() / 1000)), query_id: 'AAHtestQuery', user: JSON.stringify(user),
    signature: 'c3R1Yi1zaWduYXR1cmUtZm9yLWxvY2FsLWNoZWNrcw' };
  const dcs = Object.keys(f).sort().map((k) => `${k}=${f[k]}`).join('\n');
  f.hash = hmac(hmac('WebAppData', BOT_TOKEN), dcs).toString('hex');
  return new URLSearchParams(f).toString();
}
function tmaHash(initData) {
  const theme = { bg_color: '#06070b', secondary_bg_color: '#0b0d14', text_color: '#eef0f5', hint_color: '#8a90a1',
    link_color: '#d4af37', button_color: '#d4af37', button_text_color: '#1a1408', header_bg_color: '#06070b' };
  return '#' + new URLSearchParams({ tgWebAppData: initData, tgWebAppVersion: '8.0', tgWebAppPlatform: 'ios',
    tgWebAppThemeParams: JSON.stringify(theme) }).toString();
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

// ---------- прокси к локальному бэкенду ----------
function proxyLocal(route) {
  const req = route.request();
  const u = new URL(req.url());
  const target = new URL(LOCAL);
  return req.allHeaders().then((hdrs) => new Promise((resolve) => {
    const headers = { ...hdrs, host: HOST };
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
      headers: { 'content-type': 'application/json', 'content-length': data.length } }, (res) => { res.resume(); res.on('end', resolve); });
    r.on('error', reject);
    r.end(data);
  });
}
const script = (s) => localPost('/api/games/_test/script', s);

async function open(browser, vp, { tma = false, video = null, reducedMotion = 'no-preference' } = {}) {
  const context = await browser.newContext({ ...vp, locale: 'ru-RU', timezoneId: 'Europe/Moscow', reducedMotion,
    ...(video ? { recordVideo: { dir: video, size: vp.viewport } } : {}) });
  const log = { external: {}, errors: [], failed: [], assets: [] };
  if (tma) await context.addInitScript(TMA_MOCK);
  await context.route(`${SITE}/**`, async (route) => {
    const p = new URL(route.request().url()).pathname;
    if (/^\/api\/(games|auth|predict)\//.test(p)) return proxyLocal(route);
    if (p.startsWith('/api/') || p.startsWith('/img/')) return route.continue();
    const file = path.join(DIST, decodeURIComponent(p));
    if (p !== '/' && fs.existsSync(file) && fs.statSync(file).isFile()) {
      if (p.startsWith('/assets/')) log.assets.push(p);
      return route.fulfill({ status: 200, headers: { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' }, body: fs.readFileSync(file) });
    }
    return route.fulfill({ status: 200, headers: { 'content-type': 'text/html' }, body: fs.readFileSync(path.join(DIST, 'index.html')) });
  });
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

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
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
// снимок только сцены (крупно)
async function stageShot(page, name, vp) {
  const el = await page.$('.pk-wrap');
  await el.screenshot({ path: path.join(OUT, `${name}-${vp.name}.png`) });
}
const freeze = (page, t) => page.evaluate((v) => { if (v == null) delete window.__rmPkAt; else window.__rmPkAt = v; }, t);
const idleReady = (page) => page.waitForFunction(() => !document.querySelector('.pk-stage.is-busy') && !document.querySelector('.pk-flash'), null, { timeout: 15000 });

async function startSeries(page, levelIdx = 0) {
  await page.click(`.gm-level >> nth=${levelIdx}`);
  await page.waitForSelector('.pk-stage');
  await page.waitForFunction(() => [...document.querySelectorAll('.pk-world img')].every((i) => i.complete && i.naturalWidth > 0));
}

async function fire(page, how, zone) {
  if (how === 'key') await page.keyboard.press(String(zone));
  else if (how === 'swipe') {
    const b = await page.$eval('.pk-ballhit', (e) => { const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
    await page.mouse.move(b.x, b.y);
    await page.mouse.down();
    for (let i = 1; i <= 6; i += 1) await page.mouse.move(b.x, b.y - (70 * i) / 6);
    await page.mouse.up();
  } else await page.click(`.pk-zone >> nth=${zone - 1}`);
}

// один удар: стоп-кадры frames = [{t, name, wait?}] (по возрастанию t), затем доигрываем
async function framedShot(page, vp, how, zone, frames) {
  const out = [];
  await freeze(page, frames.length ? frames[0].t : null);
  await fire(page, how, zone);
  await page.waitForSelector('.pk-stage.is-flying', { timeout: 5000 });
  let first = true;
  for (const f of frames) {
    await freeze(page, f.t);
    await sleep(first ? 700 : 120 + (f.wait || 0));
    first = false;
    await stageShot(page, f.name, vp);
    out.push(f.name);
  }
  await freeze(page, null);
  await idleReady(page).catch(() => {});
  return out;
}

async function fits(page) {
  return page.evaluate(() => {
    const foot = document.querySelector('.gm-play__foot') || document.querySelector('.pk-hint');
    const nav = document.querySelector('.bottom-nav, nav.tabbar, .nav');
    const stage = document.querySelector('.pk-stage').getBoundingClientRect();
    return {
      inner: innerHeight,
      scroll: document.documentElement.scrollHeight,
      footBottom: Math.round(foot.getBoundingClientRect().bottom),
      navTop: nav ? Math.round(nav.getBoundingClientRect().top) : null,
      stage: { w: Math.round(stage.width), h: Math.round(stage.height), x: Math.round(stage.x) },
    };
  });
}

async function viewport(browser, vp) {
  const r = { frames: [], series: {} };
  report.viewports[vp.name] = r;

  // --- ленивость: на главной нет ни чанка пенальти, ни картинок Куртуа ---
  {
    const { context, page, log } = await open(browser, vp);
    await go(page, `${SITE}/`);
    await sleep(800);
    r.homeAssets = log.assets.filter((a) => /courtois|ball-|PenaltyScreen/.test(a));
    await page.click('a[href="/games/quiz"], a[href^="/games"]').catch(() => {});
    await go(page, `${SITE}/games/penalty`);
    await sleep(500);
    r.penaltyAssets = log.assets.filter((a) => /courtois|ball-|PenaltyScreen/.test(a));
    await context.close();
  }

  // --- серия A и B: стоп-кадры ---
  const { context, page, log } = await open(browser, vp);
  await go(page, `${SITE}/games/penalty`);
  await shot(page, 'a-pick', vp);
  // серия A: сейв справа вверху, гол влево вверх (Куртуа — влево вниз), штанга справа внизу, гол клавишей, гол свайпом
  await script({ keepers: [3, 4, 1, 6, 2], rival: [true, false, true, false, false], woodwork: [false, true, false], bar: [] });
  await startSeries(page, 0);
  await sleep(400);
  await shot(page, 'b-stance', vp);
  r.fit = await fits(page);
  r.frames.push(...await framedShot(page, vp, 'click', 3, [
    { t: 40, name: 'c-crouch' },
    { t: 300, name: 'd-flight-dive3' },
    { t: FLIGHT + 70, name: 'e-save-gloves-z3' },
    { t: FLIGHT + 110 + 300, name: 'e-save-landing-z3' },
  ]));
  r.frames.push(...await framedShot(page, vp, 'click', 1, [
    { t: FLIGHT - 10, name: 'f-dive-z4' },
    { t: FLIGHT + 150, name: 'g-goal-net-z1', wait: 0 },
    { t: FLIGHT + 150 + 380, name: 'g-goal-ball-drops-z1' },
  ]));
  r.frames.push(...await framedShot(page, vp, 'click', 6, [
    { t: FLIGHT - 10, name: 'f-dive-z1' },
    { t: FLIGHT + 40, name: 'h-post-z6' },
  ]));
  r.frames.push(...await framedShot(page, vp, 'key', 4, [{ t: FLIGHT, name: 'f-dive-z6' }]));
  r.frames.push(...await framedShot(page, vp, 'swipe', 5, [{ t: 200, name: 'i-swipe-flight-z5' }, { t: FLIGHT, name: 'f-dive-z2' }]));
  await page.waitForSelector('.gm-result', { timeout: 10000 });
  await sleep(500);
  r.series.A = await page.$eval('.gm-result', (e) => e.innerText.replace(/\s+/g, ' ').slice(0, 200));
  await shot(page, 'j-result', vp);

  // серия B: Куртуа остаётся по центру (низ), сейв слева вверху, перекладина
  await page.click('.gm-result__actions .ui-btn--primary');
  await page.waitForSelector('.pk-stage');
  await script({ keepers: [5, 1, 6, 3, 3], rival: [true, true, true, true, true], woodwork: [true, false], bar: [true] });
  await sleep(300);
  r.frames.push(...await framedShot(page, vp, 'click', 2, [{ t: FLIGHT, name: 'f-dive-z5' }]));
  r.frames.push(...await framedShot(page, vp, 'click', 1, [{ t: FLIGHT + 70, name: 'e-save-gloves-z1' }]));
  r.frames.push(...await framedShot(page, vp, 'click', 3, [{ t: FLIGHT + 60, name: 'h-bar-z3' }]));
  await framedShot(page, vp, 'click', 4, []);
  await framedShot(page, vp, 'click', 5, []);
  await page.waitForSelector('.gm-result', { timeout: 10000 });
  r.series.B = await page.$eval('.gm-result', (e) => e.innerText.replace(/\s+/g, ' ').slice(0, 200));
  r.log = log;
  await context.close();

  // --- FPS: серия в реальном времени без записи видео ---
  {
    const { context: c2, page: p2, log: l2 } = await open(browser, vp);
    await go(p2, `${SITE}/games/penalty`);
    await script({ keepers: [3, 2, 1, 4, 6], rival: [false, false, false, false, false], woodwork: [false, true], bar: [] });
    await startSeries(p2, 1);
    await p2.evaluate(() => { window.__rmShotFps = []; });
    for (const z of [3, 1, 6, 5, 2]) {
      await fire(p2, 'click', z);
      await sleep(200);
      await idleReady(p2).catch(() => {});
      await sleep(150);
    }
    r.fps = await p2.evaluate(() => window.__rmShotFps);
    r.fpsLog = { external: l2.external, errors: l2.errors };
    await c2.close();
  }

  // --- видео: сейв, гол, штанга ---
  {
    const dir = path.join(OUT, `_video-${vp.name}`);
    const { context: c3, page: p3, log: l3 } = await open(browser, vp, { video: dir });
    await go(p3, `${SITE}/games/penalty`);
    await script({ keepers: [1, 6, 2], rival: [true, false, true], woodwork: [false, true], bar: [] });
    await startSeries(p3, 0);
    await sleep(700);
    for (const [how, z] of [['click', 1], ['click', 3], ['click', 4]]) {
      await fire(p3, how, z);
      await sleep(300);
      await idleReady(p3).catch(() => {});
      await sleep(500);
    }
    const v = p3.video();
    r.videoLog = { external: l3.external, errors: l3.errors };
    await c3.close();
    const src = await v.path();
    const dst = path.join(OUT, `shots-${vp.name}.webm`);
    fs.copyFileSync(src, dst);
    fs.rmSync(dir, { recursive: true, force: true });
    r.video = path.basename(dst);
  }

  // --- prefers-reduced-motion: удар короче, без конфетти и тряски ---
  {
    const { context: c4, page: p4, log: l4 } = await open(browser, vp, { reducedMotion: 'reduce' });
    await go(p4, `${SITE}/games/penalty`);
    await script({ keepers: [6, 3], rival: [false, false], woodwork: [false], bar: [] });
    await startSeries(p4, 0);
    await p4.evaluate(() => { window.__rmShotFps = []; });
    await fire(p4, 'click', 3);
    await sleep(380);
    r.reducedConfettiOn = await p4.evaluate(() => !!document.querySelector('.pk-confetti.is-on'));
    await stageShot(p4, 'k-reduced-goal', vp);
    await idleReady(p4).catch(() => {});
    r.reduced = await p4.evaluate(() => window.__rmShotFps);
    r.reducedLog = { external: l4.external, errors: l4.errors };
    await c4.close();
  }
}

async function haptics(browser) {
  const vp = VIEWPORTS[0];
  const { context, page, log } = await open(browser, vp, { tma: true });
  await go(page, `${SITE}/games/penalty${tmaHash(signInitData(ME))}`);
  await script({ keepers: [3, 6, 2], rival: [false, false, false], woodwork: [false, true], bar: [] });
  await startSeries(page, 0);
  await page.evaluate(() => { window.__tgEvents = []; });
  const out = [];
  for (const z of [3, 1, 4]) {
    await page.evaluate(() => { window.__tgEvents = []; });
    await fire(page, 'click', z);
    await sleep(300);
    await idleReady(page).catch(() => {});
    out.push({ zone: z, events: await page.evaluate(() => window.__tgEvents.filter(([n]) => n === 'web_app_trigger_haptic_feedback').map(([, d]) => d)) });
  }
  report.haptics = { shots: out, external: log.external, errors: log.errors };
  await context.close();
}

(async () => {
  const browser = await chromium.launch();
  try {
    for (const vp of VIEWPORTS) await viewport(browser, vp);
    await haptics(browser);
  } catch (e) {
    report.error = String(e && e.stack || e);
  } finally {
    await browser.close();
    report.finished = new Date().toISOString();
    fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1));
    console.log(JSON.stringify({ error: report.error || null }, null, 1));
  }
})();
