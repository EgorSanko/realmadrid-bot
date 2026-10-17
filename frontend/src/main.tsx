import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/fonts.css';
import './styles/tokens.css';
import './styles/app.css';
import './styles/desktop.css';
import { App } from './App';
import { initTelegram, telegramReady } from './telegram';
import { bootstrapAuth } from './lib/auth';
import { initShell } from './lib/shell';

// После выкладки старые чанки удаляются: вкладка (или мини-апп), открытая до неё, не найдёт ленивый чанк
// экрана и показала бы пустоту. Перезагружаемся на свежий index.html — не чаще раза в 30 с, без петли.
window.addEventListener('vite:preloadError', (e) => {
  let last = 0;
  try {
    last = Number(sessionStorage.getItem('rmChunkReload') || 0);
    sessionStorage.setItem('rmChunkReload', String(Date.now()));
  } catch {
    return;
  }
  if (Date.now() - last < 30_000) return;
  e.preventDefault();
  window.location.reload();
});

async function start() {
  const inTelegram = await initTelegram();
  // оболочка: мини-апп или сайт (на сайте от 1024 px — десктопная раскладка)
  initShell(inTelegram);
  // вход не задерживает отрисовку: в мини-аппе — тихо по initData, на сайте — /api/auth/me по cookie
  void bootstrapAuth();
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  if (inTelegram) requestAnimationFrame(() => telegramReady());
}

void start();
