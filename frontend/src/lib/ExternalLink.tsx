import type { MouseEvent, ReactNode } from 'react';
import { openLink } from '@tma.js/sdk-react';

/** Мы внутри Telegram Mini App — initTelegram() ставит класс `tma` на <html>. */
function inTelegram(): boolean {
  return typeof document !== 'undefined' && document.documentElement.classList.contains('tma');
}

/**
 * Открыть внешнюю ссылку (новость, видео). В Telegram — через openLink из SDK (системный браузер
 * или встроенный просмотр Telegram), в браузере — обычной ссылкой в новой вкладке.
 */
export function openExternal(url: string, e?: MouseEvent): void {
  if (!inTelegram()) return; // браузер: сработает сам <a target="_blank">
  try {
    if (openLink.isAvailable()) {
      e?.preventDefault();
      openLink(url);
    }
  } catch {
    /* не вышло через SDK — остаётся обычный переход по ссылке */
  }
}

export function ExternalLink({
  href,
  children,
  className,
  ariaLabel,
}: {
  href: string;
  children: ReactNode;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <a
      className={className ? `ext-link ${className}` : 'ext-link'}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={ariaLabel}
      onClick={(e) => openExternal(href, e)}
    >
      {children}
    </a>
  );
}
