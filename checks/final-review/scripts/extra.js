// Состояния, CSP в деле, производительность, клавиатура и контраст.
//
//   NODE_PATH=C:/Users/egor3/node_modules node extra.js <out-subdir> [nginxBase] [--only=a,b]
//
// Без nginxBase — живой сайт; с ним — страницы и заголовки от локального nginx (scripts/nginx-local.mjs),
// /api/* и /img/* — с боевого сервера. Блоки: states, csp, frame, perf, keys, contrast.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const [, , SUB = 'after', NGX_ARG, ...flags] = process.argv;
const NGX = NGX_ARG && /^https?:/.test(NGX_ARG) ? NGX_ARG.replace(/\/$/, '') : null;
const ONLY = (flags.find((f) => f.startsWith('--only=')) || '').slice(7).split(',').filter(Boolean);
const SITE = 'https://realmadridfan.ru';
const OUT = path.resolve(__dirname, '..', SUB);
fs.mkdirSync(OUT, { recursive: true });
const M390 = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: 'ru-RU', timezoneId: 'Europe/Moscow' };
const D1440 = { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, locale: 'ru-RU', timezoneId: 'Europe/Moscow' };
const report = {};
const shot = (page, name, full = false) => page.screenshot({ path: path.join(OUT, `x-${name}.png`), fullPage: full });

async function ctx(browser, opts, { telegram = 'block', api = null } = {}) {
  const context = await browser.newContext(opts);
  await context.addInitScript(() => {
    window.__csp = [];
    document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
    // отключить заставку: проверяем экраны, не её
    try { sessionStorage.setItem('rmSplash', '1'); } catch {}
  });
  if (telegram === 'block') await context.route('https://telegram.org/**', (r) => r.abort('blockedbyclient'));
  await context.route(`${SITE}/**`, async (route) => {
    const req = route.request();
    const u = new URL(req.url());
    const isApi = u.pathname.startsWith('/api/') || u.pathname.startsWith('/img/');
    if (isApi && api) {
      const handled = await api(route, u);
      if (handled !== false) return;
    }
    if (NGX && !isApi) {
      const resp = await route.fetch({ url: NGX + u.pathname + u.search, maxRedirects: 0, headers: { ...req.headers(), host: new URL(NGX).host } });
      return route.fulfill({ response: resp });
    }
    return route.continue();
  });
  return context;
}
const settle = async (page, ms = 600) => {
  await page.waitForFunction(() => !document.querySelector('#splash'), null, { timeout: 12000 }).catch(() => {});
  await page.waitForFunction(() => !document.querySelector('[aria-busy="true"], .ui-skel'), null, { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(ms);
};

// ---------- состояния: загрузка, ошибка 503 → «Повторить», устаревшие данные ----------
async function states(browser) {
  const r = (report.states = {});
  const screens = [['home', '/', '/api/home'], ['matches', '/matches', '/api/fixtures'], ['team', '/team', '/api/team'], ['media', '/media', '/api/news'], ['player', '/player/170323', '/api/player/'], ['match', '/match/6106274', '/api/match/']];
  for (const [name, url, apiPrefix] of screens) {
    let mode = 'slow';
    const context = await ctx(browser, M390, {
      api: async (route, u) => {
        if (!u.pathname.startsWith(apiPrefix)) return false;
        if (mode === 'slow') { await new Promise((res) => setTimeout(res, 4000)); return route.continue(); }
        if (mode === '503') return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"unavailable"}' });
        if (mode === 'stale') {
          const resp = await route.fetch();
          let j = await resp.json();
          const mark = (o) => { if (o && typeof o === 'object' && !Array.isArray(o)) { if ('stale' in o) o.stale = true; if ('age_s' in o) o.age_s = 7200; Object.values(o).forEach(mark); } };
          mark(j);
          return route.fulfill({ response: resp, body: JSON.stringify(j) });
        }
        return route.continue();
      },
    });
    const page = await context.newPage();
    const out = (r[name] = {});
    await page.goto(SITE + url);
    await page.waitForTimeout(1500);
    out.loadingSkeleton = await page.evaluate(() => document.querySelectorAll('.ui-skel, [aria-busy="true"]').length);
    await shot(page, `state-${name}-loading`);
    mode = '503';
    await page.goto(SITE + url);
    await settle(page, 800);
    const retry = page.getByRole('button', { name: /Повторить/ }).first();
    out.errorText = await page.evaluate(() => [...document.querySelectorAll('.ui-state__title, .ui-state__text, [role="alert"]')].map((e) => e.textContent.trim()).filter(Boolean).slice(0, 4));
    out.retryVisible = await retry.isVisible().catch(() => false);
    await shot(page, `state-${name}-503`);
    mode = 'ok';
    if (out.retryVisible) {
      await retry.click();
      await settle(page, 1200);
      out.recoveredAfterRetry = await page.evaluate(() => !document.querySelector('.ui-state--error, [role="alert"]') && !/Не удалось загрузить/.test(document.body.innerText));
    }
    mode = 'stale';
    await page.goto(SITE + url);
    await settle(page, 800);
    out.staleShown = await page.evaluate(() => (document.body.innerText.match(/[^\n]*(устаре|обновлял|назад)[^\n]*/gi) || []).slice(0, 3));
    await shot(page, `state-${name}-stale`);
    await context.close();
    console.log('state', name, JSON.stringify(out));
  }
}

// ---------- CSP в деле: эфир HLS, видео YouTube, виджет Telegram ----------
async function csp(browser) {
  const r = (report.csp = {});
  {
    const context = await ctx(browser, M390);
    const page = await context.newPage();
    await page.goto(SITE + '/');
    await settle(page, 6000);
    r.homeStream = await page.evaluate(() => {
      const v = document.querySelector('video');
      return v ? { readyState: v.readyState, t: Math.round(v.currentTime * 10) / 10, paused: v.paused, err: v.error && v.error.code } : null;
    });
    r.homeViolations = await page.evaluate(() => window.__csp);
    await page.goto(SITE + '/video/EoNQQxVIW-Q');
    await settle(page, 2500);
    // плеер YouTube грузится по нажатию на постер
    const play = page.locator('.vp-poster, .vp-play, button[aria-label*="Смотреть"], button[aria-label*="Воспроиз"]').first();
    if (await play.isVisible().catch(() => false)) await play.click().catch(() => {});
    await page.waitForTimeout(4000);
    r.videoIframe = await page.evaluate(() => [...document.querySelectorAll('iframe')].map((f) => f.src.slice(0, 60)));
    r.videoViolations = await page.evaluate(() => window.__csp);
    await shot(page, 'csp-video');
    await context.close();
  }
  {
    // код входа подменён: на сервере ничего не создаём, бот не участвует
    const context = await ctx(browser, D1440, {
      telegram: 'real',
      api: async (route, u) => {
        if (u.pathname === '/api/auth/code') return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ code: '123456', deep_link: 'https://t.me/Real_Madrid_football_bot?start=login_test', bot: 'Real_Madrid_football_bot', ttl: 300, expires_at: new Date(Date.now() + 300000).toISOString() }) });
        if (u.pathname === '/api/auth/code/status') return route.fulfill({ contentType: 'application/json', body: '{"status":"pending","ttl":290}' });
        return false;
      },
    });
    const page = await context.newPage();
    await page.goto(SITE + '/profile');
    await settle(page, 1000);
    await page.getByRole('button', { name: /Войти через Telegram/ }).first().click().catch(() => {});
    await page.waitForTimeout(1500);
    const alt = page.getByText('Другой способ входа').first();
    r.altLoginLink = await alt.isVisible().catch(() => false);
    if (r.altLoginLink) {
      await alt.click();
      await page.waitForTimeout(9000);
      r.widgetIframe = await page.evaluate(() => [...document.querySelectorAll('iframe')].map((f) => f.src.slice(0, 70)));
      r.widgetText = await page.evaluate(() => (document.body.innerText.match(/[^\n]*(Telegram|не загрузил)[^\n]*/g) || []).slice(0, 4));
    }
    r.widgetViolations = await page.evaluate(() => window.__csp);
    await shot(page, 'csp-widget');
    await context.close();
  }
  console.log('csp', JSON.stringify(r));
}

// ---------- frame-ancestors: Telegram Web может встроить, чужой сайт — нет ----------
async function frame(browser) {
  const r = (report.frame = {});
  for (const origin of ['https://web.telegram.org', 'https://evil.example']) {
    const context = await ctx(browser, D1440);
    await context.route(`${origin}/**`, (route) => route.fulfill({ contentType: 'text/html', body: `<!doctype html><iframe id="f" src="${SITE}/matches" style="width:1200px;height:800px"></iframe>` }));
    const page = await context.newPage();
    await page.goto(origin + '/k/');
    await page.waitForTimeout(6000);
    const f = page.frames().find((fr) => fr.url().startsWith(SITE));
    let loaded = false;
    if (f) loaded = await f.evaluate(() => !!document.getElementById('root') && document.getElementById('root').childElementCount > 0).catch(() => false);
    r[origin] = { appRendered: loaded };
    await context.close();
  }
  console.log('frame', JSON.stringify(r));
}

// ---------- производительность: Fast 3G, LCP, CLS, вес первой загрузки ----------
async function perf(browser) {
  const r = (report.perf = {});
  for (const [name, opts] of [['m390-fast3g', M390], ['d1440', D1440]]) {
    const context = await ctx(browser, opts);
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    await cdp.send('Network.enable');
    await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
    if (name.includes('fast3g'))
      await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 562.5, downloadThroughput: (1.6 * 1024 * 1024) / 8 * 0.9, uploadThroughput: (750 * 1024) / 8 * 0.9 });
    let bytes = 0;
    const byType = {};
    cdp.on('Network.loadingFinished', (e) => { bytes += e.encodedDataLength; });
    cdp.on('Network.responseReceived', (e) => { byType[e.requestId] = { type: e.type, url: e.response.url }; });
    const sizes = {};
    cdp.on('Network.loadingFinished', (e) => { const t = byType[e.requestId]; if (t) sizes[t.type] = (sizes[t.type] || 0) + e.encodedDataLength; });
    await page.addInitScript(() => {
      window.__lcp = 0; window.__lcpEl = ''; window.__cls = 0;
      new PerformanceObserver((l) => { for (const e of l.getEntries()) { window.__lcp = e.startTime; window.__lcpEl = (e.element && (e.element.tagName + '.' + e.element.className).slice(0, 60)) || e.url; } }).observe({ type: 'largest-contentful-paint', buffered: true });
      new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({ type: 'layout-shift', buffered: true });
    });
    const t0 = Date.now();
    await page.goto(SITE + '/', { waitUntil: 'load', timeout: 90000 });
    const loadMs = Date.now() - t0;
    await page.waitForTimeout(name.includes('fast3g') ? 12000 : 5000);
    const m = await page.evaluate(() => ({ lcp: Math.round(window.__lcp), lcpEl: window.__lcpEl, cls: Math.round(window.__cls * 1000) / 1000, fcp: Math.round((performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime || 0) }));
    r[name] = { ...m, loadMs, kb: Math.round(bytes / 1024), kbByType: Object.fromEntries(Object.entries(sizes).map(([k, v]) => [k, Math.round(v / 1024)])) };
    console.log('perf', name, JSON.stringify(r[name]));
    await context.close();
  }
}

// ---------- клавиатура: видимый фокус по Tab на сайте ----------
async function keys(browser) {
  const r = (report.keys = { steps: [] });
  const context = await ctx(browser, D1440);
  const page = await context.newPage();
  await page.goto(SITE + '/');
  await settle(page, 800);
  for (let i = 0; i < 25; i++) {
    await page.keyboard.press('Tab');
    const s = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return null;
      const cs = getComputedStyle(el);
      const visible = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
      return { el: el.tagName.toLowerCase() + '.' + String(el.className).split(' ')[0], name: (el.getAttribute('aria-label') || el.innerText || '').trim().slice(0, 30), focusVisible: visible };
    });
    r.steps.push(s);
  }
  r.noVisibleFocus = r.steps.filter((s) => s && !s.focusVisible);
  await shot(page, 'keys-focus');
  await context.close();
  console.log('keys', r.steps.length, 'без видимого фокуса:', JSON.stringify(r.noVisibleFocus));
}

// ---------- контраст текста (WCAG, по вычисленным цветам; фон — ближайший непрозрачный предок) ----------
async function contrast(browser) {
  const r = (report.contrast = {});
  const context = await ctx(browser, M390);
  const page = await context.newPage();
  for (const [name, url] of [['home', '/'], ['matches', '/matches'], ['team', '/team'], ['media', '/media'], ['predict', '/predict'], ['profile', '/profile'], ['match', '/match/6106274']]) {
    await page.goto(SITE + url);
    await settle(page, 800);
    r[name] = await page.evaluate(() => {
      const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p[3] ?? 1 }; };
      const lum = ({ r, g, b }) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
      const bgOf = (el) => { for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.backgroundImage !== 'none') return null; const c = parse(cs.backgroundColor); if (c && c.a > 0.9) return c; } return { r: 6, g: 7, b: 11, a: 1 }; };
      const low = [];
      const seen = new Set();
      const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let n;
      while ((n = w.nextNode())) {
        const t = n.textContent.trim();
        const el = n.parentElement;
        if (!t || !el || seen.has(el) || el.closest('#splash, svg, .bottom-nav')) continue;
        seen.add(el);
        const rc = el.getBoundingClientRect();
        if (!rc.width || !rc.height) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || +cs.opacity === 0) continue;
        const fg = parse(cs.color);
        const bg = bgOf(el);
        if (!fg || !bg) continue;
        const mix = { r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a) };
        const L1 = lum(mix), L2 = lum(bg);
        const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
        const size = parseFloat(cs.fontSize);
        const large = size >= 24 || (size >= 18.66 && +cs.fontWeight >= 700);
        if (ratio < (large ? 3 : 4.5)) low.push(`${ratio.toFixed(2)} ${size}px ${cs.color} «${t.slice(0, 28)}»`);
      }
      return { lowN: low.length, low: [...new Set(low)].slice(0, 8) };
    });
    console.log('contrast', name, JSON.stringify(r[name]));
  }
  await context.close();
}

(async () => {
  const browser = await chromium.launch();
  const blocks = { states, csp, frame, perf, keys, contrast };
  for (const [k, fn] of Object.entries(blocks)) {
    if (ONLY.length && !ONLY.includes(k)) continue;
    try { await fn(browser); } catch (e) { console.error(k, 'FAILED', e.message); report[k] = { failed: e.message }; }
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, 'extra.json'), JSON.stringify(report, null, 1));
})();
