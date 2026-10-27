import { useCallback, useEffect, useRef, useState } from 'react';
import { GamesTabs } from '../../components/GamesTabs';
import { BOT_USERNAME, inMiniApp, useAuth } from '../../lib/auth';
import {
  ANSWER_LETTERS,
  QUIZ_LEVELS,
  answerFromKey,
  bestFor,
  levelTitle,
  ringOffset,
  shareText,
} from '../../lib/games';
import type { GameResult, QuizAnswer, QuizLevel, QuizQuestion, QuizStart } from '../../lib/games';
import { t } from '../../lib/i18n';
import { shareLink } from '../../lib/share';
import { LeagueLogo, PlayerPhoto, TeamCrest } from '../../ui';
import { ErrorNote, GamesHeader, LevelPicker, WeeklyBoard } from './common';
import { gamesFetch, haptic, reducedMotion, useGamesMe, useLocalBest } from './kit';
import './games.css';

type Phase =
  | { kind: 'pick' }
  | { kind: 'play'; level: QuizLevel; session: string; q: QuizQuestion | null; picked: number | null; res: QuizAnswer | null }
  | { kind: 'result'; level: QuizLevel; result: GameResult; localRecord: boolean };

const RING_R = 30;
const RING_C = 2 * Math.PI * RING_R;
/** сколько показываем подсветку ответа перед следующим вопросом */
const REVEAL_MS = 1500;

export default function QuizScreen() {
  const auth = useAuth();
  const [phase, setPhase] = useState<Phase>({ kind: 'pick' });
  const [error, setError] = useState<{ text: string; retry?: () => void } | null>(null);
  const [ver, setVer] = useState(0);
  const [local, saveLocal] = useLocalBest();
  const me = useGamesMe(ver);
  const busy = useRef(false);

  useEffect(() => {
    document.title = t('Викторина о «Реале» — Мадридиста');
  }, []);

  const loadNext = useCallback(async (level: QuizLevel, session: string) => {
    setError(null);
    try {
      const q = await gamesFetch<QuizQuestion>(`/quiz/${session}/next`, {});
      setPhase({ kind: 'play', level, session, q, picked: null, res: null });
    } catch (e) {
      setError({ text: (e as Error).message, retry: () => void loadNext(level, session) });
    }
  }, []);

  const start = useCallback(
    async (level: QuizLevel) => {
      if (busy.current) return;
      busy.current = true;
      setError(null);
      try {
        const s = await gamesFetch<QuizStart>('/quiz/start', { level });
        setPhase({ kind: 'play', level, session: s.session, q: null, picked: null, res: null });
        await loadNext(level, s.session);
      } catch (e) {
        setError({ text: (e as Error).message, retry: () => void start(level) });
      } finally {
        busy.current = false;
      }
    },
    [loadNext],
  );

  const finish = useCallback(
    (level: QuizLevel, result: GameResult) => {
      const localRecord = saveLocal('quiz', level, result.score);
      haptic.notify(result.record || localRecord ? 'success' : 'warning');
      setPhase({ kind: 'result', level, result, localRecord });
      setVer((v) => v + 1);
    },
    [saveLocal],
  );

  const answer = useCallback(
    async (choice: number | null) => {
      if (phase.kind !== 'play' || !phase.q || phase.picked !== null || phase.res || busy.current) return;
      busy.current = true;
      setError(null);
      const { level, session } = phase;
      setPhase({ ...phase, picked: choice ?? -1 });
      try {
        const res = await gamesFetch<QuizAnswer>(`/quiz/${session}/answer`, { choice });
        if (res.correct) haptic.impact('light');
        else haptic.notify('error');
        setPhase((p) => (p.kind === 'play' && p.session === session ? { ...p, res } : p));
        window.setTimeout(() => {
          busy.current = false;
          if (res.done && res.result) finish(level, res.result);
          else void loadNext(level, session);
        }, reducedMotion() ? 900 : REVEAL_MS);
      } catch (e) {
        busy.current = false;
        const msg = (e as Error).message;
        // ответ не принят (например, «слишком быстро») — вопрос остаётся открытым
        setPhase((p) => (p.kind === 'play' && p.session === session ? { ...p, picked: null } : p));
        setError({ text: msg });
      }
    },
    [phase, finish, loadNext],
  );

  if (phase.kind === 'pick') {
    return (
      <main className="gm">
        <GamesHeader aside={t('викторина')} />
        <GamesTabs />
        <section className="gm-intro" aria-label={t('Викторина')}>
          <h2 className="gm-intro__title">{t('Насколько хорошо ты знаешь «Реал»?')}</h2>
          <p className="gm-muted">{t('10 вопросов, 15 секунд на каждый. Серия верных ответов включает множитель ×2 и ×3.')}</p>
        </section>
        {error && <ErrorNote text={error.text} onRetry={error.retry} />}
        <LevelPicker<QuizLevel> levels={QUIZ_LEVELS} best={(l) => bestFor('quiz', l, local, me)} onPick={(l) => void start(l)} />
        <WeeklyBoard game="quiz" ver={ver} />
      </main>
    );
  }

  if (phase.kind === 'result') {
    return (
      <main className="gm">
        <GamesHeader aside={t('викторина')} />
        <GamesTabs />
        <QuizResult
          level={phase.level}
          result={phase.result}
          best={bestFor('quiz', phase.level, local, me)}
          record={!!phase.result.record || (!phase.result.saved && phase.localRecord)}
          authed={auth.status === 'user'}
          onAgain={() => void start(phase.level)}
          onLevels={() => setPhase({ kind: 'pick' })}
        />
        <WeeklyBoard game="quiz" ver={ver} />
      </main>
    );
  }

  return (
    <main className="gm gm--play">
      <GamesHeader aside={`${t('викторина')} · ${levelTitle('quiz', phase.level)}`} />
      <GamesTabs />
      {error && <ErrorNote text={error.text} onRetry={error.retry} />}
      {phase.q ? (
        <QuestionCard key={phase.q.index} q={phase.q} picked={phase.picked} res={phase.res} onAnswer={(c) => void answer(c)} />
      ) : (
        !error && <div className="gm-loading" aria-live="polite">{t('Готовим вопросы…')}</div>
      )}
      <div className="gm-play__foot">
        <button type="button" className="gm-link" onClick={() => setPhase({ kind: 'pick' })}>
          {t('Выйти к уровням')}
        </button>
      </div>
    </main>
  );
}

/* ---------- вопрос ---------- */

function QuestionCard({
  q,
  picked,
  res,
  onAnswer,
}: {
  q: QuizQuestion;
  picked: number | null;
  res: QuizAnswer | null;
  onAnswer: (choice: number | null) => void;
}) {
  const ring = useRef<SVGCircleElement>(null);
  const num = useRef<HTMLSpanElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const answered = picked !== null;
  const onAnswerRef = useRef(onAnswer);
  onAnswerRef.current = onAnswer;

  // таймер: кольцо и цифры обновляются на каждом кадре без перерисовки React
  useEffect(() => {
    if (answered) return;
    const deadline = performance.now() + q.left_s * 1000;
    let raf = 0;
    let shown = -1;
    const tick = () => {
      const left = Math.max(0, (deadline - performance.now()) / 1000);
      if (ring.current) ring.current.style.strokeDashoffset = String(ringOffset(left, q.timer_s, RING_C));
      const sec = Math.ceil(left);
      if (sec !== shown && num.current) {
        shown = sec;
        num.current.textContent = String(sec);
        box.current?.classList.toggle('is-hurry', sec <= 5);
      }
      if (left <= 0) {
        onAnswerRef.current(null);
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [q, answered]);

  // клавиатура: 1–4 / A–D
  useEffect(() => {
    if (answered) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const i = answerFromKey(e.key, e.code);
      if (i != null && i < q.a.length) {
        e.preventDefault();
        onAnswerRef.current(i);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [q, answered]);

  const mult = res ? res.multiplier : q.multiplier;
  const streak = res ? res.streak : q.streak;
  const score = res ? res.score : q.score;

  return (
    <section className="gm-q" aria-label={t('Вопрос {n} из {total}', { n: q.index + 1, total: q.total })}>
      <div className="gm-q__bar">
        <div className="gm-q__progress" aria-hidden="true">
          {Array.from({ length: q.total }, (_, i) => (
            <i key={i} className={i < q.index ? 'done' : i === q.index ? 'now' : undefined} />
          ))}
        </div>
        <div className="gm-q__meta">
          <span>
            {t('Вопрос')} <b>{q.index + 1}</b> {t('из {n}', { n: q.total })}
          </span>
          <span className="gm-q__score" aria-label={t('Счёт {score}', { score })}>
            {score}
          </span>
        </div>
      </div>

      <div className="gm-q__card">
        <div className="gm-q__top">
          <div ref={box} className={`gm-timer${res ? ' is-stopped' : ''}`} role="timer" aria-label={t('Осталось секунд')}>
            <svg viewBox="0 0 72 72" aria-hidden="true">
              <defs>
                <linearGradient id="gm-ring-grad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="#F4D57A" />
                  <stop offset="1" stopColor="#D4AF37" />
                </linearGradient>
              </defs>
              <circle className="gm-timer__track" cx="36" cy="36" r={RING_R} />
              <circle
                ref={ring}
                className="gm-timer__ring"
                cx="36"
                cy="36"
                r={RING_R}
                strokeDasharray={RING_C}
                strokeDashoffset={ringOffset(q.left_s, q.timer_s, RING_C)}
              />
            </svg>
            <span ref={num} className="gm-timer__num">
              {Math.ceil(q.left_s)}
            </span>
          </div>
          <div className={`gm-streak${streak >= 3 ? ' is-hot' : ''}`} aria-label={t('Серия {streak}, множитель ×{mult}', { streak, mult })}>
            <span className="gm-streak__label">{t('Серия')}</span>
            <span className="gm-streak__val">{streak}</span>
            <span className="gm-streak__mult">×{mult}</span>
          </div>
          {q.media && (
            <span className="gm-q__media">
              {q.media.type === 'player' ? (
                <PlayerPhoto id={q.media.id} name="" size={56} />
              ) : q.media.type === 'team' ? (
                <TeamCrest id={q.media.id} name="" size={56} />
              ) : (
                <LeagueLogo id={q.media.id} name="" size={52} />
              )}
            </span>
          )}
        </div>
        <h2 className="gm-q__text">{q.q}</h2>
      </div>

      <div className="gm-answers" role="group" aria-label={t('Варианты ответа')}>
        {q.a.map((text, i) => {
          let state = '';
          if (res) {
            if (i === res.correct_choice) state = ' is-right';
            else if (i === picked) state = ' is-wrong';
            else state = ' is-dim';
          } else if (i === picked) state = ' is-picked';
          return (
            <button key={i} type="button" className={`gm-ans${state}`} disabled={answered} onClick={() => onAnswer(i)}>
              <span className="gm-ans__key">{ANSWER_LETTERS[i]}</span>
              <span className="gm-ans__text">{text}</span>
              {res && i === res.correct_choice && (
                <svg className="gm-ans__mark" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 12.5l4.2 4.2L19 7" />
                </svg>
              )}
            </button>
          );
        })}
      </div>

      <div className="gm-q__feedback" aria-live="polite">
        {res &&
          (res.correct ? (
            <span className="gm-fb gm-fb--ok">
              {t('Верно!')} <b>+{res.points}</b>
              {res.multiplier > 1 && <em> ×{res.multiplier}</em>}
            </span>
          ) : res.timeout ? (
            <span className="gm-fb gm-fb--bad">{t('Время вышло')}</span>
          ) : (
            <span className="gm-fb gm-fb--bad">{t('Мимо — серия сброшена')}</span>
          ))}
        {!res && <span className="gm-hint">{t('Клавиши 1–4 или A–D')}</span>}
      </div>
    </section>
  );
}

/* ---------- итог ---------- */

function QuizResult({
  level,
  result,
  best,
  record,
  authed,
  onAgain,
  onLevels,
}: {
  level: QuizLevel;
  result: GameResult;
  best: number | null;
  record: boolean;
  authed: boolean;
  onAgain: () => void;
  onLevels: () => void;
}) {
  const [shareMsg, setShareMsg] = useState<string | null>(null);
  const again = useRef<HTMLButtonElement>(null);
  useEffect(() => again.current?.focus(), []);

  const share = async () => {
    const url = inMiniApp() ? `https://t.me/${BOT_USERNAME}?startapp=quiz` : `${location.origin}/games/quiz`;
    const r = await shareLink(url, shareText('quiz', level, result));
    setShareMsg(r === 'copied' ? t('Ссылка скопирована') : r === 'failed' ? t('Не удалось поделиться') : null);
  };

  return (
    <section className="gm-result" aria-label={t('Итог викторины')}>
      {record && <span className="gm-result__badge">{t('Новый рекорд')}</span>}
      <p className="gm-result__level">{t('Викторина')} · {levelTitle('quiz', level)}</p>
      <p className="gm-result__score">{result.score}</p>
      <p className="gm-result__unit">{t('очков')}</p>
      <div className="gm-result__stats">
        <div>
          <b>
            {result.correct ?? 0}/{result.total ?? 0}
          </b>
          <span>{t('верных ответов')}</span>
        </div>
        <div>
          <b>{result.best_streak ?? 0}</b>
          <span>{t('лучшая серия')}</span>
        </div>
        <div>
          <b>{best ?? result.score}</b>
          <span>{t('рекорд уровня')}</span>
        </div>
      </div>
      {!authed && <p className="gm-muted gm-result__note">{t('Без входа результат сохранён только на этом устройстве.')}</p>}
      <div className="gm-result__actions">
        <button ref={again} type="button" className="ui-btn ui-btn--primary ui-btn--block" onClick={onAgain}>
          {t('Ещё раз')}
        </button>
        <div className="gm-result__row">
          <button type="button" className="ui-btn ui-btn--secondary ui-btn--block" onClick={() => void share()}>
            {t('Поделиться')}
          </button>
          <button type="button" className="ui-btn ui-btn--outline ui-btn--block" onClick={onLevels}>
            {t('Другой уровень')}
          </button>
        </div>
        {shareMsg && <p className="gm-muted gm-result__note">{shareMsg}</p>}
      </div>
    </section>
  );
}
