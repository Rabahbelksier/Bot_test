import unittest

from utils.app_promotion import (
    APP_DOWNLOAD_URL,
    APP_PROMOTION_IMAGE_URL,
    APP_PROMOTION_CALLBACK,
    APP_PROMOTION_TEXT,
    app_download_keyboard,
    app_promotion_button,
)


class AppPromotionTests(unittest.TestCase):
    def test_offer_message_button_opens_promotion_callback(self):
        button = app_promotion_button()

        self.assertEqual(button.text, "تطبيق العروض Offers 365")
        self.assertEqual(button.callback_data, APP_PROMOTION_CALLBACK)

    def test_download_keyboard_points_to_google_play(self):
        button = app_download_keyboard().inline_keyboard[0][0]

        self.assertEqual(button.text, "⬇️تحميل التطبيق⬇️")
        self.assertEqual(button.url, APP_DOWNLOAD_URL)

    def test_promotion_message_contains_requested_app_features(self):
        self.assertIn("تطبيق العروض Offres 365", APP_PROMOTION_TEXT)
        self.assertIn("السلة الذكية AI", APP_PROMOTION_TEXT)
        self.assertIn("طلب عرض AI", APP_PROMOTION_TEXT)

    def test_promotion_image_uses_requested_url(self):
        self.assertEqual(
            APP_PROMOTION_IMAGE_URL,
            "https://gcdnb.pbrd.co/images/izrHmBCJ5zgs.jpg",
        )


if __name__ == "__main__":
    unittest.main()