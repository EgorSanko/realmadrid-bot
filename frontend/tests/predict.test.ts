// Прогнозы: правила очков (как rules.py), «пока +N», ошибки API по-русски, рейтинг, мои прогнозы.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  boardView,
  computePoints,
  historyItem,
  homeLine,
  livePoints,
  matchTitle,
  nextLine,
  placeLine,
  predictError,
  rowSub,
  scorePoints,
  shortName,
  summaryTiles,
  waitingPeople,
  withPlaces,
} from '../src/lib/predict.ts';
import type { LbRow, Leaderboard, LeagueHeader, MeHistoryEntry, NextMatch } from '../src/lib/predict.ts';

test('очки за счёт: точный 5, разница 3, исход 2, мимо 0', () => {
  assert.equal(scorePoints(2, 1, 2, 1), 5);
  assert.equal(scorePoints(3, 2, 2, 1), 3);
  assert.equal(scorePoints(1, 1, 2, 2), 3); // ничья другим счётом — разница
  assert.equal(scorePoints(3, 0, 2, 1), 2);
  assert.equal(scorePoints(0, 1, 2, 1), 0);
});

test('бомбардир +2 сверху; Реал не забил — бонуса нет', () => {
  // Рома 3:4 Реал (Реал в гостях), первый гол Реала — Мбаппе
  assert.deepEqual(computePoints({ home: 3, away: 4, first_scorer_id: '701154' }, { home: 3, away: 4 }, '701154', false), {
    total: 7, score: 5, scorer: 2, kind: 'exact',
  });
  assert.equal(computePoints({ home: 1, away: 2, first_scorer_id: '846033' }, { home: 3, away: 4 }, '701154', false).total, 3);
  assert.equal(computePoints({ home: 1, away: 0, first_scorer_id: '701154' }, { home: 1, away: 0 }, '701154', false).scorer, 0);
});

const NEXT: NextMatch = {
  id: '5868098',
  kickoff_utc: '2026-10-18T19:00:00Z',
  home: { id: 8633, name: 'Real Madrid' },
  away: { id: 8302, name: 'Sevilla' },
  rm_side: 'home',
  status: 'live',
  score: { home: 2, away: 1 },
  accepting: false,
  closes_at: '2026-10-18T19:00:00Z',
  first_rm_scorer_player_id: '701154',
  tournament: { id: 87, name: 'LaLiga' },
  rm_squad: [{ id: '701154', name: 'Kylian Mbappé' }],
  my_prediction: { home: 2, away: 1, first_scorer_id: '701154' },
  my_points: null,
};

test('главная: «пока +N» по текущему счёту; до начала — «изменить»', () => {
  assert.deepEqual(livePoints(NEXT), { total: 7, score: 5, scorer: 2, kind: 'exact' });
  assert.deepEqual(homeLine(NEXT), { pick: '2:1', tail: 'пока +7' });
  assert.deepEqual(homeLine({ ...NEXT, status: 'live', score: { home: 0, away: 0 }, first_rm_scorer_player_id: null }), {
    pick: '2:1', tail: 'пока +0',
  });
  assert.deepEqual(homeLine({ ...NEXT, status: 'scheduled', accepting: true, score: null }), { pick: '2:1', tail: 'изменить' });
  assert.deepEqual(homeLine({ ...NEXT, my_prediction: null }), { pick: null, tail: null });
  assert.equal(livePoints({ ...NEXT, status: 'scheduled' }), null);
});

test('ошибки API — понятные сообщения по-русски', () => {
  assert.deepEqual(predictError(409, 'closed'), { kind: 'closed', message: 'Приём закрыт: матч уже начался' });
  assert.equal(predictError(409, 'match_cancelled').message, 'Матч отменён — прогнозы не принимаются');
  assert.equal(predictError(429, 'rate_limited').kind, 'rate');
  assert.match(predictError(429, 'rate_limited').message, /подождите минуту/);
  assert.equal(predictError(401, 'unauthorized').kind, 'auth');
  assert.match(predictError(401, null).message, /войти через Telegram/);
  assert.match(predictError(422, 'scorer_without_goal').message, /Реал не забивает/);
  assert.equal(predictError(422, 'validation', 'Голы — целые числа от 0 до 20').message, 'Голы — целые числа от 0 до 20');
  assert.equal(predictError(0, null).kind, 'network');
  assert.equal(predictError(503, 'matches_unavailable').kind, 'unavailable');
});

test('короткое имя игрока — фамилия латиницей', () => {
  assert.equal(shortName('Kylian Mbappé'), 'Mbappé');
  assert.equal(shortName('Vinícius Júnior'), 'Vinícius Júnior');
  assert.equal(shortName('Endrick'), 'Endrick');
  assert.equal(shortName('Trent Alexander-Arnold'), 'Alexander-Arnold');
});

const LB: Leaderboard = {
  key: 'S2026', period: 'season', label: '2026/27', league: null, total: 12,
  top: [
    { rank: 1, name: 'Мария', username: 'maria_rm', avatar: '/img/avatar/1001.jpg?v=1', points: 14, exact: 2, played: 3, is_me: false },
    { rank: 2, name: 'Дмитрий К.', username: null, avatar: null, points: 9, exact: 1, played: 3, is_me: false },
  ],
  me: { rank: 7, points: 3, exact: 0, played: 3 },
};

test('рейтинг: моя строка отдельно, если я не в топе', () => {
  const v = boardView(LB, 'Алексей М.', '/img/avatar/4242.jpg');
  assert.equal(v.rows.length, 2);
  assert.deepEqual(
    { rank: v.meRow?.rank, name: v.meRow?.name, pts: v.meRow?.points, me: v.meRow?.is_me, av: v.meRow?.avatar },
    { rank: 7, name: 'Алексей М.', pts: 3, me: true, av: '/img/avatar/4242.jpg' },
  );
  const inTop = boardView({ ...LB, top: [{ ...LB.top[0], is_me: true }], me: { rank: 1, points: 14, exact: 2, played: 3 } }, 'x', null);
  assert.equal(inTop.meRow, null);
  assert.equal(boardView({ ...LB, me: { rank: null, points: 0, exact: 0, played: 0 } }, 'x', null).meRow, null);
  assert.equal(boardView({ ...LB, top: [] }, 'x', null).empty, true);
});

test('мои прогнозы: мой счёт против итогового, разбивка очков', () => {
  const h: MeHistoryEntry = {
    match: { ...NEXT, id: '6106274', status: 'finished', home: { id: '8686', name: 'Roma' }, away: { id: '8633', name: 'Real Madrid' },
      rm_side: 'away', score: { home: 3, away: 4 } },
    prediction: { home: 3, away: 4, first_scorer_id: '701154' },
    points: { total: 7, score: 5, scorer: 2, kind: 'exact' },
    state: 'settled',
  };
  const it = historyItem(h);
  assert.deepEqual([it.pick, it.result, it.points, it.tone, it.home.id, it.scorerPick], ['3:4', '3:4', 7, 'exact', 8686, '701154']);
  assert.equal(it.note, 'точный счёт +5 · бомбардир +2');
  const miss = historyItem({ ...h, prediction: { home: 1, away: 2, first_scorer_id: '846033' }, points: { total: 3, score: 3, scorer: 0, kind: 'diff' } });
  assert.equal(miss.note, 'разница мячей +3 · бомбардир мимо');
  const noSc = historyItem({ ...h, prediction: { home: 0, away: 0, first_scorer_id: null }, points: { total: 0, score: 0, scorer: 0, kind: 'miss' } });
  assert.deepEqual([noSc.note, noSc.tone], ['счёт мимо', 'miss']);
  assert.equal(historyItem({ ...h, points: null, state: 'open' }).note, 'можно изменить до начала');
  assert.equal(historyItem({ ...h, points: null, state: 'waiting' }).points, null);
});

test('мои итоги: очки, место, точных', () => {
  assert.deepEqual(summaryTiles({ points: 21, rank: 12, exact: 2, played: 7 }).map((t) => t.value), ['21', '12', '2']);
  assert.deepEqual(summaryTiles(null).map((t) => t.value), ['0', '—', '0']);
});

test('мои итоги: место с учётом равенства, если сервер его отдал', () => {
  assert.equal(summaryTiles({ points: 3, rank: 4, place: 3, exact: 0, played: 2 })[1].value, '3');
});

const row = (rank: number, points: number, exact: number, played = 2, extra: Partial<LbRow> = {}): LbRow => ({
  rank, name: `U${rank}`, username: null, avatar: null, points, exact, played, is_me: false, ...extra,
});

test('рейтинг: общие места при равных очках и точных (1, 1, 3…)', () => {
  // без place от сервера — считаем по порядку строк
  const local = withPlaces([row(1, 5, 1), row(2, 5, 1), row(3, 5, 0), row(4, 3, 0), row(5, 3, 0), row(6, 2, 0)]);
  assert.deepEqual(local.map((r) => r.place), [1, 1, 3, 4, 4, 6]);
  // place от сервера — главнее
  assert.deepEqual(withPlaces([row(1, 0, 0, 0, { place: 1 }), row(2, 0, 0, 0, { place: 1 })]).map((r) => r.place), [1, 1]);
  const v = boardView({ ...LB, top: [row(1, 3, 0), row(2, 3, 0, 2, { is_me: true })], me: { rank: 2, place: 1, points: 3, exact: 0, played: 2 } }, 'x', null);
  assert.equal(v.myPlace, 1);
  const out = boardView({ ...LB, me: { rank: 9, place: 7, points: 1, exact: 0, played: 1 } }, 'Я', null);
  assert.equal(out.meRow?.place, 7);
  assert.equal(out.meRow?.sub, '1 прогноз · 0 точных');
});

test('рейтинг: подпись «N прогнозов · M точных»', () => {
  assert.equal(rowSub({ played: 3, exact: 1 }), '3 прогноза · 1 точный');
  assert.equal(rowSub({ played: 5, exact: 2 }), '5 прогнозов · 2 точных');
  assert.equal(rowSub({ played: 21, exact: 11 }), '21 прогноз · 11 точных');
  assert.equal(rowSub({ played: 0, exact: 0 }), 'пока без прогнозов');
});

const HEAD: LeagueHeader = {
  id: 1, name: 'Бомжи', code: 'ABC', invite_link: null, is_owner: true, members: 2,
  people: [
    { name: 'Егор', avatar: null, is_me: false, is_owner: true, predicted_next: false },
    { name: 'artur', avatar: null, is_me: true, is_owner: false, predicted_next: true },
  ],
  next_match: { id: '7', kickoff_utc: '2026-10-25T15:15:00Z', home: { id: 9, name: 'Барселона' }, away: { id: 8633, name: 'Реал Мадрид' }, rm_side: 'away' },
  predicted_next_count: 1,
};

test('лига до старта: у всех 0 сыгранных, я первым, кто сделал прогноз', () => {
  const zero = boardView({ ...LB, league: { id: 1, name: 'Бомжи' }, total: 2, top: [row(1, 0, 0, 0), row(2, 0, 0, 0, { is_me: true })], me: { rank: 2, place: 1, points: 0, exact: 0, played: 0 } }, 'x', null);
  assert.equal(zero.started, false);
  assert.equal(placeLine(zero, 2), null); // все пока первые — «ты 1-й из 2» не пишем
  assert.deepEqual(waitingPeople(HEAD).map((p) => [p.name, p.state]), [['artur', 'done'], ['Егор', 'wait']]);
  assert.deepEqual(waitingPeople({ ...HEAD, next_match: null }).map((p) => p.state), ['none', 'none']);
  assert.equal(matchTitle(HEAD.next_match!), 'Барселона — Реал');
  assert.equal(matchTitle({ ...HEAD.next_match!, home: HEAD.next_match!.away, away: HEAD.next_match!.home, rm_side: 'home' }), 'Реал — Барселона');
});

test('лига: «ты N-й из M» и «прогнозы сделали K из M»', () => {
  const v = boardView({ ...LB, total: 5, top: [row(1, 5, 1), row(2, 3, 0, 2, { is_me: true, place: 2 })], me: { rank: 2, place: 2, points: 3, exact: 0, played: 2 } }, 'x', null);
  assert.equal(v.started, true);
  assert.equal(placeLine(v, 5), 'ты 2-й из 5');
  assert.equal(nextLine(HEAD), 'Прогнозы сделали 1 из 2');
  assert.equal(nextLine({ ...HEAD, predicted_next_count: 2 }), 'Прогнозы сделали все');
  assert.equal(nextLine({ ...HEAD, predicted_next_count: 0 }), 'Прогнозов пока нет ни у кого');
  assert.equal(nextLine({ ...HEAD, next_match: null }), null);
});
