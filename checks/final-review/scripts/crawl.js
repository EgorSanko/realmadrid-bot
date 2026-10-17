// Финальный обход «как живой пользователь» (Playwright) против https://realmadridfan.ru.
//
//   NODE_PATH=C:/Users/egor3/node_modules node crawl.js <out-subdir> [distDir] [--csp]
//
// Без distDir — живой сайт как есть («до»). С distDir — страницы и /assets/* из локальной сборки,
// /api/* и /img/* — с сервера («после»). --csp — на HTML-ответы вешается заголовок CSP из
// deploy/nginx.conf.template (строка add_header Content-Security-Policy), нарушения собираются.
// Профили: m390 — телефон в браузере, tma390 — имитация Telegram Mini App, d1440 и d1280 — ПК.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const [, , SUB = 'before', DIST_ARG, ...flags] = process.argv;
// distDir или адрес локального nginx (scripts/nginx-local.mjs): тогда страницы и их заголовки (CSP, 404) — от него
const NGX = DIST_ARG && /^https?:/.test(DIST_ARG) ? DIST_ARG.replace(/\/$/, '') : null;
const DIST = DIST_ARG && DIST_ARG !== '-' && !NGX ? path.resolve(DIST_ARG) : null;
const WITH_CSP = flags.includes('--csp');
const PAGES_ONLY = (flags.find((f) => f.startsWith('--pages=')) || '').slice(8).split(',').filter(Boolean);
const ONLY = (flags.find((f) => f.startsWith('--only=')) || '').slice(7).split(',').filter(Boolean);
const SITE = 'https://realmadridfan.ru';
const HOST = 'realmadridfan.ru';
const OUT = path.resolve(__dirname, '..', SUB);
fs.mkdirSync(OUT, { recursive: true });
const MIME = {
  '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.woff2': 'font/woff2', '.woff': 'font/woff',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.json': 'application/json', '.ico': 'image/x-icon',
  '.webp': 'image/webp', '.webmanifest': 'application/manifest+json', '.txt': 'text/plain', '.xml': 'application/xml',
};

function cspFromTemplate() {
  const t = fs.readFileSync(path.resolve(__dirname, '../../../deploy/nginx.conf.template'), 'utf8');
  const m = /add_header Content-Security-Policy "([^"]+)"/.exec(t);
  if (!m) throw new Error('CSP в шаблоне не найден');
  return m[1];
}
const CSP = WITH_CSP ? cspFromTemplate() : null;
const LISTEN_CSP = !!(CSP || NGX);

const PROFILES = {
  m390: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  tma390: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, tma: true },
  d1440: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
  d1280: { viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 },
};

const TMA_THEME = { bg_color: '#06070b', secondary_bg_color: '#0b0d14', text_color: '#eef0f5', hint_color: '#8a90a1',
  link_color: '#d4af37', button_color: '#d4af37', button_text_color: '#1a1408', header_bg_color: '#06070b' };
// initData без подписи: вход по нему сервер отклонит — экраны мини-аппа это переживают (проверяем и это)
const TMA_HASH = '#' + new URLSearchParams({
  tgWebAppData: new URLSearchParams({ auth_date: String(Math.floor(Date.now() / 1000)), user: JSON.stringify({ id: 1, first_name: 'Review' }), hash: '0'.repeat(64) }).toString(),
  tgWebAppVersion: '8.0', tgWebAppPlatform: 'ios', tgWebAppThemeParams: JSON.stringify(TMA_THEME),
}).toString();
const TMA_MOCK = `
  window.__tgEvents = [];
  window.Telegram = { WebApp: { platform: 'ios', version: '8.0' } };
  window.TelegramWebviewProxy = {
    postEvent(name, data) {
      window.__tgEvents.push([name, data]);
      const reply = (ev, payload) => setTimeout(() => window.Telegram && window.Telegram.WebView && window.Telegram.WebView.receiveEvent(ev, payload), 0);
      if (name === 'web_app_request_viewport') reply('viewport_changed', { height: innerHeight, width: innerWidth, is_expanded: true, is_state_stable: true });
      if (name === 'web_app_request_theme') reply('theme_changed', { theme_params: ${JSON.stringify(TMA_THEME)} });
      if (name === 'web_app_request_safe_area') reply('safe_area_changed', { top: 0, bottom: 0, left: 0, right: 0 });
      if (name === 'web_app_request_content_safe_area') reply('content_safe_area_changed', { top: 0, bottom: 0, left: 0, right: 0 });
    },
  };
  window.TelegramWebviewProxy.postEvent.toString = () => 'function postEvent() { [native code] }';
`;
const CSP_LISTENER = `
  window.__csp = [];
  document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));
`;

async function ids() {
  const j = async (p) => (await fetch(SITE + p)).json();
  const fx = await j('/api/fixtures');
  const past = fx.matches.filter((m) => m.status.state === 'finished').at(-1);
  const future = fx.matches.find((m) => m.status.state !== 'finished');
  const team = await j('/api/team');
  // squad: { группа: [игроки] } или массив — ищем первый объект с числовым id
  const found = [];
  const walk = (v) => { if (Array.isArray(v)) v.forEach(walk); else if (v && typeof v === 'object') { if (typeof v.id === 'number' && v.name) found.push(v); else Object.values(v).forEach(walk); } };
  walk(team.squad);
  const player = found[0] || {};
  const news = await j('/api/news');
  const vids = await j('/api/videos');
  return { past: past.id, future: future && future.id, player: player.id, news: news.items[0].aid, video: vids.items.find((v) => !v.short)?.id || vids.items[0].id };
}

// аудит экрана в странице: всё, что видно пользователю
const AUDIT = (mobile) => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity !== 0;
  };
  const txt = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60);
  const sel = (el) => el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
  const imgs = [...document.images];
  const out = {
    title: document.title,
    hscroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    imgs: imgs.length,
    brokenImg: imgs.filter((i) => vis(i) && i.complete && i.naturalWidth === 0).map((i) => i.getAttribute('src')).slice(0, 10),
    noAlt: imgs.filter((i) => !i.hasAttribute('alt')).map((i) => i.getAttribute('src')).slice(0, 10),
    noName: [],
    hashLinks: [...document.querySelectorAll('a')].filter((a) => !a.getAttribute('href') || a.getAttribute('href') === '#').map((a) => sel(a) + ' ' + txt(a)).slice(0, 10),
    small: [],
    tiny: [],
    trunc: [],
    placeholder: [],
    plural: [],
    h1: [...document.querySelectorAll('h1')].map(txt),
  };
  for (const el of document.querySelectorAll('button, a, [role="button"], [role="tab"], input, select')) {
    if (!vis(el)) continue;
    const name = (el.getAttribute('aria-label') || el.getAttribute('title') || txt(el) || [...el.querySelectorAll('img')].map((i) => i.alt).join('') || el.getAttribute('aria-labelledby') || el.value || '').trim();
    if (!name) out.noName.push(sel(el));
    if (mobile) {
      const r0 = el.getBoundingClientRect();
      const af = getComputedStyle(el, '::after');
      const ins = (v) => Math.min(0, parseFloat(v) || 0);
      const r = af.content !== 'none' && af.position === 'absolute'
        ? { width: r0.width - ins(af.left) - ins(af.right), height: r0.height - ins(af.top) - ins(af.bottom) } : r0;
      if (r.height < 44 && r.width < 44) out.tiny.push(`${sel(el)} ${Math.round(r.width)}×${Math.round(r.height)} «${txt(el) || el.getAttribute('aria-label') || ''}»`);
      else if (r.height < 32 && el.tagName === 'BUTTON') out.tiny.push(`${sel(el)} ${Math.round(r.width)}×${Math.round(r.height)} «${txt(el) || el.getAttribute('aria-label') || ''}»`);
    }
  }
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  let n;
  while ((n = walker.nextNode())) {
    const t = n.textContent.replace(/\s+/g, ' ').trim();
    if (!t) continue;
    const el = n.parentElement;
    if (!el || seen.has(el) || !vis(el) || el.closest('#splash, script, style, svg')) continue;
    seen.add(el);
    const fs = parseFloat(getComputedStyle(el).fontSize);
    if (fs < 11) out.small.push(`${fs}px ${sel(el)} «${t.slice(0, 30)}»`);
    if (/этап[еау]? \d|появится|скоро|lorem|todo|undefined|NaN|\bnull\b|\[object|заглушк/i.test(t)) out.placeholder.push(`${sel(el)} «${t.slice(0, 80)}»`);
    if (/(^|[^\d])(1|21|31|41|51) (матчей|голов|очков|игроков|дней|часов|минут|секунд|прогнозов|вопросов|ударов|матча|гола|очка)(?![а-я])|(^|[^\d])([5-9]|1\d|20) (матча|гола|очка|игрока|дня|часа|минуты|прогноза|удара)(?![а-я])|(^|[^\d])[2-4] (матчей|голов|очков|игроков|дней|часов|минут|прогнозов|ударов)(?![а-я])/.test(t))
      out.plural.push(`«${t.slice(0, 60)}»`);
    const cs = getComputedStyle(el);
    if (cs.textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1) out.trunc.push(`${sel(el)} «${t.slice(0, 40)}»`);
  }
  out.small = [...new Set(out.small)];
  for (const k of ['small', 'tiny', 'trunc', 'noName', 'placeholder', 'plural']) {
    out[k + 'N'] = out[k].length;
    out[k] = out[k].slice(0, 12);
  }
  return out;
};

let lastDocStatus = 0;
async function openCtx(browser, prof) {
  const p = PROFILES[prof];
  const context = await browser.newContext({ viewport: p.viewport, deviceScaleFactor: p.deviceScaleFactor, isMobile: !!p.isMobile, hasTouch: !!p.hasTouch, locale: 'ru-RU', timezoneId: 'Europe/Moscow',
    userAgent: p.isMobile ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1' : undefined });
  const log = { external: {}, extSeq: [], errors: [], bad: [], csp: [] };
  if (p.tma) await context.addInitScript(TMA_MOCK);
  if (LISTEN_CSP) await context.addInitScript(CSP_LISTENER);
  await context.route('https://telegram.org/**', (r) => r.abort('blockedbyclient'));
  await context.route(`${SITE}/**`, async (route) => {
    const req = route.request();
    const u = new URL(req.url());
    const p2 = u.pathname;
    const isApi = p2.startsWith('/api/') || p2.startsWith('/img/');
    if (NGX && !isApi) {
      const resp = await route.fetch({ url: NGX + p2 + u.search, maxRedirects: 0, headers: { ...req.headers(), host: new URL(NGX).host } });
      return route.fulfill({ response: resp });
    }
    if (DIST && !isApi) {
      const file = path.join(DIST, decodeURIComponent(p2));
      const headers = {};
      let body;
      let status = 200;
      if (p2 !== '/' && fs.existsSync(file) && fs.statSync(file).isFile()) {
        headers['content-type'] = MIME[path.extname(file)] || 'application/octet-stream';
        body = fs.readFileSync(file);
      } else if (p2.startsWith('/assets/')) { status = 404; body = ''; }
      else { headers['content-type'] = 'text/html; charset=utf-8'; body = fs.readFileSync(path.join(DIST, 'index.html')); }
      if (CSP && String(headers['content-type']).startsWith('text/html')) headers['content-security-policy'] = CSP;
      return route.fulfill({ status, headers, body });
    }
    if (CSP && req.resourceType() === 'document') {
      const resp = await route.fetch();
      return route.fulfill({ response: resp, headers: { ...resp.headers(), 'content-security-policy': CSP } });
    }
    return route.continue();
  });
  const page = await context.newPage();
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (u.protocol.startsWith('http') && u.host !== HOST) {
      log.external[u.host] = (log.external[u.host] || 0) + 1;
      log.extSeq.push(u.host);
    }
  });
  page.on('response', (r) => { if (r.request().resourceType() === 'document' && r.frame() === page.mainFrame()) lastDocStatus = r.status(); if (r.status() >= 400) log.bad.push(`${r.status()} ${r.url().replace(SITE, '')}`); });
  page.on('console', (m) => { if (m.type() === 'error') log.errors.push(m.text().slice(0, 200)); });
  page.on('pageerror', (e) => log.errors.push('pageerror: ' + e.message.slice(0, 200)));
  return { context, page, log, tma: !!p.tma, mobile: !!p.isMobile };
}

async function settle(page, ms = 700) {
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForSelector('#splash', { state: 'detached', timeout: 10000 }).catch(() => {});
  // скелетоны ушли (идёт эфир — networkidle не наступает, поэтому ждём по разметке)
  await page.waitForFunction(() => !document.querySelector('[aria-busy="true"], .ui-skel'), null, { timeout: 10000 }).catch(() => {});
  // пролистать вниз и обратно — ленивые картинки ниже первого экрана тоже грузятся
  await page.evaluate(async () => {
    for (let y = 0; y < document.documentElement.scrollHeight; y += innerHeight) { scrollTo(0, y); await new Promise((r) => setTimeout(r, 120)); }
    scrollTo(0, 0);
  });
  await page.waitForFunction(() => [...document.images].every((i) => i.complete), null, { timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(ms);
}

async function main() {
  const I = await ids();
  console.log('ids', I);
  const PAGES = [
    ['home', '/'],
    ['matches', '/matches'],
    ['match-past', `/match/${I.past}`],
    ['match-past-lineups', `/match/${I.past}/lineups`],
    ['match-past-stats', `/match/${I.past}/stats`],
    ['match-future', `/match/${I.future}`],
    ['team', '/team'],
    ['player', `/player/${I.player}`],
    ['media', '/media'],
    ['news', `/news/${I.news}`],
    ['video', `/video/${I.video}`],
    ['predict', '/predict'],
    ['quiz', '/games/quiz'],
    ['penalty', '/games/penalty'],
    ['profile', '/profile'],
    ['admin', '/admin'],
    ['notfound', '/no-such-page-xyz'],
    ['notfound-match', '/match/abc'],
  ];
  const browser = await chromium.launch();
  const report = { ids: I, csp: CSP, profiles: {} };
  for (const prof of Object.keys(PROFILES)) {
    if (ONLY.length && !ONLY.includes(prof)) continue;
    const { context, page, log, tma, mobile } = await openCtx(browser, prof);
    const rep = (report.profiles[prof] = { pages: {} });
    for (const [name, url] of PAGES) {
      if (PAGES_ONLY.length && !PAGES_ONLY.includes(name)) continue;
      const before = { e: log.errors.length, b: log.bad.length, x: log.extSeq.length };
      await page.goto(SITE + url + (tma ? TMA_HASH : ''), { waitUntil: 'domcontentloaded' }).catch((e) => log.errors.push('goto ' + e.message));
      await settle(page);
      const a = await page.evaluate(AUDIT, mobile);
      a.finalUrl = page.url().replace(SITE, '').split('#')[0];
      a.errors = log.errors.slice(before.e);
      a.bad = log.bad.slice(before.b);
      a.external = [...new Set(log.extSeq.slice(before.x))];
      if (LISTEN_CSP) a.csp = await page.evaluate(() => window.__csp || []);
      a.status = lastDocStatus;
      await page.screenshot({ path: path.join(OUT, `${prof}-${name}.png`), fullPage: !tma && name !== 'penalty' });
      // вкладки экрана: щёлкаем каждую, снимок
      const tabs = await page.locator('[role="tab"]:visible').all();
      a.tabs = [];
      for (let i = 0; i < Math.min(tabs.length, 8); i++) {
        const t = tabs[i];
        const label = ((await t.innerText().catch(() => '')) || '').trim().replace(/\s+/g, ' ');
        await t.click({ timeout: 3000 }).catch(() => {});
        await settle(page, 400);
        const b = await page.evaluate(AUDIT, mobile);
        a.tabs.push({ label, url: page.url().replace(SITE, '').split('#')[0], brokenImg: b.brokenImg, hscroll: b.hscroll, placeholder: b.placeholder, plural: b.plural, smallN: b.smallN, truncN: b.truncN, trunc: b.trunc });
        if (i > 0 || tabs.length > 1) await page.screenshot({ path: path.join(OUT, `${prof}-${name}-tab${i}.png`) });
      }
      rep.pages[name] = a;
      console.log(prof, name, a.finalUrl, '|', a.title, '| hs', a.hscroll, 'broken', a.brokenImg.length, 'small', a.smallN, 'tiny', a.tinyN, 'noName', a.noNameN, 'ph', a.placeholderN, 'err', a.errors.length, 'bad', a.bad.length, 'ext', a.external.join(','), 'doc', a.status, LISTEN_CSP ? 'csp ' + a.csp.length + ' ' + a.csp.slice(0, 3).join(' | ') : '');
    }
    rep.external = log.external;
    await context.close();
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1));
}
main().catch((e) => { console.error(e); process.exit(1); });
