// Vite multi-target build for RM frontend (Block 3 audit 2026-05-11).
//
// Two modes share src/ but produce different bundles via .env.<mode>:
//   npm run build:webapp  → dist/webapp/ → /root/realmadrid-bot-fixed/static/
//   npm run build:site    → dist/site/   → /var/www/realmadrid-site/
//
// Entry HTML differs (TG SDK loaded only in webapp), but src/ is shared.
// VITE_FEATURE_* flags tree-shake disabled features (esbuild constant fold).

import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { copyFileSync } from 'fs';

const __dirname = dirname(fileURLToPath(import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '');

  // Copy mode-specific index.html → frontend/index.html so Vite finds it at root.
  // This runs at config-load time (before build).
  copyFileSync(
    resolve(__dirname, `public/${mode}/index.html`),
    resolve(__dirname, 'index.html'),
  );

  return {
    plugins: [react()],
    publicDir: false,
    resolve: {
      alias: {
        '@': resolve(__dirname, './src'),
      },
    },
    build: {
      outDir: `dist/${mode}`,
      emptyOutDir: true,
      minify: 'esbuild',
      target: 'es2018',
      rollupOptions: {
        output: {
          entryFileNames: 'app.js',
          chunkFileNames: 'chunks/[name]-[hash].js',
          assetFileNames: 'assets/[name]-[hash][extname]',
        },
      },
    },
    server: {
      port: mode === 'webapp' ? 5173 : 5174,
      proxy: {
        '/api': {
          target: env.VITE_API_BASE || 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
  };
});
