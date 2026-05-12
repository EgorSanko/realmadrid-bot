// src/pages/Games.jsx — мини-игры (webapp-only).
//
// Webapp-only (FEATURES.games). Cooldown 24ч общий на все игры.
// API:
//   GET /api/games/status
//   POST /api/games/start  {game, difficulty}
//   POST /api/games/result {game, difficulty, won}
//
// 4 игры: penalty, catch, runner, memory. Реализован играбельный penalty;
// остальные — одна кнопка «Сыграть» с random-исходом (минимальный MVP).

import React, { useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api.js';
import { isAuthenticated } from '@/lib/auth.js';
import LoginModal from '@/components/LoginModal.jsx';

const GAMES = [
  { id: 'penalty', label: 'Пенальти',    emoji: '⚽' },
  { id: 'catch',   label: 'Лови мяч',    emoji: '🧤' },
  { id: 'runner',  label: 'Беги, Винни', emoji: '🏃' },
];

const DIFFICULTIES = [
  { id: 'easy',   label: 'Лёгкий' },
  { id: 'medium', label: 'Средний' },
  { id: 'hard',   label: 'Сложный' },
  { id: 'expert', label: 'Эксперт' },
];

function PenaltyMiniGame({ onFinish }) {
  const [choice, setChoice] = useState(null);
  const [keeper, setKeeper] = useState(null);

  const shoot = (dir) => {
    if (choice != null) return;
    setChoice(dir);
    const k = Math.floor(Math.random() * 3);
    setTimeout(() => {
      setKeeper(k);
      setTimeout(() => onFinish(dir !== k), 800);
    }, 400);
  };

  return (
    <div className="bg-zinc-800 rounded-lg p-6 text-center">
      <h3 className="text-lg font-semibold mb-4">Куда бьёшь?</h3>
      <div className="relative h-32 bg-green-900/40 rounded mb-4 overflow-hidden">
        <div className="absolute inset-x-0 top-2 grid grid-cols-3 gap-1 px-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className={`h-24 rounded transition ${
              keeper === i ? 'bg-blue-500/60' : 'bg-zinc-700/30'
            }`} />
          ))}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {['←', '↑', '→'].map((arrow, i) => (
          <button key={i} onClick={() => shoot(i)} disabled={choice != null}
            className={`py-4 rounded text-2xl ${
              choice === i ? 'bg-rm-gold text-zinc-900' : 'bg-zinc-700 hover:bg-zinc-600'
            } disabled:opacity-50`}>
            {arrow}
          </button>
        ))}
      </div>
    </div>
  );
}

function SimpleMiniGame({ game, onFinish }) {
  const [pressed, setPressed] = useState(false);

  const play = () => {
    if (pressed) return;
    setPressed(true);
    setTimeout(() => onFinish(Math.random() > 0.5), 600);
  };

  return (
    <div className="bg-zinc-800 rounded-lg p-6 text-center">
      <div className="text-6xl mb-4">{GAMES.find((g) => g.id === game)?.emoji}</div>
      <button onClick={play} disabled={pressed}
        className="bg-rm-gold text-zinc-900 font-bold px-6 py-3 rounded disabled:opacity-50">
        {pressed ? 'Играем...' : 'Сыграть'}
      </button>
    </div>
  );
}

export default function Games() {
  const [mode, setMode] = useState('chooser');
  const [game, setGame] = useState(null);
  const [difficulty, setDifficulty] = useState(null);
  const [status, setStatus] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [showLogin, setShowLogin] = useState(false);

  const loadStatus = useCallback(async () => {
    if (!isAuthenticated()) return;
    try {
      const s = await api.get('/games/status', { auth: 'required' });
      setStatus(s);
    } catch {}
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const startGame = async (g, d) => {
    if (!isAuthenticated()) { setShowLogin(true); return; }
    setError(null);
    try {
      await api.post('/games/start', { game: g, difficulty: d }, { auth: 'required' });
      setGame(g); setDifficulty(d);
      setMode('playing');
    } catch (e) {
      setError(e.body?.detail || e.message);
      loadStatus();
    }
  };

  const finishGame = async (won) => {
    try {
      const r = await api.post('/games/result',
        { game, difficulty, won }, { auth: 'required' });
      setResult({ won, points_earned: r.points_earned || 0 });
      setMode('result');
      loadStatus();
    } catch (e) {
      setError(e.body?.detail || e.message);
    }
  };

  if (mode === 'chooser') {
    return (
      <div className="p-4 max-w-2xl mx-auto">
        <h2 className="text-2xl font-bold mb-4">Игры</h2>

        {status && !status.available && (
          <div className="bg-zinc-800 rounded p-3 mb-4 text-center text-sm">
            Следующая игра через {status.remaining_text}
          </div>
        )}

        <h3 className="text-sm text-zinc-400 mb-2">Сложность:</h3>
        <div className="grid grid-cols-4 gap-2 mb-4">
          {DIFFICULTIES.map((d) => (
            <button key={d.id} onClick={() => setDifficulty(d.id)}
              className={`p-2 rounded text-sm ${
                difficulty === d.id ? 'bg-rm-gold text-zinc-900' : 'bg-zinc-800'
              }`}>
              {d.label}
            </button>
          ))}
        </div>

        <h3 className="text-sm text-zinc-400 mb-2">Игра:</h3>
        <div className="grid grid-cols-2 gap-2">
          {GAMES.map((g) => (
            <button key={g.id} onClick={() => difficulty && startGame(g.id, difficulty)}
              disabled={!difficulty || (status && !status.available)}
              className="bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 rounded p-4 text-left">
              <div className="text-3xl mb-2">{g.emoji}</div>
              <div className="font-semibold">{g.label}</div>
            </button>
          ))}
        </div>

        {error && <div className="mt-4 text-red-400 text-sm">{error}</div>}

        <LoginModal open={showLogin} onClose={() => setShowLogin(false)}
          onLogin={() => { setShowLogin(false); loadStatus(); }} />
      </div>
    );
  }

  if (mode === 'playing') {
    return (
      <div className="p-4 max-w-2xl mx-auto">
        <div className="text-xs text-zinc-500 mb-3">
          {GAMES.find((g) => g.id === game)?.label} · {difficulty}
        </div>
        {game === 'penalty'
          ? <PenaltyMiniGame onFinish={finishGame} />
          : <SimpleMiniGame game={game} onFinish={finishGame} />}
      </div>
    );
  }

  if (mode === 'result' && result) {
    return (
      <div className="p-4 max-w-2xl mx-auto">
        <div className={`rounded-lg p-6 text-center ${result.won ? 'bg-green-900/50' : 'bg-red-900/50'}`}>
          <div className="text-6xl mb-4">{result.won ? '🏆' : '😢'}</div>
          <div className="text-xl font-semibold mb-2">
            {result.won ? 'Победа!' : 'Поражение'}
          </div>
          {result.points_earned > 0 && (
            <div className="text-rm-gold text-lg mt-2">+{result.points_earned} очков</div>
          )}
        </div>

        <button onClick={() => { setMode('chooser'); setResult(null); setGame(null); }}
          className="w-full mt-4 bg-zinc-800 hover:bg-zinc-700 rounded p-3">
          К списку
        </button>
      </div>
    );
  }

  return <div className="p-8 text-zinc-500">Загрузка...</div>;
}
