/**
 * Официальный Telegram Login Widget — единственное внешнее подключение приложения.
 * Скрипт грузится ТОЛЬКО по нажатию «Войти через Telegram» (не на старте, не в бандле):
 * он рисует кнопку Telegram (iframe oauth.telegram.org), после подтверждения вызывает data-onauth.
 * Не загрузился за 8 с (telegram.org в России бывает недоступен) — ошибка, показываем запасной путь.
 * Для работы владелец бота должен выполнить в @BotFather /setdomain → realmadridfan.ru.
 */

export const WIDGET_SRC = 'https://telegram.org/js/telegram-widget.js?22';
export const WIDGET_TIMEOUT_MS = 8000;
const CALLBACK = '__rmTelegramAuth';

export interface WidgetUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  auth_date: number;
  hash: string;
}

type Win = Window & { [CALLBACK]?: (u: WidgetUser) => void };

/**
 * Вставить виджет в `container`. Promise выполняется, когда скрипт загрузился (кнопка появится сама),
 * и отклоняется при ошибке загрузки или по таймауту. `onAuth` — данные пользователя для /api/auth/telegram.
 * Возвращает и функцию отмены (убрать скрипт и обработчик).
 */
export function mountTelegramWidget(
  container: HTMLElement,
  bot: string,
  onAuth: (u: WidgetUser) => void,
  timeoutMs = WIDGET_TIMEOUT_MS,
): { loaded: Promise<void>; cancel: () => void } {
  const w = window as Win;
  w[CALLBACK] = (u) => onAuth(u);
  const s = document.createElement('script');
  s.async = true;
  s.src = WIDGET_SRC;
  s.setAttribute('data-telegram-login', bot);
  s.setAttribute('data-size', 'large');
  s.setAttribute('data-radius', '14');
  s.setAttribute('data-userpic', 'false');
  s.setAttribute('data-lang', 'ru');
  s.setAttribute('data-onauth', `${CALLBACK}(user)`);
  let timer = 0;
  let settle: { ok: () => void; fail: (e: Error) => void } | null = null;
  const loaded = new Promise<void>((resolve, reject) => {
    settle = {
      ok: () => {
        window.clearTimeout(timer);
        settle = null;
        resolve();
      },
      fail: (e) => {
        window.clearTimeout(timer);
        settle = null;
        reject(e);
      },
    };
    timer = window.setTimeout(() => settle?.fail(new Error('timeout')), timeoutMs);
    s.onload = () => settle?.ok();
    s.onerror = () => settle?.fail(new Error('network'));
  });
  container.replaceChildren(s);
  return {
    loaded,
    cancel: () => {
      window.clearTimeout(timer);
      settle = null;
      s.onload = s.onerror = null;
      container.replaceChildren();
      if (w[CALLBACK]) delete w[CALLBACK];
    },
  };
}
