import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router';
import { ExternalLink, openExternal } from '../../lib/ExternalLink';
import { newsHref, plainClick, useMediaNav, useOverlayBack, type MediaNavState } from '../../lib/mediaNav';
import { backgroundOf } from '../../lib/playerNav';
import { shareLink } from '../../lib/share';
import { isDesktop, useDesktop } from '../../lib/shell';
import { useTelegramBackButton } from '../../lib/tmaNav';
import { Button, EmptyState, ErrorState, NewsItem, Skeleton } from '../../ui';
import { articleMeta, newsTime, type ArticleData, type NewsBrief } from './mediaData';
import { useArticle } from './useArticle';
import './media.css';
import './reader.css';

const BACK_ICON = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M15 5l-7 7 7 7" />
  </svg>
);
const SHARE_ICON = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M12 3v12M7 8l5-5 5 5M5 13v6a2 2 0 002 2h10a2 2 0 002-2v-6" />
  </svg>
);

/** Чтение новости внутри приложения: /news/:aid — полноэкранный слой поверх экрана, с которого открыли. */
export default function NewsScreen() {
  const { id = '' } = useParams();
  const location = useLocation();
  const preview = (location.state as MediaNavState | null)?.news;
  const pre = preview && preview.aid === id ? preview : null;
  const { state, reload } = useArticle(id);
  const goBack = useOverlayBack('/media?tab=news');
  const nativeBack = useTelegramBackButton(goBack);
  const ref = useRef<HTMLDivElement>(null);
  const page = useDesktop();
  const overlay = backgroundOf(location) != null;

  // фон не прокручивается под слоем; фокус — в слой; Esc закрывает
  useEffect(() => {
    const prev = document.body.style.overflow;
    // сайт на компьютере: это обычная страница, прокручивается сама страница
    if (!isDesktop()) document.body.style.overflow = 'hidden';
    ref.current?.focus({ preventScroll: true });
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') goBack();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [goBack]);
  useEffect(() => {
    ref.current?.scrollTo(0, 0);
  }, [id]);

  const data = state.kind === 'ok' || state.kind === 'pending' ? state.data : null;
  const title = data?.title ?? pre?.title ?? null;
  useEffect(() => {
    const prev = document.title;
    document.title = title ? `${title} — Мадридиста` : 'Новость — Мадридиста';
    return () => {
      document.title = prev;
    };
  }, [title]);

  return (
    <div
      ref={ref}
      className={overlay ? 'nr nr--overlay' : 'nr'}
      role={page ? undefined : 'dialog'}
      aria-modal={page ? undefined : true}
      aria-label={title ? `Новость: ${title}` : 'Новость'}
      tabIndex={-1}
    >
      <div className="nr-in">
        <header className="nr-top">
          {nativeBack ? (
            <span className="nr-top__gap" aria-hidden="true" />
          ) : (
            <button type="button" className="nr-top__back" aria-label="Назад" onClick={goBack}>
              {BACK_ICON}
            </button>
          )}
          <span className="nr-top__title">Новость</span>
          {data ? <ShareButton aid={id} title={data.title} icon /> : <span className="nr-top__gap" aria-hidden="true" />}
        </header>

        {state.kind === 'not_found' ? (
          <EmptyState
            className="nr-state"
            title="Новость не найдена"
            text="Её уже нет в ленте — загляни в свежие"
            action={{ label: 'Все новости', onClick: goBack }}
          />
        ) : state.kind === 'error' ? (
          <ErrorState className="nr-state" onRetry={reload} />
        ) : (
          <Article data={data} pre={pre} pending={state.kind !== 'ok'} />
        )}
      </div>
    </div>
  );
}

function Hero({ src, caption }: { src: string; caption?: string | null }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <figure className="nr-hero">
      <img
        src={src}
        alt=""
        decoding="async"
        onError={() => setFailed(true)}
        onLoad={(e) => {
          if (e.currentTarget.naturalWidth <= 1) setFailed(true); // заглушка 1×1 вместо картинки
        }}
      />
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

function Article({
  data,
  pre,
  pending,
}: {
  data: ArticleData | null;
  pre: { title: string; source: string; image: string | null; published: string | null } | null;
  pending: boolean;
}) {
  const head = data ?? (pre ? { ...pre, words: null } : null);
  // у статьи своё решение о главной картинке (фото может быть первым в тексте) — превью из списка только до загрузки
  const image = data ? data.image : (pre?.image ?? null);
  return (
    <article className="nr-art" aria-busy={pending || undefined}>
      {image && <Hero key={image} src={image} caption={data?.image_caption} />}
      {head ? (
        <>
          <h1 className="nr-title">{head.title}</h1>
          <p className="nr-meta">{articleMeta({ source: head.source, published: head.published, words: data?.words ?? null })}</p>
        </>
      ) : (
        <div className="nr-pad">
          <Skeleton width="92%" height={24} />
          <Skeleton width="70%" height={24} style={{ marginTop: 10 }} />
          <Skeleton width="40%" height={13} style={{ marginTop: 14 }} />
        </div>
      )}

      {data?.full ? (
        <>
          {data.lead && <p className="nr-lead">{data.lead}</p>}
          <Body html={data.html ?? ''} />
        </>
      ) : pending ? (
        <div className="nr-pad nr-wait" role="status">
          {data?.summary && <p className="nr-lead">{data.summary}</p>}
          <p className="nr-wait__text">Загружаем текст новости…</p>
          {['100%', '96%', '88%', '100%', '93%', '60%'].map((w, i) => (
            <Skeleton key={i} width={w} height={14} style={{ marginTop: 12 }} />
          ))}
        </div>
      ) : data ? (
        <Partial data={data} />
      ) : null}

      {data && <Footer data={data} />}
      {data && data.more.length > 0 && <More items={data.more} />}
    </article>
  );
}

/** Источник не отдал текст (или блокирует) — лид, картинка и «Читать полностью на <источник>». */
function Partial({ data }: { data: ArticleData }) {
  return (
    <div className="nr-pad">
      {data.summary && <p className="nr-lead">{data.summary}</p>}
      <p className="nr-note">Полный текст этой новости есть только на сайте источника.</p>
      <ExternalLink href={data.url} className="ui-btn ui-btn--secondary ui-btn--block nr-full">
        Читать полностью на {data.source}
      </ExternalLink>
    </div>
  );
}

/**
 * Текст статьи — HTML с сервера (белый список тегов, картинки только /img/news). Клики по ссылкам:
 * на наши новости — внутри приложения, на прочие страницы — в браузере (в Telegram — openLink).
 */
function Body({ html }: { html: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    root.querySelectorAll('a').forEach((a) => {
      if (a.dataset.internal) return;
      a.target = '_blank';
      a.rel = 'noopener nofollow noreferrer';
    });
    const hide = (img: HTMLImageElement) => {
      const box = img.closest('figure') ?? img;
      (box as HTMLElement).style.display = 'none';
    };
    root.querySelectorAll('img').forEach((img) => {
      img.decoding = 'async';
      if (img.complete && img.naturalWidth <= 1 && img.currentSrc) hide(img);
      img.addEventListener('error', () => hide(img), { once: true });
      img.addEventListener('load', () => img.naturalWidth <= 1 && hide(img), { once: true });
    });
  }, [html]);

  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    const a = (e.target as HTMLElement).closest('a');
    if (!a || !plainClick(e)) return;
    const href = a.getAttribute('href') ?? '';
    if (a.dataset.internal && href.startsWith('/news/')) {
      e.preventDefault();
      const state: MediaNavState = { backgroundLocation: backgroundOf(location) ?? location };
      navigate(href, { state });
      return;
    }
    openExternal(href, e);
  };

  // HTML собран сервером заново из белого списка тегов (backend/app/sources/article.py)
  return <div ref={ref} className="nr-body" onClick={onClick} dangerouslySetInnerHTML={{ __html: html }} />;
}

function ShareButton({ aid, title, icon }: { aid: string; title: string; icon?: boolean }) {
  const [msg, setMsg] = useState<string | null>(null);
  const share = async () => {
    const r = await shareLink(`${window.location.origin}${newsHref(aid)}`, title);
    setMsg(r === 'copied' ? 'Ссылка скопирована' : r === 'failed' ? 'Не удалось поделиться' : null);
    if (r !== 'shared') window.setTimeout(() => setMsg(null), 2500);
  };
  if (icon) {
    return (
      <button type="button" className="nr-top__back" aria-label="Поделиться" onClick={share}>
        {SHARE_ICON}
        {msg && (
          <span className="nr-toast" role="status">
            {msg}
          </span>
        )}
      </button>
    );
  }
  return (
    <>
      <Button variant="secondary" block onClick={share} className="nr-share">
        {SHARE_ICON}
        <span>Поделиться</span>
      </Button>
      {msg && (
        <p className="nr-note" role="status">
          {msg}
        </p>
      )}
    </>
  );
}

/** Внизу: «Источник: Спорт-Экспресс» со ссылкой на оригинал (обязательно), автор, «Поделиться». */
function Footer({ data }: { data: ArticleData }) {
  return (
    <footer className="nr-foot">
      <p className="nr-src">
        Источник:{' '}
        <ExternalLink href={data.url} className="nr-src__link">
          {data.source}
        </ExternalLink>
        {data.origin && data.origin !== `«${data.source}»` && <> · со ссылкой на {data.origin}</>}
        {data.author && <> · {data.author}</>}
      </p>
      <ShareButton aid={data.aid} title={data.title} />
    </footer>
  );
}

function More({ items }: { items: NewsBrief[] }) {
  const { openNews } = useMediaNav();
  return (
    <section className="nr-more" aria-label="Ещё новости">
      <h2 className="nr-more__title">Ещё новости</h2>
      {items.map((n) => (
        <a key={n.aid} href={newsHref(n.aid)} className="mx-link nr-more__item" onClick={(e) => openNews(n, e)}>
          <NewsItem title={n.title} source={n.source} time={newsTime(n.published)} imageUrl={n.image ?? undefined} variant="list" />
        </a>
      ))}
    </section>
  );
}
