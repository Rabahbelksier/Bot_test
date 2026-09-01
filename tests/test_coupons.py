import unittest
from unittest.mock import patch

from core.coupons import get_available_coupons, get_best_coupon_for_price
from handlers.coupons import (
    NO_COUPONS_TEXT,
    format_coupons_message,
    format_coupons_messages,
)


class CouponMessageTests(unittest.TestCase):
    def test_formats_all_codes_as_copyable_code_entities(self):
        message = format_coupons_message([
            {
                "label": "3/15$",
                "codes": ["first-code", "second<code>"],
            },
        ])

        self.assertIn("🎟️<b>3/15$</b>🎟️", message)
        self.assertIn("✂️ <code>first-code</code>", message)
        self.assertIn("✂️ <code>second&lt;code&gt;</code>", message)

    def test_skips_coupon_without_codes(self):
        self.assertEqual(
            format_coupons_message([{"label": "3/15$", "codes": []}]),
            "",
        )

    def test_separates_coupon_types_with_a_blank_line(self):
        message = format_coupons_messages([
            {"label": "3/15$", "codes": ["first-code"]},
            {"label": "5/30$", "codes": ["second-code"]},
        ])[0]

        self.assertIn(
            "✂️ <code>first-code</code>\n\n🎟️<b>5/30$</b>🎟️",
            message,
        )

    def test_empty_message_uses_unavailable_text(self):
        self.assertEqual(NO_COUPONS_TEXT, "❌ لا تتوفر رموز ترويجية حاليا، يرجى المحاولة لاحقا.")

    def test_collects_all_code_columns_and_groups_duplicate_coupon_values(self):
        rows = [
            {"id": 1, "value": "3/15$", "cod_1": "first", "cod_20": "last"},
            {"id": 2, "value": "3/15$", "cod_2": "second", "cod_20": "last"},
        ]

        with patch("core.coupons._query_rows", return_value=rows):
            coupons = get_available_coupons()

        self.assertEqual(coupons[0]["codes"], ["first", "last", "second"])

    def test_selects_highest_discount_when_multiple_thresholds_apply(self):
        coupons = [
            {"label": "6/50$", "discount": 6, "threshold": 50, "codes": ["six"]},
            {"label": "30/200$", "discount": 30, "threshold": 200, "codes": ["thirty"]},
            {"label": "40/280$", "discount": 40, "threshold": 280, "codes": ["forty"]},
        ]

        selected = get_best_coupon_for_price(coupons, "210 USD")

        self.assertEqual(selected["label"], "30/200$")

    def test_coupon_threshold_is_inclusive_and_codes_are_required(self):
        coupons = [
            {"label": "10/100$", "discount": 10, "threshold": 100, "codes": []},
            {"label": "8/100$", "discount": 8, "threshold": 100, "codes": ["eight"]},
        ]

        selected = get_best_coupon_for_price(coupons, "$100.00")

        self.assertEqual(selected["label"], "8/100$")

    def test_splits_long_responses_between_code_lines(self):
        messages = format_coupons_messages([
            {"label": "3/15$", "codes": ["a" * 10, "b" * 10]},
        ], max_length=45)

        self.assertEqual(len(messages), 2)
        self.assertTrue(all(len(message) <= 45 for message in messages))