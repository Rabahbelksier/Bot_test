import unittest
import os
from decimal import Decimal

# The application configuration validates these values during import.
for name in ("APP_KEY", "APP_SECRET", "TRACKING_ID", "TELEGRAM_TOKEN"):
    os.environ.setdefault(name, "test")

from handlers.admin import _parse_cart_line, format_cart_row


class AdminCartTests(unittest.TestCase):
    def test_parses_the_admin_cart_template(self):
        row = _parse_cart_line(
            "1 | https://example.com/item?a=1&b=2 | 45.2 | 20 | 2 | 0"
        )

        self.assertEqual(row["id"], 1)
        self.assertEqual(row["link"], "https://example.com/item?a=1&b=2")
        self.assertEqual(row["price"], Decimal("45.2"))
        self.assertEqual(row["final_price"], Decimal("20"))
        self.assertEqual(row["stor"], Decimal("2"))
        self.assertEqual(row["shipping"], Decimal("0"))

    def test_formats_link_label_and_url_as_html(self):
        message = format_cart_row({
            "id": 1,
            "linkcart": "https://example.com/item?a=1&b=2",
            "pricecart": Decimal("45.20"),
            "pricefinalecart": Decimal("20.00"),
            "stor": Decimal("2"),
            "ship": Decimal("0"),
        })

        self.assertIn("1 | <a href=\"https://example.com/item?a=1&amp;b=2\">link</a>", message)
        self.assertIn(
            "<a href=\"https://example.com/item?a=1&amp;b=2\">"
            "https://example.com/item?a=1&amp;b=2</a>",
            message,
        )
        self.assertIn("| 45.2 | 20 | 2 | 0", message)

    def test_rejects_a_row_with_the_wrong_number_of_columns(self):
        with self.assertRaises(ValueError):
            _parse_cart_line("1 | https://example.com | 45.2 | 20 | 2")


if __name__ == "__main__":
    unittest.main()