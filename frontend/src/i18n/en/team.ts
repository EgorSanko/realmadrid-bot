/** Английские строки: team. Ключ — русский текст из t()/plural(), значение — перевод (подстановки {имя} те же). */
const en: Record<string, string> = {
  // экран «Команда»
  'Состав «Реала», лазарет и трансферы — Мадридиста': 'Real Madrid squad, injuries and transfers — Madridista',
  'Команда': 'Team',
  'сезон {season}': 'season {season}',
  'Данные могли устареть · обновлено в {time} МСК': 'Data may be outdated · updated at {time} MSK',
  'Лидеры и лазарет': 'Leaders and injuries',
  'Лидеры сезона': 'Season leaders',
  '{label}: {name} — карточка игрока': '{label}: {name} — player profile',
  'Лазарет': 'Injuries',
  'все здоровы': 'all fit',
  'игрок|игрока|игроков': 'player|players',
  'травма': 'injury',
  'ожидался:': 'expected:',
  'Вернулись в общую группу · {n}': 'Back in training · {n}',
  'Состав': 'Squad',
  'Тренер': 'Coach',
  'Главный тренер': 'Head coach',
  'главный тренер': 'head coach',
  'номер {n}': 'number {n}',
  'дискв.': 'susp.',
  'Трансферы': 'Transfers',
  'Пришли': 'Arrivals',
  'Ушли': 'Departures',
  'свободный агент': 'free agent',
  'из {club}': 'from {club}',
  'в {club}': 'to {club}',
  'Ещё {n}': '{n} more',

  // линии состава
  'Вратари': 'Goalkeepers',
  'Защитники': 'Defenders',
  'Полузащитники': 'Midfielders',
  'Нападающие': 'Forwards',

  // возраст, сроки возвращения, суммы трансферов (teamData)
  'год|года|лет': 'year|years',
  'срок неизвестен': 'return date unknown',
  'вернулся в общую группу': 'back in training',
  'под вопросом': 'doubtful',
  'до конца сезона': 'out for the season',
  'до {date}': 'until {date}',
  'начало': 'early',
  'середина': 'mid',
  'конец': 'late',
  'срок уточняется': 'return date TBC',
  'аренда': 'loan',
  'бесплатно': 'free',
  '€{s} млн': '€{s}m',
  '€{s} тыс.': '€{s}k',
};

export default en;
