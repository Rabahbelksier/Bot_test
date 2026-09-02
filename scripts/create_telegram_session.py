import asyncio
import getpass
import os
from pathlib import Path

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession


OUTPUT_PATH = Path(".telegram_session_string")


async def create_session():
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        print("Choose login method: [1] QR code (recommended), [2] phone code")
        method = input("Selection [1]: ").strip() or "1"

        if method == "2":
            await client.start()
        else:
            await client.connect()
            qr_login = await client.qr_login()
            qr = qrcode.QRCode(border=1)
            qr.add_data(qr_login.url)
            qr.make(fit=True)
            print("\nOpen Telegram on your phone:")
            print("Settings > Devices > Link Desktop Device")
            print("Scan this QR code before it expires:\n")
            qr.print_ascii(invert=True)
            print(f"\nQR login URL: {qr_login.url}")
            try:
                await qr_login.wait()
            except SessionPasswordNeededError:
                password = getpass.getpass("Telegram two-step verification password: ")
                await client.sign_in(password=password)

        if not await client.is_user_authorized():
            raise RuntimeError("Telegram account authorization was not completed")

        session_string = client.session.save()
        OUTPUT_PATH.write_text(session_string, encoding="utf-8")
        OUTPUT_PATH.chmod(0o600)
        print(f"\nSession created in {OUTPUT_PATH}")
        print(
            "Copy the file contents into the TELEGRAM_SESSION_STRING secret, "
            "then delete the file."
        )
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(create_session())