// src/pages/News.jsx — news list + article detail view.
//
// Shared between webapp and site. No auth required.
// Data source: /api/news + /api/news/article?url=<link>.
// Article HTML comes from fondoruso.ru parser — already sanitized server-side.

import React, { useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api.js';
import { formatNewsDate } from '@/lib/format.js';

function NewsCard({ item, onOpen }) {
  return (
    <button
      onClick={() => onOpen(item)}
      className="card overflow-hidden cursor-pointer bg-zinc-800 rounded-lg text-left
                 hover:bg-zinc-700 transition w-full"
    >
      {item.image && (
        <img src={item.image} alt="" loading="lazy"
             className="w-full h-48 object-cover" />
      )}
      <div className="p-4">
        <h3 className="font-semibold text-white mb-2 leading-snug">{item.title}</h3>
        {item.description && (
          <p className="text-sm text-zinc-400 line-clamp-2 mb-2">{item.description}</p>
        )}
        <div className="flex justify-between items-center text-xs text-zinc-500">
          <span>{formatNewsDate(item.date)}</span>
          {item.tag && <span className="text-rm-gold">{item.tag}</span>}
        </div>
      </div>
    </button>
  );
}

function ArticleView({ article, loading, error, onBack }) {
  return (
    <div className="p-4 max-w-2xl mx-auto">
      <button onClick={onBack} className="text-rm-gold mb-4 text-sm">
        ← К списку
      </button>
      {loading && <div className="text-zinc-500">Загрузка...</div>}
      {error && <div className="text-red-400">Ошибка: {error}</div>}
      {article && (
        <article>
          <h1 className="text-2xl font-bold mb-2">{article.title}</h1>
          <div className="text-sm text-zinc-500 mb-4">{formatNewsDate(article.date)}</div>
          {article.images?.[0] && (
            <img src={article.images[0]} alt="" className="w-full rounded mb-4" />
          )}
          <div className="space-y-3 text-zinc-200 leading-relaxed">
            {(Array.isArray(article.content) ? article.content : [article.content || '']).map((para, i) => (
              <p key={i}>{para}</p>
            ))}
          </div>
        </article>
      )}
    </div>
  );
}

export default function News() {
  const [news, setNews] = useState(null);
  const [listError, setListError] = useState(null);
  const [openItem, setOpenItem] = useState(null);
  const [article, setArticle] = useState(null);
  const [articleLoading, setArticleLoading] = useState(false);
  const [articleError, setArticleError] = useState(null);

  // Load list once on mount
  useEffect(() => {
    api.news.list()
      .then(setNews)
      .catch((e) => setListError(e.message));
  }, []);

  // Load article when item opens
  const openArticle = useCallback(async (item) => {
    setOpenItem(item);
    setArticle(null);
    setArticleError(null);
    setArticleLoading(true);
    try {
      const a = await api.news.article(item.link);
      setArticle(a);
    } catch (e) {
      setArticleError(e.message);
    } finally {
      setArticleLoading(false);
    }
  }, []);

  if (openItem) {
    return (
      <ArticleView
        article={article}
        loading={articleLoading}
        error={articleError}
        onBack={() => { setOpenItem(null); setArticle(null); }}
      />
    );
  }

  return (
    <div className="p-4 max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">Новости</h2>
      {listError && <div className="text-red-400 mb-4">Ошибка: {listError}</div>}
      {news == null && !listError && <div className="text-zinc-500">Загрузка...</div>}
      {news?.length === 0 && <div className="text-zinc-500">Новостей нет.</div>}
      {news?.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          {news.map((item) => (
            <NewsCard key={item.id} item={item} onOpen={openArticle} />
          ))}
        </div>
      )}
    </div>
  );
}
