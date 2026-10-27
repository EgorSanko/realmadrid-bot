import { useCallback, useEffect, useRef, useState } from 'react';
import { GamesTabs } from '../../components/GamesTabs';
import type { ApiHome } from '../../lib/api';
import { useApiResource } from '../../lib/apiResource';
import { BOT_USERNAME, inMiniApp, useAuth } from '../../lib/auth';
import { PENALTY_LEVELS, bestFor, levelTitle, moveZone, penaltyHeadline, shareText, shotMarks } from '../../lib/games';
import type { GameResult, PenaltyLevel, PenaltyShot, PenaltyStart } from '../../lib/games';
import { REAL_ID, outcomeText, rivalFrom, shotOutcome } from '../../lib/penalty';
import type { PenaltyOutcome } from '../../lib/penalty';
import { t, tc } from '../../lib/i18n';
import { shareLink } from '../../lib/share';
import ballSrc from '../../assets/games/ball.webp';
import diveSrc from '../../assets/games/courtois-dive.webp';
import idleSrc from '../../assets/games/courtois-idle.webp';
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

type Flash = { title: string; sub: string; rival: string; outcome: PenaltyOutcome } | null;
type Rival = { id: number; name: string } | null;

/** после удара: надпись и счёт видны ещё столько, потом — следующий удар */
const HOLD_MS = 700;

/** картинки Куртуа и мяча — заранее, пока выбирают уровень (только на экране пенальти) */
function preloadSprites() {
  for (const src of [idleSrc, diveSrc, ballSrc]) {
    const img = new Image();
    img.decoding = 'async';
    img.src = src;
  }
}

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
  const home = useApiResource<ApiHome>('/api/home');
  const rival = rivalFrom(home.data);

  useEffect(() => {
    document.title = t('Пенальти — игра «Мадридиста»');
    preloadSprites();
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
      scene.current?.prepare();
      try {
        const r = await gamesFetch<PenaltyShot>(`/penalty/${s.session}/shot`, { zone });
        const outcome = shotOutcome(r);
        const text = outcomeText(outcome);
        await scene.current?.play({
          zone: r.zone,
          keeper: r.keeper,
          outcome,
          onImpact: () => {
            // сейв — тяжёлый удар, гол — «успех», каркас — жёсткий щелчок
            if (outcome === 'goal') haptic.notify('success');
            else if (outcome === 'save') haptic.impact('heavy');
            else haptic.impact('rigid');
            setFlash({ title: text.title, sub: text.sub, rival: r.rival_goal ? t('Соперник забил') : t('Соперник не забил'), outcome });
          },
        });
        const next: Series = {
          ...s,
          me: [...s.me, r.goal],
          rival: [...s.rival, r.rival_goal],
          goals: r.goals,
          rivalGoals: r.rival,
          sudden: r.sudden_next || r.phase === 'sudden',
        };
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
        <GamesHeader aside={tc('game', 'пенальти')} />
        <GamesTabs />
        <section className="gm-intro" aria-label={t('Пенальти')}>
          <h2 className="gm-intro__title">{t('Серия пенальти против соперника')}</h2>
          <p className="gm-muted">{t('5 ударов. Вратарь угадывает угол наугад — выбирайте зону. Ничья — бьём до первого промаха.')}</p>
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
        <GamesHeader aside={tc('game', 'пенальти')} />
        <GamesTabs />
        <PenaltyResult
          series={s}
          result={phase.result}
          best={bestFor('penalty', s.level, local, me)}
          record={!!phase.result.record || (!phase.result.saved && phase.localRecord)}
          authed={auth.status === 'user'}
          onAgain={() => void start(s.level)}
          onLevels={() => setPhase({ kind: 'pick' })}
          rival={rival}
        />
        <WeeklyBoard game="penalty" ver={ver} />
      </main>
    );
  }

  return (
    <main className="gm gm--play gm--pk">
      <GamesHeader aside={`${tc('game', 'пенальти')} · ${levelTitle('penalty', s.level)}`} />
      <GamesTabs />
      <Scoreboard s={s} rival={rival} />
      <p className={`pk-round${s.sudden ? ' is-sudden' : ''}`} aria-live="polite">
        {s.sudden ? t('Серия до промаха · удар {n}', { n: round }) : t('Удар {n} из 5', { n: Math.min(round, 5) })}
      </p>
      <div className="pk-wrap">
        <PenaltyScene ref={scene} aim={aim} disabled={busy} onShoot={(z) => void shoot(z)} onAim={setAim} />
        {flash && (
          <div className={`pk-flash pk-flash--${flash.outcome === 'post' || flash.outcome === 'bar' ? 'wood' : flash.outcome}`} role="status">
            <b>{flash.title}</b>
            <em>{flash.sub}</em>
            <span>{flash.rival}</span>
          </div>
        )}
      </div>
      {error && <ErrorNote text={error.text} />}
      <p className="gm-hint pk-hint">{t('Нажмите на угол ворот, проведите пальцем от мяча или 1–6 на клавиатуре')}</p>
      <div className="gm-play__foot">
        <button type="button" className="gm-link" onClick={() => setPhase({ kind: 'pick' })}>
          {t('Выйти к уровням')}
        </button>
      </div>
    </main>
  );
}

function Dots({ marks, label, live }: { marks: ReturnType<typeof shotMarks>; label: string; live?: boolean }) {
  const next = marks.indexOf('pending');
  const last = next < 0 ? marks.length - 1 : next - 1;
  return (
    <span className="pk-dots" role="img" aria-label={label}>
      {marks.map((m, i) => (
        <i
          key={i}
          className={`pk-dot pk-dot--${m}${live && i === next ? ' pk-dot--next' : ''}${live && i === last && m !== 'pending' ? ' pk-dot--new' : ''}`}
        >
          {m === 'goal' && (
            <svg viewBox="0 0 10 10" aria-hidden="true">
              <path d="M2 5.3 4.2 7.4 8.2 2.8" />
            </svg>
          )}
          {m === 'miss' && (
            <svg viewBox="0 0 10 10" aria-hidden="true">
              <path d="M2.8 2.8 7.2 7.2M7.2 2.8 2.8 7.2" />
            </svg>
          )}
        </i>
      ))}
    </span>
  );
}

function Scoreboard({ s, rival, live = true }: { s: Series; rival: Rival; live?: boolean }) {
  const n = Math.max(5, s.me.length);
  const rivalName = rival?.name ?? t('Соперник');
  return (
    <section className="pk-board" aria-label={t('Счёт серии {score}', { score: `${s.goals}:${s.rivalGoals}` })}>
      <div className="pk-board__side">
        <TeamCrest id={REAL_ID} name={t('Реал Мадрид')} size={28} />
        <span className="pk-board__name">{t('Реал')}</span>
        <Dots marks={shotMarks(s.me, n)} label={t('Наши удары: забито {n}', { n: s.goals })} live={live} />
      </div>
      <div className="pk-board__score">
        <b>{s.goals}</b>
        <span>:</span>
        <b>{s.rivalGoals}</b>
      </div>
      <div className="pk-board__side pk-board__side--rival">
        {rival ? (
          <TeamCrest id={rival.id} name={rival.name} size={28} className="pk-board__crest" />
        ) : (
          <span className="pk-board__rival" aria-hidden="true">
            {/* нейтральный силуэт игрока — пока нет данных о сопернике */}
            <svg viewBox="0 0 40 40">
              <circle cx="20" cy="15.5" r="7" />
              <path d="M6 40c1.2-8.4 6.8-13 14-13s12.8 4.6 14 13z" />
            </svg>
          </span>
        )}
        <span className="pk-board__name">{rivalName}</span>
        <Dots marks={shotMarks(s.rival, n)} label={t('Удары соперника ({name}): забито {n}', { name: rivalName, n: s.rivalGoals })} live={live} />
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
  rival,
}: {
  series: Series;
  result: GameResult;
  best: number | null;
  record: boolean;
  authed: boolean;
  onAgain: () => void;
  onLevels: () => void;
  rival: Rival;
}) {
  const [shareMsg, setShareMsg] = useState<string | null>(null);
  const again = useRef<HTMLButtonElement>(null);
  useEffect(() => again.current?.focus(), []);
  const share = async () => {
    const url = inMiniApp() ? `https://t.me/${BOT_USERNAME}?startapp=penalty` : `${location.origin}/games/penalty`;
    const r = await shareLink(url, shareText('penalty', series.level, result));
    setShareMsg(r === 'copied' ? t('Ссылка скопирована') : r === 'failed' ? t('Не удалось поделиться') : null);
  };
  return (
    <section className={`gm-result${result.won ? ' is-win' : ''}`} aria-label={t('Итог серии пенальти')}>
      {record && <span className="gm-result__badge">{t('Новый рекорд')}</span>}
      <p className="gm-result__level">{t('Пенальти')} · {levelTitle('penalty', series.level)}</p>
      <p className="gm-result__headline">{penaltyHeadline(result)}</p>
      <p className="gm-result__score gm-result__score--pk">
        {result.goals ?? series.goals}
        <span>:</span>
        {result.rival ?? series.rivalGoals}
      </p>
      <Scoreboard s={series} rival={rival} live={false} />
      <div className="gm-result__stats">
        <div>
          <b>{result.score}</b>
          <span>{t('очков')}</span>
        </div>
        <div>
          <b>{result.shots ?? series.me.length}</b>
          <span>{t('ударов')}</span>
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
