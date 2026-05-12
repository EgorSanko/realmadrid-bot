// src/components/LoginModal.jsx — code-based login для site mode.
// В webapp mode не используется — там auth берётся из initData автоматически.

import React, { useEffect, useState, useCallback } from 'react';
import { requestLoginCode, pollLoginCode, botStartLink } from '@/lib/auth.js';
import { AUTH_MODE } from '@/config/features.js';

export default function LoginModal({ open, onClose, onLogin }) {
  const [stage, setStage] = useState('idle'); // idle | requesting | waiting | error
  const [code, setCode] = useState(null);
  const [error, setError] = useState(null);

  const start = useCallback(async () => {
    setStage('requesting');
    setError(null);
    try {
      const { code: c } = await requestLoginCode();
      setCode(c);
      setStage('waiting');
      const user = await pollLoginCode(c);
      onLogin?.(user);
      onClose?.();
    } catch (e) {
      setError(e.message);
      setStage('error');
    }
  }, [onLogin, onClose]);

  useEffect(() => {
    if (open && stage === 'idle') start();
  }, [open, stage, start]);

  if (!open || AUTH_MODE !== 'login-widget') return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="bg-zinc-900 rounded-lg p-6 max-w-md w-full">
        <div className="flex justify-between items-start mb-4">
          <h2 className="text-xl font-bold">Вход через Telegram</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-white">✕</button>
        </div>

        {stage === 'requesting' && (
          <div className="text-zinc-400">Запрашиваю код...</div>
        )}

        {stage === 'waiting' && code && (
          <div>
            <p className="text-zinc-300 mb-4">
              Нажмите кнопку, бот откроется в Telegram. После того как вы напишете /start —
              эта страница автоматически продолжит.
            </p>
            <a href={botStartLink(code)} target="_blank" rel="noopener"
               className="block w-full text-center bg-rm-gold text-zinc-900 font-semibold py-3 rounded mb-3">
              Открыть бота с кодом {code}
            </a>
            <div className="text-xs text-zinc-500 text-center">
              Код действителен 10 минут. Не закрывайте окно.
            </div>
          </div>
        )}

        {stage === 'error' && (
          <div>
            <div className="text-red-400 mb-3">Ошибка: {error}</div>
            <button onClick={start} className="px-4 py-2 bg-zinc-800 rounded">
              Повторить
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
