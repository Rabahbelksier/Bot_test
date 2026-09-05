from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.ai import _call_gemini, analyze_channel_post, parse_user_request


class AiParsingTests(unittest.TestCase):
    @patch("core.ai._call_gemini")
    def test_normalizes_channel_offer_analysis(self, call_gemini):
        call_gemini.return_value = {
            "is_offer": True,
            "title": "  POCO C85 6/128GB Batterie 5000mAh - عرض كامل  ",
            "discounted_price": "12,50",
        }
        self.assertEqual(
            analyze_channel_post("POCO C85 6/128GB Batterie 5000mAh بسعر 12.50$"),
            {
                "is_offer": True,
                "title": "POCO C85 6/128GB Batterie 5000mAh - عرض كامل",
                "price": 12.5,
            },
        )
        prompt = call_gemini.call_args.args[0]
        self.assertIn("العنوان الكامل", prompt)

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
                "category": "phones",
                "min_price": 50.0,
                "max_price": 100.0,
                "required_specs": [],
            },
        )

    @patch("core.ai._call_gemini")
    def test_keeps_supported_long_request_details_for_model(self, call_gemini):
        call_gemini.return_value = {
            "request_type": "product_cheapest",
            "keywords": ["Samsung S24 Ultra", "256GB"],
        }
        long_request = (
            "السلام عليكم، أبحث عن هاتف مناسب للعمل والتصوير. "
            + ("شرح إضافي لا يغير الطلب. " * 400)
            + "المهم أريد Samsung S24 Ultra 256GB بأرخص عرض."
        )

        result = parse_user_request(long_request)

        self.assertEqual(result["request_type"], "product_cheapest")
        self.assertEqual(result["keywords"], ["Samsung S24 Ultra", "256GB"])
        self.assertEqual(
            result["required_specs"],
            [],
        )
        prompt = call_gemini.call_args.args[0]
        self.assertIn("اقرأ رسالة المستخدم كاملة", prompt)
        self.assertIn("Samsung S24 Ultra 256GB", prompt)
        self.assertIn("... [تم اختصار الجزء الأوسط", prompt)

    @patch("core.ai._call_gemini")
    def test_rejects_incomplete_category_intent(self, call_gemini):
        call_gemini.return_value = {
            "request_type": "category_cheapest",
            "keywords": [],
            "category": None,
        }

        self.assertEqual(
            parse_user_request("أريد أفضل شيء بسعر مناسب"),
            {
                "request_type": "unsupported",
                "keywords": [],
                "category": None,
                "min_price": None,
                "max_price": None,
                "required_specs": [],
            },
        )

    @patch("core.ai._call_gemini")
    def test_extracts_storage_and_ram_constraints_from_user_text(self, call_gemini):
        call_gemini.return_value = {
            "request_type": "category_price_range",
            "keywords": ["هواتف", "phones"],
            "category": "phones",
            "max_price": 300,
        }

        result = parse_user_request(
            "اريد عروض هواتف دات مساحة تخزين 256gb ورام 12gb "
            "ويجب ان تكون بسعر اقل من 300$"
        )

        self.assertEqual(result["request_type"], "category_price_range")
        self.assertEqual(result["max_price"], 300.0)
        self.assertEqual(
            result["required_specs"],
            [
                {"type": "storage", "value": "256GB"},
                {"type": "ram", "value": "12GB"},
            ],
        )
        self.assertIn("required_specs", call_gemini.call_args.args[0])

    @patch("core.ai._call_gemini")
    def test_preserves_category_filter_for_trending_requests(self, call_gemini):
        call_gemini.return_value = {
            "request_type": "trending",
            "keywords": ["هواتف", "phones"],
            "category": "phones",
        }

        result = parse_user_request(
            "اريد العروض الرائجة اليوم على الهواتف فقط"
        )

        self.assertEqual(result["request_type"], "trending")
        self.assertEqual(result["category"], "phones")
        self.assertEqual(result["keywords"], ["هواتف", "phones"])

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

    @patch("core.ai._wait_for_gemini_request_slot")
    @patch("core.ai.requests.post")
    @patch("core.ai.GEMINI_MODEL", "gemini-flash-latest")
    @patch("core.ai.GEMINI_API_KEY", "test-key")
    def test_switches_model_after_rate_limit(self, post, _wait_for_slot):
        rate_limited = SimpleNamespace(
            status_code=429,
            headers={},
            ok=False,
        )
        successful = SimpleNamespace(
            status_code=200,
            headers={},
            ok=True,
        )
        successful.json = lambda: {
            "candidates": [
                {"content": {"parts": [{"text": '{"ok": true}'}]}}
            ]
        }
        post.side_effect = [rate_limited, successful]

        self.assertEqual(_call_gemini("أعد JSON فقط"), {"ok": True})
        self.assertIn(
            "/models/gemini-3.5-flash-lite:generateContent",
            post.call_args_list[1].args[0],
        )


if __name__ == "__main__":
    unittest.main()