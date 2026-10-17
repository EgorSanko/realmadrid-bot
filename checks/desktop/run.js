// Проверка десктопной версии сайта и неизменности мини-аппа (Playwright) против https://realmadridfan.ru.
//
//   NODE_PATH=C:/Users/egor3/node_modules node checks/desktop/run.js <distDir> <baseDistDir> <outDir> [only]
//
// Страницы, /assets/* и статичные файлы (og.png, favicon, manifest, robots, sitemap) — из локальной сборки
// distDir; /api/* и /img/* — с сервера. baseDistDir — сборка до изменений (для сравнения мини-аппа).
// Вход: /api/auth/* подменён (аноним; в одном сценарии — тестовый пользователь), чтобы не трогать сервер.
// only — через запятую: desk,widths,mobile,tma,static,user (по умолчанию всё).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const [, , DIST, BASE, OUT, ONLY] = process.argv;
const SITE = 'https://realmadridfan.ru';
const HOST = 'realmadridfan.ru';
const only = new Set((ONLY || 'desk,widths,mobile,tma,static,user').split(','));
const MIME = {
  '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.woff2': 'font/woff2', '.woff': 'font/woff',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.json': 'application/json', '.ico': 'image/x-icon',
  '.webmanifest': 'application/manifest+json', '.txt': 'text/plain', '.xml': 'application/xml',
};
fs.mkdirSync(OUT, { recursive: true });

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
function tmaHash() {
  const user = { id: 4242, first_name: 'Алексей', last_name: 'Морозов', username: 'madridista_alex', language_code: 'ru' };
  const data = new URLSearchParams({ auth_date: String(Math.floor(Date.now() / 1000)), query_id: 'AAHtestQuery', user: JSON.stringify(user), hash: 'x'.repeat(64), signature: 'c3R1Yg' }).toString();
  const theme = { bg_color: '#06070b', secondary_bg_color: '#0b0d14', text_color: '#eef0f5', hint_color: '#8a90a1', link_color: '#d4af37', button_color: '#d4af37', button_text_color: '#1a1408', header_bg_color: '#06070b' };
  return '#' + new URLSearchParams({ tgWebAppData: data, tgWebAppVersion: '8.0', tgWebAppPlatform: 'ios', tgWebAppThemeParams: JSON.stringify(theme) }).toString();
}

const TEST_USER = { id: 4242, name: 'Алексей Морозов', first_name: 'Алексей', last_name: 'Морозов', username: 'madridista_alex', avatar: null };

async function open(browser, { viewport, mobile = false, tma = false, dist = DIST, user = false, fixedTime = null, noSplash = true }) {
  const context = await browser.newContext({
    viewport, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile, locale: 'ru-RU', timezoneId: 'Europe/Moscow',
  });
  const log = { external: {}, errors: [], failed: [], fromDist: [] };
  if (tma) await context.addInitScript(TMA_MOCK);
  if (noSplash) await context.addInitScript(() => { try { sessionStorage.setItem('rmSplash', '1'); } catch (e) { /* */ } });
  if (fixedTime) await context.clock.setFixedTime(fixedTime);
  await context.route('**/*', async (route) => {
    const u = new URL(route.request().url());
    if (u.host !== HOST) {
      // плеер YouTube на странице /video — встроенный iframe (так было и до этой задачи); считаем отдельно
      const key = /(^|\.)youtube(-nocookie)?\.com$/.test(u.host) && route.request().resourceType() === 'document' ? 'iframe:' + u.host : u.host;
      log.external[key] = (log.external[key] || 0) + 1;
      return route.abort('blockedbyclient');
    }
    const p = u.pathname;
    if (p.startsWith('/api/auth/')) {
      const body = JSON.stringify(user ? { user: TEST_USER, is_admin: false, token: 'local-test' } : { user: null, is_admin: false });
      return route.fulfill({ status: 200, headers: { 'content-type': 'application/json' }, body });
    }
    if (p.startsWith('/api/') || p.startsWith('/img/')) return route.continue();
    const file = path.join(dist, decodeURIComponent(p));
    if (p !== '/' && fs.existsSync(file) && fs.statSync(file).isFile()) {
      log.fromDist.push(p);
      return route.fulfill({ status: 200, headers: { 'content-type': MIME[path.extname(file)] || 'application/octet-stream', 'x-from-dist': '1' }, body: fs.readFileSync(file) });
    }
    if (p.startsWith('/assets/') || /\.[a-z0-9]{2,12}$/i.test(p)) return route.fulfill({ status: 404, body: '' });
    return route.fulfill({ status: 200, headers: { 'content-type': 'text/html', 'x-from-dist': '1' }, body: fs.readFileSync(path.join(dist, 'index.html')) });
  });
  const page = await context.newPage();
  page.on('console', (m) => { if (m.type() === 'error') log.errors.push(m.text()); });
  page.on('pageerror', (e) => log.errors.push('pageerror: ' + e.message));
  page.on('requestfailed', (r) => {
    const f = (r.failure() || {}).errorText || '';
    // ERR_BLOCKED_BY_CLIENT — это наш перехват чужих хостов (их считаем отдельно, в external)
    if (!/ERR_ABORTED|BLOCKED_BY_CLIENT/i.test(f)) log.failed.push(r.url() + ' ' + f);
  });
  return { context, page, log };
}

async function settle(page, ms = 900) {
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForSelector('#splash', { state: 'detached', timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(ms);
}

/** Прокрутка до конца и обратно — чтобы подгрузились картинки loading=lazy. */
async function scrollThrough(page) {
  await page.evaluate(async () => {
    const step = Math.max(300, innerHeight - 100);
    for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 120));
    }
    window.scrollTo(0, 0);
  });
  await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(400);
}

const layout = (page) => page.evaluate(() => {
  const de = document.documentElement;
  const app = document.querySelector('.app');
  const r = app ? app.getBoundingClientRect() : null;
  const meta = (sel) => document.querySelector(sel)?.getAttribute('content') ?? null;
  // карточки шире контейнера или пустые растянутые (высокие без содержимого) — подозрительно
  const wide = [...document.querySelectorAll('.ui-card, .ui-mc, .home-tile')].filter((el) => el.getBoundingClientRect().right > de.clientWidth + 1).length;
  return {
    hscroll: de.scrollWidth - de.clientWidth,
    classes: de.className,
    header: !!document.querySelector('header.sh'),
    footer: !!document.querySelector('footer.sf'),
    bottomNav: !!document.querySelector('.bottom-nav'),
    appWidth: r ? Math.round(r.width) : null,
    centered: r ? Math.abs(r.left - (de.clientWidth - r.right)) <= 2 : null,
    overflowCards: wide,
    title: document.title,
    description: meta('meta[name="description"]'),
    ogTitle: meta('meta[property="og:title"]'),
    ogImage: meta('meta[property="og:image"]'),
    twitter: meta('meta[name="twitter:card"]'),
    canonical: document.querySelector('link[rel="canonical"]')?.getAttribute('href') ?? null,
    activeNav: document.querySelector('.sh__link.on')?.textContent ?? null,
  };
});

/** Структура DOM #root (теги и классы), без текста — для сравнения мини-аппа «до/после». */
const structure = (page) => page.evaluate(() => {
  const walk = (el, d) => {
    if (d > 7) return '';
    const kids = [...el.children].map((c) => walk(c, d + 1)).join('');
    return `<${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).sort().join('.') : ''}>${kids}`;
  };
  return walk(document.getElementById('root'), 0);
});

async function pixelDiff(browser, a, b) {
  const ctx = await browser.newContext();
  const pg = await ctx.newPage();
  const res = await pg.evaluate(async ([a64, b64]) => {
    const load = (s) => new Promise((ok) => { const i = new Image(); i.onload = () => ok(i); i.src = 'data:image/png;base64,' + s; });
    const [ia, ib] = await Promise.all([load(a64), load(b64)]);
    if (ia.width !== ib.width || ia.height !== ib.height) return { sameSize: false, a: [ia.width, ia.height], b: [ib.width, ib.height] };
    const c = document.createElement('canvas'); c.width = ia.width; c.height = ia.height;
    const x = c.getContext('2d');
    x.drawImage(ia, 0, 0); const da = x.getImageData(0, 0, c.width, c.height).data;
    x.clearRect(0, 0, c.width, c.height); x.drawImage(ib, 0, 0); const db = x.getImageData(0, 0, c.width, c.height).data;
    let diff = 0;
    for (let i = 0; i < da.length; i += 4) if (Math.abs(da[i] - db[i]) + Math.abs(da[i + 1] - db[i + 1]) + Math.abs(da[i + 2] - db[i + 2]) > 24) diff++;
    return { sameSize: true, size: [c.width, c.height], diffPixels: diff, diffShare: +(diff / (c.width * c.height)).toFixed(5) };
  }, [a.toString('base64'), b.toString('base64')]);
  await ctx.close();
  return res;
}

async function ids(browser) {
  const ctx = await browser.newContext();
  const get = async (p) => (await ctx.request.get(SITE + p)).json();
  const [fx, team, news, videos] = await Promise.all([get('/api/fixtures'), get('/api/team'), get('/api/news?limit=10'), get('/api/videos?limit=10')]);
  await ctx.close();
  const done = fx.matches.filter((m) => m.status && m.status.finished).sort((a, b) => Date.parse(b.kickoff) - Date.parse(a.kickoff));
  const player = (team.squad && (team.squad.attackers || team.squad.midfielders || [])[0]) || null;
  const art = news.items.find((n) => n.image) || news.items[0];
  const vid = (videos.items.find((v) => !v.short) || videos.items[0] || {}).id;
  return { match: done[0] && done[0].id, player: player && player.id, news: art && art.aid, video: vid };
}

(async () => {
  const browser = await chromium.launch();
  const report = { when: new Date().toISOString(), ids: null, desk: {}, widths: {}, mobile: {}, tma: {}, static: {}, user: null, totals: {} };
  const I = await ids(browser);
  report.ids = I;
  const PAGES = [
    ['home', '/'], ['matches', '/matches'], ['match', `/match/${I.match}`], ['team', '/team'], ['media', '/media'],
    ['media-news', '/media?tab=news'], ['media-video', '/media?tab=video'], ['news', `/news/${I.news}`], ['video', `/video/${I.video}`],
    ['player', `/player/${I.player}`], ['predict', '/predict'], ['profile', '/profile'],
  ];
  const allErrors = [];
  const allExternal = {};
  const allIframes = {};
  const merge = (log, where) => {
    for (const e of log.errors) allErrors.push(`${where}: ${e}`);
    for (const f of log.failed) allErrors.push(`${where}: requestfailed ${f}`);
    for (const [h, n] of Object.entries(log.external)) {
      const bucket = h.startsWith('iframe:') ? allIframes : allExternal;
      bucket[h] = (bucket[h] || 0) + n;
    }
  };

  // ---------- 1. десктоп: скриншоты 1440×900 и 1280×800 ----------
  if (only.has('desk')) {
    for (const [w, h] of [[1440, 900], [1280, 800]]) {
      const { context, page, log } = await open(browser, { viewport: { width: w, height: h } });
      for (const [name, url] of PAGES) {
        await page.goto(SITE + url);
        await settle(page);
        await scrollThrough(page);
        await page.screenshot({ path: path.join(OUT, `desk-${w}-${name}.png`), fullPage: true });
        report.desk[`${w}/${name}`] = await layout(page);
      }
      // ховер по карточке матча и фокус с клавиатуры — на главной
      await page.goto(SITE + '/');
      await settle(page);
      const card = page.locator('a.hero-mc, a.ui-mc-past').first();
      if (await card.count()) {
        await card.hover();
        await page.waitForTimeout(250);
        await page.screenshot({ path: path.join(OUT, `desk-${w}-home-hover.png`) });
        report.desk[`${w}/hover`] = await card.evaluate((el) => ({ cursor: getComputedStyle(el).cursor, border: getComputedStyle(el).borderColor }));
      }
      await page.mouse.move(1, 1);
      await page.keyboard.press('Tab');
      await page.keyboard.press('Tab');
      await page.waitForTimeout(150);
      report.desk[`${w}/focus`] = await page.evaluate(() => {
        const a = document.activeElement;
        const cs = a ? getComputedStyle(a) : null;
        return a ? { tag: a.tagName, cls: a.className, text: (a.textContent || '').trim().slice(0, 30), outline: cs.outlineStyle + ' ' + cs.outlineWidth + ' ' + cs.outlineColor } : null;
      });
      await page.screenshot({ path: path.join(OUT, `desk-${w}-focus.png`), clip: { x: 0, y: 0, width: w, height: 90 } });
      // вход в шапке: панель открывается (виджет telegram.org в проверке заблокирован — должна быть ошибка-запасной путь)
      if (w === 1440) {
        const btn = page.locator('.sh-login__btn');
        if (await btn.count()) {
          await btn.click();
          await page.waitForTimeout(700);
          await page.screenshot({ path: path.join(OUT, 'desk-1440-login-panel.png'), clip: { x: 0, y: 0, width: w, height: 420 } });
          report.desk['1440/loginPanel'] = await page.evaluate(() => ({ open: !!document.querySelector('.sh-login__panel'), text: document.querySelector('.sh-login__panel')?.innerText.slice(0, 200) }));
          await page.keyboard.press('Escape');
        }
      }
      // telegram.org блокируется только по нажатию «Войти» — ожидаемо; в счёт внешних хостов при обычном просмотре не идёт
      const ext = { ...log.external };
      delete ext['telegram.org'];
      merge({ ...log, external: ext }, `desk${w}`);
      report.desk[`${w}/telegramOrgOnLoginClick`] = log.external['telegram.org'] || 0;
      await context.close();
    }
  }

  // ---------- 2. ширины 1024 / 1280 / 1440 / 1920: горизонтальная прокрутка, центрирование ----------
  if (only.has('widths')) {
    for (const w of [1024, 1280, 1440, 1920]) {
      const { context, page, log } = await open(browser, { viewport: { width: w, height: 900 } });
      for (const [name, url] of PAGES) {
        await page.goto(SITE + url);
        await settle(page, 600);
        await scrollThrough(page);
        const l = await layout(page);
        report.widths[`${w}/${name}`] = { hscroll: l.hscroll, centered: l.centered, appWidth: l.appWidth, overflowCards: l.overflowCards, desk: /\bdesk\b/.test(l.classes) };
        if (w === 1024 || w === 1920) await page.screenshot({ path: path.join(OUT, `w${w}-${name}.png`), fullPage: false });
      }
      merge(log, `w${w}`);
      await context.close();
    }
  }

  // ---------- 3. телефон в браузере 390×844 ----------
  if (only.has('mobile')) {
    const { context, page, log } = await open(browser, { viewport: { width: 390, height: 844 }, mobile: true });
    for (const [name, url] of PAGES) {
      await page.goto(SITE + url);
      await settle(page);
      await scrollThrough(page);
      await page.screenshot({ path: path.join(OUT, `m390-${name}.png`), fullPage: true });
      const l = await layout(page);
      report.mobile[name] = { hscroll: l.hscroll, header: l.header, footer: l.footer, bottomNav: l.bottomNav, classes: l.classes, title: l.title };
    }
    merge(log, 'm390');
    await context.close();
  }

  // ---------- 4. мини-апп 390×844 (и широкое окно Telegram Desktop 1440): до/после ----------
  if (only.has('tma')) {
    const fixed = new Date();
    const tmaPages = PAGES.filter(([n]) => !['media-news', 'media-video'].includes(n));
    for (const vp of [{ width: 390, height: 844, mobile: true, tag: '390' }, { width: 1440, height: 900, mobile: false, tag: '1440' }]) {
      const runs = {};
      for (const [label, dist] of [['new', DIST], ['base', BASE]]) {
        const { context, page, log } = await open(browser, { viewport: { width: vp.width, height: vp.height }, mobile: vp.mobile, tma: true, dist, fixedTime: fixed });
        runs[label] = {};
        for (const [name, url] of (vp.tag === '390' ? tmaPages : tmaPages.slice(0, 5))) {
          await page.goto(SITE + url + tmaHash());
          await settle(page, 1200);
          await scrollThrough(page);
          const shot = await page.screenshot({ fullPage: true });
          if (label === 'new') fs.writeFileSync(path.join(OUT, `tma${vp.tag}-${name}.png`), shot);
          else fs.writeFileSync(path.join(OUT, `tma${vp.tag}-${name}-before.png`), shot);
          runs[label][name] = { shot, struct: await structure(page), l: await layout(page) };
        }
        if (label === 'new') merge(log, `tma${vp.tag}`);
        await context.close();
      }
      for (const name of Object.keys(runs.new)) {
        const a = runs.new[name];
        const b = runs.base[name];
        report.tma[`${vp.tag}/${name}`] = {
          header: a.l.header, footer: a.l.footer, bottomNav: a.l.bottomNav, classes: a.l.classes, hscroll: a.l.hscroll,
          sameStructure: a.struct === b.struct,
          pixels: await pixelDiff(browser, a.shot, b.shot),
        };
        if (a.struct !== b.struct) {
          fs.writeFileSync(path.join(OUT, `tma${vp.tag}-${name}-struct-new.txt`), a.struct);
          fs.writeFileSync(path.join(OUT, `tma${vp.tag}-${name}-struct-base.txt`), b.struct);
        }
      }
    }
    // заставка в мини-аппе: первый заход, sessionStorage пуст — #splash есть и держится
    const { context, page } = await open(browser, { viewport: { width: 390, height: 844 }, mobile: true, tma: true, noSplash: false });
    await page.goto(SITE + '/' + tmaHash());
    await page.waitForTimeout(800);
    report.tma.splashShownAt800ms = await page.evaluate(() => !!document.getElementById('splash'));
    await page.screenshot({ path: path.join(OUT, 'tma390-splash.png') });
    await context.close();
    // и на компьютере (сайт) заставки нет
    const s2 = await open(browser, { viewport: { width: 1440, height: 900 }, noSplash: false });
    await s2.page.goto(SITE + '/');
    await s2.page.waitForTimeout(300);
    report.desk.splashOnDesktopAt300ms = await s2.page.evaluate(() => !!document.getElementById('splash'));
    await s2.context.close();
  }

  // ---------- 5. статичные файлы: отдаются 200 из dist ----------
  if (only.has('static')) {
    const { context, page } = await open(browser, { viewport: { width: 1280, height: 800 } });
    await page.goto(SITE + '/');
    await settle(page, 300);
    for (const p of ['/og.png', '/favicon.ico', '/favicon.svg', '/favicon-32.png', '/apple-touch-icon.png', '/icon-192.png', '/icon-512.png', '/manifest.webmanifest', '/robots.txt', '/sitemap.xml']) {
      const r = await page.evaluate(async (u) => {
        try {
          const res = await fetch(u, { cache: 'no-store' });
          const b = await res.arrayBuffer();
          return { status: res.status, type: res.headers.get('content-type'), fromDist: res.headers.get('x-from-dist') === '1', bytes: b.byteLength };
        } catch (e) {
          return { error: String(e) };
        }
      }, p);
      report.static[p] = r;
    }
    // fetch('/favicon.ico') Chromium под перехватом Playwright обрывает (особый запрос значка);
    // тот же файл с query — обычный запрос, перехват отдаёт его из dist
    report.static['/favicon.ico?check=1'] = await page.evaluate(async () => {
      try {
        const res = await fetch('/favicon.ico?check=1', { cache: 'no-store' });
        const b = new Uint8Array(await res.arrayBuffer());
        return { status: res.status, type: res.headers.get('content-type'), fromDist: res.headers.get('x-from-dist') === '1', bytes: b.length, icoMagic: [...b.slice(0, 4)].map((x) => x.toString(16).padStart(2, '0')).join('') };
      } catch (e) {
        return { error: String(e) };
      }
    });
    report.static.head = await page.evaluate(() => [...document.head.querySelectorAll('link[rel*="icon"], link[rel="manifest"], link[rel="canonical"], meta[property^="og:"], meta[name^="twitter:"], meta[name="description"], meta[name="robots"]')].map((e) => e.outerHTML));
    report.static.ogImageSize = await page.evaluate(() => new Promise((ok) => { const i = new Image(); i.onload = () => ok([i.naturalWidth, i.naturalHeight]); i.onerror = () => ok(null); i.src = '/og.png'; }));
    report.static.manifest = await page.evaluate(async () => (await fetch('/manifest.webmanifest')).json());
    await context.close();
  }

  // ---------- 6. вошедший пользователь: аватар в шапке ----------
  if (only.has('user')) {
    const { context, page, log } = await open(browser, { viewport: { width: 1440, height: 900 }, user: true });
    await page.goto(SITE + '/team'); // без прогнозов: тестовая сессия на сервере недействительна
    await settle(page);
    await page.screenshot({ path: path.join(OUT, 'desk-1440-header-user.png'), clip: { x: 0, y: 0, width: 1440, height: 90 } });
    report.user = await page.evaluate(() => ({ user: document.querySelector('.sh__user')?.getAttribute('aria-label'), href: document.querySelector('.sh__user')?.getAttribute('href'), login: !!document.querySelector('.sh-login__btn') }));
    merge(log, 'user');
    await context.close();
  }

  report.totals = { consoleErrors: allErrors.length, errors: allErrors.slice(0, 40), externalHosts: allExternal, youtubeIframeOnVideoPage: allIframes };
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report.totals, null, 2));
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
