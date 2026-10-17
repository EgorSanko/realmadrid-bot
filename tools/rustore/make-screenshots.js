// Скриншоты карточки RuStore: 1080×1920 (9:16, портрет), тёмно-синий фон с тёплым золотым свечением,
// сверху золотая надпись разрядкой, заголовок, подпись с точкой, ниже — телефон с настоящим экраном приложения.
// Стиль — как у прошедших модерацию слайдов КиТ (Snapframe), свёрстано в HTML и снято Playwright.
// Шрифты — локальные (design/fonts), без Google Fonts.
//
//   NODE_PATH=C:/Users/egor3/node_modules node tools/rustore/make-screenshots.js <папка с экранами>
//
// Экраны (<имя>.png, 412×915 CSS px, DPR 3) снимаются Playwright с User-Agent приложения
// (MadridistaApp/…) на живых данных — без эфира, без входа, без личных данных.
// Результат: rustore/screenshots/01-….png … (порядок = порядок загрузки, ordinal 0..N).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');
const RAW = process.argv[2];
const OUT = path.join(ROOT, 'rustore/screenshots');
const FONTS = 'file:///' + path.join(ROOT, 'design/fonts/fonts.css').replace(/\\/g, '/');
if (!RAW) {
  console.error('укажите папку с экранами');
  process.exit(1);
}
fs.mkdirSync(OUT, { recursive: true });

const KICKER = 'МАДРИДИСТА · ФАН-ПРИЛОЖЕНИЕ REAL MADRID';
const SLIDES = [
  { file: 'home', name: '01-match-day', title: 'Матч дня —<br>с отсчётом', sub: 'Ближайшая игра, прогноз и форма' },
  { file: 'match', name: '02-match', title: 'Весь матч<br>в одном экране', sub: 'Счёт, голы, обзор и лучшие игроки' },
  { file: 'stats', name: '03-stats', title: 'Вся статистика<br>матча', sub: 'Владение, удары, xG и давление' },
  { file: 'lineups', name: '04-lineups', title: 'Составы<br>на поле', sub: 'Схема, оценки игроков и замены' },
  { file: 'table', name: '05-table', title: 'Таблица<br>Ла Лиги', sub: 'И Лига чемпионов — место «Реала» видно сразу' },
  { file: 'player', name: '06-player', title: 'Профиль<br>каждого игрока', sub: 'Статистика сезона, матчи и карьера' },
  { file: 'media', name: '07-media', title: 'Новости и видео<br>внутри', sub: 'Читайте и смотрите, не выходя из приложения' },
  { file: 'predict', name: '08-predict', title: 'Прогнозы<br>на матчи', sub: 'Угадайте счёт и первого бомбардира' },
  { file: 'penalty', name: '09-penalty', title: 'Пенальти<br>и викторина', sub: 'Мини-игры о «Реале» с рейтингом недели' },
];

const html = (img, s) => `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="${FONTS}">
<style>
  html, body { margin: 0; width: 1080px; height: 1920px; overflow: hidden; }
  body {
    position: relative; box-sizing: border-box; padding-top: 96px; text-align: center; color: #EEF0F5;
    font-family: 'Onest', sans-serif;
    background:
      radial-gradient(620px 520px at 50% 6%, rgba(212, 175, 55, .22), transparent 72%),
      radial-gradient(900px 700px at 50% 0%, rgba(40, 56, 110, .30), transparent 75%),
      radial-gradient(700px 600px at 50% 92%, rgba(212, 175, 55, .10), transparent 70%),
      linear-gradient(180deg, #0B0F1D 0%, #06070B 55%, #06070B 100%);
  }
  .kicker { font-weight: 600; font-size: 24px; letter-spacing: .22em; color: #D4AF37; text-transform: uppercase; }
  h1 { margin: 34px 60px 0; font-family: 'Unbounded', sans-serif; font-weight: 700; font-size: 76px; line-height: 1.14;
       letter-spacing: -.01em; color: #F6F2E6; }
  .sub { margin-top: 30px; font-weight: 500; font-size: 38px; color: rgba(238, 240, 245, .74); }
  .sub::before { content: ''; display: inline-block; width: 14px; height: 14px; margin: 0 18px 6px 0; border-radius: 50%;
       background: #D4AF37; box-shadow: 0 0 14px rgba(212, 175, 55, .7); vertical-align: middle; }
  .phone {
    position: absolute; left: 50%; top: 528px; width: 600px; height: 1332px; transform: translateX(-50%);
    padding: 18px; border-radius: 86px; box-sizing: content-box;
    background: linear-gradient(160deg, #2A2E3A, #0D0F15 40%, #1A1D27);
    box-shadow: 0 0 0 2px rgba(212, 175, 55, .35), 0 40px 100px rgba(0, 0, 0, .65), 0 0 90px rgba(212, 175, 55, .16);
  }
  .screen { width: 600px; height: 1332px; border-radius: 70px; overflow: hidden; background: #06070B; position: relative; }
  .screen img { display: block; width: 600px; height: auto; }
  .btn { position: absolute; right: -6px; width: 6px; border-radius: 0 4px 4px 0; background: #22252F; }
</style></head><body>
  <div class="kicker">${KICKER}</div>
  <h1>${s.title}</h1>
  <div class="sub">${s.sub}</div>
  <div class="phone">
    <span class="btn" style="top: 260px; height: 110px"></span>
    <span class="btn" style="top: 400px; height: 180px"></span>
    <div class="screen"><img src="${img}"></div>
  </div>
</body></html>`;

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
  for (const s of SLIDES) {
    const src = path.join(RAW, s.file + '.png');
    if (!fs.existsSync(src)) {
      console.warn('нет экрана', src);
      continue;
    }
    const img = 'file:///' + src.replace(/\\/g, '/');
    const tmp = path.join(RAW, `_slide-${s.name}.html`);
    fs.writeFileSync(tmp, html(img, s));
    await page.goto('file:///' + tmp.replace(/\\/g, '/'), { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(150);
    let file = path.join(OUT, s.name + '.png');
    let buf = await page.screenshot({ type: 'png' });
    if (buf.length > 3 * 1024 * 1024) {
      // RuStore: до 3 МБ (консоль) — крупный PNG заменяем на JPEG высокого качества
      file = path.join(OUT, s.name + '.jpg');
      buf = await page.screenshot({ type: 'jpeg', quality: 92 });
    }
    fs.writeFileSync(file, buf);
    fs.unlinkSync(tmp);
    console.log(path.relative(ROOT, file), Math.round(buf.length / 1024) + ' КБ');
  }
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
