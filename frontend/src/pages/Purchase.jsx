// src/pages/Purchase.jsx — покупка очков за рубли.
//
// Webapp-only (FEATURES.purchase).
// API:
//   GET  /api/purchase/config        — карта, цена, мин. покупка, пресеты сумм
//   POST /api/purchase (multipart)   — amount + receipt photo
//
// Админ получает уведомление в TG в фоне (request возвращается мгновенно).

import React, { useEffect, useState } from 'react';
import { api } from '@/lib/api.js';
import { isAuthenticated } from '@/lib/auth.js';
import LoginModal from '@/components/LoginModal.jsx';

export default function Purchase() {
  const [config, setConfig] = useState(null);
  const [amount, setAmount] = useState(100);
  const [receipt, setReceipt] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [showLogin, setShowLogin] = useState(false);

  useEffect(() => {
    api.get('/purchase/config').then(setConfig).catch(() => {});
  }, []);

  const copyCard = () => {
    if (!config?.card_number) return;
    navigator.clipboard?.writeText(config.card_number.replace(/\s/g, ''));
  };

  const submit = async () => {
    if (!isAuthenticated()) { setShowLogin(true); return; }
    if (!receipt) { setError('Прикрепи скрин чека'); return; }
    setError(null); setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append('amount', String(amount));
      fd.append('receipt', receipt);
      await api.post('/purchase', fd, { auth: 'required' });
      setSuccess(`Заявка на ${amount} очков отправлена. Админ подтвердит вручную.`);
      setReceipt(null);
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (!config) return <div className="p-8 text-zinc-500">Загрузка...</div>;

  const totalRub = Math.round(amount * (config.price_per_point || 2.5));

  return (
    <div className="p-4 max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">Покупка очков</h2>

      <div className="bg-zinc-800 rounded-lg p-4 mb-4">
        <div className="text-xs text-zinc-500 mb-1">Курс</div>
        <div className="font-semibold">1 очко = {config.price_per_point}₽</div>
        <div className="text-xs text-zinc-500 mt-2 mb-1">Минимум</div>
        <div>{config.min_purchase} очков</div>
      </div>

      <div className="bg-zinc-800 rounded-lg p-4 mb-4">
        <div className="text-xs text-zinc-500 mb-1">Карта для перевода ({config.card_bank})</div>
        <button onClick={copyCard} className="font-mono text-lg w-full text-left">
          {config.card_number} <span className="text-xs text-zinc-500 ml-2">нажми чтобы скопировать</span>
        </button>
      </div>

      <h3 className="text-sm text-zinc-400 mb-2">Сколько очков:</h3>
      <div className="grid grid-cols-4 gap-2 mb-3">
        {(config.amounts || [100, 250, 500, 1000]).map((a) => (
          <button key={a} onClick={() => setAmount(a)}
            className={`p-2 rounded text-sm ${
              amount === a ? 'bg-rm-gold text-zinc-900 font-semibold' : 'bg-zinc-800'
            }`}>
            {a}
          </button>
        ))}
      </div>

      <input
        type="number" min={config.min_purchase} value={amount}
        onChange={(e) => setAmount(Math.max(config.min_purchase, parseInt(e.target.value) || 0))}
        className="w-full bg-zinc-800 border border-zinc-700 rounded p-2 mb-3 text-center"
      />

      <div className="bg-zinc-900 border border-zinc-700 rounded p-3 mb-4 text-center">
        <span className="text-zinc-400">К оплате: </span>
        <span className="text-rm-gold font-bold text-xl">{totalRub}₽</span>
      </div>

      <h3 className="text-sm text-zinc-400 mb-2">Скрин чека:</h3>
      <input
        type="file" accept="image/*"
        onChange={(e) => setReceipt(e.target.files?.[0] || null)}
        className="w-full bg-zinc-800 border border-zinc-700 rounded p-2 mb-4 text-sm"
      />
      {receipt && <div className="text-xs text-zinc-500 mb-3">{receipt.name}</div>}

      {error && <div className="text-red-400 text-sm mb-3">{error}</div>}
      {success && <div className="bg-green-900/50 border border-green-700 rounded p-3 mb-3 text-sm text-green-300">{success}</div>}

      <button onClick={submit} disabled={submitting || !receipt}
        className="w-full bg-rm-gold text-zinc-900 font-bold py-3 rounded disabled:opacity-50">
        {submitting ? 'Отправка...' : 'Отправить заявку'}
      </button>

      <LoginModal open={showLogin} onClose={() => setShowLogin(false)}
        onLogin={() => setShowLogin(false)} />
    </div>
  );
}
