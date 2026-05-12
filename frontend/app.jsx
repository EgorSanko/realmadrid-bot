// src/app.jsx — entry point for both WebApp and public site.
// FEATURES gating + tree-shaking demo.

import React, { lazy, Suspense } from 'react';
import ReactDOM from 'react-dom/client';
import { FEATURES, TARGET, AUTH_MODE } from './config/features.js';
import './styles/tailwind.css';

// Feature-gated lazy import: when FEATURES.games is false (site build),
// esbuild sees the dead branch and tree-shakes the whole Games chunk.
const Games = FEATURES.games ? lazy(() => import('./pages/Games.jsx')) : null;

function App() {
  return (
    <div className="min-h-screen bg-zinc-900 text-white p-8">
      <h1 className="text-3xl font-bold mb-4">Real Madrid Hub</h1>
      <p className="text-zinc-400">Block 3 scaffold — single source, dual build.</p>

      <div className="mt-8 grid grid-cols-2 gap-4 max-w-lg">
        <div className="bg-zinc-800 p-4 rounded">
          <div className="text-xs text-zinc-500">TARGET</div>
          <div className="font-mono">{TARGET}</div>
        </div>
        <div className="bg-zinc-800 p-4 rounded">
          <div className="text-xs text-zinc-500">AUTH</div>
          <div className="font-mono">{AUTH_MODE}</div>
        </div>
      </div>

      <h2 className="text-xl font-semibold mt-8 mb-2">Feature flags</h2>
      <div className="grid grid-cols-2 gap-2 max-w-lg text-sm">
        {Object.entries(FEATURES).map(([k, v]) => (
          <div key={k} className="flex justify-between bg-zinc-800 px-3 py-2 rounded">
            <span className="text-zinc-400">{k}</span>
            <span className={v ? 'text-green-400' : 'text-red-400'}>
              {v ? 'on' : 'off'}
            </span>
          </div>
        ))}
      </div>

      {Games && (
        <div className="mt-8 max-w-lg">
          <Suspense fallback={<div className="text-zinc-500">loading games...</div>}>
            <Games />
          </Suspense>
        </div>
      )}
    </div>
  );
}

const root = document.getElementById('root');
if (root) {
  ReactDOM.createRoot(root).render(<App />);
}
