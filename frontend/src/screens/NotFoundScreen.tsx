import { useEffect } from 'react';
import { useSpaLink } from '../lib/spaLink';
import { t } from '../lib/i18n';
import { EmptyState } from '../ui';

/**
 * Неизвестный адрес: честная страница «не найдено» вместо молчаливого перехода на главную.
 * Поисковикам — noindex, человеку — ссылки на главную и матчи.
 */
export default function NotFoundScreen() {
  const link = useSpaLink();
  useEffect(() => {
    document.title = t('Страница не найдена — Мадридиста');
    // не индексировать: поисковик, выполняющий JS, увидит noindex (nginx на такие адреса отдаёт 404)
    const robots = document.createElement('meta');
    robots.name = 'robots';
    robots.content = 'noindex';
    document.head.appendChild(robots);
    return () => robots.remove();
  }, []);
  const home = link('/');
  const matches = link('/matches');
  return (
    <main className="nf">
      <header className="topbar">
        <h1 className="topbar__title">{t('Не найдено')}</h1>
      </header>
      <EmptyState
        title={t('Такой страницы нет')}
        text={t('Ссылка устарела или в адресе опечатка. Всё главное — на главной')}
        action={{ label: t('На главную'), href: home.href, onClick: home.onClick }}
      />
      <p className="nf__more">
        <a href={matches.href} onClick={matches.onClick}>
          {t('Календарь матчей')}
        </a>
      </p>
    </main>
  );
}
