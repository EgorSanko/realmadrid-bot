// Проверка этапа 3 (трансляция) локально.
// Нужны: uvicorn на 127.0.0.1:8011 (ADMIN_TOKEN=test, временный DATA_DIR)
// и `vite preview` собранного dist по https на 127.0.0.1:4443 с прокси /api → 8011.
// Запуск: NODE_PATH=C:/Users/egor3/node_modules node checks/stage3/run.js
const path = require('path');
const { chromium } = require('playwright');

const BASE = process.env.BASE || 'https://127.0.0.1:4443';
const TOKEN = process.env.ADMIN_TOKEN || 'test';
const OUT = __dirname;
// тестовые потоки — только для проверки, в коде приложения их нет
const TEST_STREAM = process.env.TEST_STREAM || 'https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8';
const TEST_HOST = new URL(TEST_STREAM).host;
const BROKEN = `https://${TEST_HOST}/stage3-check-does-not-exist/chunks.m3u8`;

const b64url = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
// ссылка в формате поставщика: query-строка с session id и token (exp через 2 ч)
const EXP = Math.floor(Date.now() / 1000) + 2 * 3600;
const STREAM_URL = `${TEST_STREAM}?nimblesessionid=160194540&token=${b64url({ ch: 'fut2', exp: EXP })}.c2lnbmF0dXJl`;

const log = (...a) => console.log(...a);
const sec = (t0) => ((Date.now() - t0) / 1000).toFixed(1);

(async () => {
  const browser = await chromium.launch({ channel: process.env.CHANNEL || undefined });
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    locale: 'ru-RU',
    ignoreHTTPSErrors: true, // самоподписанный сертификат localhost
  });

  const hosts = new Map();
  const consoleErrors = [];
  const requests = [];
  ctx.on('request', (req) => {
    const u = new URL(req.url());
    const key = u.protocol === 'data:' || u.protocol === 'blob:' ? u.protocol : u.host;
    hosts.set(key, (hosts.get(key) || 0) + 1);
    requests.push({ t: Date.now(), url: req.url() });
  });
  const watch = (p, name) => {
    p.on('console', (m) => m.type() === 'error' && consoleErrors.push(`[${name}] ${m.text()}`));
    p.on('pageerror', (e) => consoleErrors.push(`[${name}] pageerror: ${e.message}`));
  };

  // исходное состояние: эфир выключен
  await ctx.request.post(`${BASE}/api/admin/stream/stop`, { headers: { 'X-Admin-Token': TOKEN } });

  // 1. главная без эфира
  const home = await ctx.newPage();
  watch(home, 'home');
  await home.goto(BASE + '/', { waitUntil: 'networkidle' });
  await home.evaluate(() => document.fonts.ready);
  await home.waitForSelector('.stream-empty');
  const offlineText = await home.locator('.stream-empty').innerText();
  const hlsBefore = requests.filter((r) => /\/assets\/hls-[^/]+\.js/.test(r.url)).length;
  await home.screenshot({ path: path.join(OUT, '01-home-offline.png') });
  log('1. Главная без эфира:', JSON.stringify(offlineText.replace(/\n+/g, ' / ')), '| hls-чанк загружен до эфира:', hlsBefore ? 'ДА (плохо)' : 'нет');

  // 2. админка: вход по токену
  const admin = await ctx.newPage();
  watch(admin, 'admin');
  await admin.goto(BASE + '/admin', { waitUntil: 'networkidle' });
  await admin.fill('#admin-token', 'wrong-token');
  await admin.click('button:has-text("Войти")');
  const denied = await admin.locator('.admin-msg--err').innerText();
  log('2a. Неверный токен →', JSON.stringify(denied));
  await admin.fill('#admin-token', TOKEN);
  await admin.click('button:has-text("Войти")');
  await admin.waitForSelector('text=Эфир выключен');
  const stored = await admin.evaluate(() => sessionStorage.getItem('rm-admin-token'));
  log('2b. Вход по токену: ок, токен в sessionStorage:', stored === TOKEN);

  // 3. вставить ссылку → срок действия → «Начать эфир»
  await admin.fill('#stream-url', STREAM_URL);
  await admin.fill('#stream-title', 'Проверка эфира');
  const expText = await admin.locator('.admin-exp').first().innerText();
  log('3. Срок действия ссылки в админке:', JSON.stringify(expText));
  await admin.screenshot({ path: path.join(OUT, '02-admin-link.png'), fullPage: true });
  const tStart = Date.now();
  await admin.click('button:has-text("Начать эфир")');
  await admin.waitForSelector('text=ИДЁТ ЭФИР');
  log('   «Начать эфир» → статус «ИДЁТ ЭФИР»');

  // 4. главная сама (опрос 20 с) переключается на плеер, видео играет
  await home.bringToFront();
  await home.waitForSelector('.player', { timeout: 25_000 });
  log(`4. Главная показала плеер через ${sec(tStart)} с после старта (без перезагрузки)`);
  await home.waitForFunction(
    () => {
      const v = document.querySelector('.player video');
      return v && v.readyState >= 3 && v.currentTime > 1;
    },
    null,
    { timeout: 45_000 },
  );
  const p1 = await home.evaluate(() => {
    const v = document.querySelector('.player video');
    return { t: v.currentTime, rs: v.readyState, paused: v.paused, muted: v.muted, w: v.videoWidth, h: v.videoHeight, src: v.currentSrc.slice(0, 5) };
  });
  await home.waitForTimeout(3000);
  const p2 = await home.evaluate(() => {
    const v = document.querySelector('.player video');
    return { t: v.currentTime, rs: v.readyState, phase: document.querySelector('.player').dataset.phase };
  });
  const hlsChunk = requests.find((r) => /\/assets\/hls-[^/]+\.js/.test(r.url));
  const manifestReq = requests.find((r) => r.url.startsWith(TEST_STREAM));
  log(
    `   video: currentTime ${p1.t.toFixed(2)} → ${p2.t.toFixed(2)} за 3 с, readyState ${p1.rs}/${p2.rs}, ` +
      `phase=${p2.phase}, muted=${p1.muted}, paused=${p1.paused}, ${p1.w}x${p1.h}, src=${p1.src}…`,
  );
  log('   hls-чанк:', hlsChunk ? new URL(hlsChunk.url).pathname : 'НЕ загружен');
  log('   плейлист запрошен с исходной query-строкой:', manifestReq?.url === STREAM_URL);
  await home.evaluate(() => {
    // показать кнопки на скриншоте
    document.querySelector('.player').classList.remove('player--idle');
  });
  await home.screenshot({ path: path.join(OUT, '03-home-live.png') });

  // кнопка «Включить звук»
  await home.click('.player__unmute');
  const mutedAfter = await home.evaluate(() => document.querySelector('.player video').muted);
  log('   «Включить звук» → muted =', mutedAfter);

  // 5. «Остановить» → главная вернулась к заглушке ≤ 20 с
  await admin.bringToFront();
  const tStop = Date.now();
  await admin.click('button:has-text("Остановить")');
  await admin.waitForSelector('text=Эфир выключен');
  await home.waitForSelector('.stream-empty', { timeout: 25_000 });
  const backIn = (Date.now() - tStop) / 1000;
  log(`5. «Остановить» → заглушка на главной через ${backIn.toFixed(1)} с (${backIn <= 20 ? '≤ 20 с' : '> 20 с!'})`);

  // 6. битая ссылка → состояние ошибки
  await admin.fill('#stream-url', BROKEN);
  await admin.click('button:has-text("Начать эфир")');
  await admin.waitForSelector('text=ИДЁТ ЭФИР');
  const tBroken = Date.now();
  await home.reload({ waitUntil: 'domcontentloaded' });
  await home.waitForSelector('.player__msg', { timeout: 90_000 });
  const errText = await home.locator('.player__msg').innerText();
  log(`6. Битая ссылка → ${JSON.stringify(errText.replace(/\n+/g, ' / '))} через ${sec(tBroken)} с (с переподключениями)`);
  await home.screenshot({ path: path.join(OUT, '04-home-error.png') });

  // 7. http-ссылка → предупреждение в админке (сайт открыт по https)
  await admin.click('button:has-text("Остановить")');
  await admin.fill('#stream-url', 'http://example.com/live/chunks.m3u8');
  const warn = await admin.locator('.admin-msg--warn').innerText();
  log('7. http-ссылка на https-сайте →', JSON.stringify(warn));
  await admin.screenshot({ path: path.join(OUT, '05-admin-http-warning.png'), fullPage: true });

  // 8. клиентская проверка ссылки
  await admin.fill('#stream-url', 'ftp://example.com/x.m3u8');
  await admin.locator('#stream-url').blur();
  log('8. ftp-ссылка →', JSON.stringify(await admin.locator('.admin-msg--err').first().innerText()));
  await admin.fill('#stream-url', '');
  await admin.click('button:has-text("Начать эфир")');
  log('   пустая ссылка →', JSON.stringify(await admin.locator('.admin-msg--err').first().innerText()));

  await browser.close();

  const own = new Set([new URL(BASE).host, 'data:', 'blob:']);
  const foreign = [...hosts.keys()].filter((h) => !own.has(h) && h !== TEST_HOST);
  log('\n== Хосты запросов:', JSON.stringify(Object.fromEntries(hosts)));
  log('== Внешние хосты, кроме тестового потока:', foreign.length ? foreign : '(нет)');
  log('== Ошибки консоли:', consoleErrors.length);
  for (const e of consoleErrors) log('   ', e.slice(0, 200));
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
