import { useEffect } from 'react';
import { useLocation } from 'react-router';

/**
 * Мета страницы для поиска и превью ссылок. SPA без SSR: статичные og-теги лежат в index.html
 * (их читают боты чатов, которые не выполняют JS), а здесь — то, что видят поисковики, выполняющие JS:
 * свой meta description и canonical на каждой странице; og:title / og:url повторяют текущую страницу.
 * <title> ставит сам экран (document.title), сюда он попадает через наблюдатель.
 */

export const SITE_ORIGIN = 'https://realmadridfan.ru';

const DEFAULT_DESC =
  'Мадридиста — фан-приложение «Реала»: ближайший матч с отсчётом, онлайн-трансляции, календарь и таблица Ла Лиги, состав, новости и видео, прогнозы на матчи.';

/** Описание страницы по адресу. Для конкретных матчей и новостей — общее описание раздела. */
export function descriptionFor(pathname: string): string {
  if (pathname === '/') return DEFAULT_DESC;
  if (pathname.startsWith('/matches'))
    return 'Календарь и результаты матчей «Реала» в Ла Лиге и Лиге чемпионов, турнирные таблицы с текущим местом команды.';
  if (pathname.startsWith('/match/'))
    return 'Матч «Реала»: счёт и хронология, стартовые составы на поле, статистика, лучшие игроки и обзор.';
  if (pathname.startsWith('/team'))
    return 'Состав «Реала» сезона: игроки по линиям, лидеры по голам, передачам и оценкам, лазарет и трансферы.';
  if (pathname.startsWith('/player/')) return 'Карточка игрока «Реала»: статистика сезона, последние матчи, карьера и травмы.';
  if (pathname.startsWith('/media')) return 'Свежие новости о «Реале» из Чемпионата, Спорт-Экспресса и Sports.ru, обзоры матчей и видео клуба.';
  if (pathname.startsWith('/news/')) return 'Новость о «Реале» — текст целиком внутри приложения, со ссылкой на источник.';
  if (pathname.startsWith('/video/')) return 'Видео «Реала»: обзоры матчей и ролики клуба.';
  if (pathname.startsWith('/predict'))
    return 'Угадывай счёт матчей «Реала» и первого бомбардира, набирай очки, соревнуйся в рейтинге и лигах с друзьями.';
  if (pathname.startsWith('/profile')) return 'Профиль болельщика: очки за прогнозы, история прогнозов и лиги с друзьями.';
  return DEFAULT_DESC;
}

/** Канонический адрес: домен без www, без query и хвостовых вкладок экрана матча. */
export function canonicalFor(pathname: string): string {
  let p = pathname.replace(/\/{2,}/g, '/');
  p = p.replace(/^(\/match\/[^/]+)\/(lineups|stats)\/?$/, '$1');
  if (p.length > 1) p = p.replace(/\/+$/, '');
  return SITE_ORIGIN + p;
}

function setMeta(attr: 'name' | 'property', key: string, value: string) {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  if (el.content !== value) el.content = value;
}

function setCanonical(href: string) {
  let el = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!el) {
    el = document.createElement('link');
    el.rel = 'canonical';
    document.head.appendChild(el);
  }
  if (el.href !== href) el.href = href;
}

export function RouteMeta() {
  const { pathname } = useLocation();

  useEffect(() => {
    const desc = descriptionFor(pathname);
    const url = canonicalFor(pathname);
    setMeta('name', 'description', desc);
    setMeta('property', 'og:description', desc);
    setMeta('name', 'twitter:description', desc);
    setMeta('property', 'og:url', url);
    setCanonical(url);
  }, [pathname]);

  // og:title / twitter:title — вслед за <title>, который ставят экраны
  useEffect(() => {
    const sync = () => {
      const t = document.title;
      setMeta('property', 'og:title', t);
      setMeta('name', 'twitter:title', t);
    };
    sync();
    const title = document.querySelector('title');
    if (!title) return;
    const mo = new MutationObserver(sync);
    mo.observe(title, { childList: true, characterData: true, subtree: true });
    return () => mo.disconnect();
  }, []);

  return null;
}
