import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, type Connect, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const DEV_IMG = path.join(ROOT, 'dev-img');
const MIME: Record<string, string> = { '.png': 'image/png', '.svg': 'image/svg+xml', '.jpg': 'image/jpeg', '.webp': 'image/webp' };

/**
 * Локальная проверка картинок. Картинки /img/* отдаёт наш сервер; здесь их нет.
 * DEV_IMG=1 — отдаём файлы из frontend/dev-img/ (в git не попадают), чего нет — 404.
 * Без DEV_IMG запросы уходят в прокси на недоступный адрес — проверка поведения при ошибке.
 */
function devImages(): Plugin {
  const handler: Connect.NextHandleFunction = (req, res, next) => {
    if (process.env.DEV_IMG !== '1' || !req.url?.startsWith('/img/')) return next();
    const rel = decodeURIComponent(req.url.split('?')[0].slice('/img/'.length));
    const file = path.resolve(DEV_IMG, rel);
    if (!file.startsWith(DEV_IMG + path.sep)) {
      res.statusCode = 400;
      return res.end();
    }
    fs.readFile(file, (err, buf) => {
      if (err) {
        res.statusCode = 404;
        return res.end();
      }
      res.setHeader('Content-Type', MIME[path.extname(file)] ?? 'application/octet-stream');
      res.setHeader('Cache-Control', 'no-store');
      res.end(buf);
    });
  };
  return {
    name: 'dev-img',
    configureServer: (s) => void s.middlewares.use(handler),
    configurePreviewServer: (s) => void s.middlewares.use(handler),
  };
}

// 127.0.0.1:1 — заведомо недоступно: картинки честно не грузятся
const proxy = {
  '/api': 'http://127.0.0.1:8000',
  '/img': 'http://127.0.0.1:1',
};

// Домен нигде не зашит: клиент ходит только по относительным путям /api и /img.
export default defineConfig({
  plugins: [react(), devImages()],
  build: {
    target: 'es2020',
    assetsInlineLimit: 0, // шрифты — отдельными файлами в /assets, не base64
  },
  server: { proxy },
  preview: { proxy },
});
