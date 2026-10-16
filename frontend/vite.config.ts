import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Домен нигде не зашит: клиент ходит только по относительному пути /api.
export default defineConfig({
  plugins: [react()],
  build: {
    target: 'es2020',
    assetsInlineLimit: 0, // шрифты — отдельными файлами в /assets, не base64
    // hls.js (~575 kB, ~180 kB gzip) — отдельный ленивый чанк, грузится только при включённом эфире
    chunkSizeWarningLimit: 600,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
});
