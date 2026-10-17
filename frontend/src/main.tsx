import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/fonts.css';
import './styles/tokens.css';
import './styles/app.css';
import { App } from './App';
import { initTelegram, telegramReady } from './telegram';
import { bootstrapAuth } from './lib/auth';

async function start() {
  const inTelegram = await initTelegram();
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
