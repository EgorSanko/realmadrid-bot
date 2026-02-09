#!/usr/bin/env python3
"""
Скрипт для авторизации Telethon
Запустить ОДИН раз на сервере для создания сессии
"""

import asyncio
from telethon import TelegramClient

API_ID = 34185547
API_HASH = '643cd6834f58c6756392a8d7128ebf7b'
SESSION_PATH = '/root/RealMadridBot/data/tg_session'

async def main():
    print("🔐 Авторизация Telethon...")
    print(f"Session path: {SESSION_PATH}")
    
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start()
    
    me = await client.get_me()
    print(f"✅ Авторизован как: {me.first_name} (@{me.username})")
    print(f"✅ Сессия сохранена в: {SESSION_PATH}.session")
    
    # Тест - получим последние сообщения из канала
    print("\n📰 Тест - последние 5 постов из @realmadridcdf:")
    async for msg in client.iter_messages('realmadridcdf', limit=5):
        if msg.text:
            print(f"  - {msg.date.strftime('%d.%m %H:%M')}: {msg.text[:60]}...")
    
    await client.disconnect()
    print("\n✅ Готово! Теперь перезапусти docker-compose")

if __name__ == '__main__':
    asyncio.run(main())
