// Заголовки ответа боевого сервера: node checks/final-review/scripts/headers.mjs [base]
const base = process.argv[2] || 'https://realmadridfan.ru';
const paths = ['/', '/index.html', '/matches', '/nonexistent-page', '/api/health', '/api/nonexistent', '/og.png', '/manifest.webmanifest', '/favicon.ico', '/robots.txt', '/sitemap.xml'];
const want = ['content-security-policy', 'x-content-type-options', 'referrer-policy', 'strict-transport-security', 'permissions-policy', 'x-frame-options', 'cache-control', 'content-type', 'server'];
for (const u of paths) {
  const r = await fetch(base + u, { redirect: 'manual' });
  const h = want.map((k) => `${k}: ${r.headers.get(k) ?? '—'}`).join('\n  ');
  console.log('==', u, r.status, '\n  ' + h);
}
