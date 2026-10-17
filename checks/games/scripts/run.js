// Проверки игр (викторина, пенальти, рейтинг недели) — Playwright против https://realmadridfan.ru.
//
//   NODE_PATH=C:/Users/egor3/node_modules node run.js <distDir> <dataDir> <localApi> <outDir> <quiz_questions.json>
//
// Страницы и /assets/* — из локальной сборки (distDir); /api/games/*, /api/auth/*, /api/predict/* — локальный
// бэкенд (local_backend.py, фейковый токен бота); /img/avatar/* — из dataDir/avatars (как nginx);
// остальное /api/* и /img/* — с сервера. Внешние хосты (telegram.org и др.) блокируются и считаются.
const { chromium } = require('playwright');
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const path = require('path');

const [, , DIST, DATA, LOCAL, OUT, BANK] = process.argv;
const SITE = 'https://realmadridfan.ru';
const HOST = 'realmadridfan.ru';
const BOT_TOKEN = '123456:LOCAL-fake-bot-token';
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
const ME = { id: 4242, first_name: 'Алексей', last_name: 'Морозов', username: 'madridista_alex', language_code: 'ru' };
fs.mkdirSync(OUT, { recursive: true });
const report = { started: new Date().toISOString(), viewports: {} };

// банк вопросов: верный вариант ищем по тексту вопроса, как знаток
const bank = JSON.parse(fs.readFileSync(BANK, 'utf8'));
const byText = new Map();
for (const items of Object.values(bank)) for (const q of items) byText.set(q.q, q);
function rightIndex(qText, shown) {
  const q = byText.get(qText);
  if (!q) throw new Error('вопрос не найден в банке: ' + qText);
  return shown.indexOf(q.a[q.correct]);
}

// ---------- подпись initData с фейковым токеном ----------
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
const script = (keepers, rival) => localPost('/api/games/_test/script', { keepers, rival });

async function open(browser, vp, { tma = false, video = null } = {}) {
  const context = await browser.newContext({ ...vp, locale: 'ru-RU', timezoneId: 'Europe/Moscow',
    ...(video ? { recordVideo: { dir: video, size: vp.viewport } } : {}) });
  const log = { external: {}, errors: [], failed: [] };
  if (tma) await context.addInitScript(TMA_MOCK);
  await context.route(`${SITE}/**`, async (route) => {
    const p = new URL(route.request().url()).pathname;
    if (/^\/api\/(games|auth|predict)\//.test(p)) return proxyLocal(route);
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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// заставка при первом открытии (index.html) — ждём, пока уйдёт
async function go(page, url) {
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => !document.getElementById('splash'), null, { timeout: 15000 });
}
async function shot(page, name, vp, full = false) {
  await page.screenshot({ path: path.join(OUT, `${name}-${vp.name}.png`), fullPage: full });
  const h = await hscroll(page);
  if (h > 0) throw new Error(`${name}-${vp.name}: горизонтальная прокрутка ${h}px`);
  return h;
}

// ---------- викторина ----------
async function currentQuestion(page) {
  await page.waitForSelector('.gm-q__text');
  const q = await page.textContent('.gm-q__text');
  const a = await page.$$eval('.gm-ans__text', (els) => els.map((e) => e.textContent));
  const idx = await page.$eval('.gm-q', (e) => e.getAttribute('aria-label'));
  return { q, a, idx };
}
async function waitNextQuestion(page, prevIdx) {
  await page.waitForFunction((prev) => {
    const el = document.querySelector('.gm-q');
    return (el && el.getAttribute('aria-label') !== prev) || document.querySelector('.gm-result');
  }, prevIdx, { timeout: 25000 });
}

async function playQuiz(page, vp, plan, prefix) {
  // plan: массив 'right' | 'wrong' | 'timeout' | 'key' (верный клавишей) длиной 10
  const out = { answers: [] };
  await page.click('.gm-level >> nth=0');
  for (let i = 0; i < plan.length; i += 1) {
    const cur = await currentQuestion(page);
    const right = rightIndex(cur.q, cur.a);
    const media = await page.$('.gm-q__media img');
    if (media) out.media = (out.media || 0) + 1;
    if (i === 0 && prefix) await shot(page, `${prefix}-question`, vp);
    const act = plan[i];
    if (act !== 'timeout') await sleep(700); // человек читает вопрос (сервер не принимает ответ быстрее 0,35 с)
    if (act === 'right') await page.click(`.gm-ans >> nth=${right}`);
    else if (act === 'key') await page.keyboard.press(String(right + 1));
    else if (act === 'wrong') await page.click(`.gm-ans >> nth=${(right + 1) % 4}`);
    else if (act === 'timeout') {
      await page.waitForSelector('.gm-timer.is-hurry', { timeout: 15000 });
      if (prefix) await shot(page, `${prefix}-hurry`, vp);
      await page.waitForSelector('.gm-fb', { timeout: 20000 });
    }
    await page.waitForSelector('.gm-fb');
    const fb = await page.textContent('.gm-fb');
    out.answers.push({ act, fb });
    if (prefix && i < 3) {
      await sleep(act === 'wrong' ? 160 : 260);
      await shot(page, `${prefix}-${act}`, vp);
    }
    await waitNextQuestion(page, cur.idx);
  }
  await page.waitForSelector('.gm-result');
  out.score = Number(await page.textContent('.gm-result__score'));
  out.stats = await page.$$eval('.gm-result__stats b', (els) => els.map((e) => e.textContent));
  out.badge = !!(await page.$('.gm-result__badge'));
  return out;
}

// ---------- пенальти ----------
async function fireShot(page, how, zone) {
  if (how === 'click') await page.click(`.pk-zone >> nth=${zone - 1}`);
  else if (how === 'key') await page.keyboard.press(String(zone));
  else if (how === 'arrows') {
    // прицел стрелками: ряд, затем до упора влево и вправо по нужному числу колонок; удар — Enter
    await page.evaluate(() => document.activeElement && document.activeElement.blur());
    const col = (zone - 1) % 3;
    await page.keyboard.press(zone <= 3 ? 'ArrowUp' : 'ArrowDown');
    await page.keyboard.press('ArrowLeft');
    await page.keyboard.press('ArrowLeft');
    for (let i = 0; i < col; i += 1) await page.keyboard.press('ArrowRight');
    await page.keyboard.press('Enter');
  } else if (how === 'swipe') {
    const b = await page.$eval('.pk-ballhit', (e) => { const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
    const w = await page.$eval('.pk-stage', (e) => e.clientWidth);
    const col = (zone - 1) % 3;
    const dx = col === 0 ? -0.35 * w : col === 2 ? 0.35 * w : 0;
    const dy = zone <= 3 ? -0.5 * w : -0.2 * w;
    await page.mouse.move(b.x, b.y);
    await page.mouse.down();
    await page.mouse.move(b.x + dx / 2, b.y + dy / 2, { steps: 4 });
    await page.mouse.move(b.x + dx, b.y + dy, { steps: 4 });
    await page.mouse.up();
  }
}
async function waitShotDone(page, n) {
  await page.waitForFunction((k) => document.querySelectorAll('.pk-board__side:first-child .pk-dot--goal, .pk-board__side:first-child .pk-dot--miss').length >= k || document.querySelector('.gm-result'), n, { timeout: 15000 });
  await page.waitForFunction(() => !document.querySelector('.pk-flash'), null, { timeout: 15000 });
}

async function startPenalty(page, levelIdx) {
  await page.click(`.gm-level >> nth=${levelIdx}`);
  await page.waitForSelector('.pk-stage');
  await sleep(150);
}

async function main() {
  // аватары соседей по рейтингу (как будто сборщик их уже скачал)
  const browser = await chromium.launch();
  const avDir = path.join(DATA, 'avatars');
  fs.mkdirSync(avDir, { recursive: true });
  {
    const p = await browser.newPage();
    const people = { 1001: ['МР', '#3a2a4f'], 1002: ['ДК', '#20384a'], 1003: ['СБ', '#3d2f1c'], 1005: ['ПЕ', '#1f3d2e'], 4242: ['АМ', '#2a3350'] };
    for (const [id, [txt, col]] of Object.entries(people)) {
      const data = await p.evaluate(([t, c]) => {
        const cv = document.createElement('canvas');
        cv.width = cv.height = 160;
        const g = cv.getContext('2d');
        g.fillStyle = c; g.fillRect(0, 0, 160, 160);
        g.fillStyle = '#e9d39a'; g.beginPath(); g.arc(80, 64, 31, 0, 7); g.fill();
        g.beginPath(); g.ellipse(80, 165, 60, 55, 0, Math.PI, 0); g.fill();
        g.fillStyle = '#1b2240'; g.font = 'bold 26px sans-serif'; g.textAlign = 'center'; g.fillText(t, 80, 73);
        return cv.toDataURL('image/jpeg', 0.9);
      }, [txt, col]);
      fs.writeFileSync(path.join(avDir, `${id}.jpg`), Buffer.from(data.split(',')[1], 'base64'));
    }
    await p.close();
  }

  for (const vp of VIEWPORTS) {
    const r = {};
    report.viewports[vp.name] = r;

    // ---- А. Викторина без входа: правильные, неправильные, таймер, клавиатура ----
    {
      const { context, page, log } = await open(browser, vp);
      await go(page, `${SITE}/games/quiz`);
      await page.waitForSelector('.gm-level');
      await page.waitForSelector('.gm-board .ui-lb');
      await shot(page, 'a-quiz-levels', vp, true);
      r.navLabel = vp.isMobile ? await page.textContent('.bottom-nav a.on') : await page.textContent('.sh__link.on');
      const quiz = await playQuiz(page, vp, ['right', 'wrong', 'timeout', 'key', 'right', 'right', 'wrong', 'key', 'right', 'right'], 'a-quiz');
      await shot(page, 'a-quiz-result', vp, true);
      const local = await page.evaluate(() => localStorage.getItem('rm-games-best'));
      await page.click('text=Другой уровень');
      await page.waitForSelector('.gm-level');
      const bestCard = await page.textContent('.gm-level >> nth=0');
      r.quizAnon = { ...quiz, localStorage: local, levelCard: bestCard, external: log.external, errors: log.errors, failed: log.failed };
      await context.close();
    }

    // ---- Б. Пенальти без входа: серия из 5 и серия до промаха ----
    {
      const { context, page, log } = await open(browser, vp);
      await go(page, `${SITE}/games/penalty`);
      await page.waitForSelector('.gm-level');
      await page.waitForSelector('.gm-board .ui-lb');
      await shot(page, 'b-pk-levels', vp, true);
      await startPenalty(page, 1);
      await shot(page, 'b-pk-ready', vp);
      // 5 ударов: вратарь угадывает 3-й; соперник забивает 1-й, 3-й, 5-й → 4:3
      await script([6, 6, 1, 4, 1], [true, false, true, false, true]);
      const hows = ['click', 'key', 'click', 'arrows', vp.hasTouch ? 'swipe' : 'swipe'];
      const zones = [1, 3, 1, 5, 4];
      for (let i = 0; i < 5; i += 1) {
        await fireShot(page, hows[i], zones[i]);
        if (i === 0) { await sleep(260); await shot(page, 'b-pk-flight', vp); }
        if (i === 0) { await page.waitForSelector('.pk-flash'); await shot(page, 'b-pk-goal', vp); }
        if (i === 2) { await page.waitForSelector('.pk-flash'); await shot(page, 'b-pk-save', vp); }
        await waitShotDone(page, i + 1);
      }
      await page.waitForSelector('.gm-result');
      await shot(page, 'b-pk-result', vp, true);
      const res5 = { headline: await page.textContent('.gm-result__headline'), score: await page.textContent('.gm-result__score'),
        stats: await page.$$eval('.gm-result__stats b', (els) => els.map((e) => e.textContent)) };
      // «Ещё раз» → ничья 5:5 → серия до промаха: 6-й — гол/гол, 7-й — сейв, соперник забил → 6:7
      await script([6, 6, 6, 6, 6, 6, 2], [true, true, true, true, true, true, true]);
      await page.click('text=Ещё раз');
      await page.waitForSelector('.pk-stage');
      for (let i = 0; i < 7; i += 1) {
        await fireShot(page, 'key', i < 6 ? 1 : 2);
        await waitShotDone(page, i + 1);
        if (i === 5) await shot(page, 'b-pk-sudden', vp);
      }
      await page.waitForSelector('.gm-result');
      await shot(page, 'b-pk-sudden-result', vp, true);
      const resSd = { headline: await page.textContent('.gm-result__headline'), score: await page.textContent('.gm-result__score') };
      const fps = await page.evaluate(() => window.__rmShotFps || []);
      r.penaltyAnon = { five: res5, sudden: resSd, fps, external: log.external, errors: log.errors, failed: log.failed };
      await context.close();
    }

    // ---- В. Со входом (мини-апп, подписанный initData): результаты сохраняются, рейтинг ----
    {
      const { context, page, log } = await open(browser, vp, { tma: true });
      await go(page, `${SITE}/games/quiz${tmaHash(signInitData(ME))}`);
      await page.waitForFunction(() => document.querySelector('.gm-level'));
      await page.waitForFunction(() => !document.querySelector('.gm-board__login'));
      const quiz = await playQuiz(page, vp, Array(10).fill('right'), null);
      // «Новый рекорд» — только если результат лучше прежнего на сервере (на 1440 пользователь уже играл на 390)
      await page.waitForFunction(() => [...document.querySelectorAll('.gm-board .ui-lb.is-me')].length > 0, null, { timeout: 10000 });
      await shot(page, 'c-tma-quiz-result', vp, true);
      await page.click('text=Поделиться');
      await sleep(300);
      const share = await page.evaluate(() => window.__tgEvents.filter((e) => e[0] === 'web_app_open_tg_link').map((e) => e[1]));
      const myRow = await page.textContent('.gm-board .ui-lb.is-me');
      // пенальти со входом
      await page.click('.gtabs__tab >> text=Пенальти');
      await page.waitForSelector('.gm-level');
      await startPenalty(page, 3);
      await script([6, 6, 6, 6, 6], [false, false, false, false, false]);
      for (let i = 0; i < 5; i += 1) {
        await fireShot(page, 'click', 1);
        await waitShotDone(page, i + 1);
      }
      await page.waitForSelector('.gm-result');
      await page.waitForFunction(() => [...document.querySelectorAll('.gm-board .ui-lb.is-me')].length > 0, null, { timeout: 10000 });
      await shot(page, 'c-tma-pk-result', vp, true);
      const haptics = await page.evaluate(() => window.__tgEvents.filter((e) => e[0] === 'web_app_trigger_haptic_feedback').map((e) => e[1]));
      const me = await page.evaluate(async () => {
        const r = await fetch('/api/games/me', { credentials: 'same-origin' });
        return { status: r.status, body: await r.json() };
      });
      const lbPen = await page.evaluate(async () => (await fetch('/api/games/leaderboard?game=penalty')).json());
      // рейтинг: экран уровней со строкой «моё место»
      await page.click('text=Другой уровень');
      await page.waitForSelector('.gm-board .ui-lb.is-me');
      await page.$eval('.gm-board', (e) => e.scrollIntoView());
      await shot(page, 'd-rating-penalty', vp);
      // вкладка «Прогнозы» внутри «Игр»
      await page.click('.gtabs__tab >> text=Прогнозы');
      await page.waitForURL('**/predict');
      await sleep(600);
      await shot(page, 'd-predict-tabs', vp);
      r.loggedIn = { quiz: { score: quiz.score, badge: quiz.badge, stats: quiz.stats }, myRow, share, haptics: haptics.length,
        hapticKinds: [...new Set(haptics.map((h) => JSON.stringify(h)))], me, penaltyTop: lbPen.top.map((x) => [x.rank, x.name, x.score]),
        external: log.external, errors: log.errors, failed: log.failed };
      await context.close();
    }

    // ---- Г. Рейтинг недели без входа (сайт) ----
    {
      const { context, page, log } = await open(browser, vp);
      await go(page, `${SITE}/games/quiz`);
      await page.waitForSelector('.gm-board .ui-lb');
      await page.$eval('.gm-board', (e) => e.scrollIntoView());
      await shot(page, 'd-rating-quiz', vp);
      const rows = await page.$$eval('.gm-board .ui-lb', (els) => els.map((e) => e.textContent.replace(/\s+/g, ' ').trim()));
      const avatars = await page.$$eval('.gm-board .ui-lb__av img', (els) => els.map((e) => [e.getAttribute('src'), e.naturalWidth]));
      r.rating = { rows, avatars, external: log.external, errors: log.errors, failed: log.failed };
      await context.close();
    }
  }

  // ---- Д. Видео одного удара (390) ----
  {
    const vp = VIEWPORTS[0];
    const vdir = path.join(OUT, '_video');
    const { context, page } = await open(browser, vp, { video: vdir });
    await go(page, `${SITE}/games/penalty`);
    await startPenalty(page, 0);
    await script([1], [true]);
    await sleep(400);
    await fireShot(page, 'click', 3);
    await waitShotDone(page, 1);
    await sleep(300);
    const v = page.video();
    await context.close();
    const src = await v.path();
    fs.copyFileSync(src, path.join(OUT, 'shot-390.webm'));
    fs.rmSync(vdir, { recursive: true, force: true });
    report.video = 'shot-390.webm';
  }

  await browser.close();
  report.finished = new Date().toISOString();
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1));
  console.log('ok');
}

main().catch((e) => {
  console.error(e);
  report.error = String(e && e.stack || e);
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1));
  process.exit(1);
});
