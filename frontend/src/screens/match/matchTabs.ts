/*
 * Вкладки экрана матча и их адрес.
 *  — телефон: /match/:id, /match/:id/lineups, /match/:id/stats, /match/:id/online (как было);
 *  — компьютер: /match/:id?tab=lineups … (?tab=table — «Турнир», ?tab=h2h — «Очные встречи»).
 * Читаются оба вида: ссылка с телефона открывает ту же вкладку на компьютере и наоборот.
 */

import { t, tc } from '../../lib/i18n';

export type MatchTab = 'overview' | 'lineups' | 'stats' | 'online' | 'table' | 'h2h';

/** словарь грузится до импорта приложения — t() в константе модуля можно */
export const TAB_LABEL: Record<MatchTab, string> = {
  overview: t('Обзор'),
  lineups: t('Составы'),
  stats: t('Статистика'),
  online: t('Онлайн'),
  table: tc('tab', 'Турнир'),
  h2h: t('Очные встречи'),
};

/** порядок на компьютере */
export const DESK_TABS: MatchTab[] = ['overview', 'lineups', 'stats', 'online', 'table', 'h2h'];
/** телефон: «Турнир» и личные встречи остаются в «Обзоре» */
export const MOBILE_TABS: MatchTab[] = ['overview', 'lineups', 'stats', 'online'];

const PATH_TABS: MatchTab[] = ['lineups', 'stats', 'online'];
const isTab = (s: string | null | undefined): s is MatchTab => !!s && s in TAB_LABEL;

/** Вкладка из адреса: ?tab= важнее хвоста пути; неизвестное — «Обзор». */
export function tabFromLocation(pathname: string, search = ''): MatchTab {
  const q = new URLSearchParams(search).get('tab');
  if (isTab(q)) return q;
  const m = /\/match\/[^/]+\/([a-z]+)\/?$/.exec(pathname);
  if (m && (PATH_TABS as string[]).includes(m[1])) return m[1] as MatchTab;
  return 'overview';
}

/** Адрес вкладки на компьютере: /match/:id?tab=… («Обзор» — без параметра); прочие параметры сохраняются. */
export function deskTabHref(id: string, tab: MatchTab, search = ''): string {
  const q = new URLSearchParams(search);
  if (tab === 'overview') q.delete('tab');
  else q.set('tab', tab);
  const s = q.toString();
  return `/match/${encodeURIComponent(id)}${s ? `?${s}` : ''}`;
}

/** Адрес вкладки на телефоне: хвост пути, без ?tab. */
export function mobileTabHref(id: string, tab: MatchTab, search = ''): string {
  const q = new URLSearchParams(search);
  q.delete('tab');
  const s = q.toString();
  const suffix = (PATH_TABS as string[]).includes(tab) ? `/${tab}` : '';
  return `/match/${encodeURIComponent(id)}${suffix}${s ? `?${s}` : ''}`;
}

/** Выбранная вкладка, если она есть среди показанных; иначе «Обзор». */
export function pickTab(want: MatchTab, shown: MatchTab[]): MatchTab {
  return shown.includes(want) ? want : 'overview';
}
