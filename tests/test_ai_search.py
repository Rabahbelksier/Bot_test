import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove

import core.db as db
from handlers.ai_search import (
    AI_SEARCH_BUTTON_TEXT,
    _navigation_keyboard,
    _replace_stored_post_message,
    ai_next_callback,
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
        self.assertEqual(message.replies, [])
        self.assertTrue(context.user_data["restore_ai_search_keyboard"])

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

    async def test_navigation_replaces_existing_text_message(self):
        context = FakeContext()
        context.bot = SimpleNamespace(
            edit_message_text=AsyncMock(),
            delete_message=AsyncMock(),
            send_message=AsyncMock(),
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
            message_id=456,
            photo=None,
        )
        query = SimpleNamespace(
            message=message,
            answer=AsyncMock(),
        )
        post = {
            "id": 43,
            "content": "عرض آخر",
            "title": "عرض آخر",
            "photo_file_id": None,
            "source_channel_id": -100,
            "source_message_id": 8,
        }

        with patch(
            "handlers.ai_search._load_post_photo",
            new=AsyncMock(return_value=(None, False)),
        ):
            await _replace_stored_post_message(
                query,
                context,
                post,
                has_previous=True,
                has_next=False,
            )

        edit_kwargs = context.bot.edit_message_text.await_args.kwargs
        buttons = edit_kwargs["reply_markup"].inline_keyboard[0]
        self.assertEqual([button.text for button in buttons], ["السابق"])

    async def test_search_keeps_complete_results_for_fast_navigation(self):
        context = FakeContext()
        message = FakeMessage("أرخص الهواتف")
        posts = [
            {"id": 1, "title": "هاتف أول"},
            {"id": 2, "title": "هاتف ثان"},
        ]
        update = SimpleNamespace(
            effective_message=message,
            effective_chat=SimpleNamespace(id=123),
        )

        with patch(
            "handlers.ai_search.parse_user_request",
            return_value={"request_type": "category_cheapest"},
        ), patch(
            "handlers.ai_search.search_channel_posts",
            return_value=posts,
        ), patch(
            "handlers.ai_search.send_stored_post",
            new=AsyncMock(),
        ) as send_post:
            handled = await handle_ai_search_message(update, context)

        self.assertTrue(handled)
        self.assertEqual(context.user_data["ai_search_results"], posts)
        self.assertEqual(context.user_data["ai_search_index"], 0)
        send_post.assert_awaited_once_with(
            123,
            context,
            posts[0],
            has_previous=False,
            has_next=True,
        )

    async def test_next_uses_in_memory_result_without_database_lookup(self):
        context = FakeContext()
        context.user_data["ai_search_results"] = [
            {"id": 1, "title": "العرض الأول"},
            {"id": 2, "title": "العرض الثاني", "photo_file_id": "cached-photo"},
        ]
        context.user_data["ai_search_index"] = 0
        query_message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
            message_id=456,
            photo=None,
            reply_text=AsyncMock(),
        )
        query = SimpleNamespace(
            message=query_message,
            answer=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)

        with patch(
            "handlers.ai_search.get_channel_post",
            side_effect=AssertionError("navigation should not query the database"),
        ), patch(
            "handlers.ai_search._replace_stored_post_message",
            new=AsyncMock(),
        ) as replace_post:
            await ai_next_callback(update, context)

        query.answer.assert_awaited_once()
        replace_post.assert_awaited_once_with(
            query,
            context,
            context.user_data["ai_search_results"][1],
            has_previous=True,
            has_next=False,
        )
        self.assertEqual(context.user_data["ai_search_index"], 1)

    async def test_navigation_does_not_wait_for_uncached_source_photo(self):
        context = FakeContext()
        context.bot = SimpleNamespace(
            edit_message_text=AsyncMock(),
            delete_message=AsyncMock(),
            send_message=AsyncMock(),
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
            message_id=456,
            photo=None,
        )
        query = SimpleNamespace(message=message)
        post = {
            "id": 43,
            "content": "عرض سريع بدون صورة مخزنة",
            "photo_file_id": None,
            "source_channel_id": -100,
            "source_message_id": 8,
        }

        with patch(
            "handlers.ai_search._download_source_photo",
            new=AsyncMock(side_effect=AssertionError("photo download should be skipped")),
        ):
            await _replace_stored_post_message(
                query,
                context,
                post,
                has_previous=True,
                has_next=False,
            )

        context.bot.edit_message_text.assert_awaited_once()

    async def test_failed_navigation_does_not_advance_index(self):
        context = FakeContext()
        context.user_data["ai_search_results"] = [
            {"id": 1, "title": "العرض الأول"},
            {"id": 2, "title": "العرض الثاني"},
        ]
        context.user_data["ai_search_index"] = 0
        query_message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
            reply_text=AsyncMock(),
        )
        query = SimpleNamespace(
            message=query_message,
            answer=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)

        with patch(
            "handlers.ai_search._replace_stored_post_message",
            new=AsyncMock(side_effect=RuntimeError("Telegram error")),
        ):
            await ai_next_callback(update, context)

        self.assertEqual(context.user_data["ai_search_index"], 0)
        query_message.reply_text.assert_awaited_once()

    def test_navigation_buttons_are_side_by_side(self):
        markup = _navigation_keyboard(has_previous=True, has_next=True)

        self.assertEqual(
            [button.text for button in markup.inline_keyboard[0]],
            ["السابق", "التالي"],
        )


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
        self.assertNotIn("content ILIKE", query)
        self.assertEqual(params, [500])

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

    def test_category_and_typo_matching_stay_in_the_requested_product_family(self):
        from core.db import _post_match_score

        phone_intent = {
            "request_type": "category_price_range",
            "category": "phones",
        }
        self.assertIsNotNone(
            _post_match_score(
                {"title": "iPhone 15 Pro"},
                phone_intent,
                ["هواتف", "phones"],
            )
        )
        self.assertIsNone(
            _post_match_score(
                {"title": "Bluetooth Earbuds"},
                phone_intent,
                ["هواتف", "phones"],
            )
        )

        product_intent = {"request_type": "product_best"}
        self.assertIsNotNone(
            _post_match_score(
                {"title": "iPhone 15 Pro"},
                product_intent,
                ["iphnoe 15"],
            )
        )


if __name__ == "__main__":
    unittest.main()