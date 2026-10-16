import { useEffect, useState } from 'react';
import { backButton, isTMA, openLink } from '@tma.js/sdk-react';

const inTma = () => {
  try {
    return isTMA();
  } catch {
    return false;
  }
};

/**
 * Нативная кнопка «Назад» Telegram. Возвращает true, если она показана —
 * тогда своя кнопка в шапке не нужна. В браузере (и если метод недоступен) — false.
 */
export function useTelegramBackButton(onBack: () => void): boolean {
  const [native, setNative] = useState(false);

  useEffect(() => {
    if (!inTma()) return;
    let off: (() => void) | undefined;
    try {
      if (!backButton.isMounted()) backButton.mount.ifAvailable();
      if (backButton.show.isAvailable() && backButton.onClick.isAvailable()) {
        backButton.show();
        off = backButton.onClick(onBack);
        setNative(true);
      }
    } catch (e) {
      console.warn('[tma] кнопка «Назад» недоступна', e);
    }
    return () => {
      off?.();
      try {
        backButton.hide.ifAvailable();
      } catch {
        /* мини-апп уже закрывается */
      }
      setNative(false);
    };
  }, [onBack]);

  return native;
}

/**
 * Открыть внешнюю ссылку: в Telegram — через openLink (во внешнем браузере / встроенном просмотрщике),
 * иначе — вернуть false, и сработает обычная ссылка с target=_blank.
 */
export function openExternal(url: string): boolean {
  if (!inTma()) return false;
  try {
    if (openLink.isAvailable()) {
      openLink(url);
      return true;
    }
  } catch (e) {
    console.warn('[tma] openLink не сработал', e);
  }
  return false;
}
