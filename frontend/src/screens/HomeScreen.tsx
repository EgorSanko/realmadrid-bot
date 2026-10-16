import { useEffect, useMemo, useState } from 'react';
import { ScreenHeader } from '../components/ScreenHeader';
import { StreamBlock } from '../components/StreamBlock';
import type { ApiHome } from '../lib/api';
import {
  errorText,
  formResults,
  heroOf,
  homePollMs,
  lastMatchOf,
  leagueSummary,
  matchStatusOf,
  splitFixtures,
  staleNote,
} from '../lib/mapMatches';
import { useSpaLink } from '../lib/spaLink';
import { useStream } from '../lib/stream';
import { usePoll } from '../lib/usePoll';
import { EmptyState, ErrorState, FormStrip, MatchCard, Skeleton, plural } from '../ui';
import { CalendarRow, HeroMatchCard } from '../ui/matchExtra';
import './screens.css';

/** Тик раз в минуту — для подписи «обновлено N мин назад» и смены «только что сыгран» → «ближайший». */
function useNow(stepMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), stepMs);
    return () => window.clearInterval(t);
  }, [stepMs]);
  return now;
}

export default function HomeScreen() {
  const stream = useStream();
  const home = usePoll<ApiHome>('/api/home', (d) => homePollMs(d));
  const link = useSpaLink();
  const now = useNow();

  useEffect(() => {
    document.title = 'Мадридиста';
  }, []);

  const d = home.data;
  const view = useMemo(() => {
    if (!d) return null;
    const hero = heroOf(d, now);
    const last = lastMatchOf(d);
    // если сверху итог только что сыгранного матча — ниже показываем следующий, а не тот же матч ещё раз
    const heroIsLast = hero != null && last != null && hero.id === last.id;
    const nextRow =
      heroIsLast && d.next && matchStatusOf(d.next.status) === 'upcoming'
        ? splitFixtures([d.next], 'all').upcoming[0]
        : null;
    return { hero, last: heroIsLast ? null : last, nextRow, form: formResults(d), league: leagueSummary(d) };
  }, [d, now]);

  const note = d ? staleNote(d, home.receivedAt ? (now - home.receivedAt) / 1000 : 0) : null;
  const err = errorText(home.error);
  const live = view?.hero?.status === 'live';

  return (
    <main className="home">
      <ScreenHeader title="Главная" brand live={!!stream?.live} />

      {/* 1. Ближайший матч / идёт / итог */}
      {!d && home.loading ? (
        <Skeleton shape="match" className="hero-wrap" />
      ) : !d ? (
        <ErrorState title={err.title} text={err.text} onRetry={home.reload} />
      ) : view?.hero ? (
        <HeroMatchCard
          {...view.hero}
          {...link(view.hero.href)}
          onKickoff={home.reload}
          footer={note && <p className="screen-note">{note}</p>}
        />
      ) : (
        <EmptyState title="Ближайших матчей нет" text="Расписание появится, как только его опубликуют" />
      )}

      {/* 2. Трансляция (этап 3) — без изменений */}
      <StreamBlock stream={stream} />

      {/* 3. Прогноз: пока только вход в раздел, ввод — на следующем этапе */}
      <a className="ui-card home-predict" {...link('/predict')}>
        <span className="home-predict__head">
          <span className="home-predict__title">Твой прогноз</span>
          <span className="home-predict__aside">{live ? 'матч уже идёт' : 'приём до начала матча'}</span>
        </span>
        <span className="home-predict__row">
          <span className="home-predict__cta">Сделать прогноз на матч</span>
          <svg className="home-predict__chev" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </span>
      </a>

      {/* 4. Форма и место в Ла Лиге */}
      {!d && home.loading ? (
        <div className="home-grid" aria-hidden="true">
          <Skeleton height={104} radius={20} />
          <Skeleton height={104} radius={20} />
        </div>
      ) : (
        view &&
        (view.form.length > 0 || view.league) && (
          <div className="home-grid">
            {view.form.length > 0 && (
              <section className="home-tile" aria-label="Форма">
                <div className="home-tile__cap">Форма, {view.form.length} {plural(view.form.length, ['матч', 'матча', 'матчей'])}</div>
                <FormStrip results={view.form} size={24} className="home-tile__form" />
              </section>
            )}
            {view.league && (
              <a className="home-tile" aria-label="Таблица Ла Лиги" {...link('/matches')}>
                <div className="home-tile__cap">Ла Лига</div>
                <div className="home-tile__pos">
                  <span className="disp">{view.league.pos}</span>
                  <span>{view.league.line}</span>
                </div>
                {view.league.gap && <div className="home-tile__cap home-tile__gap">{view.league.gap}</div>}
              </a>
            )}
          </div>
        )
      )}

      {/* 5. Прошлый матч (или следующий, если сверху итог только что сыгранного) */}
      {!d && home.loading ? (
        <div className="home-skel-last" aria-hidden="true">
          <Skeleton height={86} radius={20} />
        </div>
      ) : view?.last ? (
        <MatchCard
          status="finished"
          competition={view.last.competition}
          kickoff={view.last.kickoff}
          home={view.last.home}
          away={view.last.away}
          score={view.last.score}
          caption="Прошлый матч"
          actionLabel="Обзор"
          {...link(view.last.href)}
        />
      ) : view?.nextRow ? (
        <section className="ui-card home-next" aria-label="Следующий матч">
          <div className="home-tile__cap">Следующий матч</div>
          <CalendarRow {...view.nextRow} highlighted={false} {...link(view.nextRow.href)} />
        </section>
      ) : null}

      {/* 6. НОВОСТИ — место для блока агента «Медиа» (этап 9): заголовок «Новости» + «Все» → /media,
          2–3 NewsItem из ui/media.tsx. Подключается при слиянии; здесь намеренно пусто. */}
    </main>
  );
}
