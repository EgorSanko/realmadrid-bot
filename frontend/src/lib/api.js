// src/lib/api.js — fetch wrapper for both targets.
//
// VITE_API_BASE differs per target:
//   webapp: /api (same-origin via nginx)
//   site:   https://realmadrid.lead-seek.ru/api
//
// Auth: caller sets Authorization header explicitly (no implicit credential).
// WebApp uses initData header, site uses Login Widget querystring.

import { API_BASE } from '@/config/features.js';
import { authHeader } from '@/lib/auth.js';

export class ApiError extends Error {
  constructor(status, body) {
    super(`API ${status}: ${typeof body === 'string' ? body : JSON.stringify(body).slice(0, 200)}`);
    this.status = status;
    this.body = body;
  }
}

async function _fetch(path, { method = 'GET', body, headers = {}, signal, auth = 'auto' } = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  const opts = { method, headers: { ...headers }, signal };
  // auth='auto' — добавить заголовок если залогинен; 'required' — кинуть ошибку если нет; 'skip' — не добавлять.
  if (auth !== 'skip') {
    const h = authHeader();
    if (h) Object.assign(opts.headers, h);
    else if (auth === 'required') throw new ApiError(401, 'No authorization');
  }
  if (body !== undefined) {
    if (body instanceof FormData) {
      opts.body = body;
    } else {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
  }
  const r = await fetch(url, opts);
  let data = null;
  try {
    data = await r.json();
  } catch {
    data = await r.text();
  }
  if (!r.ok) {
    // 401 — событие для UI: подписка на это даёт глобальный re-login flow.
    if (r.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('rm:auth-expired'));
    }
    throw new ApiError(r.status, data);
  }
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
  user: {
    me: () => api.get('/user/me', { auth: 'required' }),
    bets: (limit = 20) => api.get(`/user/bets?limit=${limit}`, { auth: 'required' }).then((r) => r.bets || []),
    predictions: (limit = 20) => api.get(`/user/predictions?limit=${limit}`, { auth: 'required' }).then((r) => r.predictions || []),
    transactions: (limit = 50) => api.get(`/user/transactions?limit=${limit}`, { auth: 'required' }).then((r) => r.transactions || []),
  },
  streams: {
    list: () => api.get('/streams').then((r) => r.streams || []),
  },
};
