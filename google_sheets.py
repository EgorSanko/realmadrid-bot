"""
Google Sheets клиент для Real Madrid Bot v3.0
Поддержка: матчи, таблица, статистика игроков, коэффициенты, прогнозы
"""

import gspread
from google.oauth2.service_account import Credentials
import logging
from datetime import datetime
from typing import List, Dict, Optional
import os

logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]


class GoogleSheetsClient:
    def __init__(self, credentials_file: str = 'credentials.json', spreadsheet_id: str = None):
        self.connected = False
        self.spreadsheet = None
        
        self.spreadsheet_id = spreadsheet_id or os.getenv('GOOGLE_SHEETS_ID', '1ER1z9pmuyKar-w59-3uPvOuurW4yyeH0Zst9Byob5oo')
        
        try:
            if os.path.exists(credentials_file):
                creds = Credentials.from_service_account_file(credentials_file, scopes=SCOPES)
                client = gspread.authorize(creds)
                self.spreadsheet = client.open_by_key(self.spreadsheet_id)
                self.connected = True
                logger.info("✅ Google Sheets подключен!")
            else:
                logger.warning(f"❌ Файл {credentials_file} не найден!")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения: {e}")
    
    def get_matches(self, limit: int = 5) -> List[Dict]:
        """Получить ближайшие матчи"""
        if not self.connected:
            return self._demo_matches()[:limit]
        
        try:
            sheet = self.spreadsheet.worksheet('Matches')
            data = sheet.get_all_records()
            
            now = datetime.now()
            upcoming = []
            
            for row in data:
                if row.get('status') == 'scheduled':
                    try:
                        match_date = datetime.strptime(f"{row['date']} {row['time']}", '%d.%m.%Y %H:%M')
                        if match_date > now:
                            opponent = row['awayTeam'] if 'Real Madrid' in str(row.get('homeTeam', '')) else row['homeTeam']
                            is_home = 'Real Madrid' in str(row.get('homeTeam', ''))
                            
                            upcoming.append({
                                'id': row.get('matchId', ''),
                                'date': row['date'],
                                'date_raw': match_date.strftime('%Y-%m-%d'),
                                'time': row['time'],
                                'tournament': row['tournament'],
                                'opponent': opponent,
                                'is_home': is_home,
                                'home_crest': row.get('homeCrest', ''),
                                'away_crest': row.get('awayCrest', '')
                            })
                    except:
                        pass
            
            upcoming.sort(key=lambda x: x['date_raw'])
            return upcoming[:limit]
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return self._demo_matches()[:limit]
    
    def get_all_upcoming_matches(self) -> List[Dict]:
        return self.get_matches(limit=20)
    
    def get_results(self, limit: int = 5) -> List[Dict]:
        """Последние результаты из листа Results"""
        if not self.connected:
            return self._demo_results()[:limit]
        
        try:
            # Читаем из листа Results!
            sheet = self.spreadsheet.worksheet('Results')
            data = sheet.get_all_records()
            
            results = []
            for row in data:
                # Формат листа Results: homeTeam, awayTeam, homeScore, awayScore, competition
                home_team = str(row.get('homeTeam', ''))
                away_team = str(row.get('awayTeam', ''))
                
                is_home = 'Real Madrid' in home_team
                opponent = away_team if is_home else home_team
                
                home_score = int(row.get('homeScore', 0) or 0)
                away_score = int(row.get('awayScore', 0) or 0)
                
                rm_score = home_score if is_home else away_score
                opp_score = away_score if is_home else home_score
                
                result = 'win' if rm_score > opp_score else ('loss' if rm_score < opp_score else 'draw')
                
                # Дата в формате YYYY-MM-DD из date_local
                date_raw = str(row.get('date_local', ''))
                # Конвертируем в DD.MM.YYYY для отображения
                try:
                    date_obj = datetime.strptime(date_raw, '%Y-%m-%d')
                    date_display = date_obj.strftime('%d.%m.%Y')
                except:
                    date_display = date_raw
                
                results.append({
                    'date': date_display,
                    'date_raw': date_raw,
                    'opponent': opponent,
                    'score': f"{home_score}-{away_score}",
                    'result': result,
                    'is_home': is_home,
                    'tournament': row.get('competition', ''),
                    'home_crest': row.get('homeCrest', ''),
                    'away_crest': row.get('awayCrest', '')
                })
            
            # Сортируем по дате (новые первые)
            results.sort(key=lambda x: x.get('date_raw', ''), reverse=True)
            return results[:limit]
            
        except Exception as e:
            logger.error(f"Ошибка получения результатов: {e}")
            return self._demo_results()[:limit]
    
    def get_standings(self, limit: int = 20) -> List[Dict]:
        """Таблица La Liga"""
        if not self.connected:
            return self._demo_standings()[:limit]
        
        try:
            sheet = self.spreadsheet.worksheet('Standings')
            data = sheet.get_all_records()
            
            standings = [{
                'position': int(row.get('position', 0)),
                'team': row.get('team', ''),
                'played': int(row.get('played', 0)),
                'won': int(row.get('won', 0)),
                'draw': int(row.get('draw', 0)),
                'lost': int(row.get('lost', 0)),
                'points': int(row.get('points', 0))
            } for row in data]
            
            standings.sort(key=lambda x: x['position'])
            return standings[:limit]
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return self._demo_standings()[:limit]
    
    def get_player_stats(self, limit: int = 10) -> List[Dict]:
        """Статистика игроков - из модуля player_stats"""
        try:
            from player_stats import get_real_player_stats
            players = get_real_player_stats()
            return players[:limit]
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return self._demo_player_stats()[:limit]
    
    def get_odds(self) -> Optional[Dict]:
        """Коэффициенты"""
        if not self.connected:
            return self._demo_odds()
        
        try:
            sheet = self.spreadsheet.worksheet('Odds')
            data = sheet.get_all_records()
            if data:
                row = data[0]
                return {
                    'home_team': row.get('homeTeam', ''),
                    'away_team': row.get('awayTeam', ''),
                    'date': row.get('date', ''),
                    'home_odds': row.get('homeOdds', 'N/A'),
                    'draw_odds': row.get('drawOdds', 'N/A'),
                    'away_odds': row.get('awayOdds', 'N/A'),
                    'source': row.get('source', '')
                }
        except:
            pass
        return self._demo_odds()
    
    def get_form(self) -> str:
        """Серия последних 5 матчей"""
        results = self.get_results(limit=5)
        return ''.join(['W' if r['result'] == 'win' else ('L' if r['result'] == 'loss' else 'D') for r in results])
    
    # ДЕМО ДАННЫЕ
    def _demo_matches(self):
        return [
            {'id': '1', 'date': '04.01.2026', 'date_raw': '2026-01-04', 'time': '18:15',
             'tournament': 'La Liga', 'opponent': 'Real Betis', 'is_home': True, 'home_crest': '', 'away_crest': ''},
        ]
    
    def _demo_results(self):
        return [
            {'date': '20.12.2025', 'opponent': 'Sevilla', 'score': '2-0', 'result': 'win',
             'is_home': True, 'tournament': 'La Liga', 'home_crest': '', 'away_crest': ''},
        ]
    
    def _demo_standings(self):
        return [
            {'position': 1, 'team': 'Barcelona', 'played': 18, 'won': 13, 'draw': 3, 'lost': 2, 'points': 42},
            {'position': 2, 'team': 'Real Madrid', 'played': 17, 'won': 12, 'draw': 3, 'lost': 2, 'points': 39},
        ]
    
    def _demo_player_stats(self):
        return [
            {'rank': 1, 'name': 'Kylian Mbappé', 'position': 'F', 'goals': 12, 'assists': 5, 'matches': 17, 'rating': '7.8', 'photo': ''},
            {'rank': 2, 'name': 'Vinícius Jr', 'position': 'F', 'goals': 8, 'assists': 9, 'matches': 17, 'rating': '7.6', 'photo': ''},
            {'rank': 3, 'name': 'Jude Bellingham', 'position': 'M', 'goals': 6, 'assists': 4, 'matches': 16, 'rating': '7.4', 'photo': ''},
            {'rank': 4, 'name': 'Rodrygo', 'position': 'F', 'goals': 5, 'assists': 6, 'matches': 15, 'rating': '7.2', 'photo': ''},
            {'rank': 5, 'name': 'Federico Valverde', 'position': 'M', 'goals': 3, 'assists': 4, 'matches': 17, 'rating': '7.3', 'photo': ''},
        ]
    
    def _demo_odds(self):
        return {
            'home_team': 'Real Madrid', 'away_team': 'Real Betis', 'date': '04.01.2026 18:15',
            'home_odds': '1.45', 'draw_odds': '4.50', 'away_odds': '6.50', 'source': 'Demo'
        }
