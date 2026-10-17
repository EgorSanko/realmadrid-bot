// Значки и картинка превью ссылок — один раз, скриптом (Playwright), из векторной эмблемы tools/splash/logo.svg.
//
//   NODE_PATH=C:/Users/egor3/node_modules node tools/brand/make-assets.js
//
// Пишет в frontend/public/: og.png (1200×630), favicon.svg, favicon.ico (16+32), favicon-32.png,
// apple-touch-icon.png (180, на фоне палитры), icon-192.png, icon-512.png, icon-maskable-512.png.
// Шрифты — локальные @fontsource из frontend/node_modules (никаких внешних запросов).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');
const OUT = path.join(ROOT, 'frontend/public');
const LOGO = fs.readFileSync(path.join(ROOT, 'tools/splash/logo.svg'), 'utf8');
const FONTS = path.join(ROOT, 'frontend/node_modules/@fontsource');
const font = (pkg, file) => fs.readFileSync(path.join(FONTS, pkg, 'files', file)).toString('base64');
fs.mkdirSync(OUT, { recursive: true });

// эмблема без фиксированных размеров — масштабируется по контейнеру
const crest = LOGO.replace(/\s(width|height)="[^"]*"/g, '');
const crestUri = 'data:image/svg+xml;base64,' + Buffer.from(crest).toString('base64');

const fontCss = `
@font-face { font-family: 'Unbounded'; font-weight: 700; src: url(data:font/woff2;base64,${font('unbounded', 'unbounded-cyrillic-700-normal.woff2')}) format('woff2'); unicode-range: U+0400-045F; }
@font-face { font-family: 'Unbounded'; font-weight: 700; src: url(data:font/woff2;base64,${font('unbounded', 'unbounded-latin-700-normal.woff2')}) format('woff2'); unicode-range: U+0000-00FF, U+2014; }
@font-face { font-family: 'Onest'; font-weight: 500; src: url(data:font/woff2;base64,${font('onest', 'onest-cyrillic-500-normal.woff2')}) format('woff2'); unicode-range: U+0400-045F; }
@font-face { font-family: 'Onest'; font-weight: 500; src: url(data:font/woff2;base64,${font('onest', 'onest-latin-500-normal.woff2')}) format('woff2'); unicode-range: U+0000-00FF, U+2014, U+00B7; }
`;

const OG_HTML = `<!doctype html><html><head><meta charset="utf-8"><style>${fontCss}
html, body { margin: 0; width: 1200px; height: 630px; overflow: hidden; }
body {
  position: relative; display: flex; align-items: center; gap: 60px; padding: 0 80px; box-sizing: border-box;
  background:
    radial-gradient(760px 520px at 22% 50%, rgba(212, 175, 55, .20), transparent 70%),
    radial-gradient(640px 480px at 100% 0%, rgba(40, 60, 120, .28), transparent 70%),
    linear-gradient(180deg, #0B0D14, #06070B);
  color: #EEF0F5; font-family: 'Onest', sans-serif;
}
body::after { content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 8px; background: linear-gradient(90deg, #F4D57A, #D4AF37, #F4D57A); }
.crest { width: 270px; height: 363px; flex: none; filter: drop-shadow(0 18px 46px rgba(212, 175, 55, .30)); }
.word { font-family: 'Unbounded', sans-serif; font-weight: 700; font-size: 58px; letter-spacing: .05em; line-height: 1; }
.word b { color: #D4AF37; }
.line { width: 120px; height: 4px; margin: 34px 0 30px; border-radius: 4px; background: linear-gradient(90deg, #F4D57A, #D4AF37); }
.sub { font-size: 38px; line-height: 1.3; color: #EEF0F5; }
.small { margin-top: 26px; font-size: 26px; color: #8A90A1; }
</style></head><body>
<img class="crest" src="${crestUri}" alt="">
<div>
  <div class="word">МАДРИДИСТА</div>
  <div class="line"></div>
  <div class="sub">Мадридиста — фан-приложение<br>Real Madrid</div>
  <div class="small">Матчи · трансляции · новости · прогнозы</div>
</div>
</body></html>`;

/** Квадратный значок: эмблема по центру с полями; bg — заливка (null — прозрачный фон). */
const iconHtml = (size, pad, bg) => `<!doctype html><html><head><style>
html, body { margin: 0; width: ${size}px; height: ${size}px; overflow: hidden; background: ${bg ?? 'transparent'}; }
body { display: flex; align-items: center; justify-content: center; }
img { height: ${size - 2 * pad}px; width: auto; }
</style></head><body><img src="${crestUri}" alt=""></body></html>`;

/** ICO из PNG-кадров (формат ICO допускает PNG внутри, начиная с Windows Vista). */
function ico(frames) {
  const head = Buffer.alloc(6 + 16 * frames.length);
  head.writeUInt16LE(0, 0);
  head.writeUInt16LE(1, 2);
  head.writeUInt16LE(frames.length, 4);
  let offset = head.length;
  frames.forEach(({ size, png }, i) => {
    const e = 6 + 16 * i;
    head.writeUInt8(size >= 256 ? 0 : size, e);
    head.writeUInt8(size >= 256 ? 0 : size, e + 1);
    head.writeUInt8(0, e + 2);
    head.writeUInt8(0, e + 3);
    head.writeUInt16LE(1, e + 4);
    head.writeUInt16LE(32, e + 6);
    head.writeUInt32LE(png.length, e + 8);
    head.writeUInt32LE(offset, e + 12);
    offset += png.length;
  });
  return Buffer.concat([head, ...frames.map((f) => f.png)]);
}

(async () => {
  const browser = await chromium.launch();
  const render = async (html, w, h, transparent) => {
    const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    await page.route('**/*', (r) => (r.request().url().startsWith('data:') ? r.continue() : r.abort()));
    await page.setContent(html, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    const png = await page.screenshot({ omitBackground: !!transparent, type: 'png' });
    await page.close();
    return png;
  };

  const out = (name, buf) => {
    fs.writeFileSync(path.join(OUT, name), buf);
    console.log(name, buf.length, 'байт');
  };

  out('og.png', await render(OG_HTML, 1200, 630));
  out('favicon.svg', Buffer.from(crest.replace('<svg ', '<svg width="32" height="43" ')));
  const f16 = await render(iconHtml(16, 0, null), 16, 16, true);
  const f32 = await render(iconHtml(32, 1, null), 32, 32, true);
  out('favicon-32.png', f32);
  out('favicon.ico', ico([{ size: 16, png: f16 }, { size: 32, png: f32 }]));
  out('apple-touch-icon.png', await render(iconHtml(180, 26, '#06070B'), 180, 180));
  out('icon-192.png', await render(iconHtml(192, 18, '#06070B'), 192, 192));
  out('icon-512.png', await render(iconHtml(512, 48, '#06070B'), 512, 512));
  // maskable: значимая часть — в центральных 80 %
  out('icon-maskable-512.png', await render(iconHtml(512, 110, '#06070B'), 512, 512));
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
