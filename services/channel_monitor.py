import io
import logging
from urllib.parse import urlparse

from telethon import TelegramClient, events, utils
from telethon.tl.types import PeerChannel
from telethon.sessions import StringSession

from config import (
    CHANNEL_HISTORY_LIMIT,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    TELEGRAM_SESSION_STRING,
)
from core.db import get_retryable_channel_posts, get_telegram_channel_links
from core.channel_processor import process_channel_message

logger = logging.getLogger(__name__)


class ChannelMonitor:
    """Long-lived MTProto listener using a dedicated Telegram user account."""

    def __init__(self):
        self.client = None
        self.task = None
        self.history_task = None
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
            missing = [
                name
                for name, value in (
                    ("TELEGRAM_API_ID", TELEGRAM_API_ID),
                    ("TELEGRAM_API_HASH", TELEGRAM_API_HASH),
                    ("TELEGRAM_SESSION_STRING", TELEGRAM_SESSION_STRING),
                )
                if not value
            ]
            logger.warning(
                "Channel monitor is disabled; missing environment variable(s): %s",
                ", ".join(missing),
            )
            return False

        try:
            session = StringSession(TELEGRAM_SESSION_STRING)
        except ValueError:
            logger.error(
                "Channel monitor is disabled: TELEGRAM_SESSION_STRING is not a "
                "valid Telethon StringSession; run scripts/create_telegram_session.py"
            )
            return False

        self.client = TelegramClient(
            session,
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
        )
        try:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                logger.error(
                    "Channel monitor is disabled: the Telegram user session is unauthorized"
                )
                await self.client.disconnect()
                self.client = None
                return False
        except Exception:
            logger.exception("Channel monitor could not connect to Telegram")
            await self.client.disconnect()
            self.client = None
            return False

        try:
            channels = get_telegram_channel_links()
        except Exception:
            logger.exception("Channel monitor could not load channels from the database")
            await self.client.disconnect()
            self.client = None
            return False
        logger.info("Loaded %d channel(s) from the database", len(channels))
        for channel in channels:
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
        if CHANNEL_HISTORY_LIMIT:
            self.history_task = self.client.loop.create_task(
                self._backfill_recent_posts()
            )
        logger.info("Channel monitor started for %d channel(s)", len(self.entities))
        return True

    async def _handle_new_message(self, event):
        message = event.message
        chat = await event.get_chat()
        logger.info(
            "Received new post from channel_id=%s message_id=%s",
            event.chat_id,
            getattr(message, "id", None),
        )
        await process_channel_message(
            message,
            channel_id=event.chat_id,
            channel_username=getattr(chat, "username", None),
        )

    async def _backfill_recent_posts(self):
        """Process recent history so posts published before startup are not missed."""
        logger.info(
            "Starting channel history sync: up to %d post(s) per channel",
            CHANNEL_HISTORY_LIMIT,
        )
        entities_by_id = {
            utils.get_peer_id(entity): entity for entity in self.entities
        }
        retry_total = await self._retry_failed_posts(entities_by_id)
        total = retry_total
        for entity in self.entities:
            channel_id = utils.get_peer_id(entity)
            channel_username = getattr(entity, "username", None)
            examined = 0
            try:
                async for message in self.client.iter_messages(
                    entity,
                    limit=CHANNEL_HISTORY_LIMIT,
                ):
                    examined += 1
                    await process_channel_message(
                        message,
                        channel_id=channel_id,
                        channel_username=channel_username,
                    )
                total += examined
                logger.info(
                    "History sync completed for channel_id=%s: examined %d post(s)",
                    channel_id,
                    examined,
                )
            except Exception:
                logger.exception(
                    "History sync failed for channel_id=%s after %d post(s)",
                    channel_id,
                    examined,
                )
        logger.info("Channel history sync finished: examined %d post(s)", total)

    async def _retry_failed_posts(self, entities_by_id):
        """Retry known failed posts without downloading unrelated channel history."""
        try:
            retryable_posts = get_retryable_channel_posts()
        except Exception:
            logger.exception("Could not load retryable channel posts")
            return 0

        if not retryable_posts:
            return 0

        logger.info(
            "Retrying %d failed/pending channel post(s) from the database",
            len(retryable_posts),
        )
        examined = 0
        for post in retryable_posts:
            entity = entities_by_id.get(post["source_channel_id"])
            if not entity:
                continue
            try:
                message = await self.client.get_messages(
                    entity,
                    ids=post["source_message_id"],
                )
                if not message:
                    continue
                examined += 1
                await process_channel_message(
                    message,
                    channel_id=post["source_channel_id"],
                    channel_username=getattr(entity, "username", None),
                )
            except Exception:
                logger.exception(
                    "Retry failed for channel post %s/%s",
                    post["source_channel_id"],
                    post["source_message_id"],
                )
        logger.info("Retry pass finished: examined %d post(s)", examined)
        return examined

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
        self.task = None
        self.history_task = None


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