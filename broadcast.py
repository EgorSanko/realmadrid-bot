#!/usr/bin/env python3
"""
Скрипт массовой рассылки уведомлений всем пользователям бота
Запуск: docker exec rm-bot python3 /app/broadcast.py
"""

import sqlite3
import os
import time
import requests

# Токен бота
BOT_TOKEN = os.getenv('BOT_TOKEN', '')

# Путь к базе данных
DB_PATH = '/app/data/betting.db'

# Текст сообщения
MESSAGE = """
🚀 <b>ОБНОВЛЕНИЕ ПРИЛОЖЕНИЯ!</b> 🚀

Привет, мадридисты! 

Мы добавили кучу новых фич для вашего удобства:

🆕 <b>НОВЫЕ ТИПЫ СТАВОК:</b>

🟨 <b>Жёлтые карточки</b>
Ставь на больше/меньше 3.5 или 4.5 карточек!

⚽ <b>Индивидуальные тоталы</b>
• ИТ хозяев (сколько забьёт первая команда)
• ИТ гостей (сколько забьёт вторая команда)

⚠️ <b>Пенальти в матче</b>
Будет или не будет пенальти? Коэф до 4.50!

📜 <b>ИСТОРИЯ ТРАНЗАКЦИЙ</b>
Теперь в профиле есть вкладка "История" — смотри все свои ставки, выигрыши, бонусы!

💡 <b>Предложения и идеи?</b>
Пишите @papito007

<b>¡HALA MADRID! ⚪🏆</b>
"""

def get_all_users():
    """Получить всех пользователей из БД"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name FROM users WHERE is_banned = 0")
    users = cursor.fetchall()
    conn.close()
    return users

def send_message(user_id, text):
    """Отправить сообщение через Telegram API"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        'chat_id': user_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    response = requests.post(url, data=data, timeout=10)
    return response.json()

def broadcast():
    """Отправить сообщение всем пользователям"""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не установлен!")
        return
    
    users = get_all_users()
    print(f"📢 Начинаю рассылку для {len(users)} пользователей...")
    
    success = 0
    failed = 0
    blocked = 0
    
    for user_id, username, first_name in users:
        try:
            result = send_message(user_id, MESSAGE)
            
            if result.get('ok'):
                success += 1
                print(f"✅ {success}/{len(users)} - @{username or first_name or user_id}")
            else:
                error = result.get('description', '').lower()
                if 'blocked' in error or 'deactivated' in error or 'not found' in error:
                    blocked += 1
                    print(f"🚫 Заблокировал/удалён: @{username or user_id}")
                else:
                    failed += 1
                    print(f"❌ Ошибка для {user_id}: {result.get('description')}")
            
            # Задержка чтобы не словить лимит Telegram
            time.sleep(0.05)
            
        except Exception as e:
            failed += 1
            print(f"❌ Ошибка для {user_id}: {e}")
    
    print(f"\n{'='*50}")
    print(f"📊 ИТОГИ РАССЫЛКИ:")
    print(f"✅ Успешно: {success}")
    print(f"🚫 Заблокировали бота: {blocked}")
    print(f"❌ Ошибки: {failed}")
    print(f"📨 Всего пользователей: {len(users)}")
    print(f"{'='*50}")

if __name__ == '__main__':
    broadcast()
