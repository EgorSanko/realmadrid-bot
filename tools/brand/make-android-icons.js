// Значки Android-приложения и магазина RuStore — один раз, скриптом (Playwright), из настоящей эмблемы
// tools/splash/logo.svg (палитра сайта: тёмно-синий/чёрный фон, тонкое золото).
//
//   NODE_PATH=C:/Users/egor3/node_modules node tools/brand/make-android-icons.js
//
// Пишет:
//   android/app/src/main/res/mipmap-*/ic_launcher_{background,foreground,monochrome}.png, ic_launcher.png,
//     ic_launcher_round.png — адаптивная иконка (Android 8+), монохромная (Android 13) и старые (Android 7);
//   android/app/src/main/res/drawable-*/splash_icon.png — значок системного splash (Android 12+);
//   rustore/icon-512.png — иконка карточки (совпадает с иконкой на устройстве);
//   rustore/fallback-icon/ — ЗАПАСНОЙ вариант без эмблемы клуба (золотая «М» на тёмном): icon-512.png и те же
//     mipmap-* — на случай, если модерация не пропустит чужой товарный знак (как подменить — README там же).
// Шрифт «М» — локальный Unbounded из frontend/node_modules/@fontsource (никаких внешних запросов).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');
const RES = path.join(ROOT, 'android/app/src/main/res');
const RUSTORE = path.join(ROOT, 'rustore');
const FALLBACK = path.join(RUSTORE, 'fallback-icon');
const LOGO = fs.readFileSync(path.join(ROOT, 'tools/splash/logo.svg'), 'utf8');
const FONTS = path.join(ROOT, 'frontend/node_modules/@fontsource');
const font = (pkg, file) => fs.readFileSync(path.join(FONTS, pkg, 'files', file)).toString('base64');

const crest = LOGO.replace(/\s(width|height)="[^"]*"/g, '');
const crestUri = 'data:image/svg+xml;base64,' + Buffer.from(crest).toString('base64');

const fontCss = `
@font-face { font-family: 'Unbounded'; font-weight: 700; src: url(data:font/woff2;base64,${font('unbounded', 'unbounded-cyrillic-700-normal.woff2')}) format('woff2'); }
`;

const DENS = { mdpi: 1, hdpi: 1.5, xhdpi: 2, xxhdpi: 3, xxxhdpi: 4 };

// всё в долях «dp» холста 108×108 (адаптивная иконка); безопасная зона — круг 66 dp в центре
const BG = (glow = true) => `
  background:
    ${glow ? 'radial-gradient(60% 60% at 50% 42%, rgba(212,175,55,.16), transparent 70%),' : ''}
    radial-gradient(90% 90% at 50% 30%, #101830, #06070B 75%);`;

function ring(size, k) {
  // тонкое золотое кольцо диаметром 64 dp
  const d = 64 * k;
  const w = Math.max(1, 1.4 * k);
  return `<div style="position:absolute;left:${(size - d) / 2}px;top:${(size - d) / 2}px;width:${d}px;height:${d}px;
    border-radius:50%;box-sizing:border-box;border:${w}px solid #D4AF37;"></div>`;
}

const page0 = (size, body, bg = 'transparent') =>
  `<!doctype html><html><head><meta charset="utf-8"><style>${fontCss}
  html,body{margin:0;width:${size}px;height:${size}px;overflow:hidden;background:${bg};}
  .c{position:absolute;inset:0}</style></head><body>${body}</body></html>`;

// --- слои адаптивной иконки (108 dp) ---
const bgLayer = (k) => page0(108 * k, `<div class="c" style="${BG()}"></div>`);
const crestFg = (k, mono = false) => {
  const s = 108 * k;
  const h = 44 * k; // высота эмблемы (корона + круг) — внутри кольца
  const w = (h * 32) / 43;
  const filter = mono ? 'filter:brightness(0) invert(1);' : '';
  return `${mono ? ring(s, k).replace('#D4AF37', '#FFFFFF') : ring(s, k)}
     <img src="${crestUri}" style="position:absolute;left:${(s - w) / 2}px;top:${(s - h) / 2 - 1 * k}px;width:${w}px;height:${h}px;${filter}">`;
};
const letterFg = (k, mono = false) => {
  const s = 108 * k;
  const color = mono ? '#FFFFFF' : 'linear-gradient(160deg,#F4D57A,#D4AF37 60%,#B8932A)';
  const fill = mono ? 'color:#FFFFFF;' : `background:${color};-webkit-background-clip:text;background-clip:text;color:transparent;`;
  return `${mono ? ring(s, k).replace('#D4AF37', '#FFFFFF') : ring(s, k)}
     <div style="position:absolute;left:0;top:0;width:${s}px;height:${s}px;display:flex;align-items:center;justify-content:center;">
       <span style="font-family:Unbounded;font-weight:700;font-size:${34 * k}px;line-height:1;${fill};transform:translateY(${1 * k}px)">М</span>
     </div>`;
};

// --- старые иконки (48 dp): квадрат со скруглением / круг; видна безопасная зона 66 dp → 48 dp ---
const legacy = (k, fg, round) => {
  const s = 48 * k;
  const k2 = (k * 48) / 66;
  const off = (s - 108 * k2) / 2;
  const r = round ? '50%' : `${10 * k}px`;
  return page0(
    s,
    `<div class="c" style="${BG()};border-radius:${r};overflow:hidden;">
       <div style="position:absolute;left:${off}px;top:${off}px;width:${108 * k2}px;height:${108 * k2}px">${fg(k2)}</div>
     </div>`,
  );
};

// --- иконка магазина 512×512: тот же рисунок, что на устройстве (без прозрачности по краям) ---
const store = (fg) => {
  const s = 512;
  return page0(s, `<div class="c" style="${BG()}"></div>${fg(s / 108)}`);
};

// --- значок splash (Android 12+): 288×288 dp холст, видимый круг ~192 dp; рисуем эмблему без кольца ---
const splash = (k) => {
  const s = 288 * k;
  const h = 132 * k;
  const w = (h * 32) / 43;
  return page0(s, `<img src="${crestUri}" style="position:absolute;left:${(s - w) / 2}px;top:${(s - h) / 2}px;width:${w}px;height:${h}px">`);
};

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const render = async (html, w, h, transparent = true) => {
    await page.setViewportSize({ width: Math.round(w), height: Math.round(h) });
    await page.setContent(html, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(60);
    return page.screenshot({ omitBackground: transparent, type: 'png' });
  };
  const write = (file, buf) => {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, buf);
    console.log(path.relative(ROOT, file), buf.length);
  };

  const sets = [
    { root: RES, fg: crestFg, store: path.join(RUSTORE, 'icon-512.png') },
    { root: FALLBACK, fg: letterFg, store: path.join(FALLBACK, 'icon-512.png') },
  ];
  for (const set of sets) {
    for (const [d, k] of Object.entries(DENS)) {
      const dir = path.join(set.root, `mipmap-${d}`);
      write(path.join(dir, 'ic_launcher_background.png'), await render(bgLayer(k), 108 * k, 108 * k, false));
      write(path.join(dir, 'ic_launcher_foreground.png'), await render(page0(108 * k, set.fg(k)), 108 * k, 108 * k));
      write(path.join(dir, 'ic_launcher_monochrome.png'), await render(page0(108 * k, set.fg(k, true)), 108 * k, 108 * k));
      write(path.join(dir, 'ic_launcher.png'), await render(legacy(k, (q) => set.fg(q), false), 48 * k, 48 * k));
      write(path.join(dir, 'ic_launcher_round.png'), await render(legacy(k, (q) => set.fg(q), true), 48 * k, 48 * k));
    }
    write(set.store, await render(store(set.fg), 512, 512, false));
  }
  for (const [d, k] of Object.entries(DENS)) {
    write(path.join(RES, `drawable-${d}`, 'splash_icon.png'), await render(splash(k), 288 * k, 288 * k));
  }
  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
