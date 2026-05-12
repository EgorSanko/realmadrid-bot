// src/config/features.js — build-time feature flags.
//
// Values come from .env.webapp / .env.site and are inlined by Vite at build time.
// esbuild tree-shakes any branch gated on `false`, so disabled features ship ZERO bytes.

export const TARGET = import.meta.env.VITE_TARGET;
export const AUTH_MODE = import.meta.env.VITE_AUTH_MODE;
export const API_BASE = import.meta.env.VITE_API_BASE;
export const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME;

export const FEATURES = {
  games: import.meta.env.VITE_FEATURE_GAMES === 'true',
  quiz: import.meta.env.VITE_FEATURE_QUIZ === 'true',
  purchase: import.meta.env.VITE_FEATURE_PURCHASE === 'true',
  stream: import.meta.env.VITE_FEATURE_STREAM === 'true',
};
