/** Английские строки: shell. Ключ — русский текст из t()/plural(), значение — перевод (подстановки {имя} те же). */
const en: Record<string, string> = {
  // sections.tsx — разделы меню
  'Главная': 'Home',
  'Матчи': 'Matches',
  'Команда': 'Team',
  'Медиа': 'Media',
  'Игры': 'Games',
  'Ближайший матч, обратный отсчёт и главное за день.': 'Next match, countdown and the day’s top stories.',
  'Календарь, результаты и онлайн матчей.': 'Fixtures, results and live matches.',
  'Состав и статистика игроков.': 'Squad and player stats.',
  'Видео и новости клуба.': 'Club videos and news.',
  'Прогнозы на матчи, викторина и пенальти.': 'Match predictions, quiz and penalties.',

  // шапка, подвал, нижнее меню
  'Разделы': 'Sections',
  'Разделы сайта': 'Site sections',
  'МАДРИДИСТА': 'MADRIDISTA',
  'Мадридиста': 'Madridista',
  'Real Madrid · фан-приложение': 'Real Madrid · fan app',
  'Мадридиста — {title}': 'Madridista — {title}',
  'Мадридиста — на главную': 'Madridista — go to home',
  'В ЭФИРЕ': 'LIVE',
  'Идёт эфир — смотреть на главной': 'Live now — watch on the home page',
  'Профиль': 'Profile',
  'Профиль: {name}': 'Profile: {name}',
  'Профиль и вход': 'Profile and sign-in',
  'Открыть в Telegram': 'Open in Telegram',
  'Войти через Telegram': 'Log in with Telegram',
  'Вход через Telegram': 'Log in with Telegram',
  'Прогнозы, рейтинг и лиги с друзьями — после входа через Telegram. Пароль не нужен.':
    'Predictions, leaderboards and leagues with friends — after signing in with Telegram. No password needed.',
  'Неофициальный фан-проект, не связан с Real Madrid CF. Данные: FotMob, SofaScore, ESPN; новости: Чемпионат, Спорт-Экспресс, Sports.ru.':
    'Unofficial fan project, not affiliated with Real Madrid CF. Data: FotMob, SofaScore, ESPN; news: Championat, Sport-Express, Sports.ru.',
  'Политика конфиденциальности': 'Privacy policy',
  'Условия': 'Terms',

  // трансляция и плеер
  'Трансляция': 'Live stream',
  'Трансляция: {title}': 'Live stream: {title}',
  'Трансляция появится здесь': 'The stream will appear here',
  'Эфир включится перед стартовым свистком': 'The broadcast starts just before kick-off',
  'Включить звук': 'Unmute',
  'Выключить звук': 'Mute',
  'Загрузка трансляции': 'Loading stream',
  'Смотреть': 'Play',
  'Пауза': 'Pause',
  'Не удалось загрузить трансляцию': 'Couldn’t load the stream',
  'Трансляция закончилась': 'The stream has ended',
  'Громкость': 'Volume',
  'Свернуть': 'Exit full screen',
  'На весь экран': 'Full screen',

  // анимация гола
  'Соперник': 'Opponent',
  'Пропустили': 'Conceded',
  'Пропустили: {by}': 'Conceded: {by}',
  'Гол! {who}': 'Goal! {who}',
  'ГОЛ!': 'GOAL!',

  // lib/seo — описания страниц
  'Мадридиста — фан-приложение «Реала»: ближайший матч с отсчётом, онлайн-трансляции, календарь и таблица Ла Лиги, состав, новости и видео, прогнозы на матчи, викторина и пенальти.':
    'Madridista — a Real Madrid fan app: next match with a countdown, live streams, LaLiga fixtures and table, squad, news and videos, match predictions, a quiz and penalties.',
  'Календарь и результаты матчей «Реала» в Ла Лиге и Лиге чемпионов, турнирные таблицы с текущим местом команды.':
    'Real Madrid fixtures and results in LaLiga and the Champions League, league tables with the team’s current position.',
  'Матч «Реала»: счёт и хронология, стартовые составы на поле, статистика, лучшие игроки и обзор.':
    'Real Madrid match: score and timeline, starting lineups on the pitch, stats, top players and highlights.',
  'Состав «Реала» сезона: игроки по линиям, лидеры по голам, передачам и оценкам, лазарет и трансферы.':
    'Real Madrid’s squad this season: players by position, top scorers, assists and ratings, injuries and transfers.',
  'Карточка игрока «Реала»: статистика сезона, последние матчи, карьера и травмы.':
    'Real Madrid player profile: season stats, recent matches, career and injuries.',
  'Свежие новости о «Реале» из Чемпионата, Спорт-Экспресса и Sports.ru, обзоры матчей и видео клуба.':
    'Latest Real Madrid news from Championat, Sport-Express and Sports.ru, match highlights and club videos.',
  'Новость о «Реале» — текст целиком внутри приложения, со ссылкой на источник.':
    'Real Madrid news — the full story inside the app, with a link to the source.',
  'Видео «Реала» внутри приложения: обзоры матчей, голы и ролики официального канала клуба.':
    'Real Madrid videos inside the app: match highlights, goals and clips from the club’s official channel.',
  'Угадывай счёт матчей «Реала» и первого бомбардира, набирай очки, соревнуйся в рейтинге и лигах с друзьями.':
    'Predict Real Madrid scores and the first goalscorer, earn points, compete on the leaderboard and in leagues with friends.',
  'Серия пенальти в стиле «Реала»: выбери угол, обыграй вратаря и соперника, попади в рейтинг недели.':
    'A Real Madrid penalty shootout: pick your corner, beat the keeper and your opponent, make the weekly leaderboard.',
  'Викторина о «Реале»: 4 уровня сложности, 15 секунд на вопрос, серии и множители, рейтинг недели.':
    'Real Madrid quiz: 4 difficulty levels, 15 seconds per question, streaks and multipliers, weekly leaderboard.',
  'Политика конфиденциальности «Мадридисты»: какие данные хранятся после входа через Telegram, зачем, сколько и как удалить аккаунт.':
    'Madridista privacy policy: what data is stored after signing in with Telegram, why, for how long and how to delete your account.',
  'Условия использования «Мадридисты» — бесплатного неофициального фан-приложения о «Реале»: без ставок, платежей и рекламы.':
    'Terms of use for Madridista — a free, unofficial Real Madrid fan app: no betting, payments or ads.',
  'Профиль болельщика: очки за прогнозы, история прогнозов и лиги с друзьями.':
    'Fan profile: prediction points, prediction history and leagues with friends.',
};

export default en;
