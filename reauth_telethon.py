import asyncio
import sys
from telethon import TelegramClient

API_ID = 34185547
API_HASH = "643cd6834f58c6756392a8d7128abf7b"
PHONE = "+79627124076"

async def main():
    client = TelegramClient("/root/realmadrid-bot-fixed/data/tg_session", API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        print("Sending code to", PHONE)
        await client.send_code_request(PHONE)
        print("Code sent! Enter the code from Telegram:")
        code = input("Code: ").strip()
        try:
            await client.sign_in(PHONE, code)
        except Exception as e:
            if "Two-steps verification" in str(e) or "2FA" in str(e):
                pw = input("2FA password: ").strip()
                await client.sign_in(password=pw)
            else:
                raise

    me = await client.get_me()
    print(f"Authorized as: {me.first_name} (ID: {me.id})")

    try:
        entity = await client.get_entity("realmadridruofficial")
        print(f"Channel OK: {entity.title}")
    except Exception as e:
        print(f"Channel error: {e}")

    await client.disconnect()
    print("Session saved!")

asyncio.run(main())
