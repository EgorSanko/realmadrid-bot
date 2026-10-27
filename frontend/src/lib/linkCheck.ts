/** Проверка ссылки в админке — те же правила, что на сервере (backend/app/stream.py). */
import { t } from './i18n';

export const URL_MAX = 2000;

export function linkError(raw: string): string | null {
  const url = raw.trim();
  if (!url) return t('Вставьте ссылку на трансляцию');
  if (url.length > URL_MAX) return t('Ссылка длиннее {max} символов', { max: URL_MAX });
  if (/\s/.test(url)) return t('В ссылке не должно быть пробелов');
  if (!/^https?:\/\//i.test(url)) return t('Ссылка должна начинаться с https://');
  try {
    if (!new URL(url).hostname) return t('В ссылке нет адреса сервера');
  } catch {
    return t('Ссылка не распознана');
  }
  return null;
}

/** http-поток на https-странице браузер заблокирует (смешанный контент). */
export function isMixedContent(raw: string, pageProtocol: string): boolean {
  return pageProtocol === 'https:' && /^http:\/\//i.test(raw.trim());
}
