// Рендер макетов: скриншоты экранов + сборка PDF. Внешние запросы запрещены —
// если какой-то экран полезет в интернет (Google и т.п.), скрипт это покажет.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const DIR = __dirname;
const SHOTS = path.join(DIR, 'shots');
const url = (f) => 'file:///' + path.join(DIR, f).replace(/\\/g, '/');

const STYLES = [
  ['a-home', 'A · Ночной Бернабеу', 'Тёмный фон, золотой акцент. Удобно смотреть трансляцию вечером, меньше слепит. Шрифты Unbounded + Onest.'],
  ['b-home', 'B · Белый клуб', 'Светлый, журнальный: засечки, тонкие линии, много воздуха. Шрифты Playfair Display + Manrope.'],
  ['c-home', 'C · Матч-день', 'Ярко-синий, крупный сжатый шрифт, жёлтый акцент — спортивно и громко. Шрифты Oswald + Golos Text.'],
];
const SCREENS = [
  ['a-live', 'Главная — идёт эфир', 'Плеер сверху, счёт с минутой, голы, мини-статистика и статус твоего прогноза.'],
  ['a-match-events', 'Матч — обзор', 'Видеообзор, лучшие игроки, хронология голов и карточек, стадион и судья.'],
  ['a-match-lineup', 'Матч — составы', 'Расстановка на поле с оценками FotMob, замены, кто не играл.'],
  ['a-match-stats', 'Матч — статистика', 'Давление по ходу матча, главные цифры по таймам, карта ударов.'],
  ['a-team', 'Команда', 'Лидеры сезона, лазарет со сроками, весь состав по линиям.'],
  ['a-fixtures', 'Матчи', 'Ближайшие матчи всех турниров, результаты, таблица Ла Лиги.'],
  ['a-media', 'Медиа', 'Обзоры матчей, видео клуба с YouTube, новости на русском.'],
  ['a-predict', 'Прогнозы', 'Прогноз счёта и автора первого гола, правила очков, рейтинг и лига с друзьями.'],
];

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const external = new Set();
  await ctx.route('**/*', (r) => {
    const u = r.request().url();
    if (u.startsWith('file:') || u.startsWith('data:')) return r.continue();
    external.add(u); return r.abort();
  });
  const page = await ctx.newPage();
  const sizes = {};
  for (const [f] of [...STYLES, ...SCREENS]) {
    await page.goto(url(`screens/${f}.html`));
    await page.evaluate(() => document.fonts.ready);
    const el = (await page.$('main.phone')) || (await page.$('body > div'));
    const box = await el.boundingBox();
    sizes[f] = Math.round(box.height);
    await el.screenshot({ path: path.join(SHOTS, `${f}.png`) });
    // проверка: всё ли ушло в локальные шрифты
    const fams = await page.evaluate(() => [...document.fonts].filter(x => x.status === 'loaded').map(x => x.family));
    console.log(`${f.padEnd(16)} ${String(sizes[f]).padStart(5)}px  шрифты: ${[...new Set(fams)].join(', ')}`);
  }
  console.log('внешние запросы:', external.size ? [...external] : 'НЕТ');

  // ---- сборка PDF ----
  const card = (f, title, text) => `
    <figure><img src="shots/${f}.png" style="width:390px;height:${sizes[f]}px">
    <figcaption><b>${title}</b><span>${text}</span></figcaption></figure>`;
  const W = 1500;
  const pageH = (fs_) => Math.max(...fs_.map(f => sizes[f])) + 340;
  const groups = [SCREENS.slice(0, 3), SCREENS.slice(3, 6), SCREENS.slice(6)];
  const pages = [];
  pages.push({ h: pageH(STYLES.map(s => s[0])), html: `
    <header><small>Мадридиста · дизайн нового приложения · ${new Date().toLocaleDateString('ru-RU')}</small>
    <h1>1. Стиль — выбери A, B или C</h1>
    <p>Одна и та же главная до матча в трёх стилях. Данные настоящие: ближайший матч, форма, таблица и новости взяты из FotMob и RSS.</p></header>
    <div class="row">${STYLES.map(s => card(...s)).join('')}</div>` });
  groups.forEach((g, i) => pages.push({ h: pageH(g.map(s => s[0])), html: `
    <header><small>Мадридиста · экраны в стиле A</small><h1>${i + 2}. ${['Эфир и матч', 'Матч, команда, календарь', 'Медиа и прогнозы'][i]}</h1></header>
    <div class="row">${g.map(s => card(...s)).join('')}</div>` }));

  const css = `
    @font-face{font-family:'Onest';font-weight:400;src:url(fonts/onest-cyrillic-400-normal.woff2)}
    @font-face{font-family:'Onest';font-weight:700;src:url(fonts/onest-cyrillic-700-normal.woff2)}
    @font-face{font-family:'Onest';font-weight:400;src:url(fonts/onest-latin-400-normal.woff2);unicode-range:U+0000-00FF}
    body{margin:0;font-family:'Onest',sans-serif;background:#E9ECF2;color:#0A1A44}
    .pg{width:${W}px;box-sizing:border-box;padding:56px 70px;break-after:page;overflow:hidden}
    header small{font-size:16px;color:#5A6684} h1{margin:10px 0 0;font-size:40px} header p{font-size:18px;color:#3A4664;max-width:900px;margin:12px 0 0}
    .row{display:flex;gap:60px;margin-top:40px;align-items:flex-start}
    figure{margin:0;width:390px} img{display:block;border-radius:28px;box-shadow:0 10px 40px rgba(10,26,68,.25)}
    figcaption{margin-top:18px;font-size:16px;line-height:1.45} figcaption b{display:block;font-size:20px;margin-bottom:4px} figcaption span{color:#3A4664}`;
  // у каждой страницы своя высота — печатаем по одной и склеиваем через отдельные PDF не нужно:
  // задаём @page под самую высокую страницу, остальные просто короче по содержимому
  const maxH = Math.max(...pages.map(p => p.h));
  const book = `<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>@page{size:${W}px ${maxH}px;margin:0}${css}</style></head><body>${pages.map(p => `<section class="pg" style="height:${maxH}px">${p.html}</section>`).join('')}</body></html>`;
  fs.writeFileSync(path.join(DIR, 'book.html'), book);
  const bp = await (await browser.newContext()).newPage();
  await bp.goto(url('book.html'));
  await bp.evaluate(() => document.fonts.ready);
  const out = path.join(DIR, 'Мадридиста — дизайн.pdf');
  await bp.pdf({ path: out, width: `${W}px`, height: `${maxH}px`, printBackground: true });
  console.log('PDF:', out, Math.round(fs.statSync(out).size / 1024), 'КБ, страниц:', pages.length);
  await browser.close();
})();
