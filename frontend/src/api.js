// src/lib/api.js — fetch wrapper for both targets.
//
// VITE_API_BASE differs per target:
//   webapp: /api (same-origin via nginx)
//   site:   https://realmadrid.lead-seek.ru/api
//
// Auth: caller sets Authorization header explicitly (no implicit credential).
// WebApp uses initData header, site uses Login Widget querystring.

import { API_BASE } from '@/config/features.js';

export class ApiError extends Error {
  constructor(status, body) {
    super(`API ${status}: ${typeof body === 'string' ? body : JSON.stringify(body).slice(0, 200)}`);
    this.status = status;
    this.body = body;
  }
}

async function _fetch(path, { method = 'GET', body, headers = {}, signal } = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  const opts = { method, headers: { ...headers }, signal };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(url, opts);
  let data = null;
  try {
    data = await r.json();
  } catch {
    data = await r.text();
  }
  if (!r.ok) throw new ApiError(r.status, data);
  return data;
}

export const api = {
  get: (path, opts) => _fetch(path, { ...opts, method: 'GET' }),
  post: (path, body, opts) => _fetch(path, { ...opts, method: 'POST', body }),

  // Endpoints
  news: {
    list: () => api.get('/news').then((r) => r.news || []),
    article: (link) => api.get(`/news/article?url=${encodeURIComponent(link)}`),
  },
  matches: {
    upcoming: () => api.get('/matches/upcoming').then((r) => r.matches || []),
    results:  () => api.get('/matches/results').then((r) => r.results || []),
    next:     () => api.get('/match/next'),
    details:  (id) => api.get(`/match/details/${id}`),
    analytics:() => api.get('/match/analytics'),
  },
  standings: () => api.get('/standings').then((r) => r.standings || []),
  bundle: () => api.get('/bundle'),
  health: () => api.get('/health'),
};
