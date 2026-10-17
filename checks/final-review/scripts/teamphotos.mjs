// Фото в «Команде»: лидеры и лазарет — что в API и что отдаёт /img/player/*.
const base = 'https://realmadridfan.ru';
const t = await (await fetch(base + '/api/team')).json();
console.log('leaders sample', JSON.stringify(t.leaders).slice(0, 400));
console.log('injuries sample', JSON.stringify(t.injuries).slice(0, 400));
const ids = new Set();
const walk = (v) => { if (Array.isArray(v)) v.forEach(walk); else if (v && typeof v === 'object') { if (v.player && typeof v.player.id === 'number') ids.add(v.player.id); if (typeof v.id === 'number' && 'photo' in v) ids.add(v.id); Object.values(v).forEach(walk); } };
walk([t.leaders, t.injuries]);
for (const id of ids) {
  const r = await fetch(`${base}/img/player/${id}.png`);
  const b = await r.arrayBuffer();
  console.log(id, r.status, r.headers.get('content-type'), b.byteLength, r.headers.get('x-img-fallback') || '');
}
