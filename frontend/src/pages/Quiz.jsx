// src/pages/Quiz.jsx — викторина с cooldown 24ч.
//
// Webapp-only (FEATURES.quiz). Free-play режим (без auth) тоже поддерживается.
// API:
//   GET /api/quiz/status              — cooldown info
//   GET /api/quiz/question?difficulty — вопрос (с auth, обновляет cooldown)
//   POST /api/quiz/answer             — отправка ответа
//   GET /api/quiz/freeplay/question?difficulty — без auth, без cooldown

import React, { useEffect, useState, useCallback } from 'react';
import { api, ApiError } from '@/lib/api.js';
import { isAuthenticated } from '@/lib/auth.js';
import LoginModal from '@/components/LoginModal.jsx';

const DIFFICULTIES = [
  { id: 'easy',   label: 'Лёгкий',   points: 5 },
  { id: 'medium', label: 'Средний',  points: 10 },
  { id: 'hard',   label: 'Сложный',  points: 15 },
  { id: 'expert', label: 'Эксперт',  points: 25 },
];

export default function Quiz() {
  const [mode, setMode] = useState('chooser'); // chooser | playing | result
  const [difficulty, setDifficulty] = useState(null);
  const [question, setQuestion] = useState(null);
  const [picked, setPicked] = useState(null);
  const [result, setResult] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [freeplay, setFreeplay] = useState(false);
  const [showLogin, setShowLogin] = useState(false);

  const loadStatus = useCallback(async () => {
    if (!isAuthenticated()) return;
    try {
      const s = await api.get('/quiz/status', { auth: 'required' });
      setStatus(s);
    } catch {}
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const startQuiz = async (d, isFree) => {
    setLoading(true); setError(null); setPicked(null); setResult(null);
    setDifficulty(d); setFreeplay(isFree);
    try {
      if (isFree) {
        const q = await api.get(`/quiz/freeplay/question?difficulty=${d}`, { auth: 'skip' });
        setQuestion(q);
        setMode('playing');
      } else {
        if (!isAuthenticated()) { setShowLogin(true); setLoading(false); return; }
        const q = await api.get(`/quiz/question?difficulty=${d}`, { auth: 'required' });
        setQuestion(q);
        setMode('playing');
      }
    } catch (e) {
      setError(e.body?.detail || e.message);
    } finally {
      setLoading(false);
    }
  };

  const submitAnswer = async (answerIndex) => {
    if (picked != null) return;
    setPicked(answerIndex);

    if (freeplay) {
      // Free-play: показываем правильный ответ локально
      setResult({ correct: answerIndex === question.correct, correct_index: question.correct, points_earned: 0 });
      setMode('result');
      return;
    }

    try {
      const r = await api.post('/quiz/answer',
        { difficulty, question: question.question, answer_index: answerIndex },
        { auth: 'required' });
      setResult(r);
      setMode('result');
      loadStatus();
    } catch (e) {
      setError(e.body?.detail || e.message);
    }
  };

  if (mode === 'chooser') {
    return (
      <div className="p-4 max-w-2xl mx-auto">
        <h2 className="text-2xl font-bold mb-4">Викторина</h2>

        {status && !status.available && (
          <div className="bg-zinc-800 rounded p-3 mb-4 text-center text-sm">
            Следующая викторина через {status.remaining_text}
          </div>
        )}

        <h3 className="text-sm text-zinc-400 mb-2">Выбери сложность (со ставкой очков):</h3>
        <div className="grid grid-cols-2 gap-2 mb-6">
          {DIFFICULTIES.map((d) => (
            <button key={d.id} onClick={() => startQuiz(d.id, false)}
              disabled={status && !status.available}
              className="bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 rounded p-4 text-left">
              <div className="font-semibold">{d.label}</div>
              <div className="text-rm-gold text-sm">+{d.points}</div>
            </button>
          ))}
        </div>

        <h3 className="text-sm text-zinc-400 mb-2">Или потренироваться (без очков):</h3>
        <div className="grid grid-cols-2 gap-2">
          {DIFFICULTIES.map((d) => (
            <button key={d.id} onClick={() => startQuiz(d.id, true)}
              className="bg-zinc-900 border border-zinc-700 rounded p-2 text-sm">
              {d.label}
            </button>
          ))}
        </div>

        {error && <div className="mt-4 text-red-400 text-sm">{error}</div>}

        <LoginModal open={showLogin} onClose={() => setShowLogin(false)} onLogin={() => { setShowLogin(false); loadStatus(); }} />
      </div>
    );
  }

  if (mode === 'playing' && question) {
    return (
      <div className="p-4 max-w-2xl mx-auto">
        <div className="bg-zinc-800 rounded-lg p-6">
          <div className="flex justify-between text-xs text-zinc-500 mb-3">
            <span>{difficulty.toUpperCase()}{freeplay ? ' · тренировка' : ''}</span>
            {question.timer_seconds && <span>{question.timer_seconds}с</span>}
          </div>

          <h3 className="text-lg font-semibold mb-6">{question.question}</h3>

          <div className="space-y-2">
            {question.answers.map((a, i) => (
              <button key={i} onClick={() => submitAnswer(i)} disabled={picked != null}
                className={`w-full text-left bg-zinc-900 rounded p-3 transition disabled:opacity-50 ${
                  picked === i ? 'border-2 border-rm-gold' : ''
                } ${picked != null ? '' : 'hover:bg-zinc-700'}`}>
                {a}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (mode === 'result' && result) {
    const correct = result.correct;
    return (
      <div className="p-4 max-w-2xl mx-auto">
        <div className={`rounded-lg p-6 text-center ${correct ? 'bg-green-900/50' : 'bg-red-900/50'}`}>
          <div className="text-6xl mb-4">{correct ? '✓' : '×'}</div>
          <div className="text-xl font-semibold mb-2">
            {correct ? 'Правильно!' : 'Неправильно'}
          </div>
          {!correct && question?.answers && result.correct_index >= 0 && (
            <div className="text-sm text-zinc-300 mb-2">
              Правильный ответ: <span className="font-semibold">{question.answers[result.correct_index]}</span>
            </div>
          )}
          {result.points_earned > 0 && (
            <div className="text-rm-gold text-lg mt-2">+{result.points_earned} очков</div>
          )}
          {result.new_balance != null && (
            <div className="text-sm text-zinc-400 mt-1">Баланс: {result.new_balance}</div>
          )}
        </div>

        <button onClick={() => { setMode('chooser'); setQuestion(null); setResult(null); }}
          className="w-full mt-4 bg-zinc-800 hover:bg-zinc-700 rounded p-3">
          К списку
        </button>
      </div>
    );
  }

  return <div className="p-8 text-zinc-500">Загрузка...</div>;
}
