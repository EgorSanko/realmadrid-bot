/** Проверка ссылки в админке — те же правила, что на сервере (backend/app/stream.py). */
export const URL_MAX = 2000;

export function linkError(raw: string): string | null {
  const url = raw.trim();
  if (!url) return 'Вставьте ссылку на трансляцию';
  if (url.length > URL_MAX) return `Ссылка длиннее ${URL_MAX} символов`;
  if (/\s/.test(url)) return 'В ссылке не должно быть пробелов';
  if (!/^https?:\/\//i.test(url)) return 'Ссылка должна начинаться с https://';
  try {
    if (!new URL(url).hostname) return 'В ссылке нет адреса сервера';
  } catch {
    return 'Ссылка не распознана';
  }
  return null;
}

/** http-поток на https-странице браузер заблокирует (смешанный контент). */
export function isMixedContent(raw: string, pageProtocol: string): boolean {
  return pageProtocol === 'https:' && /^http:\/\//i.test(raw.trim());
}
