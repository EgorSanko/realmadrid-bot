// src/pages/Matches.jsx — upcoming + results, two-tab view.
//
// No auth needed. Data:
//   /api/matches/upcoming → [{id, home_team, away_team, home_logo, away_logo, date, competition}]
//   /api/matches/results  → [{match_id, opponent, score, is_home, result, home_team, away_team,
//                             home_score, away_score, home_logo, away_logo, date, competition}]

import React, { useEffect, useState } from 'react';
import { api } from '@/lib/api.js';
import TeamLogo from '@/components/TeamLogo.jsx';

function UpcomingCard({ m }) {
  return (
    <div className="bg-zinc-800 rounded-lg p-4 flex items-center gap-3">
      <TeamLogo src={m.home_logo} name={m.home_team} size={40} />
      <div className="flex-1 text-center">
        <div className="font-semibold text-sm">{m.home_team}</div>
        <div className="text-xs text-zinc-500 my-1">vs</div>
        <div className="font-semibold text-sm">{m.away_team}</div>
      </div>
      <TeamLogo src={m.away_logo} name={m.away_team} size={40} />
      <div className="ml-4 text-right">
        <div className="text-sm text-zinc-300">{m.date}</div>
        <div className="text-xs text-zinc-500 mt-1">{m.competition}</div>
      </div>
    </div>
  );
}

function ResultCard({ r }) {
  const rmWon = r.result === 'win';
  const rmLost = r.result === 'loss';
  const accent = rmWon ? 'text-green-400' : rmLost ? 'text-red-400' : 'text-zinc-300';

  return (
    <div className="bg-zinc-800 rounded-lg p-4 flex items-center gap-3">
      <TeamLogo src={r.home_logo} name={r.home_team} size={36} />
      <div className="flex-1 text-center">
        <div className="text-sm">{r.home_team}</div>
        <div className={`text-xl font-bold my-1 ${accent}`}>
          {r.home_score} : {r.away_score}
        </div>
        <div className="text-sm">{r.away_team}</div>
      </div>
      <TeamLogo src={r.away_logo} name={r.away_team} size={36} />
      <div className="ml-4 text-right">
        <div className="text-sm text-zinc-300">{r.date}</div>
        <div className="text-xs text-zinc-500 mt-1">{r.competition}</div>
      </div>
    </div>
  );
}

export default function Matches() {
  const [tab, setTab] = useState('upcoming');
  const [upcoming, setUpcoming] = useState(null);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api.matches.upcoming(), api.matches.results()])
      .then(([u, r]) => { setUpcoming(u); setResults(r); })
      .catch((e) => setError(e.message));
  }, []);

  const list = tab === 'upcoming' ? upcoming : results;

  return (
    <div className="p-4 max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">Матчи</h2>

      <div className="flex bg-zinc-800 rounded-lg p-1 mb-4 max-w-xs">
        <button onClick={() => setTab('upcoming')}
          className={`flex-1 py-2 text-sm rounded ${tab === 'upcoming' ? 'bg-rm-gold text-zinc-900 font-semibold' : 'text-zinc-400'}`}>
          Расписание
        </button>
        <button onClick={() => setTab('results')}
          className={`flex-1 py-2 text-sm rounded ${tab === 'results' ? 'bg-rm-gold text-zinc-900 font-semibold' : 'text-zinc-400'}`}>
          Результаты
        </button>
      </div>

      {error && <div className="text-red-400 mb-4">Ошибка: {error}</div>}
      {list == null && !error && <div className="text-zinc-500">Загрузка...</div>}
      {list?.length === 0 && (
        <div className="text-zinc-500">
          {tab === 'upcoming' ? 'Нет запланированных матчей' : 'Нет результатов'}
        </div>
      )}

      <div className="space-y-3">
        {tab === 'upcoming' && upcoming?.map((m) => (
          <UpcomingCard key={m.id} m={m} />
        ))}
        {tab === 'results' && results?.map((r) => (
          <ResultCard key={r.match_id} r={r} />
        ))}
      </div>
    </div>
  );
}
