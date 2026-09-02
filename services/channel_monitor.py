import io
import logging
from urllib.parse import urlparse

from telethon import TelegramClient, events
from telethon.tl.types import PeerChannel
from telethon.sessions import StringSession

from config import TELEGRAM_API_HASH, TELEGRAM_API_ID, TELEGRAM_SESSION_STRING
from core.db import get_telegram_channel_links
from core.channel_processor import process_channel_message

logger = logging.getLogger(__name__)


class ChannelMonitor:
    """Long-lived MTProto listener using a dedicated Telegram user account."""

    def __init__(self):
        self.client = None
        self.task = None
        self.entities = []

    @property
    def configured(self):
        return bool(
            TELEGRAM_API_ID
            and TELEGRAM_API_HASH
            and TELEGRAM_SESSION_STRING
        )

    async def start(self):
        if not self.configured:
            logger.warning(
                "Channel monitor is disabled: TELEGRAM_API_ID, "
                "TELEGRAM_API_HASH, and TELEGRAM_SESSION_STRING are required"
            )
            return False

        self.client = TelegramClient(
            StringSession(TELEGRAM_SESSION_STRING),
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
        )
        await self.client.connect()
        if not await self.client.is_user_authorized():
            logger.error(
                "Channel monitor is disabled: the Telegram user session is unauthorized"
            )
            await self.client.disconnect()
            self.client = None
            return False

        for channel in get_telegram_channel_links():
            try:
                self.entities.append(
                    await self.client.get_entity(_channel_reference(channel["link"]))
                )
            except Exception:
                logger.exception("Could not resolve monitored channel %s", channel["link"])

        if not self.entities:
            logger.warning("Channel monitor is ready but no channels are configured")
            await self.client.disconnect()
            self.client = None
            return True

        self.client.add_event_handler(
            self._handle_new_message,
            events.NewMessage(chats=self.entities),
        )
        self.task = self.client.loop.create_task(
            self.client.run_until_disconnected()
        )
        logger.info("Channel monitor started for %d channel(s)", len(self.entities))
        return True

    async def _handle_new_message(self, event):
        message = event.message
        chat = await event.get_chat()
        await process_channel_message(
            message,
            channel_id=event.chat_id,
            channel_username=getattr(chat, "username", None),
        )

    async def download_photo(self, channel_id, message_id):
        """Download a source photo when no Bot API file_id has been cached yet."""
        if not self.client:
            return None
        source_message = await self.client.get_messages(
            channel_id,
            ids=message_id,
        )
        if not source_message or not getattr(source_message, "photo", None):
            return None
        buffer = io.BytesIO()
        await self.client.download_media(source_message, file=buffer)
        buffer.seek(0)
        return buffer

    async def stop(self):
        if self.client:
            await self.client.disconnect()
            self.client = None


def _channel_reference(link):
    """Turn a stored public channel URL into a Telethon username reference."""
    value = (link or "").strip()
    try:
        parsed = urlparse(value)
    except ValueError:
        return value
    if parsed.netloc.lower() in {"t.me", "www.t.me", "telegram.me"}:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "c" and parts[1].isdigit():
            return PeerChannel(int(parts[1]))
        if parts and parts[0] not in {"c", "joinchat", "+", "addlist"}:
            return parts[0].lstrip("@")
    return value