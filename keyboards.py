"""
Клавиатуры для Real Madrid Bot v3.0
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class Keyboards:
    
    @staticmethod
    def main_menu():
        """Главное меню"""
        keyboard = [
            [InlineKeyboardButton("📅 Ближайшие матчи", callback_data="matches")],
            [InlineKeyboardButton("📊 Последние результаты", callback_data="results")],
            [InlineKeyboardButton("🏆 Таблица La Liga", callback_data="standings")],
            [InlineKeyboardButton("⚽ Статистика игроков", callback_data="player_stats")],
            [InlineKeyboardButton("📈 Коэффициенты", callback_data="odds")],
            [InlineKeyboardButton("🎯 Прогнозы", callback_data="predictions")],
            [InlineKeyboardButton("🔔 Уведомления", callback_data="notifications")],
            [InlineKeyboardButton("ℹ️ О боте", callback_data="about")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def stats_menu():
        """Меню статистики"""
        keyboard = [
            [InlineKeyboardButton("🥇 Топ бомбардиров", callback_data="top_scorers")],
            [InlineKeyboardButton("🎯 Топ ассистентов", callback_data="top_assists")],
            [InlineKeyboardButton("📊 Все игроки", callback_data="all_players")],
            [InlineKeyboardButton("📈 Серия результатов", callback_data="form")],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def predictions_menu():
        """Меню прогнозов"""
        keyboard = [
            [InlineKeyboardButton("🎯 Сделать прогноз", callback_data="make_prediction")],
            [InlineKeyboardButton("🏆 Рейтинг прогнозистов", callback_data="predictions_rating")],
            [InlineKeyboardButton("📊 Мои прогнозы", callback_data="my_predictions")],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def prediction_vote(match_id: str, home_team: str, away_team: str):
        """Кнопки для голосования кто победит"""
        keyboard = [
            [InlineKeyboardButton(f"🏠 {home_team}", callback_data=f"vote_{match_id}_home")],
            [InlineKeyboardButton("🤝 Ничья", callback_data=f"vote_{match_id}_draw")],
            [InlineKeyboardButton(f"✈️ {away_team}", callback_data=f"vote_{match_id}_away")],
            [InlineKeyboardButton("🔙 Назад", callback_data="predictions")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def back_to_main():
        """Кнопка назад в главное меню"""
        keyboard = [[InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def back_to_stats():
        """Кнопка назад в статистику"""
        keyboard = [
            [InlineKeyboardButton("🔙 Статистика", callback_data="player_stats")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def notifications_menu(is_subscribed: bool):
        """Меню уведомлений"""
        if is_subscribed:
            btn = InlineKeyboardButton("🔕 Выключить уведомления", callback_data="notif_off")
        else:
            btn = InlineKeyboardButton("🔔 Включить уведомления", callback_data="notif_on")
        
        keyboard = [
            [btn],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def notification_dismiss():
        """Закрыть уведомление"""
        keyboard = [[InlineKeyboardButton("✖️ Закрыть", callback_data="dismiss")]]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def notification_with_stream(stream_url: str):
        """Уведомление со ссылкой на трансляцию"""
        keyboard = [
            [InlineKeyboardButton("📺 Смотреть трансляцию", url=stream_url)],
            [InlineKeyboardButton("📱 Telegram LiveBall", url="https://t.me/liveballst")],
            [InlineKeyboardButton("✖️ Закрыть", callback_data="dismiss")]
        ]
        return InlineKeyboardMarkup(keyboard)
