// Экран матча: маппинг настоящих ответов /api/match (фикстуры в src/__fixtures__) и состояния.
// Запуск: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fetchMatch, matchFingerprint, normalizeMatch, shouldPoll, type ApiMatch } from '../src/api/match.ts';
import {
  aboutRows,
  bestOfSide,
  compactTitle,
  formView,
  goalKey,
  h2hView,
  headerView,
  highlightView,
  lineupView,
  momentumView,
  potmView,
  realSide,
  returnText,
  shortName,
  shotsView,
  statPeriods,
  statsView,
  timelineView,
  tournamentLine,
} from '../src/screens/match/view.ts';

const fx = (name: string): ApiMatch =>
  normalizeMatch(JSON.parse(readFileSync(new URL(`../src/__fixtures__/${name}.json`, import.meta.url), 'utf8')));

const FOTMOB = fx('match_6106274');
const SOFA = fx('match_6106274_sofascore');
const ESPN = fx('match_6106274_espn');
const LS = fx('match_6106274_livescore');
const UPCOMING = fx('match_5868098');

const BEFORE_KICKOFF = Date.parse('2026-10-17T12:00:00Z');

/* ---------- FotMob, завершён ---------- */

test('fotmob: шапка завершённого матча, авторы голов', () => {
  const h = headerView(FOTMOB);
  assert.equal(h.phase, 'finished');
  assert.equal(h.status, 'finished');
  assert.deepEqual(h.score, [3, 4]);
  assert.equal(h.live, false);
  assert.equal(h.statusText, undefined); // «Матч завершён · 14 окт» пишет ScoreHeader
  assert.deepEqual(h.scorers.home, [
    { name: 'de Roon', minutes: ['20′'] },
    { name: 'Malen', minutes: ['51′', '57′'] },
  ]);
  assert.deepEqual(
    h.scorers.away.map((s) => s.name),
    ['Mbappé', 'Espí', 'Endrick', 'Rüdiger'],
  );
  assert.equal(tournamentLine(FOTMOB), 'Лига чемпионов · 2-й тур');
  assert.equal(compactTitle(FOTMOB), 'Roma 3 : 4 Real Madrid');
  assert.equal(realSide(FOTMOB), 'away');
});

test('fotmob: хронология — голы с пасами, карточки, замены, перерыв', () => {
  const { items, goalKeys } = timelineView(FOTMOB);
  const goals = items.filter((i) => i.kind !== 'divider' && i.type === 'goal');
  assert.equal(goals.length, 7);
  const first = goals[0];
  assert.ok(first.kind !== 'divider');
  assert.equal(first.player, 'de Roon');
  // ассистент — отдельно: фото и ссылка на карточку
  assert.deepEqual(first.related, { id: 1280082, name: 'Soulé', prefix: 'пас' });
  assert.equal(first.detail, undefined);
  assert.equal(first.playerId, 198559);
  assert.deepEqual(first.score, [1, 0]);
  const div = items.filter((i) => i.kind === 'divider');
  assert.deepEqual(div, [{ kind: 'divider', label: 'Перерыв · 1:1' }]); // конец матча — в шапке, не в ленте
  const subs = items.filter((i) => i.kind !== 'divider' && i.type === 'sub');
  assert.equal(subs.length, 10);
  const pis = subs[0];
  assert.ok(pis.kind !== 'divider');
  assert.equal(pis.player, 'Pisilli');
  assert.equal(pis.related?.prefix, 'ушёл');
  assert.equal(pis.related?.name, 'Koné');
  assert.equal(pis.related?.id, 1016132);
  assert.equal(pis.detail, 'травма');
  assert.equal(items.filter((i) => i.kind !== 'divider' && i.type === 'yellow').length, 4);
  assert.equal(goalKeys.filter(Boolean).length, 7);
  // голы Реала — справа (Реал в гостях)
  assert.ok(goals.slice(-3).every((g) => g.kind !== 'divider' && g.side === 'away'));
});

test('fotmob: лучший у Реала и игрок матча', () => {
  assert.deepEqual(bestOfSide(FOTMOB, 'away'), { id: 1735453, name: 'Diomande', rating: 8.5 });
  assert.deepEqual(potmView(FOTMOB), { id: 660301, name: 'Malen', rating: 8.7 });
});

test('fotmob: о матче и видеообзор (превью только с нашего сервера)', () => {
  assert.deepEqual(aboutRows(FOTMOB), [
    ['Стадион', 'Stadio Olimpico, Roma'],
    ['Зрители', '64 256'],
    ['Судья', 'François Letexier'],
  ]);
  const hl = highlightView(FOTMOB);
  assert.equal(hl?.href, 'https://www.youtube.com/watch?v=zkgpyvjJl84');
  assert.equal(hl?.thumb, '/img/yt/zkgpyvjJl84.jpg');
  assert.equal(hl?.provider, 'YouTube');
  assert.equal(hl?.title, 'Видеообзор: Roma 3:4 Real Madrid');
});

test('fotmob: состав Реала на поле — оси verticalLayout', () => {
  const lu = lineupView(FOTMOB, 'away');
  assert.ok(lu?.pitch);
  assert.equal(lu.formation, '4-2-3-1');
  assert.equal(lu.avgRating, 7);
  const by = (n: string) => lu.pitch!.find((p) => p.name === n)!;
  // y: от своих ворот (0) к чужим (1) — вратарь внизу, нападающий вверху
  assert.ok(by('Courtois').y < by('Mbappé').y);
  // x FotMob: 0 — правый фланг; Pitch по умолчанию зеркалит (left = 1 − x)
  assert.ok(1 - by('Dumfries').x > 0.5, 'Dumfries справа');
  assert.ok(1 - by('Cucurella').x < 0.5, 'Cucurella слева');
  assert.ok(1 - by('Vinícius').x < 0.5, 'Vinícius слева');
  assert.equal(by('Mbappé').rating, 8.2);
  // замены с событиями
  const guler = lu.subs.find((s) => s.name === 'Arda Güler')!;
  assert.equal(guler.detail, 'вышел на 59′ вместо Dumfries · 2 голевые передачи');
  assert.equal(guler.rating, 8.3);
  const endrick = lu.subs.find((s) => s.name === 'Endrick')!;
  assert.match(endrick.detail, /гол · голевая передача/);
  assert.equal(lu.coach, 'José Mourinho');
  assert.equal(lu.bench.length, 7);
});

test('fotmob: статистика по периодам, xG, точные передачи', () => {
  assert.deepEqual(statPeriods(FOTMOB), ['all', 'first_half', 'second_half']);
  const [main] = statsView(FOTMOB, 'all');
  assert.equal(main.title, 'Главное');
  const row = (k: string) => main.rows.find((r) => r.key === k)!;
  assert.equal(row('possession').home, '54%');
  assert.equal(row('possession').bar, true);
  assert.equal(row('xg').away, '1.43');
  assert.equal(row('passes_accurate').home, '469 (86%)');
  assert.equal(row('yellow_cards').better, 'none');
  assert.deepEqual(main.rows.map((r) => r.key), [
    'possession', 'xg', 'shots_total', 'shots_on_target', 'big_chances', 'touches_opp_box', 'passes_accurate', 'corners', 'yellow_cards',
  ]);
});

test('fotmob: карта ударов Реала — метры FotMob, у чужих ворот', () => {
  const s = shotsView(FOTMOB)!;
  assert.equal(s.summary, '16 ударов · xG 1.43');
  assert.equal(s.shots.length, 16);
  assert.equal(s.shots.filter((x) => x.outcome === 'goal').length, 4);
  // все удары — в атакующей половине (x > 52.5 м), гол Espí — с 2 м от линии ворот
  assert.ok(s.shots.every((x) => x.x > 52.5 && x.x <= 105 && x.y >= 0 && x.y <= 68));
  const espi = s.shots.find((x) => x.xg === 0.451)!;
  assert.ok(espi.x > 102 && Math.abs(espi.y - 32) < 0.5);
});

test('fotmob: давление — Реал золотом снизу', () => {
  const m = momentumView(FOTMOB)!;
  assert.equal(m.awayColor, 'var(--gold)');
  assert.equal(m.caption, 'вверх — Roma, вниз — Real');
  assert.deepEqual(m.ticks, ['0′', '45′', '90′']);
});

/* ---------- FotMob, до начала ---------- */

test('5868098: до начала — дата, отсчёт, ожидаемый состав, отсутствующие', () => {
  const h = headerView(UPCOMING, BEFORE_KICKOFF);
  assert.equal(h.phase, 'scheduled');
  assert.equal(h.status, 'upcoming');
  assert.equal(h.countdown, true);
  assert.equal(h.score, undefined);
  assert.equal(compactTitle(UPCOMING), 'Real Madrid — Sevilla');
  assert.equal(tournamentLine(UPCOMING), 'Ла Лига · 9-й тур');
  const lu = lineupView(UPCOMING, 'home')!;
  assert.equal(lu.confirmed, false);
  assert.equal(lu.avgRating, undefined);
  assert.deepEqual(
    lu.unavailable.map((u) => `${u.name}: ${u.reason}`),
    [
      'Éder Militao: травма, до конца октября',
      'Ferland Mendy: травма, вернулся к тренировкам',
      'Raúl Asencio: травма, до начала января',
      'Rodrygo: травма, до конца декабря',
      'Vinícius Júnior: дисквалификация, до начала ноября',
    ],
  );
  assert.equal(statPeriods(UPCOMING).length, 0);
  assert.equal(shotsView(UPCOMING), null);
  assert.equal(timelineView(UPCOMING).items.length, 0);
});

test('5868098: личные встречи и форма (Реал первым)', () => {
  const h = h2hView(UPCOMING)!;
  assert.equal(h.home.name, 'Real Madrid');
  assert.equal(h.home.wins, 29);
  assert.equal(h.draws, 3);
  assert.equal(h.matches.length, 5);
  assert.ok(h.matches.every((x) => x.result));
  assert.deepEqual(h.matches[0].score, [0, 1]);
  assert.equal(h.matches[0].result, 'W'); // Sevilla 0:1 Real
  const f = formView(UPCOMING)!;
  assert.equal(f[0].team.name, 'Real Madrid');
  assert.deepEqual(f[0].results, ['W', 'W', 'L', 'W', 'W']);
});

/* ---------- SofaScore-форма ---------- */

test('sofascore: те же голы, VAR в ленте, сроки отсутствующих из ISO-дат', () => {
  const h = headerView(SOFA);
  assert.deepEqual(h.score, [3, 4]);
  assert.deepEqual(h.scorers.home.map((s) => s.name), ['de Roon', 'Malen']);
  const { items } = timelineView(SOFA);
  assert.ok(items.some((i) => i.kind !== 'divider' && i.type === 'var'));
  assert.equal(tournamentLine(SOFA), 'Лига чемпионов · 2-й тур');
  const lu = lineupView(SOFA, 'away')!;
  assert.ok(lu.pitch && lu.pitch.length === 11);
  assert.ok(lu.unavailable.some((u) => u.reason === 'травма, до 10 января'));
  assert.ok(momentumView(SOFA));
  assert.equal(highlightView(SOFA), null);
  assert.equal(shotsView(SOFA)!.summary.startsWith('16 ударов · xG'), true);
});

/* ---------- ESPN-форма (урезанная) ---------- */

test('espn: без координат — список вместо поля, без оценок/ударов/давления', () => {
  assert.equal(tournamentLine(ESPN), 'Лига чемпионов');
  const lu = lineupView(ESPN, 'away')!;
  assert.equal(lu.pitch, null);
  assert.equal(lu.starters.length, 11);
  assert.ok(lu.starters.every((p) => p.rating === undefined));
  assert.equal(lu.starters[0].id, 170323); // фото — по id FotMob из ctx сборщика
  assert.deepEqual(statPeriods(ESPN), ['all']);
  assert.equal(shotsView(ESPN), null);
  assert.equal(momentumView(ESPN), null);
  assert.equal(potmView(ESPN), null);
  assert.equal(bestOfSide(ESPN, 'away'), null);
  assert.deepEqual(aboutRows(ESPN).map((r) => r[0]), ['Стадион', 'Зрители']);
  assert.equal(timelineView(ESPN).items.filter((i) => i.kind !== 'divider' && i.type === 'goal').length, 7);
});

/* ---------- LiveScore-форма ---------- */

test('livescore: удары без xG — подпись без xG, поле без оценок', () => {
  const s = shotsView(LS)!;
  assert.equal(s.summary, '16 ударов');
  const lu = lineupView(LS, 'away')!;
  assert.ok(lu.pitch);
  assert.equal(lu.avgRating, undefined);
  assert.ok(lu.pitch.every((p) => p.rating === undefined));
  assert.equal(momentumView(LS), null);
  assert.deepEqual(statPeriods(LS), ['all']);
  assert.ok(statsView(LS, 'all')[0].rows.some((r) => r.key === 'xg'));
});

/* ---------- состояния ---------- */

const live = (minute: number, extra: Partial<ApiMatch['status']> = {}): ApiMatch => {
  const events = FOTMOB.events.filter((e) => (e.minute ?? 0) <= minute && e.type !== 'period' && e.type !== 'added_time');
  const goals = events.filter((e) => e.type === 'goal');
  const last = goals.at(-1);
  const sc = last && last.type === 'goal' && last.score ? last.score : [0, 0];
  return {
    ...FOTMOB,
    status: { state: 'live', live: true, finished: false, minute, added: null, label: `${minute}'`, ...extra },
    home: { ...FOTMOB.home, score: sc[0] },
    away: { ...FOTMOB.away, score: sc[1] },
    events,
    highlights: null,
    available: FOTMOB.available.filter((k) => k !== 'highlights'),
  };
};

test('идёт: минута, LIVE, опрос', () => {
  const m = live(67);
  const h = headerView(m);
  assert.equal(h.phase, 'live');
  assert.equal(h.status, 'live');
  assert.equal(h.minute, '67′');
  assert.equal(h.live, true);
  assert.deepEqual(h.score, [3, 1]);
  assert.equal(compactTitle(m), 'Roma 3 : 1 Real Madrid');
  assert.equal(shouldPoll(m), true);
  assert.equal(headerView(live(90, { added: 4 })).minute, '90+4′');
});

test('перерыв: «Перерыв», LIVE, опрос', () => {
  const m = live(45, { state: 'halftime', minute: null });
  const h = headerView(m);
  assert.equal(h.phase, 'halftime');
  assert.equal(h.statusText, 'Перерыв');
  assert.equal(h.minute, undefined);
  assert.equal(h.live, true);
  assert.equal(shouldPoll(m), true);
});

test('завершён и до начала: без опроса; после времени начала, но без статуса — опрос', () => {
  assert.equal(shouldPoll(FOTMOB), false);
  assert.equal(shouldPoll(UPCOMING, BEFORE_KICKOFF), false);
  assert.equal(shouldPoll(UPCOMING, Date.parse('2026-10-18T19:01:00Z')), true);
  assert.equal(shouldPoll(UPCOMING, Date.parse('2026-10-19T03:00:00Z')), false);
  assert.equal(headerView(UPCOMING, Date.parse('2026-10-18T19:01:00Z')).countdown, false);
});

test('pending: шапка из календаря, опрос раз в 10 с', () => {
  const body = {
    id: 5868105,
    ids: { fotmob: 5868105 },
    kickoff: '2026-10-25T20:00:00Z',
    tournament: { id: 87, name: 'LaLiga', round: null, logo: '/img/league/87.png' },
    home: { id: 9906, name: 'Barcelona', score: null, logo: '/img/team/9906.png' },
    away: { id: 8633, name: 'Real Madrid', score: null, logo: '/img/team/8633.png' },
    status: { state: 'scheduled', live: false, finished: false, minute: null, added: null, label: null },
    is_home: false,
    events: [],
    lineups: null,
    stats: null,
    shots: [],
    momentum: [],
    potm: null,
    highlights: null,
    h2h: null,
    form: null,
    venue: null,
    available: [],
    pending: true,
    source: 'fotmob',
  } as unknown as ApiMatch;
  const m = normalizeMatch(body);
  const h = headerView(m, BEFORE_KICKOFF);
  assert.equal(h.phase, 'pending');
  assert.equal(h.status, 'upcoming');
  assert.equal(tournamentLine(m), 'Ла Лига');
  assert.equal(shouldPoll(m, BEFORE_KICKOFF), true);
  assert.equal(lineupView(m, 'away'), null);
  assert.equal(statPeriods(m).length, 0);
});

test('fetchMatch: 200 / 404 / 503 / сеть', async () => {
  const reply = (status: number, body: unknown) => async () => ({ ok: status < 400, status, json: async () => body });
  const ok = await fetchMatch(6106274, undefined, reply(200, FOTMOB));
  assert.equal(ok.kind, 'ok');
  assert.equal((await fetchMatch(1, undefined, reply(404, { error: 'not_found' }))).kind, 'not_found');
  const no = await fetchMatch(1, undefined, reply(503, { error: 'no_data', available: [] }));
  assert.equal(no.kind, 'unavailable');
  const bad = await fetchMatch(1, undefined, reply(200, { error: 'x' }));
  assert.equal(bad.kind, 'error');
  const net = await fetchMatch(1, undefined, async () => {
    throw new TypeError('Failed to fetch');
  });
  assert.deepEqual(net, { kind: 'error', message: 'Failed to fetch' });
});

test('лайв: новые голы определяются по ключу, отпечаток не зависит от age_s', () => {
  const a = timelineView(live(80));
  const b = timelineView(live(86));
  const before = new Set(a.goalKeys.filter(Boolean));
  const fresh = b.goalKeys.filter((k) => k && !before.has(k));
  assert.equal(fresh.length, 2); // Espí 82′, Endrick 85′
  const espi = FOTMOB.events.find((e) => e.type === 'goal' && e.minute === 82)!;
  assert.ok(espi.type === 'goal' && fresh.includes(goalKey(espi)));
  assert.equal(matchFingerprint({ ...FOTMOB, age_s: 1 }), matchFingerprint({ ...FOTMOB, age_s: 99, stale: true }));
});

test('имена: фамилии латиницей, как в API', () => {
  assert.equal(shortName('Vinícius Júnior'), 'Vinícius');
  assert.equal(shortName('Marten de Roon'), 'de Roon');
  assert.equal(shortName('Trent Alexander-Arnold'), 'Alexander-Arnold');
  assert.equal(shortName('Endrick'), 'Endrick');
  assert.equal(returnText('Mid October 2026'), 'до середины октября');
  assert.equal(returnText('Doubtful'), 'под вопросом');
});
