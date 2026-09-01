import unittest

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.telegram import markup_without_callback


class TelegramKeyboardTests(unittest.TestCase):
    def test_removes_only_the_pressed_button(self):
        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("التفاصيل", callback_data="details_123"),
                InlineKeyboardButton("السلة الذكية", callback_data="smart_cart_123"),
            ],
            [
                InlineKeyboardButton("الكوبونات", callback_data="show_coupons"),
            ],
        ])

        updated = markup_without_callback(markup, "details_123")

        self.assertEqual(
            [
                [button.callback_data for button in row]
                for row in updated.inline_keyboard
            ],
            [["smart_cart_123"], ["show_coupons"]],
        )

    def test_returns_no_markup_when_last_button_is_pressed(self):
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("التفاصيل", callback_data="details_123"),
        ]])

        self.assertIsNone(markup_without_callback(markup, "details_123"))


if __name__ == "__main__":
    unittest.main()