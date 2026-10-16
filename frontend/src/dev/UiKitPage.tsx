import { useEffect, useState, type ReactNode } from 'react';
import {
  Badge,
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  EventIcon,
  FixtureRow,
  Flag,
  FormStrip,
  LeaderboardRow,
  LeagueLogo,
  MatchCard,
  MomentumChart,
  NewsItem,
  Pitch,
  PlayerPhoto,
  RatingChip,
  ScoreHeader,
  ScorePicker,
  ScoreStepper,
  SectionHeader,
  ShotMap,
  Skeleton,
  StandingsTable,
  StatRow,
  Tabs,
  TeamCrest,
  Timeline,
  VideoCard,
  shotSummary,
  type MatchEventType,
} from '../ui';
import {
  LEADERBOARD,
  LEAGUE,
  LINEUP,
  MOMENTUM,
  NEWS,
  NEXT_KICKOFF,
  PLAYER_ID,
  RESULTS,
  ROMA_KICKOFF,
  SCORERS,
  SHOTS,
  STANDINGS,
  STATS,
  SUBS,
  TEAM,
  TIMELINE,
  UPCOMING,
  VIDEOS,
} from './demoData';
import './uikit.css';

function Demo({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="kit-sec" data-demo={id} aria-labelledby={`kit-${id}`}>
      <h2 className="kit-sec__title" id={`kit-${id}`}>
        {title}
      </h2>
      {children}
    </section>
  );
}

const EVENT_TYPES: MatchEventType[] = ['goal', 'own-goal', 'penalty-missed', 'yellow', 'second-yellow', 'red', 'sub', 'var'];
const EVENT_NAMES: Record<MatchEventType, string> = {
  goal: 'гол',
  'own-goal': 'автогол',
  'penalty-missed': 'пенальти мимо',
  yellow: 'жёлтая',
  'second-yellow': '2-я жёлтая',
  red: 'красная',
  sub: 'замена',
  var: 'VAR',
};

/** Скрытая страница /dev/ui: все компоненты на данных из макетов. */
export default function UiKitPage() {
  const [matchTab, setMatchTab] = useState<'events' | 'lineup' | 'stats'>('events');
  const [period, setPeriod] = useState<'all' | '1' | '2'>('all');
  const [side, setSide] = useState<'real' | 'roma'>('real');
  const [scorer, setScorer] = useState('mbappe');
  const [pred, setPred] = useState<[number, number]>([2, 1]);
  const [ranking, setRanking] = useState<'season' | 'month' | 'friends'>('season');
  const [retries, setRetries] = useState(0);

  useEffect(() => {
    document.title = 'UI — Мадридиста';
  }, []);

  return (
    <main className="kit">
      <header className="topbar">
        <h1 className="topbar__title">UI-кит</h1>
        <span className="kit-muted">/dev/ui</span>
      </header>

      {/* ---------- базовые ---------- */}
      <Demo id="base" title="Базовые">
        <Card>
          <SectionHeader title="Новости" href="#" />
          <SectionHeader title="Ла Лига" aside="после 8 туров" style={{ marginTop: 14 }} />
          <div className="kit-row" style={{ marginTop: 16 }}>
            <Chip label="Ла Лига" />
            <Chip label="Ла Лига" leagueId={LEAGUE.laliga.id} />
            <Chip label="ЛЧ" tone="ucl" size="sm" />
            <Chip label="ЛЛ" size="sm" />
          </div>
          <div className="kit-row" style={{ marginTop: 12 }}>
            <Badge tone="live" />
            <Badge tone="live">В ЭФИРЕ</Badge>
            <Badge tone="injury" />
          </div>
        </Card>
        <SectionHeader title="Новости" href="#" page />
        <Tabs
          ariaLabel="Разделы матча"
          value={matchTab}
          onChange={setMatchTab}
          items={[
            { id: 'events', label: 'Обзор' },
            { id: 'lineup', label: 'Составы' },
            { id: 'stats', label: 'Статистика' },
          ]}
        />
        <Card>
          <Tabs
            variant="outline"
            ariaLabel="Период"
            value={period}
            onChange={setPeriod}
            items={[
              { id: 'all', label: 'Матч' },
              { id: '1', label: '1-й тайм' },
              { id: '2', label: '2-й тайм' },
            ]}
          />
          <Tabs
            variant="pill"
            ariaLabel="Команда"
            value={side}
            onChange={setSide}
            style={{ marginTop: 12 }}
            items={[
              { id: 'real', label: 'Real Madrid' },
              { id: 'roma', label: 'Roma' },
            ]}
          />
          <div style={{ display: 'grid', gap: 12, marginTop: 16 }}>
            <Button>Сохранить прогноз</Button>
            <Button variant="secondary">Весь матч: события, составы, статистика</Button>
            <Button variant="outline">Позвать друга в свою лигу</Button>
            <Button disabled>Приём прогнозов закрыт</Button>
          </div>
        </Card>
      </Demo>

      {/* ---------- состояния ---------- */}
      <Demo id="states" title="Загрузка, пусто, ошибка">
        <Skeleton shape="match" style={{ margin: '14px 16px 0' }} />
        <Card>
          <Skeleton shape="news" rows={2} />
        </Card>
        <Card>
          <Skeleton shape="list" rows={3} />
        </Card>
        <Card>
          <Skeleton shape="stats" rows={3} />
        </Card>
        <EmptyState title="Матчей пока нет" text="Календарь появится, когда лига опубликует расписание" />
        <ErrorState onRetry={() => setRetries((n) => n + 1)} text={retries ? `Попыток: ${retries}` : undefined} />
        <Card>
          <SectionHeader title="Таблица" />
          <ErrorState plain onRetry={() => setRetries((n) => n + 1)} />
        </Card>
      </Demo>

      {/* ---------- картинки ---------- */}
      <Demo id="images" title="Картинки">
        <Card>
          <div className="kit-cap">TeamCrest 24 / 36 / 52 / 68</div>
          {Object.values(TEAM).map((t) => (
            <div key={t.id} className="kit-row kit-row--crests">
              <TeamCrest id={t.id} name={t.name} size={24} />
              <TeamCrest id={t.id} name={t.name} size={36} />
              <TeamCrest id={t.id} name={t.name} size={52} />
              <TeamCrest id={t.id} name={t.name} size={68} />
              <span className="kit-name">{t.name}</span>
            </div>
          ))}
          <div className="kit-cap" style={{ marginTop: 14 }}>
            Пустая картинка 1×1 и несуществующий id — спрятаны, место держат
          </div>
          <div className="kit-row kit-row--crests kit-probe" data-probe="crest-fail">
            <TeamCrest id={1} name="Пустая 1×1" size={36} />
            <TeamCrest id={999999} name="Нет такой" size={36} />
            <span className="kit-name">← рамок нет</span>
          </div>
        </Card>
        <Card>
          <div className="kit-cap">PlayerPhoto 36 / 40 / 52 / 68 · без id — силуэт</div>
          <div className="kit-row kit-row--crests">
            <PlayerPhoto id={PLAYER_ID.mbappe} name="Kylian Mbappé" size={36} />
            <PlayerPhoto id={PLAYER_ID.vinicius} name="Vinícius Júnior" size={40} />
            <PlayerPhoto id={PLAYER_ID.bellingham} name="Jude Bellingham" size={52} />
            <PlayerPhoto id={PLAYER_ID.guler} name="Arda Güler" size={68} />
            <PlayerPhoto name="Endrick" size={52} />
          </div>
          <div className="kit-cap" style={{ marginTop: 14 }}>
            LeagueLogo · Flag
          </div>
          <div className="kit-row kit-row--crests">
            <LeagueLogo id={LEAGUE.laliga.id} name="LaLiga" size={36} />
            <LeagueLogo id={LEAGUE.ucl.id} name="Champions League" size={36} />
            <LeagueLogo id={LEAGUE.ucl.id} name="Champions League" size={24} />
            <Flag iso2="es" name="Испания" width={24} />
            <Flag iso2="fr" name="Франция" width={24} />
            <Flag iso2="br" name="Бразилия" width={24} />
            <Flag iso2="tr" name="Турция" width={24} />
          </div>
        </Card>
      </Demo>

      {/* ---------- матч ---------- */}
      <Demo id="match-card" title="MatchCard · Countdown">
        <div data-cmp="match-upcoming">
          <MatchCard
            status="upcoming"
            competition={LEAGUE.laliga}
            kickoff={NEXT_KICKOFF}
            home={TEAM.real}
            away={TEAM.sevilla}
            venue="Сантьяго Бернабеу, Мадрид"
          />
        </div>
        <div data-cmp="match-live">
          <MatchCard
            status="live"
            competition={LEAGUE.laliga}
            kickoff={NEXT_KICKOFF}
            home={TEAM.real}
            away={TEAM.sevilla}
            score={[2, 1]}
            minute="67′"
            period="2-й тайм"
          >
            <div className="kit-live-ev">
              <div className="kit-row">
                <span className="kit-min">12′</span>
                <EventIcon type="goal" />
                <span>Mbappé</span>
                <span className="kit-muted">пас Bellingham</span>
              </div>
              <div className="kit-row" style={{ justifyContent: 'flex-end' }}>
                <span className="kit-muted">гол Sevilla</span>
                <span className="kit-min" style={{ textAlign: 'right' }}>
                  38′
                </span>
              </div>
              <div className="kit-row">
                <span className="kit-min">55′</span>
                <EventIcon type="goal" />
                <span>Bellingham</span>
                <span className="kit-muted">пас Güler</span>
              </div>
            </div>
          </MatchCard>
        </div>
        <div data-cmp="match-finished">
          <MatchCard
            status="finished"
            caption="Прошлый матч"
            competition={LEAGUE.ucl}
            kickoff={ROMA_KICKOFF}
            home={TEAM.roma}
            away={TEAM.real}
            score={[3, 4]}
            href="#"
          />
        </div>
      </Demo>

      <Demo id="score-header" title="ScoreHeader">
        <div data-cmp="score-header">
          <ScoreHeader home={TEAM.roma} away={TEAM.real} status="finished" score={[3, 4]} kickoff={ROMA_KICKOFF} scorers={SCORERS} />
        </div>
        <ScoreHeader home={TEAM.real} away={TEAM.sevilla} status="live" score={[2, 1]} minute="67′" />
        <ScoreHeader home={TEAM.real} away={TEAM.sevilla} status="upcoming" kickoff={NEXT_KICKOFF} />
      </Demo>

      <Demo id="form" title="FormStrip · FixtureRow · StandingsTable">
        <div className="kit-grid2">
          <Card inset={false} style={{ padding: 16, borderRadius: 20 }}>
            <div className="kit-cap">Форма, 5 матчей</div>
            <FormStrip results={['W', 'W', 'L', 'W', 'W']} className="kit-mt12" />
          </Card>
          <Card inset={false} style={{ padding: 16, borderRadius: 20 }}>
            <div className="kit-cap">С ничьей</div>
            <FormStrip results={['D', 'W', 'L', 'D', 'W']} className="kit-mt12" />
          </Card>
        </div>
        <Card>
          <SectionHeader title="Ближайшие" />
          {UPCOMING.map((f, i) => (
            <FixtureRow key={i} {...f} />
          ))}
        </Card>
        <Card>
          <SectionHeader title="Результаты" />
          {RESULTS.map((f, i) => (
            <FixtureRow key={i} {...f} />
          ))}
        </Card>
        <div data-cmp="standings">
          <Card ariaLabel="Таблица Ла Лиги">
            <SectionHeader title="Ла Лига" aside="после 8 туров" />
            <StandingsTable
              rows={STANDINGS}
              highlightTeamId={TEAM.real.id}
              zones={[{ from: 1, to: 4, color: 'var(--gold)', label: 'зона Лиги чемпионов' }]}
              footnote="вся таблица — по нажатию"
            />
          </Card>
        </div>
      </Demo>

      <Demo id="timeline" title="EventIcon · Timeline">
        <Card>
          <div className="kit-icons">
            {EVENT_TYPES.map((t) => (
              <span key={t} className="kit-icon">
                <EventIcon type={t} />
                <span>{EVENT_NAMES[t]}</span>
              </span>
            ))}
          </div>
        </Card>
        <div data-cmp="timeline">
          <Card ariaLabel="Хронология">
            <SectionHeader title="Хронология" />
            <Timeline items={TIMELINE} />
          </Card>
        </div>
      </Demo>

      {/* ---------- составы и статистика ---------- */}
      <Demo id="pitch" title="Pitch · RatingChip">
        <div className="kit-lineup-head">
          <Tabs
            variant="pill"
            ariaLabel="Команда"
            value={side}
            onChange={setSide}
            items={[
              { id: 'real', label: 'Real Madrid' },
              { id: 'roma', label: 'Roma' },
            ]}
          />
          <div style={{ textAlign: 'right' }}>
            <div className="kit-formation">4-2-3-1</div>
            <div className="kit-cap">средняя оценка 7.0</div>
          </div>
        </div>
        <div data-cmp="pitch">
          <Pitch players={LINEUP} />
        </div>
        <Card ariaLabel="Замены">
          <SectionHeader title="Замены" />
          <div style={{ marginTop: 6 }}>
            {SUBS.map((s) => (
              <div key={s.name} className="kit-li">
                <PlayerPhoto id={s.id} name={s.name} size={36} />
                <div style={{ flex: 1 }}>
                  <div className="kit-li__name">{s.name}</div>
                  <div className="kit-cap">{s.note}</div>
                </div>
                {s.rating != null ? <RatingChip value={s.rating} /> : s.goal && <EventIcon type="goal" />}
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <div className="kit-row">
            <RatingChip value={8.7} />
            <RatingChip value={8.0} />
            <RatingChip value={7.4} />
            <RatingChip value={7.0} />
            <RatingChip value={6.9} />
            <RatingChip value={5.7} size="sm" />
          </div>
        </Card>
      </Demo>

      <Demo id="stats" title="MomentumChart · StatRow · ShotMap">
        <div data-cmp="momentum">
          <Card ariaLabel="Давление по ходу матча">
            <SectionHeader title="Давление" aside="вверх — Roma, вниз — Real" />
            <MomentumChart data={MOMENTUM} />
          </Card>
        </div>
        <div data-cmp="statrow">
          <Card ariaLabel="Статистика">
            <div className="ui-section-head">
              <span className="kit-cap">Roma</span>
              <h2 className="ui-section-head__title">Главное</h2>
              <span className="kit-cap">Real</span>
            </div>
            <Tabs
              variant="outline"
              ariaLabel="Период"
              value={period}
              onChange={setPeriod}
              style={{ marginTop: 12 }}
              items={[
                { id: 'all', label: 'Матч' },
                { id: '1', label: '1-й тайм' },
                { id: '2', label: '2-й тайм' },
              ]}
            />
            <div style={{ marginTop: 8 }}>
              {STATS.map((s) => (
                <StatRow key={s.label} {...s} />
              ))}
            </div>
          </Card>
        </div>
        <div data-cmp="shotmap">
          <Card ariaLabel="Карта ударов">
            <SectionHeader title="Удары Реала" aside={shotSummary(SHOTS)} />
            <ShotMap shots={SHOTS} ariaLabel="Карта ударов Реала по воротам Ромы" />
          </Card>
        </div>
      </Demo>

      {/* ---------- медиа и прогнозы ---------- */}
      <Demo id="media" title="VideoCard · NewsItem">
        <VideoCard title="Roma 3:4 Real Madrid" subtitle="Лига чемпионов · 14 октября" tag="Обзор матча" href="#" />
        <VideoCard
          title="Видеообзор: Roma 3:4 Real Madrid"
          subtitle="Камбэк за семь минут — три гола с 82-й"
          provider="YouTube"
          height={180}
          href="#"
        />
        <SectionHeader title="Видео клуба" href="#" style={{ margin: '22px 16px 0' }} />
        <div className="kit-hscroll">
          {VIDEOS.map((v) => (
            <VideoCard key={v} variant="tile" title={v} subtitle="Real Madrid · YouTube" href="#" />
          ))}
        </div>
        <SectionHeader title="Новости" href="#" page />
        <div style={{ margin: '0 16px' }}>
          {NEWS.slice(0, 2).map((n) => (
            <NewsItem key={n.title} {...n} href="#" />
          ))}
          <NewsItem {...NEWS[2]} href="#" imageUrl="/img/news/missing.jpg" />
        </div>
        <Card>
          <SectionHeader title="Новости" />
          <NewsItem variant="hero" {...NEWS[0]} href="#" />
          <div style={{ marginTop: 8 }}>
            {NEWS.slice(1).map((n) => (
              <NewsItem key={n.title} variant="list" {...n} href="#" />
            ))}
          </div>
        </Card>
      </Demo>

      <Demo id="predict" title="ScoreStepper · LeaderboardRow">
        <Card ariaLabel="Прогноз на матч">
          <div className="ui-mc__top ui-mc__top--sm">
            <Chip label="Ла Лига" />
            <span>Вс, 18 окт · 22:00</span>
          </div>
          <div className="kit-pred-teams">
            <span>Real Madrid</span>
            <span>Sevilla</span>
          </div>
          <div style={{ marginTop: 10 }}>
            <ScorePicker>
              <ScoreStepper teamName="Real Madrid" value={pred[0]} onChange={(v) => setPred([v, pred[1]])} />
              <ScoreStepper teamName="Sevilla" value={pred[1]} onChange={(v) => setPred([pred[0], v])} />
            </ScorePicker>
          </div>
          <div className="kit-cap" style={{ marginTop: 16 }}>
            Первый гол Реала забьёт
          </div>
          <Tabs
            variant="pill"
            ariaLabel="Автор первого гола"
            value={scorer}
            onChange={setScorer}
            style={{ marginTop: 8 }}
            items={[
              { id: 'mbappe', label: 'Mbappé' },
              { id: 'vinicius', label: 'Vinícius' },
              { id: 'bellingham', label: 'Bellingham' },
              { id: 'guler', label: 'Güler' },
            ]}
          />
          <Button style={{ marginTop: 16 }}>Сохранить прогноз</Button>
        </Card>
        <Card ariaLabel="Рейтинг">
          <SectionHeader title="Рейтинг" />
          <Tabs
            ariaLabel="Период рейтинга"
            inset={false}
            value={ranking}
            onChange={setRanking}
            style={{ margin: '12px 0 4px' }}
            items={[
              { id: 'season', label: 'Сезон' },
              { id: 'month', label: 'Месяц' },
              { id: 'friends', label: 'Друзья' },
            ]}
          />
          {LEADERBOARD.map((r) => (
            <LeaderboardRow key={r.rank} {...r} />
          ))}
          <LeaderboardRow rank={12} name="Ты" points={21} isMe />
          <Button variant="outline" href="#" style={{ marginTop: 14 }}>
            Позвать друга в свою лигу
          </Button>
        </Card>
      </Demo>
    </main>
  );
}
