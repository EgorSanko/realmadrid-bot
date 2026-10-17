// Статусы и заголовки локального nginx (шаблон deploy/nginx.conf.template): node nginx-check.mjs [base]
const base = process.argv[2] || 'http://127.0.0.1:8088';
const cases = [
  ['/', 200], ['/index.html', 200], ['/matches', 200], ['/matches?tab=table', 200], ['/team', 200], ['/media', 200],
  ['/predict', 200], ['/profile', 200], ['/admin', 200], ['/games', 200], ['/games/quiz', 200], ['/games/penalty', 200],
  ['/match/6106274', 200], ['/match/6106274/lineups', 200], ['/match/6106274/stats', 200], ['/player/170323', 200],
  ['/news/0123456789ab', 200], ['/video/EoNQQxVIW-Q', 200], ['/matches/', 200],
  ['/no-such-page', 404], ['/team/extra', 404], ['/wp-login.php', 404], ['/assets/nope.js', 404, 'plain'],
  ['/robots.txt', 200], ['/sitemap.xml', 200], ['/manifest.webmanifest', 200], ['/favicon.ico', 200], ['/og.png', 200],
];
const want = ['content-security-policy', 'permissions-policy', 'strict-transport-security', 'x-content-type-options', 'referrer-policy', 'cache-control', 'content-type'];
let bad = 0;
for (const [p, code, plain] of cases) {
  const r = await fetch(base + p, { headers: { host: 'localhost' }, redirect: 'manual' });
  const body = await r.text();
  const html = (r.headers.get('content-type') || '').includes('text/html');
  const isApp = html && body.includes('id="root"');
  const ok = r.status === code && (plain ? !isApp : !html || isApp);
  if (!ok) bad++;
  const h = Object.fromEntries(want.map((k) => [k, r.headers.get(k)]));
  console.log(ok ? 'ok ' : 'BAD', r.status, p, html ? `app=${isApp} csp=${!!h['content-security-policy']} pp=${!!h['permissions-policy']} hsts=${!!h['strict-transport-security']} nosniff=${!!h['x-content-type-options']} cache=${h['cache-control']}` : h['content-type']);
}
const r = await fetch(base + '/');
console.log('\nCSP /:', r.headers.get('content-security-policy'));
console.log(bad ? `\n${bad} BAD` : '\nall ok');
