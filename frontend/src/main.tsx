import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/fonts.css';
import './styles/tokens.css';
import './styles/app.css';
import { App } from './App';
import { initTelegram, telegramReady } from './telegram';

async function start() {
  const inTelegram = await initTelegram();
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  if (inTelegram) requestAnimationFrame(() => telegramReady());
}

void start();
