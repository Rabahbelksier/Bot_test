import asyncio
import os
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession


OUTPUT_PATH = Path(".telegram_session_string")


async def create_session():
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start()
    session_string = client.session.save()
    OUTPUT_PATH.write_text(session_string, encoding="utf-8")
    await client.disconnect()
    print(f"Session created in {OUTPUT_PATH}")
    print("Copy its contents into the TELEGRAM_SESSION_STRING secret, then delete the file.")


if __name__ == "__main__":
    asyncio.run(create_session())