// Локальный прогон боевого шаблона nginx (Windows-сборка nginx 1.24, как на сервере):
//   node nginx-local.mjs <nginxDir> <distDir> <port>
// Подставляет плейсхолдеры как deploy/deploy.sh (http, HSTS-строка включена для проверки синтаксиса,
// CSP-хэши — deploy/csp-hashes.mjs), пишет <nginxDir>/conf/rmv2-test.conf. Запуск и nginx -t — снаружи.
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../../..');
const [ngx, dist, port = '8088'] = process.argv.slice(2);
const fwd = (p) => path.resolve(p).replace(/\\/g, '/');
const hashes = execFileSync(process.execPath, [path.join(root, 'deploy/csp-hashes.mjs'), path.join(dist, 'index.html')], { encoding: 'utf8' });
const cache = fwd(path.join(ngx, 'temp/rmv2img'));
mkdirSync(cache, { recursive: true });
mkdirSync(path.join(ngx, 'temp/data/avatars'), { recursive: true });
const sub = {
  LISTEN: `    listen 127.0.0.1:${port};`,
  REDIRECT: '',
  SCHEME: 'http',
  DOMAIN: '127.0.0.1', // Host запроса без порта — сервер сайта, а не блок www-редиректа
  WEBROOT: fwd(dist),
  API_PORT: '9', // /api/* в проверке перехватывает Playwright и шлёт на боевой сервер
  IMGROOT: fwd(path.join(root, 'deploy/img')),
  DATAROOT: fwd(path.join(ngx, 'temp/data')),
  HSTS: '        add_header Strict-Transport-Security "max-age=31536000" always;',
  CSP_SCRIPT_HASHES: hashes,
};
let site = readFileSync(path.join(root, 'deploy/nginx.conf.template'), 'utf8');
for (const [k, v] of Object.entries(sub)) site = site.split(`{{${k}}}`).join(v);
// Windows-сборка nginx не знает disable_symlinks (на Linux-сервере он есть)
site = site.replace(/^\s*disable_symlinks on;\r?\n/m, '');
const left = site.match(/\{\{[A-Z_]+\}\}/g);
if (left) throw new Error('не подставлено: ' + left.join(','));
const img = readFileSync(path.join(root, 'deploy/nginx-img-cache.conf'), 'utf8').replace('/var/cache/nginx/rmv2img', cache);
const conf = `worker_processes 1;
error_log logs/rmv2-error.log;
pid logs/rmv2.pid;
events { worker_connections 256; }
http {
  include mime.types;
  default_type application/octet-stream;
  access_log logs/rmv2-access.log;
  ${img}
  ${site}
}
`;
writeFileSync(path.join(ngx, 'conf/rmv2-test.conf'), conf);
console.log('ok', path.join(ngx, 'conf/rmv2-test.conf'), 'hashes:', hashes);
