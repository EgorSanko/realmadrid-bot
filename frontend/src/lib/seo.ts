// Мета страниц для поиска: описание и канонический адрес по пути. Импорт — только i18n (его тоже гоняет node --test).
import { t } from './i18n';

export const SITE_ORIGIN = 'https://realmadridfan.ru';

const DEFAULT_DESC = () =>
  t('Мадридиста — фан-приложение «Реала»: ближайший матч с отсчётом, онлайн-трансляции, календарь и таблица Ла Лиги, состав, новости и видео, прогнозы на матчи, викторина и пенальти.');

/** Описание страницы по адресу. Для конкретных матчей и новостей — общее описание раздела. */
export function descriptionFor(pathname: string): string {
  if (pathname === '/') return DEFAULT_DESC();
  if (pathname.startsWith('/matches'))
    return t('Календарь и результаты матчей «Реала» в Ла Лиге и Лиге чемпионов, турнирные таблицы с текущим местом команды.');
  if (pathname.startsWith('/match/'))
    return t('Матч «Реала»: счёт и хронология, стартовые составы на поле, статистика, лучшие игроки и обзор.');
  if (pathname.startsWith('/team'))
    return t('Состав «Реала» сезона: игроки по линиям, лидеры по голам, передачам и оценкам, лазарет и трансферы.');
  if (pathname.startsWith('/player/')) return t('Карточка игрока «Реала»: статистика сезона, последние матчи, карьера и травмы.');
  if (pathname.startsWith('/media')) return t('Свежие новости о «Реале» из Чемпионата, Спорт-Экспресса и Sports.ru, обзоры матчей и видео клуба.');
  if (pathname.startsWith('/news/')) return t('Новость о «Реале» — текст целиком внутри приложения, со ссылкой на источник.');
  if (pathname.startsWith('/video/')) return t('Видео «Реала» внутри приложения: обзоры матчей, голы и ролики официального канала клуба.');
  if (pathname.startsWith('/predict'))
    return t('Угадывай счёт матчей «Реала» и первого бомбардира, набирай очки, соревнуйся в рейтинге и лигах с друзьями.');
  if (pathname.startsWith('/games/penalty'))
    return t('Серия пенальти в стиле «Реала»: выбери угол, обыграй вратаря и соперника, попади в рейтинг недели.');
  if (pathname.startsWith('/games'))
    return t('Викторина о «Реале»: 4 уровня сложности, 15 секунд на вопрос, серии и множители, рейтинг недели.');
  if (pathname.startsWith('/privacy'))
    return t('Политика конфиденциальности «Мадридисты»: какие данные хранятся после входа через Telegram, зачем, сколько и как удалить аккаунт.');
  if (pathname.startsWith('/terms'))
    return t('Условия использования «Мадридисты» — бесплатного неофициального фан-приложения о «Реале»: без ставок, платежей и рекламы.');
  if (pathname.startsWith('/profile')) return t('Профиль болельщика: очки за прогнозы, история прогнозов и лиги с друзьями.');
  return DEFAULT_DESC();
}

/** Канонический адрес: домен без www, без query и хвостовых вкладок экрана матча. */
export function canonicalFor(pathname: string): string {
  let p = pathname.replace(/\/{2,}/g, '/');
  p = p.replace(/^(\/match\/[^/]+)\/(lineups|stats|online)\/?$/, '$1');
  if (p.length > 1) p = p.replace(/\/+$/, '');
  return SITE_ORIGIN + p;
}
