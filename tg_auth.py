#!/usr/bin/env python3
import asyncio
from telethon import TelegramClient

API_ID = 34185547
API_HASH = '643cd6834f58c6756392a8d7128ebf7b'
SESSION_PATH = '/root/realmadrid-bot-fixed/data/tg_session'

async def main():
    print("🔐 Авторизация Telethon...")
    print(f"Session path: {SESSION_PATH}")
    
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start()
    
    me = await client.get_me()
    print(f"✅ Авторизован как: {me.first_name} (@{me.username})")
    
    print("\n📰 Тест - последние 3 поста из @realmadridcdf:")
    async for msg in client.iter_messages('realmadridcdf', limit=3):
        if msg.text:
            print(f"  - {msg.text[:60]}...")
    
    await client.disconnect()
    print("\n✅ Готово!")

if __name__ == '__main__':
    asyncio.run(main())
