import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import ReplyKeyboardMarkup

from services.worker import process_link_for_user


class WorkerKeyboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_restores_ai_keyboard_when_link_processing_fails(self):
        loading = SimpleNamespace(message_id=1)
        error = SimpleNamespace(message_id=2)
        keyboard_refresh = SimpleNamespace(message_id=3)
        bot = SimpleNamespace(
            send_message=AsyncMock(
                side_effect=[loading, error, keyboard_refresh],
            ),
            delete_message=AsyncMock(),
        )
        context = SimpleNamespace(
            bot=bot,
            user_data={"restore_ai_search_keyboard": True},
        )

        with patch(
            "services.worker.extract_product_id",
            return_value="100500123",
        ), patch(
            "services.worker.get_product_info_from_api",
            side_effect=RuntimeError("temporary API failure"),
        ), patch(
            "services.worker.generate_affiliate_links",
            return_value=[],
        ):
            await process_link_for_user(
                123,
                "https://www.aliexpress.com/item/100500123.html",
                context,
            )

        refresh_call = bot.send_message.await_args_list[-1]
        self.assertIsInstance(
            refresh_call.kwargs["reply_markup"],
            ReplyKeyboardMarkup,
        )
        self.assertIn("اسأل الذكاء الاصطناعي", refresh_call.kwargs["text"])