import unittest
from unittest.mock import patch

from core.ai import analyze_channel_post, parse_user_request


class AiParsingTests(unittest.TestCase):
    @patch("core.ai._call_gemini")
    def test_normalizes_channel_offer_analysis(self, call_gemini):
        call_gemini.return_value = {
            "is_offer": True,
            "title": "  هاتف تجريبي  ",
            "discounted_price": "12,50",
        }
        self.assertEqual(
            analyze_channel_post("هاتف بسعر 12.50$"),
            {
                "is_offer": True,
                "title": "هاتف تجريبي",
                "price": 12.5,
            },
        )

    @patch("core.ai._call_gemini")
    def test_normalizes_user_search_request(self, call_gemini):
        call_gemini.return_value = {
            "request_type": "category_price_range",
            "keywords": ["هواتف", "phones"],
            "min_price": "50",
            "max_price": "100",
        }
        self.assertEqual(
            parse_user_request("هواتف بين 50 و100 دولار"),
            {
                "request_type": "category_price_range",
                "keywords": ["هواتف", "phones"],
                "min_price": 50.0,
                "max_price": 100.0,
            },
        )

    @patch("core.ai._call_gemini")
    def test_swaps_reversed_price_range(self, call_gemini):
        call_gemini.return_value = {
            "request_type": "product_price_range",
            "keywords": ["هاتف"],
            "min_price": 150,
            "max_price": 50,
        }
        result = parse_user_request("من 150 إلى 50")
        self.assertEqual(result["min_price"], 50.0)
        self.assertEqual(result["max_price"], 150.0)


if __name__ == "__main__":
    unittest.main()