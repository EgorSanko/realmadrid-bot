/**
 * «Онлайн» → «Все комментарии (EN)»: записи текстовой трансляции Opta (через FotMob) — оригинал на английском,
 * заголовки типов — наши (RU / EN). Чистые функции — их проверяет `node --test`; рантайм-импорт — только lib/i18n.
 */
import { t } from '../../lib/i18n';
import type { ApiCommentaryItem, CommentaryType, Side } from '../../api/match';

const TITLE: Partial<Record<CommentaryType, string>> = {
  goal: 'Гол!',
  own_goal: 'Автогол',
  assist: 'Голевая передача',
  yellow: 'Жёлтая карточка',
  second_yellow: 'Вторая жёлтая',
  red: 'Красная карточка',
  sub: 'Замена',
  var: 'VAR',
  chance: 'Опасный момент',
  team_news: 'Составы и новости',
  summary: 'Итоги тайма',
  penalty_missed: 'Пенальти не забит',
  penalty_saved: 'Пенальти отражён',
  penalty_goal: 'Гол с пенальти',
};

/** Текст длиннее — сворачиваем до нескольких строк с кнопкой «ещё». */
export const LONG_TEXT = 260;

export interface CommentaryRow {
  key: string;
  type: CommentaryType;
  /** «37′», «45+3′»; до матча и итоги тайма — без минуты */
  minute?: string;
  /** по-русски; у обычного комментария — нет */
  title?: string;
  text: string;
  long: boolean;
  side?: Side;
  players: Array<{ id?: number; name: string }>;
  /** подсветка: гол — золотая полоса слева */
  goal: boolean;
}

export function commentaryRows(items: ApiCommentaryItem[]): CommentaryRow[] {
  return items.map((x) => ({
    key: x.id,
    type: x.type,
    minute: x.minute != null && x.minute > 0 ? (x.added ? `${x.minute}+${x.added}′` : `${x.minute}′`) : undefined,
    title: TITLE[x.type] ? t(TITLE[x.type] as string) : undefined,
    text: x.text,
    long: x.text.length > LONG_TEXT,
    side: x.side ?? undefined,
    players: x.players.map((p) => ({ id: p.id != null && p.id > 0 && p.photo ? p.id : undefined, name: p.name })),
    goal: x.type === 'goal' || x.type === 'own_goal' || x.type === 'penalty_goal',
  }));
}

/**
 * Какие записи новые с прошлого показа (для плавного появления сверху). Первый показ — ничего не новое.
 * Возвращает новые ключи и множество «уже видели» для следующего раза.
 */
export function freshKeys(seen: Set<string> | null, keys: string[]): { fresh: Set<string>; seen: Set<string> } {
  const next = new Set(keys);
  if (!seen) return { fresh: new Set(), seen: next };
  return { fresh: new Set(keys.filter((k) => !seen.has(k))), seen: next };
}
