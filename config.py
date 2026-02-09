import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    BOT_USERNAME = os.getenv('BOT_USERNAME', 'RealMadridNewBot')
    
    # Google Sheets
    SPREADSHEET_ID = os.getenv('SPREADSHEET_ID', '1ER1z9pmuyKar-w59-3uPvOuurW4yyeH0Zst9Byob5oo')
    CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
    
    # Уведомления (в минутах до матча)
    NOTIFY_BEFORE_HOURS = 6 * 60  # 6 часов = 360 минут
    NOTIFY_BEFORE_MINUTES = 10    # 10 минут
    
    # Автоудаление сообщений (в секундах)
    DELETE_NOTIFICATION_AFTER = 60 * 60  # Удалять уведомления через 1 час
    DELETE_MESSAGE_AFTER = 300  # Удалять обычные сообщения через 5 минут (0 = не удалять)
    
    # Ссылки на трансляции (liveball - страница Real Madrid)
    LIVEBALL_REAL_MADRID = 'https://q14.liveball.st/team/541'
    LIVEBALL_TELEGRAM = 'https://t.me/liveballst'
    
    STREAM_LINKS = {
        'La Liga': 'https://q14.liveball.st/team/541',
        'LaLiga': 'https://q14.liveball.st/team/541',
        'UEFA Champions League': 'https://q14.liveball.st/team/541',
        'Champions League': 'https://q14.liveball.st/team/541',
        'Copa del Rey': 'https://q14.liveball.st/team/541',
        'Supercopa': 'https://q14.liveball.st/team/541',
        'Club World Cup': 'https://q14.liveball.st/team/541',
        'default': 'https://q14.liveball.st/team/541'
    }
    
    # Эмодзи
    EMOJIS = {
        'home': '🏠',
        'away': '✈️',
        'win': '✅',
        'draw': '🤝',
        'loss': '❌',
        'goal': '⚽',
        'calendar': '📅',
        'trophy': '🏆',
        'table': '📊',
        'clock': '🕐',
        'stadium': '🏟️',
        'real': '⚪',
        'warning': '⚠️',
        'info': 'ℹ️',
        'fire': '🔥',
        'bell': '🔔',
        'bell_off': '🔕',
        'tv': '📺',
        'link': '🔗',
        'medal1': '🥇',
        'medal2': '🥈',
        'medal3': '🥉',
        'stats': '📈',
        'refresh': '🔄',
        'back': '⬅️',
        'vs': '⚔️'
    }
