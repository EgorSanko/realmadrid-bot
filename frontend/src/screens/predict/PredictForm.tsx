import { useEffect, useMemo, useState } from 'react';
import type { MouseEvent } from 'react';
import { LoginButton } from '../../components/LoginButton';
import { AuthFetchError, authFetch, inMiniApp, useAuth } from '../../lib/auth';
import { competitionOf } from '../../lib/mapMatches';
import { livePoints, predictError, rmGoals, scorerName, shortName, teamIdOf } from '../../lib/predict';
import type { NextMatch, PredictionView, SquadPlayer } from '../../lib/predict';
import { Badge, Button, Chip, Countdown, PlayerPhoto, ScorePicker, ScoreStepper, TeamCrest, formatKickoff, formatTime, formatWeekdayShort } from '../../ui';

type Msg = { tone: 'ok' | 'err'; text: string } | null;

interface SaveState {
  busy: boolean;
  msg: Msg;
  needLogin: boolean;
}

/** Сохранение прогноза: PUT /api/predict/matches/{id}; ошибки — по-русски (lib/predict.predictError). */
function useSave(match: NextMatch, onSaved: (p: PredictionView) => void, onClosed: () => void) {
  const [st, setSt] = useState<SaveState>({ busy: false, msg: null, needLogin: false });
  useEffect(() => {
    if (!st.msg || st.msg.tone !== 'ok') return;
    const t = window.setTimeout(() => setSt((s) => ({ ...s, msg: null })), 3000);
    return () => window.clearTimeout(t);
  }, [st.msg]);
  const save = async (home: number, away: number, scorer: string | null) => {
    setSt({ busy: true, msg: null, needLogin: false });
    try {
      const body: Record<string, unknown> = { home, away };
      if (scorer != null) body.first_scorer_id = scorer;
      const r = await authFetch<PredictionView & { match_id: string }>(`/api/predict/matches/${encodeURIComponent(match.id)}`, {
        method: 'PUT',
        body,
      });
      onSaved({ home: r.home, away: r.away, first_scorer_id: r.first_scorer_id, updated_at: r.updated_at, revisions: r.revisions });
      setSt({ busy: false, msg: { tone: 'ok', text: 'Прогноз сохранён' }, needLogin: false });
    } catch (e) {
      const fe = e instanceof AuthFetchError ? e : new AuthFetchError(0, null, '');
      const { kind, message } = predictError(fe.status, fe.code, fe.message);
      setSt({ busy: false, msg: { tone: 'err', text: message }, needLogin: kind === 'auth' });
      if (kind === 'closed') onClosed();
    }
  };
  return { ...st, save };
}

function initial(m: NextMatch): [number, number, string | null] {
  const p = m.my_prediction;
  return p ? [p.home, p.away, p.first_scorer_id ?? null] : [0, 0, null];
}

function Team({ t, align }: { t: NextMatch['home']; align: 'start' | 'end' }) {
  const id = teamIdOf(t);
  return (
    <span className={`pd-team pd-team--${align}`}>
      {id != null && <TeamCrest id={id} name="" size={36} />}
      <span className="pd-team__name">{t.name}</span>
    </span>
  );
}

function ScorerPicker({
  squad,
  value,
  onChange,
  disabled,
}: {
  squad: SquadPlayer[];
  value: string | null;
  onChange: (id: string | null) => void;
  disabled: boolean;
}) {
  return (
    <div className="pd-scorers" role="radiogroup" aria-label="Автор первого гола Реала">
      <button
        type="button"
        role="radio"
        aria-checked={value == null}
        className={`pd-scorer pd-scorer--none${value == null ? ' is-on' : ''}`}
        onClick={() => onChange(null)}
      >
        <span className="pd-scorer__none" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="8" />
            <path d="M7 17L17 7" />
          </svg>
        </span>
        <span className="pd-scorer__name">Не выбирать</span>
      </button>
      {squad.map((p) => {
        const on = value === p.id;
        const pid = Number(p.id);
        return (
          <button
            key={p.id}
            type="button"
            role="radio"
            aria-checked={on}
            aria-label={p.name}
            title={p.name}
            disabled={disabled}
            className={`pd-scorer${on ? ' is-on' : ''}`}
            onClick={() => onChange(on ? null : p.id)}
          >
            <PlayerPhoto id={Number.isFinite(pid) && pid > 0 ? pid : undefined} name="" size={48} />
            <span className="pd-scorer__name">{shortName(p.name)}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Только чтение: приём закрыт (матч идёт или вот-вот начнётся). */
function ClosedView({ match }: { match: NextMatch }) {
  const p = match.my_prediction;
  const live = livePoints(match);
  const sc = match.score;
  const scorer = scorerName(match.rm_squad, p?.first_scorer_id);
  return (
    <div className="pd-closed">
      <div className="pd-closed__head">
        <span className="pd-closed__lock">Приём закрыт</span>
        {match.status === 'live' && <Badge tone="live">LIVE</Badge>}
        {sc && (
          <span className="pd-closed__score" aria-label={`Счёт ${sc.home}:${sc.away}`}>
            {sc.home}:{sc.away}
          </span>
        )}
      </div>
      {p ? (
        <p className="pd-closed__mine">
          Твой прогноз <b>{p.home}:{p.away}</b>
          {scorer && <> · {scorer}</>}
          {live && <span className="pd-closed__pts"> · пока +{live.total}</span>}
        </p>
      ) : (
        <p className="pd-muted">Прогноз на этот матч ты не сделал — до встречи на следующем.</p>
      )}
    </div>
  );
}

export interface PredictFormProps {
  match: NextMatch;
  onSaved: (p: PredictionView) => void;
  /** приём закрылся (обратный отсчёт дошёл до нуля или сервер ответил 409) — перечитать матч */
  onClosed: () => void;
}

/** Карточка прогноза на ближайший матч — полная, для /predict. */
export function PredictForm({ match, onSaved, onClosed }: PredictFormProps) {
  const auth = useAuth();
  const [[home, away, scorerRaw], setVals] = useState(() => initial(match));
  const savedKey = `${match.id}:${match.my_prediction?.updated_at ?? ''}`;
  useEffect(() => setVals(initial(match)), [savedKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const s = useSave(match, onSaved, onClosed);
  const comp = competitionOf(match.tournament ?? null);
  const realGoals = rmGoals(home, away, match.rm_side);
  const scorer = realGoals > 0 ? scorerRaw : null;
  const p = match.my_prediction;
  const dirty = !p || p.home !== home || p.away !== away || (p.first_scorer_id ?? null) !== scorer;
  const anonSite = auth.status === 'anon' && !inMiniApp();
  const squad = useMemo(() => match.rm_squad, [match.rm_squad]);

  return (
    <section className="ui-card pd-match" aria-label="Прогноз на матч">
      <div className="pd-match__meta">
        <Chip label={comp.name} tone={comp.tone === 'ucl' ? 'ucl' : 'gold'} leagueId={comp.withLogo ? comp.id : undefined} />
        <span>{formatKickoff(match.kickoff_utc)}</span>
      </div>
      <div className="pd-teams">
        <Team t={match.home} align="start" />
        <Team t={match.away} align="end" />
      </div>

      {!match.accepting ? (
        <ClosedView match={match} />
      ) : (
        <>
          <ScorePicker>
            <ScoreStepper teamName={match.home.name} value={home} max={20} onChange={(v) => setVals([v, away, scorerRaw])} />
            <ScoreStepper teamName={match.away.name} value={away} max={20} onChange={(v) => setVals([home, v, scorerRaw])} />
          </ScorePicker>
          <div className="pd-cap">
            <span>Первый гол Реала забьёт</span>
            <span className="pd-cap__pts">+2</span>
          </div>
          {squad.length > 0 ? (
            <ScorerPicker squad={squad} value={scorer} disabled={realGoals === 0} onChange={(id) => setVals([home, away, id])} />
          ) : (
            <p className="pd-muted">Состав на матч ещё не известен — автора гола можно будет выбрать позже.</p>
          )}
          {realGoals === 0 && squad.length > 0 && <p className="pd-hint">По твоему прогнозу Реал не забивает — бомбардира не выбрать.</p>}

          {anonSite ? (
            <div className="pd-login">
              <LoginButton hint="Войдите через Telegram, чтобы сохранить прогноз и попасть в рейтинг." />
            </div>
          ) : auth.status !== 'user' ? (
            <p className="pd-muted pd-login">Входим через Telegram…</p>
          ) : (
            <Button className="pd-save" disabled={s.busy || !dirty} onClick={() => void s.save(home, away, scorer)}>
              {s.busy ? 'Сохраняем…' : !dirty ? 'Прогноз сохранён' : p ? 'Изменить прогноз' : 'Сохранить прогноз'}
            </Button>
          )}
          {s.msg && (
            <p className={`pd-msg pd-msg--${s.msg.tone}`} role={s.msg.tone === 'err' ? 'alert' : 'status'}>
              {s.msg.text}
            </p>
          )}
          {s.needLogin && !inMiniApp() && <LoginButton compact />}
          <div className="pd-deadline">
            <span>Приём до начала матча</span>
            <Countdown to={match.closes_at} onEnd={onClosed} className="pd-cd" endedLabel="Приём закрыт" />
          </div>
        </>
      )}
    </section>
  );
}

/** Компактный ввод на главной: счёт + «Сохранить» + «Подробнее». */
export function PredictInline({ match, onSaved, onClosed, more }: PredictFormProps & { more: { href: string; onClick: (e?: MouseEvent<HTMLElement>) => void } }) {
  const auth = useAuth();
  const [[home, away], setVals] = useState(() => initial(match));
  const savedKey = `${match.id}:${match.my_prediction?.updated_at ?? ''}`;
  const [editing, setEditing] = useState(!match.my_prediction);
  useEffect(() => {
    setVals(initial(match));
    setEditing(!match.my_prediction);
  }, [savedKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const s = useSave(match, onSaved, onClosed);
  const p = match.my_prediction;
  // бомбардира на главной не меняем: сохраняем выбранного на /predict, если Реал по-прежнему забивает
  const keepScorer = p?.first_scorer_id && rmGoals(home, away, match.rm_side) > 0 ? p.first_scorer_id : null;
  const dirty = !p || p.home !== home || p.away !== away;
  const anonSite = auth.status === 'anon' && !inMiniApp();
  const live = livePoints(match);
  const ids = [teamIdOf(match.home), teamIdOf(match.away)];

  const crests = (
    <span className="hp-teams" role="img" aria-label={`${match.home.name} — ${match.away.name}`}>
      {ids.map((id, i) => (id != null ? <TeamCrest key={i} id={id} name="" size={24} /> : <span key={i} className="ui-crest-gap" style={{ width: 24, height: 24 }} />))}
    </span>
  );

  let body;
  if (!match.accepting) {
    body = (
      <div className="hp-line">
        {crests}
        <span className="hp-line__text">
          {p ? (
            <>
              Твой прогноз <b>{p.home}:{p.away}</b>
              {live ? <span className="hp-gold"> · пока +{live.total}</span> : ' · приём закрыт'}
            </>
          ) : (
            'Приём закрыт — матч уже начался'
          )}
        </span>
      </div>
    );
  } else if (p && !editing) {
    body = (
      <div className="hp-line">
        {crests}
        <span className="hp-line__text">
          Твой прогноз <b>{p.home}:{p.away}</b> ·{' '}
          <button type="button" className="hp-link" onClick={() => setEditing(true)}>
            изменить
          </button>
        </span>
      </div>
    );
  } else {
    body = (
      <>
        <div className="hp-pick">
          {crests}
          <ScorePicker>
            <ScoreStepper className="hp-step" teamName={match.home.name} value={home} max={20} onChange={(v) => setVals([v, away, null])} />
            <ScoreStepper className="hp-step" teamName={match.away.name} value={away} max={20} onChange={(v) => setVals([home, v, null])} />
          </ScorePicker>
        </div>
        {anonSite ? (
          <LoginButton compact hint="Войдите через Telegram, чтобы сохранить прогноз." />
        ) : (
          <Button
            className="hp-save"
            disabled={s.busy || !dirty || auth.status !== 'user'}
            onClick={() => void s.save(home, away, keepScorer)}
          >
            {s.busy ? 'Сохраняем…' : auth.status !== 'user' ? 'Входим через Telegram…' : 'Сохранить'}
          </Button>
        )}
      </>
    );
  }

  return (
    <section className="ui-card home-predict hp" aria-label="Твой прогноз">
      <div className="home-predict__head">
        <span className="home-predict__title">Твой прогноз</span>
        <a className="hp-more" {...more}>
          Подробнее
          <svg className="home-predict__chev" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </a>
      </div>
      <p className="home-predict__aside hp-aside">
        {match.accepting
          ? `приём до ${formatWeekdayShort(match.closes_at)}, ${formatTime(match.closes_at)} МСК`
          : match.status === 'live'
            ? 'матч идёт'
            : 'приём закрыт'}
      </p>
      {body}
      {s.msg && (
        <p className={`pd-msg pd-msg--${s.msg.tone}`} role={s.msg.tone === 'err' ? 'alert' : 'status'}>
          {s.msg.text}
        </p>
      )}
    </section>
  );
}
