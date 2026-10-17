import { useCallback, useEffect, useRef, useState } from 'react';
import { GamesTabs } from '../../components/GamesTabs';
import { BOT_USERNAME, inMiniApp, useAuth } from '../../lib/auth';
import { PENALTY_LEVELS, bestFor, levelTitle, moveZone, penaltyHeadline, shareText, shotMarks } from '../../lib/games';
import type { GameResult, PenaltyLevel, PenaltyShot, PenaltyStart } from '../../lib/games';
import { shareLink } from '../../lib/share';
import { TeamCrest } from '../../ui';
import { ErrorNote, GamesHeader, LevelPicker, WeeklyBoard } from './common';
import { gamesFetch, haptic, useGamesMe, useLocalBest } from './kit';
import { PenaltyScene } from './PenaltyScene';
import type { SceneHandle } from './PenaltyScene';
import './games.css';

interface Series {
  level: PenaltyLevel;
  session: string;
  me: boolean[];
  rival: boolean[];
  goals: number;
  rivalGoals: number;
  sudden: boolean;
}

type Phase =
  | { kind: 'pick' }
  | { kind: 'play'; s: Series }
  | { kind: 'result'; s: Series; result: GameResult; localRecord: boolean };

type Flash = { text: string; sub: string; tone: 'goal' | 'save' } | null;

const HOLD_MS = 1000;

export default function PenaltyScreen() {
  const auth = useAuth();
  const [phase, setPhase] = useState<Phase>({ kind: 'pick' });
  const [error, setError] = useState<{ text: string; retry?: () => void } | null>(null);
  const [busy, setBusy] = useState(false);
  const [aim, setAim] = useState<number>(5);
  const [flash, setFlash] = useState<Flash>(null);
  const [ver, setVer] = useState(0);
  const [local, saveLocal] = useLocalBest();
  const me = useGamesMe(ver);
  const scene = useRef<SceneHandle>(null);
  const lock = useRef(false);

  useEffect(() => {
    document.title = 'Пенальти — игра «Мадридиста»';
  }, []);

  const start = useCallback(async (level: PenaltyLevel) => {
    if (lock.current) return;
    lock.current = true;
    setError(null);
    try {
      const r = await gamesFetch<PenaltyStart>('/penalty/start', { level });
      setFlash(null);
      setAim(5);
      setPhase({ kind: 'play', s: { level, session: r.session, me: [], rival: [], goals: 0, rivalGoals: 0, sudden: false } });
    } catch (e) {
      setError({ text: (e as Error).message, retry: () => void start(level) });
    } finally {
      lock.current = false;
    }
  }, []);

  const shoot = useCallback(
    async (zone: number) => {
      if (phase.kind !== 'play' || lock.current) return;
      lock.current = true;
      setBusy(true);
      setError(null);
      setAim(zone);
      const s = phase.s;
      haptic.impact('medium');
      try {
        const r = await gamesFetch<PenaltyShot>(`/penalty/${s.session}/shot`, { zone });
        await scene.current?.play({ zone: r.zone, keeper: r.keeper, goal: r.goal });
        if (r.goal) haptic.notify('success');
        else haptic.impact('heavy');
        const next: Series = {
          ...s,
          me: [...s.me, r.goal],
          rival: [...s.rival, r.rival_goal],
          goals: r.goals,
          rivalGoals: r.rival,
          sudden: r.sudden_next || r.phase === 'sudden',
        };
        setFlash({
          text: r.goal ? 'ГОЛ!' : 'СЕЙВ!',
          sub: r.rival_goal ? 'Соперник забил' : 'Соперник не забил',
          tone: r.goal ? 'goal' : 'save',
        });
        setPhase({ kind: 'play', s: next });
        await new Promise((res) => window.setTimeout(res, HOLD_MS));
        setFlash(null);
        if (r.done && r.result) {
          const localRecord = saveLocal('penalty', s.level, r.result.score);
          haptic.notify(r.result.won ? 'success' : 'warning');
          setPhase({ kind: 'result', s: next, result: r.result, localRecord });
          setVer((v) => v + 1);
        } else {
          scene.current?.reset();
        }
      } catch (e) {
        scene.current?.reset();
        setError({ text: (e as Error).message });
      } finally {
        lock.current = false;
        setBusy(false);
      }
    },
    [phase, saveLocal],
  );

  // клавиатура: 1–6 — удар в зону, стрелки — прицел, Enter/пробел — удар в прицел
  useEffect(() => {
    if (phase.kind !== 'play') return;
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (/^[1-6]$/.test(e.key)) {
        e.preventDefault();
        void shoot(Number(e.key));
      } else if (e.key.startsWith('Arrow')) {
        e.preventDefault();
        setAim((z) => moveZone(z, e.key));
      } else if ((e.key === 'Enter' || e.key === ' ') && !(e.target instanceof HTMLButtonElement)) {
        e.preventDefault();
        void shoot(aim);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [phase.kind, shoot, aim]);

  if (phase.kind === 'pick') {
    return (
      <main className="gm">
        <GamesHeader aside="пенальти" />
        <GamesTabs />
        <section className="gm-intro" aria-label="Пенальти">
          <h2 className="gm-intro__title">Серия пенальти против соперника</h2>
          <p className="gm-muted">5 ударов. Вратарь угадывает угол наугад — выбирайте зону. Ничья — бьём до первого промаха.</p>
        </section>
        {error && <ErrorNote text={error.text} onRetry={error.retry} />}
        <LevelPicker<PenaltyLevel> levels={PENALTY_LEVELS} best={(l) => bestFor('penalty', l, local, me)} onPick={(l) => void start(l)} />
        <WeeklyBoard game="penalty" ver={ver} />
      </main>
    );
  }

  const s = phase.s;
  const round = s.me.length + 1;

  if (phase.kind === 'result') {
    return (
      <main className="gm">
        <GamesHeader aside="пенальти" />
        <GamesTabs />
        <PenaltyResult
          series={s}
          result={phase.result}
          best={bestFor('penalty', s.level, local, me)}
          record={!!phase.result.record || (!phase.result.saved && phase.localRecord)}
          authed={auth.status === 'user'}
          onAgain={() => void start(s.level)}
          onLevels={() => setPhase({ kind: 'pick' })}
        />
        <WeeklyBoard game="penalty" ver={ver} />
      </main>
    );
  }

  return (
    <main className="gm gm--play gm--pk">
      <GamesHeader aside={`пенальти · ${levelTitle('penalty', s.level)}`} />
      <GamesTabs />
      <Scoreboard s={s} />
      <p className={`pk-round${s.sudden ? ' is-sudden' : ''}`} aria-live="polite">
        {s.sudden ? `Серия до промаха · удар ${round}` : `Удар ${Math.min(round, 5)} из 5`}
      </p>
      <div className="pk-wrap">
        <PenaltyScene ref={scene} aim={aim} disabled={busy} onShoot={(z) => void shoot(z)} onAim={setAim} />
        {flash && (
          <div className={`pk-flash pk-flash--${flash.tone}`} role="status">
            <b>{flash.text}</b>
            <span>{flash.sub}</span>
          </div>
        )}
      </div>
      {error && <ErrorNote text={error.text} />}
      <p className="gm-hint pk-hint">Нажмите на угол ворот, проведите пальцем от мяча или 1–6 на клавиатуре</p>
      <div className="gm-play__foot">
        <button type="button" className="gm-link" onClick={() => setPhase({ kind: 'pick' })}>
          Выйти к уровням
        </button>
      </div>
    </main>
  );
}

function Dots({ marks, label }: { marks: ReturnType<typeof shotMarks>; label: string }) {
  return (
    <span className="pk-dots" aria-label={label}>
      {marks.map((m, i) => (
        <i key={i} className={`pk-dot pk-dot--${m}`} />
      ))}
    </span>
  );
}

function Scoreboard({ s }: { s: Series }) {
  const n = Math.max(5, s.me.length);
  return (
    <section className="pk-board" aria-label={`Счёт серии ${s.goals}:${s.rivalGoals}`}>
      <div className="pk-board__side">
        <TeamCrest id={8633} name="Реал Мадрид" size={28} />
        <span className="pk-board__name">Реал</span>
        <Dots marks={shotMarks(s.me, n)} label={`Наши удары: забито ${s.goals}`} />
      </div>
      <div className="pk-board__score">
        <b>{s.goals}</b>
        <span>:</span>
        <b>{s.rivalGoals}</b>
      </div>
      <div className="pk-board__side pk-board__side--rival">
        <span className="pk-board__rival" aria-hidden="true">
          {/* нейтральный силуэт игрока — не эмблема */}
          <svg viewBox="0 0 40 40">
            <circle cx="20" cy="15.5" r="7" />
            <path d="M6 40c1.2-8.4 6.8-13 14-13s12.8 4.6 14 13z" />
          </svg>
        </span>
        <span className="pk-board__name">Соперник</span>
        <Dots marks={shotMarks(s.rival, n)} label={`Удары соперника: забито ${s.rivalGoals}`} />
      </div>
    </section>
  );
}

function PenaltyResult({
  series,
  result,
  best,
  record,
  authed,
  onAgain,
  onLevels,
}: {
  series: Series;
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
    const url = inMiniApp() ? `https://t.me/${BOT_USERNAME}?startapp=penalty` : `${location.origin}/games/penalty`;
    const r = await shareLink(url, shareText('penalty', series.level, result));
    setShareMsg(r === 'copied' ? 'Ссылка скопирована' : r === 'failed' ? 'Не удалось поделиться' : null);
  };
  return (
    <section className={`gm-result${result.won ? ' is-win' : ''}`} aria-label="Итог серии пенальти">
      {record && <span className="gm-result__badge">Новый рекорд</span>}
      <p className="gm-result__level">Пенальти · {levelTitle('penalty', series.level)}</p>
      <p className="gm-result__headline">{penaltyHeadline(result)}</p>
      <p className="gm-result__score gm-result__score--pk">
        {result.goals ?? series.goals}
        <span>:</span>
        {result.rival ?? series.rivalGoals}
      </p>
      <Scoreboard s={series} />
      <div className="gm-result__stats">
        <div>
          <b>{result.score}</b>
          <span>очков</span>
        </div>
        <div>
          <b>{result.shots ?? series.me.length}</b>
          <span>ударов</span>
        </div>
        <div>
          <b>{best ?? result.score}</b>
          <span>рекорд уровня</span>
        </div>
      </div>
      {!authed && <p className="gm-muted gm-result__note">Без входа результат сохранён только на этом устройстве.</p>}
      <div className="gm-result__actions">
        <button ref={again} type="button" className="ui-btn ui-btn--primary ui-btn--block" onClick={onAgain}>
          Ещё раз
        </button>
        <div className="gm-result__row">
          <button type="button" className="ui-btn ui-btn--secondary ui-btn--block" onClick={() => void share()}>
            Поделиться
          </button>
          <button type="button" className="ui-btn ui-btn--outline ui-btn--block" onClick={onLevels}>
            Другой уровень
          </button>
        </div>
        {shareMsg && <p className="gm-muted gm-result__note">{shareMsg}</p>}
      </div>
    </section>
  );
}
