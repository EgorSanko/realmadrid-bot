// Данные для /dev/ui — из утверждённых макетов design/screens/a-*.html.
import type {
  FixtureRowProps,
  MomentumPoint,
  PitchPlayer,
  Shot,
  StandingRow,
  TeamRef,
  TimelineItem,
} from '../ui';

export const TEAM = {
  real: { id: 8633, name: 'Real Madrid' },
  roma: { id: 8686, name: 'Roma' },
  sevilla: { id: 8302, name: 'Sevilla' },
  barcelona: { id: 8634, name: 'Barcelona' },
  atletico: { id: 9906, name: 'Atlético Madrid' },
} satisfies Record<string, TeamRef>;

export const LEAGUE = {
  laliga: { id: 87, name: 'Ла Лига', short: 'ЛЛ', tone: 'gold' as const },
  ucl: { id: 42, name: 'Лига чемпионов', short: 'ЛЧ', tone: 'ucl' as const },
};

export const PLAYER_ID = {
  mbappe: 701154,
  vinicius: 846033,
  bellingham: 1077894,
  courtois: 170323,
  valverde: 743533,
  guler: 1253890,
  rudiger: 276738,
  tchouameni: 914458,
};

/** Вс, 18 октября, 22:00 МСК */
export const NEXT_KICKOFF = '2026-10-18T19:00:00Z';
/** Roma 3–4 Real Madrid, 14.10.2026, 21:00 по Риму = 22:00 МСК */
export const ROMA_KICKOFF = '2026-10-14T19:00:00Z';

/* ---------- Хронология Roma 3–4 Real ---------- */

export const TIMELINE: TimelineItem[] = [
  { minute: 20, side: 'home', type: 'goal', player: 'de Roon', detail: 'пас Soulé', score: [1, 0] },
  { minute: 25, side: 'away', type: 'goal', player: 'Mbappé', detail: 'пас Diomande', score: [1, 1] },
  { kind: 'divider', label: 'Перерыв · 1:1' },
  { minute: 51, side: 'home', type: 'goal', player: 'Malen', detail: 'пас Mora', score: [2, 1] },
  { minute: 57, side: 'home', type: 'goal', player: 'Malen', detail: 'пас Soulé', score: [3, 1] },
  { minute: 60, side: 'home', type: 'yellow', player: 'Mancini' },
  { minute: 69, side: 'home', type: 'yellow', player: 'Wesley' },
  { minute: 82, side: 'away', type: 'goal', player: 'Espí', detail: 'пас Endrick', score: [3, 2] },
  { minute: 85, side: 'away', type: 'goal', player: 'Endrick', detail: 'пас Güler', score: [3, 3] },
  { minute: 89, side: 'home', type: 'yellow', player: 'Pellegrini' },
  { minute: 90, side: 'away', type: 'goal', player: 'Rüdiger', detail: 'пас Güler', score: [3, 4] },
  { minute: 90, side: 'away', type: 'yellow', player: 'Carreras' },
];

export const SCORERS = {
  home: [
    { name: 'Malen', minutes: ['51′', '57′'] },
    { name: 'de Roon', minutes: ['20′'] },
  ],
  away: [
    { name: 'Mbappé', minutes: ['25′'] },
    { name: 'Espí', minutes: ['82′'] },
    { name: 'Endrick', minutes: ['85′'] },
    { name: 'Rüdiger', minutes: ['90′'] },
  ],
};

/* ---------- Состав Реала: a-match-lineup.html ---------- */

// В макете .pl — блок 64 px, левый верх в пикселях поля 358×470; центр кружка = (left + 32, top + 20).
// Переводим обратно в координаты FotMob verticalLayout: y от своих ворот, x зеркально (см. Pitch.mirrorX).
const fromMockup = (left: number, top: number) => ({
  x: +(1 - (left + 32) / 358).toFixed(4),
  y: +(1 - (top + 20) / 470).toFixed(4),
});

export const LINEUP: PitchPlayer[] = [
  { id: PLAYER_ID.courtois, name: 'Courtois', number: 1, rating: 6.4, ...fromMockup(147, 395) },
  { name: 'Dumfries', number: 24, rating: 5.7, ...fromMockup(283, 306) },
  { name: 'Konaté', number: 16, rating: 6.2, ...fromMockup(190, 306) },
  { id: PLAYER_ID.rudiger, name: 'Rüdiger', number: 22, rating: 7.3, ...fromMockup(104, 306) },
  { name: 'Cucurella', number: 17, rating: 6.3, ...fromMockup(11, 306) },
  { id: PLAYER_ID.valverde, name: 'Valverde', number: 8, rating: 7.2, ...fromMockup(219, 216) },
  { id: PLAYER_ID.tchouameni, name: 'Tchouaméni', number: 14, rating: 6.9, ...fromMockup(75, 216) },
  { name: 'Diomande', number: 25, rating: 8.5, ...fromMockup(269, 122) },
  { id: PLAYER_ID.bellingham, name: 'Bellingham', number: 5, rating: 7.4, ...fromMockup(147, 122) },
  { id: PLAYER_ID.vinicius, name: 'Vinícius', number: 7, rating: 5.7, ...fromMockup(25, 122) },
  { id: PLAYER_ID.mbappe, name: 'Mbappé', number: 10, rating: 8.2, ...fromMockup(147, 33) },
];

export const SUBS = [
  { id: PLAYER_ID.guler, name: 'Arda Güler', note: 'вышел на 59′ · 2 голевые передачи', rating: 8.3 },
  { name: 'Endrick', note: 'гол и голевая передача', goal: true },
  { name: 'Carlos Espí', note: 'гол', goal: true },
];

/* ---------- Давление: высоты столбиков из a-match-stats.html (из 56 px), вверх — Roma ---------- */

const MOM_PX = [0, 12, 3, 56, -3, -4, 18, 9, -17, 24, 24, -34, 0, 36, 56, 3, -20, -56, -6, 2, -3, -30, -56, -3];
export const MOMENTUM: MomentumPoint[] = MOM_PX.map((h, i) => ({
  minute: Math.round(((i + 1) * 90) / MOM_PX.length),
  value: Math.round((h / 56) * 1000) / 10,
}));

/* ---------- Удары Реала: точки из a-match-stats.html ---------- */

// svg 326×170, 1 м = 324/68 px; r = 3 + 14.4·xG — обратный пересчёт в координаты FotMob
const S = 324 / 68;
const shot = (cx: number, cy: number, r: number, outcome: Shot['outcome']): Shot => ({
  x: +(105 - (cy - 1) / S).toFixed(2),
  y: +((cx - 1) / S).toFixed(2),
  xg: +((r - 3) / 14.4).toFixed(3),
  outcome,
});

export const SHOTS: Shot[] = [
  shot(155, 113, 3.4, 'missed'),
  shot(120, 62, 4.1, 'saved'),
  shot(128, 72, 4.8, 'blocked'),
  shot(171, 89, 3.7, 'missed'),
  shot(96, 38, 3.7, 'saved'),
  shot(137, 107, 3.3, 'missed'),
  shot(93, 46, 3.3, 'blocked'),
  shot(171, 37, 4.1, 'saved'),
  shot(142, 45, 3.7, 'missed'),
  shot(151, 34, 4.3, 'saved'),
  shot(121, 129, 3.4, 'missed'),
  shot(112, 65, 3.4, 'missed'),
  shot(203, 114, 3.7, 'goal'),
  shot(173, 11, 9.3, 'goal'),
  shot(149, 38, 4.0, 'goal'),
  shot(151, 19, 6.4, 'goal'),
];

/* ---------- Статистика ---------- */

export const STATS: Array<{ label: string; home: string; away: string; bar?: boolean; better?: 'none' }> = [
  { label: 'Владение', home: '54%', away: '46%', bar: true },
  { label: 'Ожидаемые голы (xG)', home: '1.41', away: '1.43' },
  { label: 'Удары', home: '14', away: '16' },
  { label: 'В створ', home: '7', away: '8' },
  { label: 'Голевые моменты', home: '3', away: '4' },
  { label: 'Касания в штрафной', home: '24', away: '36' },
  { label: 'Точные передачи', home: '469 (86%)', away: '385 (83%)' },
  { label: 'Угловые', home: '5', away: '9' },
  { label: 'Жёлтые карточки', home: '3', away: '1', better: 'none' },
];

/* ---------- Календарь и результаты: a-fixtures.html ---------- */

export const UPCOMING: FixtureRowProps[] = [
  { kind: 'upcoming', kickoff: NEXT_KICKOFF, home: TEAM.real, away: TEAM.sevilla, competition: LEAGUE.laliga, note: 'Бернабеу', highlighted: true, href: '#' },
  { kind: 'upcoming', kickoff: '2026-10-21T19:00:00Z', home: TEAM.real, away: { name: 'RB Leipzig' }, competition: LEAGUE.ucl, note: 'Бернабеу', href: '#' },
  { kind: 'upcoming', kickoff: '2026-10-25T20:00:00Z', home: TEAM.barcelona, away: TEAM.real, competition: LEAGUE.laliga, note: 'Эль Класико', href: '#' },
  { kind: 'upcoming', kickoff: '2026-11-01T15:15:00Z', home: { name: 'Racing Santander' }, away: TEAM.real, competition: LEAGUE.laliga, note: 'Сантандер', href: '#' },
];

export const RESULTS: FixtureRowProps[] = [
  { kind: 'result', kickoff: ROMA_KICKOFF, home: TEAM.roma, away: TEAM.real, score: [3, 4], result: 'W', href: '#' },
  { kind: 'result', kickoff: '2026-10-10T19:00:00Z', home: TEAM.real, away: { name: 'Villarreal' }, score: [1, 0], result: 'W', href: '#' },
  { kind: 'result', kickoff: '2026-09-20T19:00:00Z', home: TEAM.atletico, away: TEAM.real, score: [2, 1], result: 'L', href: '#' },
  { kind: 'result', kickoff: '2026-09-15T19:00:00Z', home: { name: 'Elche' }, away: TEAM.real, score: [2, 3], result: 'W', href: '#' },
];

export const STANDINGS: StandingRow[] = [
  { pos: 1, team: TEAM.barcelona, played: 8, goalsFor: 34, goalsAgainst: 7, points: 24 },
  { pos: 2, team: { ...TEAM.atletico, name: 'Atlético' }, played: 8, goalsFor: 18, goalsAgainst: 8, points: 19 },
  { pos: 3, team: { name: 'Real Betis' }, played: 8, goalsFor: 14, goalsAgainst: 9, points: 19 },
  { pos: 4, team: TEAM.real, played: 8, goalsFor: 19, goalsAgainst: 8, points: 18 },
  { pos: 5, team: TEAM.sevilla, played: 8, goalsFor: 13, goalsAgainst: 12, points: 14 },
  { pos: 6, team: { name: 'Deportivo' }, played: 9, goalsFor: 13, goalsAgainst: 11, points: 13 },
];

/* ---------- Медиа и прогнозы ---------- */

export const NEWS = [
  { title: '«Реал» близок к продлению контракта с Беллингемом до 2031 года', source: 'Спорт-Экспресс' },
  { title: 'Апелляция «Реала» на дисквалификацию Винисиуса отклонена — бразилец пропустит класико', source: 'Спорт-Экспресс' },
  { title: '«Реал» проявляет интерес к 15-летнему таланту из «Спортинга»', source: 'Чемпионат' },
];

export const VIDEOS = [
  'Getting READY for SEVILLA with some BRILLIANT goals!',
  'Simply, Antonioooo!',
  'WHAT a header!',
  'C. Espí time!',
];

export const LEADERBOARD = [
  { rank: 1, name: 'Дмитрий С.', points: 47 },
  { rank: 2, name: 'Мадридиста_07', points: 44 },
  { rank: 3, name: 'Анна В.', points: 41 },
  { rank: 4, name: 'Сергей П.', points: 38 },
  { rank: 5, name: 'Карим Т.', points: 36 },
];
