// Проверка «новости и видео внутри приложения» против https://realmadridfan.ru.
// Страницы и /assets — из локальной сборки (frontend/dist), /api/news* — из локального бэкенда
// (на сервере его ещё нет; статьи — настоящие страницы источников, скачанные с сервера с заголовками
// сборщика), /img/news/{sportsru-photo,sportsru-dump,sportexpress}/* — так, как их будет отдавать nginx
// (новые location ещё не выложены): Node сам ходит на CDN источника, браузер видит только наш домен.
// Остальные /api и /img — с боевого сервера.
//
// Запуск: NODE_PATH=C:/Users/egor3/node_modules node checks/media-inapp/run.js
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const SITE = 'https://realmadridfan.ru';
const HOST = 'realmadridfan.ru';
const LOCAL_API = process.env.LOCAL_API || 'http://127.0.0.1:8765';
const DIST = path.resolve(__dirname, '../../frontend/dist');
const OUT = __dirname;
const MATCH_ID = process.env.MATCH_ID || '6106274'; // Roma 3:4 Real Madrid — есть видеообзор
const MIME = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json', '.ico': 'image/x-icon', '.webmanifest': 'application/manifest+json' };
// как в deploy/nginx.conf.template (новые location)
const IMG_UP = {
  'sportsru-photo': (p) => `https://photobooth.cdn.sports.ru/${p}?q=85&w=730`,
  'sportsru-dump': (p) => `https://dumpster.cdn.sports.ru/${p}`,
  sportexpress: (p) => `https://ss.sport-express.ru/${p}`,
};
const UA_IMG = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36';
const YT_HOSTS = /(^|\.)(youtube-nocookie\.com|youtube\.com|ytimg\.com|googlevideo\.com|ggpht\.com|google\.com|gstatic\.com|googleapis\.com|doubleclick\.net|withgoogle\.com|googlesyndication\.com|youtube\.googleapis\.com|jnn-pa\.googleapis\.com)$/;

const report = { started: new Date().toISOString(), viewports: {}, failures: [] };
const fail = (vp, msg) => report.failures.push(`[${vp}] ${msg}`);

async function run(vpName, viewport, dpr) {
  const R = (report.viewports[vpName] = { scenarios: {}, external: {}, consoleErrors: [], ytFrameConsole: 0, imgProxied: 0 });
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport, deviceScaleFactor: dpr, locale: 'ru-RU', timezoneId: 'Europe/Moscow' });
  let phase = 'start';
  const reqs = []; // {host, phase, url}
  await context.route(`${SITE}/**`, async (route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/api/news' || p.startsWith('/api/news/')) {
      try {
        const r = await fetch(LOCAL_API + p + u.search);
        return route.fulfill({ status: r.status, headers: { 'content-type': 'application/json', 'cache-control': r.headers.get('cache-control') || 'no-store' }, body: Buffer.from(await r.arrayBuffer()) });
      } catch (e) {
        return route.fulfill({ status: 502, body: String(e) });
      }
    }
    const m = p.match(/^\/img\/news\/(sportsru-photo|sportsru-dump|sportexpress)\/([A-Za-z0-9._~/-]{1,400}\.(?:jpe?g|png|webp))$/);
    if (m) {
      R.imgProxied++;
      try {
        const r = await fetch(IMG_UP[m[1]](m[2]), { headers: { 'User-Agent': UA_IMG, Accept: 'image/avif,image/webp,image/png,image/*;q=0.8' } });
        if (r.ok) return route.fulfill({ status: 200, headers: { 'content-type': r.headers.get('content-type') || 'image/jpeg' }, body: Buffer.from(await r.arrayBuffer()) });
      } catch { /* как nginx: ошибка → заглушка */ }
      return route.fetch({ url: `${SITE}/img/blank.png` }).then(
        (r) => route.fulfill({ response: r }),
        () => route.fulfill({ status: 404, body: '' }),
      );
    }
    if (p.startsWith('/api/') || p.startsWith('/img/')) return route.continue();
    const file = path.join(DIST, decodeURIComponent(p));
    if (p !== '/' && fs.existsSync(file) && fs.statSync(file).isFile()) {
      return route.fulfill({ status: 200, headers: { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' }, body: fs.readFileSync(file) });
    }
    if (p.startsWith('/assets/')) return route.fulfill({ status: 404, body: '' });
    return route.fulfill({ status: 200, headers: { 'content-type': 'text/html' }, body: fs.readFileSync(path.join(DIST, 'index.html')) });
  });
  const page = await context.newPage();
  context.on('request', (r) => {
    let u;
    try { u = new URL(r.url()); } catch { return; }
    if (!u.protocol.startsWith('http')) return;
    reqs.push({ host: u.host, phase, url: r.url() });
  });
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const loc = m.location()?.url || '';
    let host = '';
    try { host = new URL(loc).host; } catch { /* нет адреса */ }
    if (host && host !== HOST) R.ytFrameConsole++; // сообщения изнутри iframe YouTube — не наш код
    else R.consoleErrors.push(`${phase}: ${m.text()}`);
  });
  page.on('pageerror', (e) => R.consoleErrors.push(`${phase}: pageerror: ${e.message}`));

  const settle = async (ms = 900) => {
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(ms);
  };
  const shot = async (name, full = false) => {
    const f = path.join(OUT, `${vpName}-${name}.png`);
    await page.screenshot({ path: f, fullPage: full });
    return path.basename(f);
  };
  // прокрутка — внутри слоя .nr (position: fixed); снимок «всего текста» — растягиваем слой
  const shotLayer = async (name) => {
    await page.evaluate(() => {
      const el = document.querySelector('.nr');
      if (el) { el.dataset.h = el.style.cssText; el.style.position = 'absolute'; el.style.bottom = 'auto'; el.style.overflow = 'visible'; }
      document.body.style.overflow = 'visible';
      // экран под слоем на «длинном» снимке не нужен
      document.querySelectorAll('.app, nav').forEach((n) => { if (!n.closest('.nr')) { n.dataset.d = n.style.display; n.style.display = 'none'; } });
    });
    const f = await shot(name, true);
    await page.evaluate(() => {
      const el = document.querySelector('.nr');
      if (el) el.style.cssText = el.dataset.h || '';
      document.body.style.overflow = 'hidden';
      document.querySelectorAll('.app, nav').forEach((n) => { if (n.dataset.d !== undefined) { n.style.display = n.dataset.d; delete n.dataset.d; } });
    });
    return f;
  };
  const hscroll = () => page.evaluate(() => Math.max(
    document.documentElement.scrollWidth - document.documentElement.clientWidth,
    ...[...document.querySelectorAll('.nr')].map((e) => e.scrollWidth - e.clientWidth),
  ));
  const iframes = () => page.evaluate(() => document.querySelectorAll('iframe').length);
  const ytReqs = (ph) => reqs.filter((r) => r.phase === ph && YT_HOSTS.test(r.host.split(':')[0])).length;
  const readerInfo = () => page.evaluate(() => {
    const body = document.querySelector('.nr-body');
    const p = body?.querySelector('p');
    const cs = p ? getComputedStyle(p) : null;
    const col = document.querySelector('.nr-in')?.getBoundingClientRect();
    return {
      url: location.pathname,
      title: document.querySelector('.nr-title')?.textContent || null,
      meta: document.querySelector('.nr-meta')?.textContent || null,
      paragraphs: body ? body.querySelectorAll('p').length : 0,
      imagesInText: body ? body.querySelectorAll('img').length : 0,
      hero: !!document.querySelector('.nr-hero img'),
      fontSize: cs?.fontSize, lineHeight: cs ? (parseFloat(cs.lineHeight) / parseFloat(cs.fontSize)).toFixed(2) : null,
      column: col ? Math.round(col.width) : null,
      source: document.querySelector('.nr-src')?.textContent?.trim() || null,
      sourceHref: document.querySelector('.nr-src a')?.getAttribute('href') || null,
      share: !!document.querySelector('.nr-share'),
      more: document.querySelectorAll('.nr-more__item').length,
      externalLinksBlank: [...(body?.querySelectorAll('a:not([data-internal])') || [])].every((a) => a.target === '_blank'),
      internalLinks: body ? body.querySelectorAll('a[data-internal]').length : 0,
      full: !!body,
      partialButton: document.querySelector('.nr-full')?.textContent || null,
    };
  });

  // ---------- 1. главная → новость → чтение → «Назад» (кнопка) и браузерная «Назад»
  {
    const S = (R.scenarios.home = {});
    phase = 'home';
    await page.goto(SITE + '/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('a.mx-link[href^="/news/"]', { timeout: 20000 });
    await settle();
    S.homeShot = await shot('1-home');
    const link = page.locator('a.mx-link[href^="/news/"]').first();
    S.href = await link.getAttribute('href');
    await link.click();
    await page.waitForSelector('.nr-body', { timeout: 15000 });
    await settle(1200);
    S.reader = await readerInfo();
    S.hscroll = await hscroll();
    S.readerShot = await shot('1-home-news');
    S.readerFull = await shotLayer('1-home-news-full');
    await page.click('.nr-top__back');
    await page.waitForSelector('.nr', { state: 'detached', timeout: 5000 }).catch(() => {});
    S.afterBackUrl = new URL(page.url()).pathname;
    S.homeStillThere = await page.locator('.brandbar').count();
    // браузерная «Назад»
    await page.locator('a.mx-link[href^="/news/"]').first().click();
    await page.waitForSelector('.nr-body', { timeout: 15000 });
    await page.goBack();
    await page.waitForSelector('.nr', { state: 'detached', timeout: 5000 }).catch(() => {});
    S.afterBrowserBackUrl = new URL(page.url()).pathname;
    if (S.afterBackUrl !== '/' || S.afterBrowserBackUrl !== '/') fail(vpName, 'главная: «Назад» не вернул на главную');
    if (S.hscroll > 0) fail(vpName, `главная→новость: горизонтальная прокрутка ${S.hscroll}`);
  }

  // ---------- 2. «Медиа» → новость каждого источника
  {
    const S = (R.scenarios.sources = {});
    phase = 'media-news';
    await page.goto(SITE + '/media?tab=news', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('a.mx-link[href^="/news/"]', { timeout: 20000 });
    await settle();
    S.listShot = await shot('2-media-news');
    for (const src of ['Чемпионат', 'Спорт-Экспресс', 'Sports.ru']) {
      const link = page.locator('a.mx-link[href^="/news/"]', { has: page.locator('.ui-news__src', { hasText: src }) }).first();
      await link.scrollIntoViewIfNeeded();
      await link.click();
      await page.waitForSelector('.nr-body, .nr-full', { timeout: 15000 });
      await settle(1500);
      const info = await readerInfo();
      info.hscroll = await hscroll();
      const key = src.replace(/[^A-Za-z0-9]+/g, '') || (src === 'Чемпионат' ? 'championat' : 'sportexpress');
      info.shot = await shot(`2-${key}`);
      info.fullShot = await shotLayer(`2-${key}-full`);
      S[src] = info;
      if (!info.full) fail(vpName, `${src}: нет текста`);
      if (info.hscroll > 0) fail(vpName, `${src}: горизонтальная прокрутка ${info.hscroll}`);
      if (!info.sourceHref || !info.source?.startsWith('Источник:')) fail(vpName, `${src}: нет подписи источника`);
      await page.click('.nr-top__back');
      await page.waitForSelector('.nr', { state: 'detached', timeout: 5000 }).catch(() => {});
    }
    S.backUrl = new URL(page.url()).pathname + new URL(page.url()).search;
    // внутренняя ссылка из текста статьи (если есть) — открывается внутри
    const withInternal = await page.evaluate(async (skip) => {
      const r = await fetch('/api/news?limit=100').then((x) => x.json());
      for (const it of r.items) {
        if (it.aid === skip) continue; // не трогаем статью для сценария pending
        const a = await fetch('/api/news/' + it.aid).then((x) => x.json());
        if (a.html && a.html.includes('data-internal')) return it.aid;
      }
      return null;
    }, process.env.PENDING_AID || null);
    S.internalLinkArticle = withInternal;
    // статья с фото в тексте (блог Sports.ru): картинки только через наш /img/news/...
    const withImages = await page.evaluate(async (skip) => {
      const r = await fetch('/api/news?limit=100').then((x) => x.json());
      for (const it of r.items) {
        if (it.aid === skip) continue; // не трогаем статью для сценария pending
        const a = await fetch('/api/news/' + it.aid).then((x) => x.json());
        if (a.html && (a.html.match(/<img/g) || []).length >= 2) return it.aid;
      }
      return null;
    }, process.env.PENDING_AID || null);
    S.imagesArticle = withImages;
    if (withImages) {
      const l = page.locator(`a.mx-link[href="/news/${withImages}"]`).first();
      if (await l.count()) {
        await l.scrollIntoViewIfNeeded();
        await l.click();
      } else {
        S.imagesDirect = true; // за кнопкой «Показать ещё» — открываем по адресу
        await page.goto(`${SITE}/news/${withImages}`, { waitUntil: 'domcontentloaded' });
      }
      await page.waitForSelector('.nr-body img', { timeout: 15000 });
      await page.evaluate(() => Promise.all([...document.querySelectorAll('.nr-body img')].map((i) => { i.loading = 'eager'; return i.complete ? 0 : new Promise((r) => { i.onload = r; i.onerror = r; setTimeout(r, 8000); }); })));
      await page.waitForTimeout(800);
      S.images = await page.evaluate(() => [...document.querySelectorAll('.nr-body img')].map((i) => ({ src: i.getAttribute('src'), w: i.naturalWidth, shown: i.closest('figure')?.style.display !== 'none' })));
      S.imagesInfo = await readerInfo();
      S.imagesHscroll = await hscroll();
      S.imagesShot = await shotLayer('2-images-full');
      if (S.images.some((i) => !i.src.startsWith('/img/news/'))) fail(vpName, 'картинка в тексте не через /img/news');
      if (S.images.some((i) => i.w <= 1)) fail(vpName, 'картинка в тексте не загрузилась');
      if (S.imagesHscroll > 0) fail(vpName, `статья с фото: горизонтальная прокрутка ${S.imagesHscroll}`);
      await page.click('.nr-top__back');
      await page.waitForSelector('.nr', { state: 'detached', timeout: 5000 }).catch(() => {});
    }
    if (withInternal) {
      await page.locator(`a.mx-link[href="/news/${withInternal}"]`).first().scrollIntoViewIfNeeded();
      await page.locator(`a.mx-link[href="/news/${withInternal}"]`).first().click();
      await page.waitForSelector('.nr-body a[data-internal]', { timeout: 15000 });
      const target = await page.locator('.nr-body a[data-internal]').first().getAttribute('href');
      await page.locator('.nr-body a[data-internal]').first().click();
      await page.waitForURL((u) => u.pathname === target, { timeout: 5000 }).catch(() => {});
      await page.waitForSelector('.nr-body, .nr-full', { timeout: 15000 }).catch(() => {});
      S.internalLinkOpened = new URL(page.url()).pathname === target;
      await page.goBack();
      await page.waitForTimeout(500);
      S.internalBackTo = new URL(page.url()).pathname;
      await page.goBack();
      await page.waitForTimeout(500);
    }
  }

  // ---------- 3. «Медиа» → видео: на списке запросов к YouTube нет, iframe — только после открытия
  {
    const S = (R.scenarios.video = {});
    phase = 'video-list';
    await page.goto(SITE + '/media?tab=video', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('a.mx-tile[href^="/video/"]', { timeout: 20000 });
    await settle(1500);
    S.listShot = await shot('3-media-video');
    S.listIframes = await iframes();
    S.listYoutubeRequests = ytReqs('video-list') + ytReqs('media-news') + ytReqs('home');
    if (S.listIframes || S.listYoutubeRequests) fail(vpName, `списки: iframe ${S.listIframes}, запросов к YouTube ${S.listYoutubeRequests}`);
    phase = 'video-open';
    const tile = page.locator('a.mx-tile:not(.mx-tile--short)[href^="/video/"]').first();
    S.href = await tile.getAttribute('href');
    await tile.click();
    await page.waitForSelector('iframe.vp-frame', { timeout: 10000 });
    S.iframe = await page.evaluate(() => {
      const f = document.querySelector('iframe.vp-frame');
      return { src: f.src, allow: f.getAttribute('allow'), allowfullscreen: f.hasAttribute('allowfullscreen'), w: Math.round(f.getBoundingClientRect().width), h: Math.round(f.getBoundingClientRect().height) };
    });
    if (!S.iframe.src.startsWith('https://www.youtube-nocookie.com/embed/') || !S.iframe.src.includes('playsinline=1&rel=0&modestbranding=1')) fail(vpName, 'iframe: не тот адрес');
    if (S.iframe.allow !== 'autoplay; encrypted-media; picture-in-picture; fullscreen' || !S.iframe.allowfullscreen) fail(vpName, 'iframe: нет allow/allowfullscreen');
    S.ytLink = await page.locator('.vp-hint a').getAttribute('href');
    S.hint = await page.locator('.vp-hint').textContent();
    await page.waitForTimeout(2500);
    S.shot = await shot('3-video');
    // ждём 10 с: загрузился — подсказка обычная, нет — заметная
    await page.waitForTimeout(9000);
    S.loadedAfter11s = await page.evaluate(() => !document.querySelector('.vp-poster'));
    S.slowHint = await page.locator('.vp-hint--slow').count();
    S.shotAfter11s = await shot('3-video-11s');
    S.fullShot = await shotLayer('3-video-full');
    S.hscroll = await hscroll();
    S.youtubeRequestsOnVideo = ytReqs('video-open');
    await page.click('.nr-top__back');
    await page.waitForSelector('.nr', { state: 'detached', timeout: 5000 }).catch(() => {});
    S.iframesAfterBack = await iframes();
    S.backUrl = new URL(page.url()).pathname + new URL(page.url()).search;
  }

  // ---------- 4. Shorts — вертикальный плеер 9:16
  {
    const S = (R.scenarios.shorts = {});
    phase = 'shorts';
    const tile = page.locator('a.mx-tile--short[href^="/video/"]').first();
    await tile.scrollIntoViewIfNeeded();
    S.href = await tile.getAttribute('href');
    await tile.click();
    await page.waitForSelector('.vp--short iframe.vp-frame', { timeout: 10000 });
    await page.waitForTimeout(3000);
    S.box = await page.evaluate(() => {
      const b = document.querySelector('.vp--short').getBoundingClientRect();
      return { w: Math.round(b.width), h: Math.round(b.height), ratio: (b.width / b.height).toFixed(3) };
    });
    S.ytLink = await page.locator('.vp-hint a').getAttribute('href');
    S.hscroll = await hscroll();
    S.shot = await shot('4-shorts');
    if (Math.abs(S.box.w / S.box.h - 9 / 16) > 0.02) fail(vpName, `Shorts: не 9:16 (${S.box.ratio})`);
    await page.goBack();
    await page.waitForSelector('.nr', { state: 'detached', timeout: 5000 }).catch(() => {});
  }

  // ---------- 5. видеообзор с экрана матча
  {
    const S = (R.scenarios.matchHighlight = {});
    phase = 'match';
    await page.goto(`${SITE}/match/${MATCH_ID}`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.mt-video a', { timeout: 20000 });
    await settle(1200);
    S.iframesOnMatch = await iframes();
    S.youtubeRequestsOnMatch = ytReqs('match');
    S.cardHref = await page.locator('.mt-video a').getAttribute('href');
    await page.locator('.mt-video a').scrollIntoViewIfNeeded();
    S.matchShot = await shot('5-match-highlight-card');
    phase = 'match-video';
    await page.locator('.mt-video a').click();
    await page.waitForSelector('iframe.vp-frame', { timeout: 10000 });
    await page.waitForTimeout(3000);
    S.url = new URL(page.url()).pathname;
    S.title = await page.locator('.nr-title').textContent().catch(() => null);
    S.shot = await shot('5-match-highlight-video');
    await page.click('.nr-top__back');
    await page.waitForSelector('.nr', { state: 'detached', timeout: 5000 }).catch(() => {});
    S.backUrl = new URL(page.url()).pathname;
    if (!S.url.startsWith('/video/') || !S.backUrl.startsWith(`/match/${MATCH_ID}`)) fail(vpName, 'обзор матча: не открылся внутри или «Назад» не на матч');
    if (S.iframesOnMatch || S.youtubeRequestsOnMatch) fail(vpName, 'экран матча: запросы к YouTube до открытия');
  }

  // ---------- 6. статья в состоянии pending (только на 390 — сборщик качает её один раз)
  if (process.env.PENDING_AID && vpName === 'm390') {
    const S = (R.scenarios.pending = {});
    phase = 'pending';
    await page.goto(SITE + '/media?tab=news', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('a.mx-link[href^="/news/"]', { timeout: 20000 });
    const link = page.locator(`a.mx-link[href="/news/${process.env.PENDING_AID}"]`).first();
    await link.scrollIntoViewIfNeeded();
    await link.click();
    await page.waitForSelector('.nr-wait', { timeout: 5000 });
    await page.waitForTimeout(700);
    S.pendingText = await page.locator('.nr-wait').textContent();
    S.pendingShot = await shot('6-pending');
    const t0 = Date.now();
    await page.waitForSelector('.nr-body', { timeout: 40000 });
    S.becameFullAfterMs = Date.now() - t0;
    await page.waitForTimeout(800);
    S.reader = await readerInfo();
    S.fullShot = await shot('6-pending-done');
  }

  // ---------- 7. источник не отдал текст: лид и «Читать полностью на …»
  if (process.env.PARTIAL_AID) {
    const S = (R.scenarios.partial = {});
    phase = 'partial';
    await page.goto(`${SITE}/news/${process.env.PARTIAL_AID}`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.nr-full', { timeout: 15000 });
    await settle(800);
    S.reader = await readerInfo();
    S.shot = await shot('7-partial');
    await page.click('.nr-top__back');
    await page.waitForTimeout(800);
    S.directBackUrl = new URL(page.url()).pathname + new URL(page.url()).search; // прямой заход → «Медиа»
  }

  R.external = {};
  for (const r of reqs) {
    if (r.host === HOST) continue;
    const k = `${r.phase} ${r.host}`;
    R.external[k] = (R.external[k] || 0) + 1;
  }
  const bad = Object.keys(R.external).filter((k) => {
    const [ph, host] = k.split(' ');
    return !(['video-open', 'shorts', 'match-video'].includes(ph) && YT_HOSTS.test(host.split(':')[0]));
  });
  R.externalNotAllowed = bad;
  if (bad.length) fail(vpName, `внешние запросы вне экрана видео: ${bad.join(', ')}`);
  if (R.consoleErrors.length) fail(vpName, `ошибки консоли: ${R.consoleErrors.length}`);
  await browser.close();
}

(async () => {
  await run('m390', { width: 390, height: 844 }, 2);
  await run('d1366', { width: 1366, height: 768 }, 1);
  report.finished = new Date().toISOString();
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1));
  console.log(JSON.stringify({ failures: report.failures }, null, 1));
})().catch((e) => {
  console.error(e);
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify({ ...report, crash: String(e.stack || e) }, null, 1));
  process.exit(1);
});
