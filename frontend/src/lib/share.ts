import { shareURL } from '@tma.js/sdk-react';
import { inMiniApp } from './auth';

/** Скопировать текст: Clipboard API, иначе — старый способ через скрытое поле. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } catch {
      ok = false;
    }
    ta.remove();
    return ok;
  }
}

/** Поделиться: в Telegram — shareURL из SDK; в браузере — системное меню; иначе копируем. */
export async function shareLink(url: string, text: string): Promise<'shared' | 'copied' | 'failed'> {
  if (inMiniApp()) {
    try {
      if (shareURL.isAvailable()) {
        shareURL(url, text);
        return 'shared';
      }
    } catch (e) {
      console.warn('[tma] shareURL недоступен', e);
    }
  }
  if (typeof navigator.share === 'function') {
    try {
      await navigator.share({ url, text });
      return 'shared';
    } catch (e) {
      if ((e as Error).name === 'AbortError') return 'shared';
    }
  }
  return (await copyText(url)) ? 'copied' : 'failed';
}
