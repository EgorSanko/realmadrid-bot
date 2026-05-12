// src/pages/Predictions.jsx — простой 1X2 прогноз на следующий матч.
//
// Auth required. POST /api/prediction/make {match_id, prediction: 'home'|'draw'|'away'}.
// Anti-вилка проверяется на сервере — UI просто показывает ответ.

import React, { useEffect, useState, useCallback } from 'react';
import { api, ApiError } from '@/lib/api.js';
import { isAuthenticated } from '@/lib/auth.js';
import TeamLogo from '@/components/TeamLogo.jsx';
import LoginModal from '@/components/LoginModal.jsx';

const LABELS = { home: 'П1', draw: 'X', away: 'П2' };

export default function Predictions() {
  const [match, setMatch] = useState(null);
  const [my, setMy] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);
  const [showLogin, setShowLogin] = useState(false);

  const reload = useCallback(async () => {
    try {
      const m = await api.matches.next();
      if (m.match) setMatch(m.match);
      if (isAuthenticated()) {
        const preds = await api.user.predictions(20);
        setMy(preds);
      }
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) setError(e.message);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const submit = async (prediction) => {
    setError(null); setMessage(null);
    if (!isAuthenticated()) { setShowLogin(true); return; }
    if (!match?.id) { setError('Нет активного матча'); return; }
    setSubmitting(true);
    try {
      const r = await api.post('/prediction/make',
        { match_id: match.id, prediction },
        { auth: 'required' });
      setMessage(r.message || 'Прогноз принят!');
      reload();
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const existing = my?.find?.((p) => String(p.match_id) === String(match?.id));

  return (
    <div className="p-4 max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">Прогнозы</h2>

      {!match && <div className="text-zinc-500">Загрузка...</div>}

      {match && (
        <div className="bg-zinc-800 rounded-lg p-4 mb-4">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs text-zinc-500">{match.competition} · {match.date}</div>
          </div>
          <div className="flex items-center justify-around gap-3 mb-4">
            <div className="text-center flex-1">
              <TeamLogo src={match.home_logo} name={match.home_team} size={48} />
              <div className="text-sm mt-1">{match.home_team}</div>
            </div>
            <div className="text-xl text-zinc-500">vs</div>
            <div className="text-center flex-1">
              <TeamLogo src={match.away_logo} name={match.away_team} size={48} />
              <div className="text-sm mt-1">{match.away_team}</div>
            </div>
          </div>

          {existing ? (
            <div className="bg-zinc-900 rounded p-3 text-center">
              <div className="text-xs text-zinc-500 mb-1">Ваш прогноз</div>
              <div className="text-lg font-bold text-rm-gold">
                {LABELS[existing.prediction]} ({existing.prediction})
              </div>
              {existing.status && existing.status !== 'pending' && (
                <div className={`text-xs mt-1 ${existing.status === 'correct' ? 'text-green-400' : 'text-red-400'}`}>
                  {existing.status === 'correct' ? '✓ Угадал' : '× Не угадал'}
                </div>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-2">
              {['home', 'draw', 'away'].map((k) => (
                <button key={k} onClick={() => submit(k)} disabled={submitting}
                  className="bg-zinc-900 hover:bg-rm-gold hover:text-zinc-900 transition rounded p-3 font-bold disabled:opacity-50">
                  {LABELS[k]}
                </button>
              ))}
            </div>
          )}

          {message && <div className="mt-3 text-green-400 text-sm">{message}</div>}
          {error && <div className="mt-3 text-red-400 text-sm">{error}</div>}
        </div>
      )}

      {my?.length > 0 && (
        <>
          <h3 className="text-sm font-semibold text-zinc-400 mt-6 mb-2">Мои прогнозы</h3>
          <div className="space-y-2">
            {my.slice(0, 10).map((p) => (
              <div key={p.prediction_id} className="bg-zinc-800 rounded p-3 flex justify-between items-center text-sm">
                <div>
                  <div>{p.match_name || `match #${p.match_id}`}</div>
                  <div className="text-xs text-zinc-500">прогноз: {LABELS[p.prediction] || p.prediction}</div>
                </div>
                <div className={
                  p.status === 'correct' ? 'text-green-400' :
                  p.status === 'incorrect' || p.status === 'lost' ? 'text-red-400' :
                  'text-zinc-400'
                }>
                  {p.status === 'correct' ? '✓' : p.status === 'incorrect' ? '×' : '⋯'}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <LoginModal open={showLogin} onClose={() => setShowLogin(false)} onLogin={() => { setShowLogin(false); reload(); }} />
    </div>
  );
}
