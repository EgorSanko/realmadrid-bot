import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/fonts.css';
import './styles/tokens.css';
import './styles/app.css';
import './styles/desktop.css';
import { App } from './App';
import { telegramReady } from './telegram';
import { authHeaders, bootstrapAuth, telegramInitData } from './lib/auth';
import { initShell, isNativeApp } from './lib/shell';
import { detectPlatform, reportVisit } from './lib/visit';

/** Отрисовка приложения — после того как main.tsx выбрал язык и загрузил словарь. */
export async function start(inTelegram: boolean) {
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

