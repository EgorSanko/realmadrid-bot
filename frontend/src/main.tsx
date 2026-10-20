import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/fonts.css';
import './styles/tokens.css';
import './styles/app.css';
import './styles/desktop.css';
import { App } from './App';
import { initTelegram, telegramReady } from './telegram';
import { authHeaders, bootstrapAuth, telegramInitData } from './lib/auth';
import { initShell, isNativeApp } from './lib/shell';
import { detectPlatform, reportVisit } from './lib/visit';

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
  const authReady = bootstrapAuth();
  // счётчик людей (раз в день, анонимно): после входа — чтобы связать устройство с аккаунтом, но не дольше 4 с
  void Promise.race([authReady, new Promise((r) => setTimeout(r, 4000))])
    .catch(() => undefined)
    .then(() => reportVisit(detectPlatform(!!telegramInitData(), isNativeApp()), authHeaders()));
  // заставка: пока собирается эмблема, не рисуем — первая отрисовка блокирует главный поток и рвёт её анимацию
  const splash = (window as { __rmSplash?: Promise<void> }).__rmSplash;
  if (splash) await Promise.race([splash, new Promise((r) => setTimeout(r, 3000))]);
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  if (inTelegram) requestAnimationFrame(() => telegramReady());
}

void start();
