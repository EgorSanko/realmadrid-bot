# Эмодзи и иконки для команд
# Используем флаги стран и специальные символы

TEAM_ICONS = {
    # Испания - La Liga
    'Real Madrid': '⚪🇪🇸',
    'Barcelona': '🔵🔴',
    'Atletico Madrid': '🔴⚪',
    'Atlético Madrid': '🔴⚪',
    'Sevilla': '⚪🔴',
    'Valencia': '🦇',
    'Villarreal': '💛',
    'Real Sociedad': '🔵⚪',
    'Real Betis': '💚',
    'Athletic Bilbao': '🦁',
    'Athletic Club': '🦁',
    'Osasuna': '🔴',
    'Celta Vigo': '🔵',
    'Celta': '🔵',
    'Mallorca': '🔴',
    'Rayo Vallecano': '⚡',
    'Getafe': '🔵',
    'Girona': '🔴⚪',
    'Alaves': '🔵',
    'Alavés': '🔵',
    'Deportivo Alavés': '🔵',
    'Cadiz': '💛',
    'Cádiz': '💛',
    'Granada': '🔴',
    'Almeria': '🔴',
    'Almería': '🔴',
    'Las Palmas': '💛',
    'Espanyol': '🔵⚪',
    'Levante': '🔵🔴',
    'Elche': '💚',
    'Real Oviedo': '🔵',
    
    # Англия - Premier League
    'Manchester City': '🔵🇬🇧',
    'Manchester United': '🔴🇬🇧',
    'Liverpool': '🔴🇬🇧',
    'Chelsea': '🔵🇬🇧',
    'Arsenal': '🔴🇬🇧',
    'Tottenham': '⚪🇬🇧',
    
    # Германия - Bundesliga
    'Bayern Munich': '🔴🇩🇪',
    'Bayern München': '🔴🇩🇪',
    'Borussia Dortmund': '💛🖤',
    'RB Leipzig': '🔴🇩🇪',
    
    # Италия - Serie A
    'Juventus': '⚪⚫🇮🇹',
    'AC Milan': '🔴⚫🇮🇹',
    'Inter Milan': '🔵⚫🇮🇹',
    'Inter': '🔵⚫',
    'Napoli': '🔵🇮🇹',
    'Roma': '🟠🇮🇹',
    'AS Roma': '🟠🇮🇹',
    'Lazio': '🔵⚪🇮🇹',
    'Atalanta': '🔵⚫',
    
    # Франция - Ligue 1
    'Paris Saint-Germain': '🔵🔴🇫🇷',
    'PSG': '🔵🔴🇫🇷',
    'Monaco': '🔴⚪🇲🇨',
    'AS Monaco': '🔴⚪🇲🇨',
    'Lyon': '🔵🇫🇷',
    'Marseille': '🔵⚪🇫🇷',
    
    # Португалия
    'Benfica': '🔴🇵🇹',
    'Sport Lisboa e Benfica': '🔴🇵🇹',
    'Porto': '🔵🇵🇹',
    'Sporting': '💚🇵🇹',
    'Sporting CP': '💚🇵🇹',
    'Braga': '🔴🇵🇹',
    
    # Нидерланды
    'Ajax': '🔴⚪🇳🇱',
    'PSV': '🔴⚪🇳🇱',
    'Feyenoord': '🔴⚪🇳🇱',
    
    # Другие
    'Red Bull Salzburg': '🔴🇦🇹',
    'Salzburg': '🔴🇦🇹',
    'Celtic': '💚🏴󠁧󠁢󠁳󠁣󠁴󠁿',
    'Rangers': '🔵🏴󠁧󠁢󠁳󠁣󠁴󠁿',
    'Galatasaray': '🟠🔴🇹🇷',
    'Fenerbahce': '💛💙🇹🇷',
    'Shakhtar': '🟠⚫🇺🇦',
    'Dynamo Kyiv': '⚪🔵🇺🇦',
    'Zenit': '🔵🇷🇺',
    'CSKA Moscow': '🔴🔵🇷🇺',
    
    # Сборные (для международных турниров)
    'Spain': '🇪🇸',
    'Germany': '🇩🇪',
    'France': '🇫🇷',
    'England': '🏴󠁧󠁢󠁥󠁮󠁧󠁿',
    'Italy': '🇮🇹',
    'Portugal': '🇵🇹',
    'Netherlands': '🇳🇱',
    'Brazil': '🇧🇷',
    'Argentina': '🇦🇷',
}

def get_team_icon(team_name: str) -> str:
    """Получить иконку команды по названию"""
    # Точное совпадение
    if team_name in TEAM_ICONS:
        return TEAM_ICONS[team_name]
    
    # Частичное совпадение
    team_lower = team_name.lower()
    for key, icon in TEAM_ICONS.items():
        if key.lower() in team_lower or team_lower in key.lower():
            return icon
    
    # По умолчанию - футбольный мяч
    return '⚽'


def format_match_with_icons(home_team: str, away_team: str, is_home: bool) -> str:
    """Форматировать матч с иконками"""
    home_icon = get_team_icon(home_team)
    away_icon = get_team_icon(away_team)
    
    return f"{home_icon} {home_team}  vs  {away_team} {away_icon}"


def format_opponent_with_icon(opponent: str) -> str:
    """Форматировать соперника с иконкой"""
    icon = get_team_icon(opponent)
    return f"{icon} {opponent}"
