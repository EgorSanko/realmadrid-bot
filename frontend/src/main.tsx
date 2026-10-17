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
