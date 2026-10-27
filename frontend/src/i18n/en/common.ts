/** Английские строки: common. Ключ — русский текст из t()/plural(), значение — перевод (подстановки {имя} те же). */
const en: Record<string, string> = {
  'Язык': 'Language',
  // ui/base — общие состояния
  'Все': 'All',
  'Повторить': 'Retry',
  'Загрузка': 'Loading',
  'Не удалось загрузить': 'Couldn’t load',
  'Проверь соединение и попробуй ещё раз': 'Check your connection and try again',
  'травма': 'injury',
  'Реал Мадрид': 'Real Madrid',
  'МСК': 'MSK',
  'матч|матча|матчей': 'match|matches',

  // ui/media, ui/playerLink
  'Голы — {team}': 'Goals — {team}',
  'Меньше голов — {team}': 'Fewer goals — {team}',
  'Больше голов — {team}': 'More goals — {team}',
  'Я': 'Me',
  '{name} — карточка игрока': '{name} — player profile',

  // lib/api, lib/apiResource, lib/auth — ошибки
  'Нет соединения': 'No connection',
  'Ответ сервера не разобрать': 'Couldn’t read the server response',
  'Данные ещё собираются — загляни через пару минут': 'Data is still being collected — check back in a couple of minutes',
  'Ошибка сервера ({status})': 'Server error ({status})',

  // lib/stream — админка
  'Сервер недоступен. Проверьте интернет и попробуйте ещё раз': 'Server unavailable. Check your internet connection and try again',
  'Админка отключена на сервере': 'Admin panel is disabled on the server',
  'Нет доступа': 'Access denied',
  'Проверьте ссылку': 'Check the link',

  // lib/linkCheck, lib/linkExpiry — ссылка трансляции
  'Вставьте ссылку на трансляцию': 'Paste the stream link',
  'Ссылка длиннее {max} символов': 'The link is longer than {max} characters',
  'В ссылке не должно быть пробелов': 'The link must not contain spaces',
  'Ссылка должна начинаться с https://': 'The link must start with https://',
  'В ссылке нет адреса сервера': 'The link has no server address',
  'Ссылка не распознана': 'Link not recognized',
  'Срок действия ссылки истёк в {until}': 'The link expired at {until}',
  'Ссылка действует до {until} — осталось меньше 30 мин': 'The link is valid until {until} — less than 30 min left',
  'Ссылка действует до {until}': 'The link is valid until {until}',

  // lib/startParam, StartParamHandler — лиги по ссылке
  'Вы вступили в лигу «{name}»': 'You joined the league “{name}”',
  'Вы уже в лиге «{name}»': 'You’re already in the league “{name}”',
  'Не удалось вступить в лигу': 'Couldn’t join the league',
};

export default en;
