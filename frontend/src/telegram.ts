import {
  init,
  isTMA,
  miniApp,
  swipeBehavior,
  themeParams,
  viewport,
} from '@tma.js/sdk-react';

const BG = '#06070B';
const NAV_BG = '#0B0D14';

/**
 * Инициализация Telegram Mini App.
 * В обычном браузере (isTMA() === false) ничего не делает — приложение работает без SDK.
 * Внешних скриптов не грузит: SDK общается с Telegram через postMessage / WebView-мост.
 */
export async function initTelegram(): Promise<boolean> {
  if (!isTMA()) return false;

  try {
    init();

    themeParams.mount.ifAvailable();
    miniApp.mount.ifAvailable();
    miniApp.setHeaderColor.ifAvailable(BG);
    miniApp.setBgColor.ifAvailable(BG);
    miniApp.setBottomBarColor.ifAvailable(NAV_BG);

    // чтобы вертикальный скролл не сворачивал мини-апп
    swipeBehavior.mount.ifAvailable();
    swipeBehavior.disableVertical.ifAvailable();

    if (viewport.mount.isAvailable()) {
      await viewport.mount();
      viewport.bindCssVars.ifAvailable(); // --tg-viewport-*safe-area-inset-*
      viewport.expand.ifAvailable();
    }

    document.documentElement.classList.add('tma');
    return true;
  } catch (err) {
    console.warn('[tma] инициализация не удалась, работаем как в браузере', err);
    return false;
  }
}

/** Сообщить Telegram, что интерфейс отрисован (убирает плейсхолдер загрузки). */
export function telegramReady(): void {
  if (miniApp.ready.isAvailable()) miniApp.ready();
}
