// Экран матча, этап 1: «О матче» (стадион, погода, судья), расширенная статистика и зоны атак.
// Фикстура match_5868098_live.json — настоящий ответ /api/match (нормализатор FotMob на сыром matchDetails).
// Запуск: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { normalizeMatch, type ApiMatch } from '../src/api/match.ts';
import {
  countryNameRu,
  decimalRu,
  infoLine,
  refereeLevelText,
  refereeView,
  stadiumView,
  weatherView,
  zoneHeat,
  zonesView,
} from '../src/screens/match/info.ts';
import { STAT_KEYS, statLabel, statPeriods, statsView } from '../src/screens/match/view.ts';

const fx = (name: string): ApiMatch =>
  normalizeMatch(JSON.parse(readFileSync(new URL(`../src/__fixtures__/${name}.json`, import.meta.url), 'utf8')));

const LIVE = fx('match_5868098_live');
const OLD = fx('match_6106274'); // старый снимок FotMob — без новых полей
const SOFA = fx('match_6106274_sofascore');

test('числа по-русски', () => {
  assert.equal(decimalRu(5.51), '5,51');
  assert.equal(decimalRu(24.65), '24,65');
  assert.equal(decimalRu(4.5), '4,5');
  assert.equal(decimalRu(37), '37');
  assert.equal(countryNameRu('es'), 'Испания');
  assert.equal(countryNameRu('gb-eng'), 'Англия');
  assert.equal(countryNameRu('zz-zzz'), null);
});

test('стадион: вместимость и покрытие по-русски', () => {
  const st = stadiumView(LIVE)!;
  assert.deepEqual(st, {
    name: 'Estadio Bernabéu',
    city: 'Madrid',
    iso: 'es',
    country: 'Испания',
    capacity: '83 186',
    surface: 'Трава',
    attendance: undefined,
  });
  // неизвестное покрытие — не показываем по-английски
  const m = structuredClone(LIVE);
  m.venue!.surface = 'astroturf-x';
  assert.equal(stadiumView(m)!.surface, undefined);
  // резерв без подробностей: только название
  const s = stadiumView(SOFA);
  assert.ok(s === null || (s.capacity === undefined && s.surface === undefined));
});

test('погода: иконка, температура и описание по-русски, без ветра', () => {
  const w = weatherView(LIVE)!;
  assert.deepEqual(w, { temp: '10 °C', text: 'Облачно', icon: 'cloudy', details: 'влажность 78% · облачность 92% · осадки 0 мм' });
  assert.ok(!JSON.stringify(w).includes('ветер'));
  const m = structuredClone(LIVE);
  m.weather = { ...m.weather!, key: 'weather_condition_light_rain', temp: 7.6 };
  assert.deepEqual([weatherView(m)!.temp, weatherView(m)!.text, weatherView(m)!.icon], ['8 °C', 'Небольшой дождь', 'rain']);
  m.weather = { ...m.weather!, key: 'weather_condition_something_new' };
  assert.equal(weatherView(m)!.text, null); // английский не выводим
  assert.equal(weatherView(OLD), null); // в старом снимке погоды нет
});

test('судья: фото, страна, шкалы и метки «выше среднего / средний / ниже»', () => {
  const r = refereeView(LIVE)!;
  assert.equal(r.name, 'Mateo Busquets Ferrer');
  assert.equal(r.id, 1001070988);
  assert.equal(r.country, 'Испания');
  assert.equal(r.matches, '37 матчей в Ла Лиге');
  assert.deepEqual(r.yellow, { value: '5,51', avg: '4,46', level: 'above', label: 'Выше среднего', fill: 100, avgFill: 50 });
  assert.equal(r.fouls!.label, 'Средний');
  assert.equal(r.fouls!.value, '24,65');
  assert.equal(r.fouls!.fill, 44.88);
  assert.deepEqual(r.tiles, [
    { label: 'Жёлтых всего', value: '204' },
    { label: 'Красных', value: '8' },
    { label: 'Пенальти', value: '10' },
  ]);
  assert.equal(refereeLevelText('below'), 'Ниже среднего');
  assert.equal(refereeLevelText(null), null);
  // без статистики (резервный источник) — только имя и флаг, фото — силуэт
  const sofa = refereeView(SOFA);
  if (sofa) {
    assert.equal(sofa.yellow, null);
    assert.equal(sofa.id, undefined);
    assert.equal(sofa.tiles.length, 0);
  }
  // шкала без позиций от FotMob — среднее посередине, значение относительно него
  const m = structuredClone(LIVE);
  m.referee_info!.yellow = { ...m.referee_info!.yellow!, fill: null, avg_fill: null };
  const y = refereeView(m)!.yellow!;
  assert.equal(y.avgFill, 50);
  assert.ok(Math.abs(y.fill - 61.77) < 0.01);
});

test('лайв: «О матче» одной строкой', () => {
  assert.equal(infoLine(LIVE), 'Estadio Bernabéu · 10° · Mateo Busquets Ferrer');
});

test('статистика: 37 показателей, у каждого русское название', () => {
  assert.equal(STAT_KEYS.length, 37);
  const keys = new Set(LIVE.stats!.all.map((s) => s.key));
  assert.equal(keys.size, 37);
  for (const k of keys) assert.notEqual(statLabel(k), k, k);
  assert.ok(STAT_KEYS.every((k) => /[а-яё]|xG/i.test(statLabel(k))));
});

test('статистика: группы xG и «Единоборства», точность в скобках, полосы', () => {
  assert.deepEqual(statPeriods(LIVE), ['all', 'first_half']);
  const g = statsView(LIVE, 'all');
  assert.deepEqual(
    g.map((x) => x.title),
    ['Главное', 'xG', 'Удары', 'Передачи', 'Единоборства', 'Оборона', 'Дисциплина'],
  );
  const by = (t: string) => Object.fromEntries(g.find((x) => x.title === t)!.rows.map((r) => [r.key, r]));
  const xg = by('xG');
  assert.deepEqual(Object.keys(xg), ['xg', 'xg_open_play', 'xg_set_play', 'xg_non_penalty', 'xg_on_target', 'big_chances_missed']);
  assert.equal(xg.xg_open_play.home, '1.46');
  assert.equal(xg.big_chances_missed.better, 'lower');
  const duels = by('Единоборства');
  assert.equal(duels.ground_duels_won.home, '17 (52%)');
  assert.equal(duels.aerials_won.away, '4 (44%)');
  assert.equal(duels.ground_duels_won.bar, true);
  assert.equal(duels.duels_won.bar, true);
  const passes = by('Передачи');
  assert.equal(passes.passes_accurate.home, '273 (90%)');
  assert.equal(passes.passes_accurate.bar, true);
  assert.equal(passes.passes_own_half.home, '155');
  assert.equal(passes.throws.better, 'none');
  // «Главное» — как раньше: полоса только у владения
  const main = by('Главное');
  assert.equal(main.passes_accurate.bar, undefined);
  assert.equal(main.possession.bar, true);
  assert.ok(!('xg_on_target' in by('Удары')));
  // 1-й тайм — те же группы
  assert.equal(statsView(LIVE, 'first_half').length, 7);
});

test('статистика резерва без деталей xG: xGOT остаётся в «Ударах», группы xG нет', () => {
  const titles = statsView(SOFA, 'all').map((g) => g.title);
  assert.ok(!titles.includes('xG'));
  const shots = statsView(OLD, 'all').find((g) => g.title === 'Удары')!;
  assert.ok(shots.rows.some((r) => r.key === 'xg_on_target'));
});

test('зоны атак по таймам', () => {
  const z = zonesView(LIVE, 'all')!;
  assert.deepEqual(z.home, { left: 59, center: 21, right: 20 });
  assert.deepEqual(z.hot, { home: 'left', away: 'left' });
  assert.deepEqual(zonesView(LIVE, 'first_half')!.away, { left: 42, center: 24, right: 34 });
  // второго тайма ещё нет — показываем весь матч
  assert.deepEqual(zonesView(LIVE, 'second_half')!.home, z.home);
  assert.equal(zonesView(OLD), null);
  assert.equal(zonesView(SOFA), null);
  assert.ok(zoneHeat(59) > zoneHeat(20) && zoneHeat(0) === 0.08 && zoneHeat(100) === 0.6);
});
