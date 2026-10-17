import { useEffect } from 'react';
import { useLocation } from 'react-router';
import { canonicalFor, descriptionFor } from '../lib/seo';

/**
 * Мета страницы для поиска и превью ссылок. SPA без SSR: статичные og-теги лежат в index.html
 * (их читают боты чатов, которые не выполняют JS), а здесь — то, что видят поисковики, выполняющие JS:
 * свой meta description и canonical на каждой странице; og:title / og:url повторяют текущую страницу.
 * <title> ставит сам экран (document.title), сюда он попадает через наблюдатель.
 */

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
