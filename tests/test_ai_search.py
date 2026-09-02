import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove

import core.db as db
from handlers.ai_search import (
    AI_SEARCH_BUTTON_TEXT,
    handle_ai_search_button_message,
    handle_ai_search_message,
    send_stored_post,
)


class FakeMessage:
    def __init__(self, text=None):
        self.text = text
        self.replies = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append((text, reply_markup))


class FakeContext:
    def __init__(self):
        self.user_data = {}
        self.application = SimpleNamespace(bot_data={})
        self.bot = None


class AiSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_button_enters_ai_and_hides_keyboard(self):
        context = FakeContext()
        message = FakeMessage(AI_SEARCH_BUTTON_TEXT)

        handled = await handle_ai_search_button_message(
            SimpleNamespace(effective_message=message),
            context,
        )

        self.assertTrue(handled)
        self.assertTrue(context.user_data["ai_search_active"])
        self.assertIsInstance(message.replies[-1][1], ReplyKeyboardRemove)

    async def test_aliexpress_link_is_the_ai_exit_path(self):
        context = FakeContext()
        context.user_data["ai_search_active"] = True
        message = FakeMessage(
            "https://www.aliexpress.com/item/1005001234567890.html"
        )

        handled = await handle_ai_search_message(
            SimpleNamespace(effective_message=message),
            context,
        )

        self.assertFalse(handled)
        self.assertNotIn("ai_search_active", context.user_data)
        self.assertIsInstance(message.replies[-1][1], ReplyKeyboardMarkup)

    async def test_source_photo_is_uploaded_and_cached(self):
        context = FakeContext()
        sent = SimpleNamespace(photo=[SimpleNamespace(file_id="bot-file-id")])
        context.bot = SimpleNamespace(
            send_photo=AsyncMock(return_value=sent),
            send_message=AsyncMock(),
        )
        post = {
            "id": 42,
            "content": "عرض تجريبي",
            "photo_file_id": None,
            "source_channel_id": -100,
            "source_message_id": 7,
        }

        with patch(
            "handlers.ai_search._download_source_photo",
            new=AsyncMock(return_value=BytesIO(b"image")),
        ), patch(
            "handlers.ai_search._cache_photo_file_id",
            new=AsyncMock(),
        ) as cache:
            await send_stored_post(123, context, post, has_next=False)

        uploaded = context.bot.send_photo.await_args.kwargs["photo"]
        self.assertEqual(uploaded.filename, "channel-post-42.jpg")
        cache.assert_awaited_once_with(42, "bot-file-id")


class DatabaseSearchTests(unittest.TestCase):
    @patch.object(db, "DATABASE_URL", "postgres://test")
    @patch.object(db, "get_db_connection")
    def test_specific_product_search_uses_title_and_specific_keyword(
        self,
        get_connection,
    ):
        connection = get_connection.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        db.search_channel_posts(
            {
                "request_type": "product_best",
                "keywords": ["هاتف", "iPhone 15", "phone"],
            },
            limit=3,
        )

        query, params = cursor.execute.call_args.args
        self.assertIn("title ILIKE", query)
        self.assertNotIn("content ILIKE", query)
        self.assertEqual(params, ["%iPhone 15%", 3])

    @patch.object(db, "DATABASE_URL", "postgres://test")
    @patch.object(db, "get_db_connection")
    def test_cleanup_uses_three_day_retention_window(self, get_connection):
        connection = get_connection.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.rowcount = 2

        deleted = db.delete_expired_channel_posts()

        self.assertEqual(deleted, 2)
        query = cursor.execute.call_args.args[0]
        self.assertIn("CURRENT_TIMESTAMP - INTERVAL '3 days'", query)


if __name__ == "__main__":
    unittest.main()