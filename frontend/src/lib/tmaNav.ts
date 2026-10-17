import { useEffect, useRef, useState } from 'react';
import { backButton, isTMA, openLink } from '@tma.js/sdk-react';

const inTma = () => {
  try {
    return isTMA();
  } catch {
    return false;
  }
};

/*
 * Кнопка одна на всё приложение, а экранов с «Назад» может быть несколько одновременно
 * (карточка игрока открыта поверх экрана матча). Поэтому — стек: срабатывает только верхний
 * обработчик, кнопка прячется, когда стек пуст.
 */
const stack: Array<{ cb: () => void }> = [];
let unsubscribe: (() => void) | undefined;

function syncButton(): boolean {
  try {
    if (stack.length === 0) {
      unsubscribe?.();
      unsubscribe = undefined;
      backButton.hide.ifAvailable();
      return false;
    }
    if (!backButton.isMounted()) backButton.mount.ifAvailable();
    if (!backButton.show.isAvailable() || !backButton.onClick.isAvailable()) return false;
    backButton.show();
    if (!unsubscribe) unsubscribe = backButton.onClick(() => stack[stack.length - 1]?.cb());
    return true;
  } catch (e) {
    console.warn('[tma] кнопка «Назад» недоступна', e);
    return false;
  }
}

/**
 * Нативная кнопка «Назад» Telegram. Возвращает true, если она показана —
 * тогда своя кнопка в шапке не нужна. В браузере (и если метод недоступен) — false.
 */
export function useTelegramBackButton(onBack: () => void): boolean {
  const [native, setNative] = useState(false);
  const ref = useRef(onBack);
  ref.current = onBack;

  useEffect(() => {
    if (!inTma()) return;
    const entry = { cb: () => ref.current() };
    stack.push(entry);
    setNative(syncButton());
    return () => {
      const i = stack.indexOf(entry);
      if (i >= 0) stack.splice(i, 1);
      syncButton();
      setNative(false);
    };
  }, []);

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
