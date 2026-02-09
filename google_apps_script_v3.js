/**
 * Real Madrid Bot - Google Apps Script v3.0
 * 
 * Функции:
 * 1. Матчи (предстоящие и результаты)
 * 2. Таблица La Liga
 * 3. Статистика игроков (голы, ассисты)
 * 4. Коэффициенты букмекеров
 * 5. Серия результатов
 */

// ============ НАСТРОЙКИ ============
const TEAM_ID = 2829; // Real Madrid
const SEASON_ID = 63683; // La Liga 2025/26
const LA_LIGA_ID = 8;

// ============ ОСНОВНЫЕ ФУНКЦИИ ============

/**
 * Главная функция - обновить ВСЕ данные
 */
function updateAllData() {
  try {
    updateMatches();
    Utilities.sleep(2000);
    updateStandings();
    Utilities.sleep(2000);
    updatePlayerStats();
    Utilities.sleep(2000);
    updateOdds();
    
    Logger.log('✅ Все данные обновлены!');
  } catch (error) {
    Logger.log('❌ Ошибка: ' + error.message);
  }
}

/**
 * Обновить матчи (предстоящие + результаты)
 */
function updateMatches() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // Лист Matches
  let matchesSheet = ss.getSheetByName('Matches');
  if (!matchesSheet) {
    matchesSheet = ss.insertSheet('Matches');
  }
  
  // Заголовки
  const headers = [
    'matchId', 'date', 'time', 'tournament', 'homeTeam', 'awayTeam',
    'homeScore', 'awayScore', 'status', 'homeCrest', 'awayCrest',
    'homeOdds', 'drawOdds', 'awayOdds'
  ];
  
  matchesSheet.clear();
  matchesSheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  
  // Получаем матчи
  const url = `https://api.sofascore.com/api/v1/team/${TEAM_ID}/events/last/0`;
  const urlNext = `https://api.sofascore.com/api/v1/team/${TEAM_ID}/events/next/0`;
  
  let allMatches = [];
  
  // Прошедшие матчи
  try {
    const response = UrlFetchApp.fetch(url, {muteHttpExceptions: true});
    const data = JSON.parse(response.getContentText());
    if (data.events) {
      allMatches = allMatches.concat(data.events.slice(-10)); // Последние 10
    }
  } catch (e) {
    Logger.log('Ошибка загрузки прошедших матчей: ' + e);
  }
  
  // Будущие матчи
  try {
    const response = UrlFetchApp.fetch(urlNext, {muteHttpExceptions: true});
    const data = JSON.parse(response.getContentText());
    if (data.events) {
      allMatches = allMatches.concat(data.events.slice(0, 10)); // Следующие 10
    }
  } catch (e) {
    Logger.log('Ошибка загрузки будущих матчей: ' + e);
  }
  
  // Записываем данные
  const rows = allMatches.map(match => {
    const startTime = new Date(match.startTimestamp * 1000);
    const homeTeam = match.homeTeam.name;
    const awayTeam = match.awayTeam.name;
    
    // Статус матча
    let status = 'scheduled';
    if (match.status.type === 'finished') status = 'finished';
    else if (match.status.type === 'inprogress') status = 'live';
    
    // Счёт
    const homeScore = match.homeScore?.current ?? '';
    const awayScore = match.awayScore?.current ?? '';
    
    // Коэффициенты (если есть)
    let homeOdds = '', drawOdds = '', awayOdds = '';
    
    return [
      match.id,
      Utilities.formatDate(startTime, 'Europe/Moscow', 'dd.MM.yyyy'),
      Utilities.formatDate(startTime, 'Europe/Moscow', 'HH:mm'),
      match.tournament?.name || 'Unknown',
      homeTeam,
      awayTeam,
      homeScore,
      awayScore,
      status,
      `https://api.sofascore.app/api/v1/team/${match.homeTeam.id}/image`,
      `https://api.sofascore.app/api/v1/team/${match.awayTeam.id}/image`,
      homeOdds,
      drawOdds,
      awayOdds
    ];
  });
  
  if (rows.length > 0) {
    matchesSheet.getRange(2, 1, rows.length, headers.length).setValues(rows);
  }
  
  Logger.log(`✅ Матчи обновлены: ${rows.length}`);
}

/**
 * Обновить таблицу La Liga
 */
function updateStandings() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  
  let standingsSheet = ss.getSheetByName('Standings');
  if (!standingsSheet) {
    standingsSheet = ss.insertSheet('Standings');
  }
  
  const headers = ['position', 'team', 'played', 'won', 'draw', 'lost', 'goalsFor', 'goalsAgainst', 'goalDiff', 'points', 'form'];
  
  standingsSheet.clear();
  standingsSheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  
  try {
    const url = `https://api.sofascore.com/api/v1/unique-tournament/${LA_LIGA_ID}/season/${SEASON_ID}/standings/total`;
    const response = UrlFetchApp.fetch(url, {muteHttpExceptions: true});
    const data = JSON.parse(response.getContentText());
    
    if (data.standings && data.standings[0]?.rows) {
      const rows = data.standings[0].rows.map(team => [
        team.position,
        team.team.name,
        team.matches,
        team.wins,
        team.draws,
        team.losses,
        team.scoresFor,
        team.scoresAgainst,
        team.scoresFor - team.scoresAgainst,
        team.points,
        '' // form будет добавлена позже
      ]);
      
      standingsSheet.getRange(2, 1, rows.length, headers.length).setValues(rows);
      Logger.log(`✅ Таблица обновлена: ${rows.length} команд`);
    }
  } catch (e) {
    Logger.log('❌ Ошибка обновления таблицы: ' + e);
  }
}

/**
 * Обновить статистику игроков Real Madrid
 */
function updatePlayerStats() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  
  let statsSheet = ss.getSheetByName('PlayerStats');
  if (!statsSheet) {
    statsSheet = ss.insertSheet('PlayerStats');
  }
  
  const headers = ['rank', 'player', 'position', 'goals', 'assists', 'matches', 'minutes', 'rating', 'photo'];
  
  statsSheet.clear();
  statsSheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  
  try {
    // Получаем состав команды
    const url = `https://api.sofascore.com/api/v1/team/${TEAM_ID}/players`;
    const response = UrlFetchApp.fetch(url, {muteHttpExceptions: true});
    const data = JSON.parse(response.getContentText());
    
    if (data.players) {
      // Сортируем по голам + ассистам
      const players = data.players
        .filter(p => p.player)
        .map(p => ({
          name: p.player.name,
          position: p.player.position || 'N/A',
          id: p.player.id
        }));
      
      // Получаем статистику каждого игрока за сезон
      const statsPromises = players.slice(0, 25).map((player, index) => {
        try {
          Utilities.sleep(100); // Пауза чтобы не спамить API
          const statsUrl = `https://api.sofascore.com/api/v1/player/${player.id}/unique-tournament/${LA_LIGA_ID}/season/${SEASON_ID}/statistics/overall`;
          const statsResp = UrlFetchApp.fetch(statsUrl, {muteHttpExceptions: true});
          const statsData = JSON.parse(statsResp.getContentText());
          
          return {
            ...player,
            goals: statsData.statistics?.goals || 0,
            assists: statsData.statistics?.assists || 0,
            matches: statsData.statistics?.appearances || 0,
            minutes: statsData.statistics?.minutesPlayed || 0,
            rating: statsData.statistics?.rating?.toFixed(2) || 'N/A'
          };
        } catch (e) {
          return {
            ...player,
            goals: 0,
            assists: 0,
            matches: 0,
            minutes: 0,
            rating: 'N/A'
          };
        }
      });
      
      // Сортируем по голам
      const sortedPlayers = statsPromises
        .sort((a, b) => (b.goals + b.assists) - (a.goals + a.assists));
      
      const rows = sortedPlayers.map((p, i) => [
        i + 1,
        p.name,
        p.position,
        p.goals,
        p.assists,
        p.matches,
        p.minutes,
        p.rating,
        `https://api.sofascore.app/api/v1/player/${p.id}/image`
      ]);
      
      if (rows.length > 0) {
        statsSheet.getRange(2, 1, rows.length, headers.length).setValues(rows);
      }
      
      Logger.log(`✅ Статистика игроков обновлена: ${rows.length}`);
    }
  } catch (e) {
    Logger.log('❌ Ошибка обновления статистики игроков: ' + e);
  }
}

/**
 * Обновить коэффициенты на ближайший матч
 */
function updateOdds() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  
  let oddsSheet = ss.getSheetByName('Odds');
  if (!oddsSheet) {
    oddsSheet = ss.insertSheet('Odds');
  }
  
  const headers = ['matchId', 'homeTeam', 'awayTeam', 'date', 'homeOdds', 'drawOdds', 'awayOdds', 'source'];
  
  oddsSheet.clear();
  oddsSheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  
  try {
    // Получаем ближайший матч
    const urlNext = `https://api.sofascore.com/api/v1/team/${TEAM_ID}/events/next/0`;
    const response = UrlFetchApp.fetch(urlNext, {muteHttpExceptions: true});
    const data = JSON.parse(response.getContentText());
    
    if (data.events && data.events.length > 0) {
      const nextMatch = data.events[0];
      
      // Пробуем получить коэффициенты
      try {
        const oddsUrl = `https://api.sofascore.com/api/v1/event/${nextMatch.id}/odds/1/all`;
        const oddsResp = UrlFetchApp.fetch(oddsUrl, {muteHttpExceptions: true});
        const oddsData = JSON.parse(oddsResp.getContentText());
        
        if (oddsData.markets && oddsData.markets.length > 0) {
          const market = oddsData.markets[0];
          const choices = market.choices || [];
          
          const homeOdds = choices.find(c => c.name === '1')?.fractionalValue || 'N/A';
          const drawOdds = choices.find(c => c.name === 'X')?.fractionalValue || 'N/A';
          const awayOdds = choices.find(c => c.name === '2')?.fractionalValue || 'N/A';
          
          const startTime = new Date(nextMatch.startTimestamp * 1000);
          
          const row = [
            nextMatch.id,
            nextMatch.homeTeam.name,
            nextMatch.awayTeam.name,
            Utilities.formatDate(startTime, 'Europe/Moscow', 'dd.MM.yyyy HH:mm'),
            homeOdds,
            drawOdds,
            awayOdds,
            'Sofascore'
          ];
          
          oddsSheet.getRange(2, 1, 1, headers.length).setValues([row]);
          Logger.log('✅ Коэффициенты обновлены');
          return;
        }
      } catch (e) {
        Logger.log('Коэффициенты недоступны: ' + e);
      }
      
      // Если коэффициенты не найдены - записываем заглушку
      const startTime = new Date(nextMatch.startTimestamp * 1000);
      const row = [
        nextMatch.id,
        nextMatch.homeTeam.name,
        nextMatch.awayTeam.name,
        Utilities.formatDate(startTime, 'Europe/Moscow', 'dd.MM.yyyy HH:mm'),
        'N/A',
        'N/A',
        'N/A',
        'Unavailable'
      ];
      
      oddsSheet.getRange(2, 1, 1, headers.length).setValues([row]);
    }
  } catch (e) {
    Logger.log('❌ Ошибка обновления коэффициентов: ' + e);
  }
}

/**
 * Получить серию результатов (последние 5 матчей)
 */
function getFormString() {
  try {
    const url = `https://api.sofascore.com/api/v1/team/${TEAM_ID}/events/last/0`;
    const response = UrlFetchApp.fetch(url, {muteHttpExceptions: true});
    const data = JSON.parse(response.getContentText());
    
    if (data.events) {
      const last5 = data.events.slice(-5).reverse();
      
      const form = last5.map(match => {
        const isHome = match.homeTeam.id === TEAM_ID;
        const homeScore = match.homeScore?.current || 0;
        const awayScore = match.awayScore?.current || 0;
        
        if (isHome) {
          if (homeScore > awayScore) return 'W';
          if (homeScore < awayScore) return 'L';
          return 'D';
        } else {
          if (awayScore > homeScore) return 'W';
          if (awayScore < homeScore) return 'L';
          return 'D';
        }
      });
      
      return form.join('');
    }
  } catch (e) {
    Logger.log('Ошибка получения серии: ' + e);
  }
  return 'N/A';
}

/**
 * Настройка триггеров
 */
function setupTriggers() {
  // Удаляем старые
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(trigger => ScriptApp.deleteTrigger(trigger));
  
  // Каждые 6 часов
  ScriptApp.newTrigger('updateAllData')
    .timeBased()
    .everyHours(6)
    .create();
  
  // Каждый день в 8:00 - статистика игроков
  ScriptApp.newTrigger('updatePlayerStats')
    .timeBased()
    .atHour(8)
    .everyDays(1)
    .create();
  
  Logger.log('✅ Триггеры настроены');
}
