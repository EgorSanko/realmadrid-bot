// Реальные id для обхода: матч (прошедший и будущий), игрок, новость, видео.
const base = 'https://realmadridfan.ru';
const j = async (p) => (await fetch(base + p)).json();
const pick = (o, keys) => Object.fromEntries(keys.map((k) => [k, o?.[k]]));
const fx = await j('/api/fixtures');
const list = Array.isArray(fx) ? fx : fx.fixtures || fx.matches || fx.items || [];
console.log('fixtures keys', Object.keys(fx).slice(0, 10), 'n', list.length);
console.log('fixture sample', JSON.stringify(list[0]).slice(0, 400));
const team = await j('/api/team');
console.log('team keys', Object.keys(team));
const news = await j('/api/news');
console.log('news keys', Object.keys(news), JSON.stringify(news.items?.[0] ?? news[0] ?? news).slice(0, 300));
const vids = await j('/api/videos');
console.log('videos keys', Object.keys(vids), JSON.stringify(vids.items?.[0] ?? vids[0] ?? vids).slice(0, 300));
const home = await j('/api/home');
console.log('home keys', Object.keys(home));
