import unittest

from utils.formatter import format_product_message


class ProductMessageFormatterTests(unittest.TestCase):
    def test_includes_three_copyable_codes_in_required_lines(self):
        info = {
            "product_title": "Test product",
            "target_sale_price": "210 USD",
            "target_original_price": "250 USD",
            "target_discount": "16%",
            "lastest_volume": "100",
            "shop_name": "Test shop",
            "evaluate_rate": "95%",
            "shop_url": "https://s.click.aliexpress.com/e/_c3dTcI6F",
            "first_level_category_name": "Category",
            "second_level_category_name": "Subcategory",
            "commission_rate": "5%",
        }
        coupon = {
            "label": "30/200$",
            "codes": ["CODE-1", "CODE-2", "CODE-3", "CODE-4"],
        }

        message = format_product_message(info, coupon)
        lines = message.splitlines()

        self.assertEqual(lines[7], "🎟️ **الكوبون:** 30/200$")
        self.assertEqual(
            lines[8],
            "🎫 **الرموز الترويجية:** `CODE-1` `CODE-2` `CODE-3`",
        )
        self.assertEqual(lines[9], "")
        self.assertNotIn("CODE-4", message)
        self.assertIn("[رابط المتجر](https://s.click.aliexpress.com/e/_c3dTcI6F)", message)


if __name__ == "__main__":
    unittest.main()