// src/pages/Home.jsx — главная страница: следующий/live матч + odds кнопки.
//
// Data: /api/match/next (главный матч + bet_markets) + /api/live (live state).
// Refresh: 5s prematch / 2s live (BK-feel — matches backend cache TTL).

import React, { useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api.js';
import { formatOdds } from '@/lib/format.js';
import TeamLogo from '@/components/TeamLogo.jsx';
import LiveBadge from '@/components/LiveBadge.jsx';

function MainOdd({ label, value, accent }) {
  return (
    <button className={`flex-1 bg-zinc-800 hover:bg-zinc-700 rounded p-3 transition ${accent || ''}`}>
      <div className="text-xs text-zinc-400 mb-1">{label}</div>
      <div className="text-lg font-bold">{formatOdds(value)}</div>
    </button>
  );
}

function MatchHeader({ match, live }) {
  const score = live?.score;
  const minute = live?.minute;
  return (
    <div className="bg-gradient-to-br from-rm-purple to-zinc-900 rounded-lg p-6 mb-6">
      <div className="flex items-center justify-between text-xs text-zinc-400 mb-3">
        <span>{match.competition || ''}</span>
        {live?.is_live ? <LiveBadge minute={minute} /> : <span>{match.date}</span>}
      </div>

      <div className="flex items-center justify-around gap-4">
        <div className="flex flex-col items-center flex-1">
          <TeamLogo src={match.home_logo} name={match.home_team} size={64} />
          <div className="mt-2 text-sm font-medium text-center">{match.home_team}</div>
        </div>

        <div className="text-3xl font-bold text-rm-gold whitespace-nowrap">
          {score || (live?.is_live ? '0 : 0' : 'vs')}
        </div>

        <div className="flex flex-col items-center flex-1">
          <TeamLogo src={match.away_logo} name={match.away_team} size={64} />
          <div className="mt-2 text-sm font-medium text-center">{match.away_team}</div>
        </div>
      </div>
    </div>
  );
}

export default function Home() {
  const [match, setMatch] = useState(null);
  const [live, setLive] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const [m, l] = await Promise.all([api.matches.next(), api.get('/live')]);
      if (m.match) setMatch(m.match);
      setLive(l);
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    load();
    const isLive = live?.is_live;
    const interval = setInterval(load, isLive ? 2000 : 5000);
    return () => clearInterval(interval);
  }, [load, live?.is_live]);

  if (error && !match) {
    return <div className="p-8 max-w-2xl mx-auto text-red-400">Ошибка: {error}</div>;
  }
  if (!match) {
    return <div className="p-8 max-w-2xl mx-auto text-zinc-500">Загрузка...</div>;
  }

  const odds = match.odds || {};
  return (
    <div className="p-4 max-w-2xl mx-auto">
      <MatchHeader match={match} live={live} />

      <h3 className="text-sm font-semibold text-zinc-400 mb-2">Исход матча</h3>
      <div className="flex gap-2 mb-6">
        <MainOdd label="П1" value={odds.home} />
        <MainOdd label="X"  value={odds.draw} />
        <MainOdd label="П2" value={odds.away} />
      </div>

      {match.bet_markets?.length > 0 && (
        <div className="text-xs text-zinc-500">
          + {match.bet_markets.length} типов ставок (открыть в разделе «Ставки»)
        </div>
      )}
    </div>
  );
}
