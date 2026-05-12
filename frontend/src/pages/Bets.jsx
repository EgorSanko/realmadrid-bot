// src/pages/Bets.jsx — ставки на матч (prematch + live).
//
// Data:
//   /api/match/next → match.bet_markets [{type, category, bets:[{key, name, odds}]}]
// POST /api/bet/place {match_id, bet_type, amount} — anti-вилка проверяется на сервере.
//
// Auto-refresh: 5s prematch / 2s live (через интервал /api/live проверки).

import React, { useEffect, useState, useCallback } from 'react';
import { api, ApiError } from '@/lib/api.js';
import { isAuthenticated } from '@/lib/auth.js';
import { formatOdds } from '@/lib/format.js';
import TeamLogo from '@/components/TeamLogo.jsx';
import LiveBadge from '@/components/LiveBadge.jsx';
import LoginModal from '@/components/LoginModal.jsx';

const QUICK_AMOUNTS = [10, 50, 100, 250];

function BetSlip({ pick, balance, onClose, onConfirm, submitting, error }) {
  const [amount, setAmount] = useState(50);
  if (!pick) return null;
  const potential = (amount * pick.odds).toFixed(2);

  return (
    <div className="fixed inset-x-0 bottom-0 z-30 bg-zinc-950 border-t border-rm-gold p-4 max-w-2xl mx-auto rounded-t-lg">
      <div className="flex justify-between items-start mb-3">
        <div>
          <div className="text-xs text-zinc-500">{pick.category}</div>
          <div className="font-semibold">{pick.name} · k = {formatOdds(pick.odds)}</div>
        </div>
        <button onClick={onClose} className="text-zinc-500 text-xl leading-none">×</button>
      </div>

      <div className="flex gap-2 mb-3">
        {QUICK_AMOUNTS.map((a) => (
          <button key={a} onClick={() => setAmount(a)}
            className={`flex-1 py-2 text-sm rounded ${amount === a ? 'bg-rm-gold text-zinc-900 font-semibold' : 'bg-zinc-800'}`}>
            {a}
          </button>
        ))}
      </div>

      <input
        type="number" min="1" value={amount}
        onChange={(e) => setAmount(Math.max(1, parseInt(e.target.value) || 0))}
        className="w-full bg-zinc-800 border border-zinc-700 rounded p-2 mb-3 text-center"
      />

      <div className="flex justify-between text-sm text-zinc-400 mb-3">
        <span>Возможный выигрыш</span>
        <span className="text-rm-gold font-semibold">{potential}</span>
      </div>

      {balance != null && (
        <div className="flex justify-between text-xs text-zinc-500 mb-3">
          <span>Баланс</span>
          <span>{balance}</span>
        </div>
      )}

      {error && <div className="text-red-400 text-sm mb-2">{error}</div>}

      <button
        onClick={() => onConfirm(amount)}
        disabled={submitting || (balance != null && amount > balance)}
        className="w-full bg-rm-gold text-zinc-900 font-bold py-3 rounded disabled:opacity-50">
        {submitting ? 'Ставка...' : `Поставить ${amount}`}
      </button>
    </div>
  );
}

export default function Bets() {
  const [match, setMatch] = useState(null);
  const [live, setLive] = useState(null);
  const [balance, setBalance] = useState(null);
  const [openCat, setOpenCat] = useState(null); // null = все открыты; Set = выборочно
  const [pick, setPick] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [message, setMessage] = useState(null);
  const [showLogin, setShowLogin] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [m, l] = await Promise.all([api.matches.next(), api.get('/live')]);
      if (m.match) setMatch(m.match);
      setLive(l);
      if (isAuthenticated()) {
        try { const me = await api.user.me(); setBalance(me.balance); } catch {}
      }
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    const isLive = live?.is_live;
    const id = setInterval(reload, isLive ? 2000 : 5000);
    return () => clearInterval(id);
  }, [reload, live?.is_live]);

  const placeBet = async (amount) => {
    if (!isAuthenticated()) { setShowLogin(true); return; }
    setError(null); setMessage(null); setSubmitting(true);
    try {
      const endpoint = live?.is_live ? '/bet/live' : '/bet/place';
      const body = {
        match_id: match.id,
        bet_type: pick.key,
        amount,
        ...(live?.is_live ? { odds: pick.odds } : {}),
      };
      const r = await api.post(endpoint, body, { auth: 'required' });
      setMessage(`Ставка ${amount} принята! Возможный выигрыш: ${(amount * pick.odds).toFixed(2)}`);
      setBalance(r.new_balance ?? balance - amount);
      setPick(null);
      setTimeout(() => setMessage(null), 4000);
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setSubmitting(false);
    }
  };

  // openCat === null означает «все категории раскрыты». При первом тапе
  // материализуем Set из текущих категорий и переключаем выбранную.
  const toggleCat = (cat) => {
    setOpenCat((prev) => {
      const base = prev ?? new Set((match?.bet_markets || []).map((m) => m.category));
      const s = new Set(base);
      s.has(cat) ? s.delete(cat) : s.add(cat);
      return s;
    });
  };

  if (!match) return <div className="p-8 text-zinc-500">Загрузка...</div>;

  const markets = match.bet_markets || [];

  return (
    <div className="p-4 max-w-2xl mx-auto pb-32">
      <div className="bg-gradient-to-br from-rm-purple to-zinc-900 rounded-lg p-4 mb-4">
        <div className="flex justify-between items-center text-xs text-zinc-400 mb-3">
          <span>{match.competition}</span>
          {live?.is_live ? <LiveBadge minute={live.minute} /> : <span>{match.date}</span>}
        </div>
        <div className="flex items-center justify-around gap-3">
          <div className="flex flex-col items-center">
            <TeamLogo src={match.home_logo} name={match.home_team} size={48} />
            <div className="text-xs mt-1">{match.home_team}</div>
          </div>
          <div className="text-2xl font-bold text-rm-gold">
            {live?.score || (live?.is_live ? '0:0' : 'vs')}
          </div>
          <div className="flex flex-col items-center">
            <TeamLogo src={match.away_logo} name={match.away_team} size={48} />
            <div className="text-xs mt-1">{match.away_team}</div>
          </div>
        </div>
      </div>

      {message && (
        <div className="bg-green-900/50 border border-green-700 rounded p-3 mb-3 text-sm text-green-300">
          {message}
        </div>
      )}

      <div className="space-y-2">
        {markets.map((m) => {
          const isOpen = openCat === null || openCat.has(m.category);
          return (
            <div key={m.category} className="bg-zinc-800 rounded-lg overflow-hidden">
              <button onClick={() => toggleCat(m.category)}
                className="w-full px-4 py-3 flex justify-between items-center text-left">
                <span className="font-semibold">{m.category}</span>
                <span className="text-xs text-zinc-500">{isOpen ? '−' : `+${m.bets?.length || 0}`}</span>
              </button>
              {isOpen && (
                <div className="px-3 pb-3 grid grid-cols-3 gap-2">
                  {m.bets?.map((b) => (
                    <button key={b.key} onClick={() => setPick({ ...b, category: m.category })}
                      className="card-flat bg-zinc-900 hover:bg-rm-gold hover:text-zinc-900 transition rounded p-2 text-center">
                      <div className="text-xs text-zinc-400">{b.name}</div>
                      <div className="font-bold">{formatOdds(b.odds)}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <BetSlip
        pick={pick} balance={balance}
        onClose={() => setPick(null)}
        onConfirm={placeBet}
        submitting={submitting}
        error={error}
      />

      <LoginModal open={showLogin} onClose={() => setShowLogin(false)} onLogin={() => { setShowLogin(false); reload(); }} />
    </div>
  );
}
