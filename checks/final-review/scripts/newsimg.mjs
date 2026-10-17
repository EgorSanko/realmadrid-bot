// Картинки новостей: какие отдаются заглушкой (X-Img-Fallback) — пустые квадраты в ленте.
const base = 'https://realmadridfan.ru';
const news = await (await fetch(base + '/api/news')).json();
let blank = 0, ok = 0, none = 0;
for (const it of news.items) {
  const src = it.image || it.img || it.thumb;
  if (!src) { none++; continue; }
  const r = await fetch(base + src);
  const fb = r.headers.get('x-img-fallback');
  const len = (await r.arrayBuffer()).byteLength;
  if (fb) { blank++; console.log('fallback', fb, r.status, len, src.slice(0, 110), '|', it.source); } else ok++;
}
console.log({ total: news.items.length, ok, blank, none, keys: Object.keys(news.items[0]) });
