// src/lib/format.js — small formatting helpers used across pages.

const RU_MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                   'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

export function formatNewsDate(raw) {
  // Backend already produces strings like "11 мая 2026" or "вчера".
  // Pass through if already formatted; format only if ISO-like.
  if (!raw) return '';
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
    const d = new Date(raw);
    if (!isNaN(d)) {
      return `${d.getDate()} ${RU_MONTHS[d.getMonth()]} ${d.getFullYear()}`;
    }
  }
  return raw;
}

export function formatOdds(n) {
  if (n == null) return '—';
  return n.toFixed(2);
}
