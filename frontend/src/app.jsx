// src/app.jsx — entry point для обоих таргетов.

import React, { lazy, Suspense, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { FEATURES, TARGET, AUTH_MODE } from './config/features.js';
import './styles/tailwind.css';

const Home        = lazy(() => import('./pages/Home.jsx'));
const Matches     = lazy(() => import('./pages/Matches.jsx'));
const Bets        = lazy(() => import('./pages/Bets.jsx'));
const Predictions = lazy(() => import('./pages/Predictions.jsx'));
const News        = lazy(() => import('./pages/News.jsx'));
const Stream      = lazy(() => import('./pages/Stream.jsx'));
const Profile     = lazy(() => import('./pages/Profile.jsx'));
const Games       = FEATURES.games    ? lazy(() => import('./pages/Games.jsx'))    : null;
const Quiz        = FEATURES.quiz     ? lazy(() => import('./pages/Quiz.jsx'))     : null;
const Purchase    = FEATURES.purchase ? lazy(() => import('./pages/Purchase.jsx')) : null;

function App() {
  const [page, setPage] = useState('home');

  const tabs = [
    { id: 'home',        label: 'Главная' },
    { id: 'matches',     label: 'Матчи' },
    { id: 'bets',        label: 'Ставки' },
    { id: 'predictions', label: 'Прогнозы' },
    { id: 'news',        label: 'Новости' },
    { id: 'stream',      label: 'Стрим' },
    FEATURES.games    && { id: 'games',    label: 'Игры' },
    FEATURES.quiz     && { id: 'quiz',     label: 'Викторина' },
    FEATURES.purchase && { id: 'purchase', label: 'Купить' },
    { id: 'profile',     label: 'Профиль' },
  ].filter(Boolean);

  return (
    <div className="min-h-screen bg-zinc-900 text-white">
      <nav className="bg-zinc-950 border-b border-zinc-800 sticky top-0 z-20">
        <div className="max-w-2xl mx-auto flex overflow-x-auto">
          {tabs.map((t) => (
            <button key={t.id} onClick={() => setPage(t.id)}
              className={`flex-shrink-0 px-4 py-3 text-sm font-medium whitespace-nowrap ${
                page === t.id ? 'text-rm-gold border-b-2 border-rm-gold' : 'text-zinc-400'
              }`}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="max-w-2xl mx-auto px-4 py-1 text-[10px] text-zinc-600 flex gap-3">
          <span>{TARGET}</span><span>{AUTH_MODE}</span>
        </div>
      </nav>

      <Suspense fallback={<div className="p-8 text-zinc-500">Загрузка...</div>}>
        {page === 'home'        && <Home />}
        {page === 'matches'     && <Matches />}
        {page === 'bets'        && <Bets />}
        {page === 'predictions' && <Predictions />}
        {page === 'news'        && <News />}
        {page === 'stream'      && <Stream />}
        {page === 'profile'     && <Profile />}
        {page === 'games'       && Games    && <Games />}
        {page === 'quiz'        && Quiz     && <Quiz />}
        {page === 'purchase'    && Purchase && <Purchase />}
      </Suspense>
    </div>
  );
}

const root = document.getElementById('root');
if (root) {
  ReactDOM.createRoot(root).render(<App />);
}
