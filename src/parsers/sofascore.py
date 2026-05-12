"""src/parsers/sofascore.py — SofaScore (sofascore.com) API parser.

Endpoints used (api.sofascore.com/api/v1):
- /team/2829/events           — recent matches
- /event/{id}/incidents       — goal/card events
- /event/{id}/lineups         — player ratings
- /unique-tournament/8/...    — standings
- /team/2829/players          — squad stats

Currently used: get_sofascore_recent_matches (from api.auto_settle_task).
Others kept for potential future use (live_match, incidents, ratings, standings, player_stats).
"""
import requests
from typing import Dict, List



SOFASCORE_API = "https://api.sofascore.com/api/v1"
REAL_MADRID_TEAM_ID = 2829
LALIGA_TOURNAMENT_ID = 8  # La Liga

_sofascore_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


def get_sofascore_live_match() -> Dict:
    """Получить текущий LIVE матч Real Madrid (счёт, события)"""
    try:
        # Получаем следующие/текущие матчи
        url = f"{SOFASCORE_API}/team/{REAL_MADRID_TEAM_ID}/events/next/0"
        response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            return None

        data = response.json()
        events = data.get('events', [])

        for event in events:
            status = event.get('status', {})
            status_type = status.get('type', '')

            # inprogress = матч идёт сейчас
            if status_type == 'inprogress':
                home_team = event.get('homeTeam', {}).get('name', '')
                away_team = event.get('awayTeam', {}).get('name', '')
                home_score = event.get('homeScore', {}).get('current', 0)
                away_score = event.get('awayScore', {}).get('current', 0)

                # Минута матча
                minute = status.get('description', '')

                # Турнир
                tournament = event.get('tournament', {}).get('name', 'La Liga')

                # События матча (голы, карточки)
                match_id = event.get('id')
                incidents = get_sofascore_match_incidents(match_id) if match_id else []

                return {
                    'is_live': True,
                    'match_id': match_id,
                    'home_team': home_team,
                    'away_team': away_team,
                    'home_score': home_score,
                    'away_score': away_score,
                    'minute': minute,
                    'tournament': tournament,
                    'status': status_type,
                    'incidents': incidents,
                    'sofascore_url': f'https://www.sofascore.com/match/{match_id}'
                }

        return {'is_live': False}

    except Exception as e:
        print(f"SofaScore live error: {e}")
        return {'is_live': False, 'error': str(e)}


def get_sofascore_match_incidents(match_id: int) -> List[Dict]:
    """Получить события матча (голы, карточки, замены)"""
    try:
        url = f"{SOFASCORE_API}/event/{match_id}/incidents"
        response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        incidents = data.get('incidents', [])

        result = []
        for inc in incidents:
            inc_type = inc.get('incidentType', '')

            if inc_type == 'goal':
                result.append({
                    'type': 'goal',
                    'minute': inc.get('time', 0),
                    'player': inc.get('player', {}).get('name', ''),
                    'assist': inc.get('assist1', {}).get('name', '') if inc.get('assist1') else None,
                    'home': inc.get('isHome', False),
                    'score': f"{inc.get('homeScore', 0)}-{inc.get('awayScore', 0)}"
                })
            elif inc_type == 'card':
                card_type = inc.get('incidentClass', '')
                result.append({
                    'type': 'yellow' if card_type == 'yellow' else 'red',
                    'minute': inc.get('time', 0),
                    'player': inc.get('player', {}).get('name', ''),
                    'home': inc.get('isHome', False)
                })
            elif inc_type == 'substitution':
                result.append({
                    'type': 'sub',
                    'minute': inc.get('time', 0),
                    'player_in': inc.get('playerIn', {}).get('name', ''),
                    'player_out': inc.get('playerOut', {}).get('name', ''),
                    'home': inc.get('isHome', False)
                })

        return result

    except Exception as e:
        print(f"SofaScore incidents error: {e}")
        return []

def get_sofascore_recent_matches() -> List[Dict]:
    """Получить недавние матчи Real Madrid из SofaScore"""
    try:
        url = f"{SOFASCORE_API}/team/{REAL_MADRID_TEAM_ID}/events/last/0"
        response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        events = data.get('events', [])

        finished_matches = []
        for event in events[:10]:  # Последние 10
            status = event.get('status', {}).get('type', '')
            if status == 'finished':
                match_id = event.get('id')
                home_team = event.get('homeTeam', {}).get('name', '')
                away_team = event.get('awayTeam', {}).get('name', '')
                home_score = event.get('homeScore', {}).get('current', 0)
                away_score = event.get('awayScore', {}).get('current', 0)
                start_time = event.get('startTimestamp', 0)

                finished_matches.append({
                    'matchId': str(match_id),
                    'homeTeam': home_team,
                    'awayTeam': away_team,
                    'homeScore': home_score,
                    'awayScore': away_score,
                    'date': datetime.fromtimestamp(start_time).strftime('%d.%m.%Y'),
                    'status': 'FINISHED'
                })

        return finished_matches

    except Exception as e:
        print(f"SofaScore recent matches error: {e}")
        return []


def get_sofascore_match_ratings(match_id: int) -> Dict:
    """Получить оценки игроков за матч"""
    try:
        # Получаем lineups с рейтингами
        url = f"{SOFASCORE_API}/event/{match_id}/lineups"
        response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            return {}

        data = response.json()

        result = {'home': [], 'away': [], 'matchId': match_id}

        for side in ['home', 'away']:
            lineup = data.get(side, {})
            players = lineup.get('players', [])

            for player_group in players:
                for player_data in player_group if isinstance(player_group, list) else [player_group]:
                    player = player_data.get('player', {})
                    stats = player_data.get('statistics', {})

                    rating = stats.get('rating')
                    if rating:
                        result[side].append({
                            'name': player.get('shortName', player.get('name', '')),
                            'position': player_data.get('position', ''),
                            'rating': round(float(rating), 1),
                            'goals': stats.get('goals', 0),
                            'assists': stats.get('assists', 0),
                            'minutes': stats.get('minutesPlayed', 0)
                        })

            # Сортируем по рейтингу
            result[side] = sorted(result[side], key=lambda x: x['rating'], reverse=True)

        return result

    except Exception as e:
        print(f"SofaScore ratings error: {e}")
        return {}


def get_sofascore_laliga_standings() -> List[Dict]:
    """Получить таблицу Ла Лиги"""
    try:
        # Получаем текущий сезон
        url = f"{SOFASCORE_API}/unique-tournament/{LALIGA_TOURNAMENT_ID}/season/61643/standings/total"  # Season ID may need update
        response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            # Попробуем найти текущий сезон
            season_url = f"{SOFASCORE_API}/unique-tournament/{LALIGA_TOURNAMENT_ID}/seasons"
            season_resp = requests.get(season_url, headers=_sofascore_headers, timeout=10)
            if season_resp.status_code == 200:
                seasons = season_resp.json().get('seasons', [])
                if seasons:
                    current_season = seasons[0].get('id')
                    url = f"{SOFASCORE_API}/unique-tournament/{LALIGA_TOURNAMENT_ID}/season/{current_season}/standings/total"
                    response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        standings_data = data.get('standings', [])

        if not standings_data:
            return []

        rows = standings_data[0].get('rows', [])
        standings = []

        for row in rows:
            team = row.get('team', {})
            standings.append({
                'position': row.get('position', 0),
                'team': team.get('name', ''),
                'teamId': team.get('id'),
                'played': row.get('matches', 0),
                'won': row.get('wins', 0),
                'drawn': row.get('draws', 0),
                'lost': row.get('losses', 0),
                'goalsFor': row.get('scoresFor', 0),
                'goalsAgainst': row.get('scoresAgainst', 0),
                'goalDiff': row.get('scoresFor', 0) - row.get('scoresAgainst', 0),
                'points': row.get('points', 0),
                'isRealMadrid': team.get('id') == REAL_MADRID_TEAM_ID
            })

        return standings

    except Exception as e:
        print(f"SofaScore standings error: {e}")
        return []


def get_sofascore_player_stats() -> List[Dict]:
    """Получить статистику игроков Real Madrid"""
    try:
        url = f"{SOFASCORE_API}/team/{REAL_MADRID_TEAM_ID}/players"
        response = requests.get(url, headers=_sofascore_headers, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        players = data.get('players', [])

        player_stats = []
        for p in players:
            player = p.get('player', {})
            player_stats.append({
                'name': player.get('shortName', player.get('name', '')),
                'position': player.get('position', ''),
                'number': player.get('jerseyNumber'),
                'country': player.get('country', {}).get('name', ''),
                'age': player.get('age'),
                'height': player.get('height'),
                'marketValue': player.get('proposedMarketValue')
            })

        return player_stats

    except Exception as e:
        print(f"SofaScore player stats error: {e}")
        return []


