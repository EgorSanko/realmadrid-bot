/**
 * Параметр запуска мини-аппа `startapp` (ссылки вида t.me/<бот>?startapp=…):
 *   profile        → /profile
 *   league_<код>   → вступить в лигу и открыть профиль с сообщением
 *   match_<id>     → /match/<id>
 * Чистые функции — без SDK, проверяются node --test.
 */
export type StartAction =
  | { kind: 'profile' }
  | { kind: 'league'; code: string }
  | { kind: 'match'; id: string };

export function parseStartParam(raw: string | null | undefined): StartAction | null {
  if (!raw) return null;
  const s = raw.trim();
  if (s === 'profile') return { kind: 'profile' };
  let m = /^league_([A-Za-z0-9]{4,32})$/.exec(s);
  if (m) return { kind: 'league', code: m[1].toUpperCase() };
  m = /^match_([1-9]\d{0,11})$/.exec(s);
  if (m) return { kind: 'match', id: m[1] };
  return null;
}

/** Ссылка-приглашение в лигу: от сервера, иначе собираем сами по имени бота. */
export function inviteLink(code: string, serverLink: string | null | undefined, bot: string): string {
  return serverLink || `https://t.me/${bot}?startapp=league_${code}`;
}

/** Текст сообщения после вступления по ссылке. */
export function joinedMessage(name: string, joined: boolean): string {
  return joined ? `Вы вступили в лигу «${name}»` : `Вы уже в лиге «${name}»`;
}
