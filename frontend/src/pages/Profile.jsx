// src/pages/Profile.jsx — профиль: данные пользователя + последние ставки/прогнозы/транзакции.
//
// Auth required. В webapp — автоматически из initData. В site — LoginModal.

import React, { useEffect, useState, useCallback } from 'react';
import { api, ApiError } from '@/lib/api.js';
import { isAuthenticated, clearSiteAuth } from '@/lib/auth.js';
import { AUTH_MODE } from '@/config/features.js';
import LoginModal from '@/components/LoginModal.jsx';

const TX_COLORS = {
  win: 'text-green-400',
  bonus: 'text-rm-gold',
  deposit: 'text-rm-gold',
  bet: 'text-zinc-300',
  bet_place: 'text-zinc-300',
  lose: 'text-red-400',
};

function txAccent(type) {
  if (type?.includes('win')) return TX_COLORS.win;
  if (type?.includes('lose')) return TX_COLORS.lose;
  return TX_COLORS[type] || 'text-zinc-300';
}

// Восстанавливает последние N точек баланса из transactions (новые → старые).
// Последняя точка = текущий баланс, предыдущая = текущий − amount последней tx, и т.д.
function buildBalanceSeries(currentBalance, txs, n = 10) {
  if (currentBalance == null) return [];
  const series = [Number(currentBalance)];
  let bal = Number(currentBalance);
  for (const t of txs || []) {
    bal -= Number(t.amount) || 0;
    series.push(bal);
    if (series.length >= n) break;
  }
  return series.reverse(); // старые → новые
}

function BalanceChart({ currentBalance, txs }) {
  const points = buildBalanceSeries(currentBalance, txs, 10);
  if (points.length < 2) return null;
  const W = 320, H = 120, PAD_X = 28, PAD_Y = 18;
  const min = Math.min(...points), max = Math.max(...points);
  const range = Math.max(1, max - min);
  const xFor = (i) => PAD_X + (i * (W - 2 * PAD_X)) / (points.length - 1);
  const yFor = (v) => H - PAD_Y - ((v - min) / range) * (H - 2 * PAD_Y);
  const path = points.map((v, i) => `${i === 0 ? 'M' : 'L'} ${xFor(i)} ${yFor(v)}`).join(' ');

  // Y-axis ticks: min, mid, max
  const mid = Math.round((min + max) / 2);
  const ticks = [max, mid, min];

  return (
    <div className="bg-zinc-800 rounded p-3 mb-3">
      <div className="text-xs text-zinc-500 mb-2">Баланс — последние {points.length}</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-32" preserveAspectRatio="none">
        {ticks.map((t, i) => (
          <text key={i} x={4} y={yFor(t) + 4} className="fill-zinc-500" fontSize="9">{t}</text>
        ))}
        <path d={path} fill="none" stroke="#FFC107" strokeWidth="2" />
        {points.map((v, i) => (
          <circle key={i} cx={xFor(i)} cy={yFor(v)} r="3" fill="#FFC107" />
        ))}
        <text x={PAD_X} y={H - 4} className="fill-zinc-500" fontSize="9">{points.length} назад</text>
        <text x={W - PAD_X - 28} y={H - 4} className="fill-zinc-500" fontSize="9">сейчас</text>
      </svg>
    </div>
  );
}

export default function Profile() {
  const [tab, setTab] = useState('overview');
  const [user, setUser] = useState(null);
  const [bets, setBets] = useState(null);
  const [txs, setTxs] = useState(null);
  const [error, setError] = useState(null);
  const [showLogin, setShowLogin] = useState(false);

  const reload = useCallback(async () => {
    if (!isAuthenticated()) {
      setShowLogin(true);
      return;
    }
    try {
      const [me, b, t] = await Promise.all([
        api.user.me(),
        api.user.bets(20),
        api.user.transactions(30),
      ]);
      setUser(me);
      setBets(b);
      setTxs(t);
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setShowLogin(true);
      } else {
        setError(e.message);
      }
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  // Слушаем глобальное событие 401 (например, истёкшая сессия в Login Widget)
  useEffect(() => {
    const onExpired = () => setShowLogin(true);
    window.addEventListener('rm:auth-expired', onExpired);
    return () => window.removeEventListener('rm:auth-expired', onExpired);
  }, []);

  const handleLogout = () => {
    if (AUTH_MODE === 'login-widget') clearSiteAuth();
    setUser(null); setBets(null); setTxs(null);
    setShowLogin(true);
  };

  return (
    <div className="p-4 max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">Профиль</h2>

      {!isAuthenticated() && !showLogin && (
        <div className="bg-zinc-800 rounded p-4 text-center">
          <p className="text-zinc-300 mb-3">Войдите для доступа к профилю.</p>
          <button onClick={() => setShowLogin(true)}
                  className="px-4 py-2 bg-rm-gold text-zinc-900 font-semibold rounded">
            Войти через Telegram
          </button>
        </div>
      )}

      {error && <div className="text-red-400 mb-4">Ошибка: {error}</div>}

      {user && (
        <>
          <div className="bg-gradient-to-br from-rm-purple to-zinc-900 rounded-lg p-6 mb-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xl font-semibold">
                  {user.first_name} {user.last_name || ''}
                </div>
                {user.username && <div className="text-sm text-zinc-400">@{user.username}</div>}
              </div>
              <div className="text-right">
                <div className="text-3xl font-bold text-rm-gold">{user.balance ?? 0}</div>
                <div className="text-xs text-zinc-400">баланс</div>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-3 gap-2 text-center text-sm">
              <div className="bg-black/30 p-2 rounded">
                <div className="text-zinc-400 text-xs">Ставок</div>
                <div className="font-semibold">{user.bets_total ?? 0}</div>
              </div>
              <div className="bg-black/30 p-2 rounded">
                <div className="text-zinc-400 text-xs">Выиграно</div>
                <div className="font-semibold text-green-400">{user.bets_won ?? 0}</div>
              </div>
              <div className="bg-black/30 p-2 rounded">
                <div className="text-zinc-400 text-xs">Прогнозов</div>
                <div className="font-semibold">{user.predictions_total ?? 0}</div>
              </div>
            </div>
          </div>

          <div className="flex bg-zinc-800 rounded-lg p-1 mb-4 max-w-md">
            <button onClick={() => setTab('overview')}
              className={`flex-1 py-2 text-sm rounded ${tab === 'overview' ? 'bg-rm-gold text-zinc-900 font-semibold' : 'text-zinc-400'}`}>
              Обзор
            </button>
            <button onClick={() => setTab('bets')}
              className={`flex-1 py-2 text-sm rounded ${tab === 'bets' ? 'bg-rm-gold text-zinc-900 font-semibold' : 'text-zinc-400'}`}>
              Ставки
            </button>
            <button onClick={() => setTab('history')}
              className={`flex-1 py-2 text-sm rounded ${tab === 'history' ? 'bg-rm-gold text-zinc-900 font-semibold' : 'text-zinc-400'}`}>
              История
            </button>
          </div>

          {tab === 'overview' && (
            <div className="text-zinc-400 text-sm">
              Последние действия — см. вкладки «Ставки» и «История».
            </div>
          )}

          {tab === 'bets' && (
            <div className="space-y-2">
              {!bets?.length && <div className="text-zinc-500">Нет ставок</div>}
              {bets?.map((b) => (
                <div key={b.bet_id} className="card-flat bg-zinc-800 rounded p-3 flex justify-between">
                  <div>
                    <div className="text-sm">{b.match_name || `match_id ${b.match_id}`}</div>
                    <div className="text-xs text-zinc-500">{b.bet_type} · ставка {b.amount} · k={b.odds}</div>
                  </div>
                  <div className={`text-sm font-semibold ${b.status === 'won' ? 'text-green-400' : b.status === 'lost' ? 'text-red-400' : 'text-zinc-300'}`}>
                    {b.status === 'won' ? `+${b.payout || 0}` : b.status === 'lost' ? '−' : b.status}
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === 'history' && (
            <div className="space-y-1">
              <BalanceChart currentBalance={user.balance} txs={txs} />
              {!txs?.length && <div className="text-zinc-500">Нет транзакций</div>}
              {txs?.map((t) => (
                <div key={t.transaction_id} className="card-flat bg-zinc-800 rounded p-2 flex justify-between text-sm">
                  <div>
                    <span className="mr-1">{t.icon}</span>
                    <span className="text-zinc-300">{t.name || t.type}</span>
                    {t.description && <span className="text-xs text-zinc-500 ml-2">{t.description}</span>}
                  </div>
                  <div className={`font-mono ${txAccent(t.type)}`}>
                    {t.amount > 0 ? '+' : ''}{t.amount}
                  </div>
                </div>
              ))}
            </div>
          )}

          <button onClick={handleLogout}
            className="mt-6 text-xs text-zinc-500 hover:text-red-400">
            Выйти
          </button>
        </>
      )}

      <LoginModal open={showLogin} onClose={() => setShowLogin(false)} onLogin={() => { setShowLogin(false); reload(); }} />
    </div>
  );
}
