#!/usr/bin/env python3
"""
Скрипт массовой рассылки уведомлений всем пользователям бота
Запуск: python3 broadcast.py
"""

import sqlite3
import os
import time
import requests

# Токен бота
BOT_TOKEN = os.getenv('BOT_TOKEN', '')

# Путь к базе данных
DB_PATH = '/app/data/real_madrid.db'

# Текст сообщения
MESSAGE = """
🚨 <b>ВАЖНОЕ УВЕДОМЛЕНИЕ!</b> 🚨

Дорогие друзья! 

После ошеломительного поражения от команды, чья стоимость всей команды даже не закроет зарплату Винисиуса, многие игроки которые поставили на Реал сейчас сидят с 0 очками 😅

Дабы был стимул и дальше пользоваться этим великолепным приложением, было сделано много чего нового!

🆕 <b>ЧТО НОВОГО:</b>

📱 <b>Бот теперь только присылает уведомления о матчах</b>
Все функции перенесены в приложение!

🧠 <b>Добавлена ВИКТОРИНА</b>
Отвечай на вопросы о Реал Мадрид и зарабатывай очки!
1 вопрос → 24 часа кулдаун

⚽ <b>Новые типы ставок:</b>
• Тотал голов (больше/меньше)
• Тотал угловых
• Обе забьют (да/нет)
• Точный счёт (высокие коэфы!)
• Исход матча

Теперь каждый сам вправе ставить на те ставки которые хочет и искать выгодные для себя коэффициенты! 📈

⚠️ <b>ВАЖНО:</b>
Кнопки бота больше не функционируют!
Всё происходит в приложении для вашего удобства и комфорта 👀

🔔 <b>Пожалуйста, не отключайте уведомления</b>, чтобы не забывать ставить ставки и получать информацию о матчах!

💡 Есть пожелания и предложения? 
Пишите в личку @papito007 
<i>(Я вас благополучно пошлю... выслушаю если реально крутое предложение 😉)</i>

С любовью и без негатива,
Фан-база Реал Мадрида ⚪

<b>¡HALA MADRID! 🏆</b>
"""

def get_all_users():
    """Получить всех пользователей из БД"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name FROM users")
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
