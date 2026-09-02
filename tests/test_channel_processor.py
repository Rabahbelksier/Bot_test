import unittest
from unittest.mock import patch

from core.channel_processor import (
    build_source_link,
    rewrite_post_text,
)


class ChannelProcessorTests(unittest.TestCase):
    def test_rewrites_telegram_and_all_aliexpress_links(self):
        text = (
            "عرض جديد https://t.me/source/12\n"
            "الرابط الأول https://www.aliexpress.com/item/111.html\n"
            "والثاني https://a.aliexpress.com/_abc"
        )
        rewritten = rewrite_post_text(
            text,
            {
                "https://www.aliexpress.com/item/111.html": "https://affiliate/111",
                "https://a.aliexpress.com/_abc": "https://affiliate/abc",
            },
        )
        self.assertIn("https://t.me/rabahcopons/7366", rewritten)
        self.assertIn("https://affiliate/111", rewritten)
        self.assertIn("https://affiliate/abc", rewritten)
        self.assertNotIn("https://t.me/source/12", rewritten)

    def test_builds_public_source_link(self):
        self.assertEqual(
            build_source_link("@offers", 42),
            "https://t.me/offers/42",
        )
        self.assertEqual(
            build_source_link(None, 42, -1001234567890),
            "https://t.me/c/1234567890/42",
        )
        self.assertIsNone(build_source_link(None, 42))


class ChannelProcessorAffiliateTests(unittest.IsolatedAsyncioTestCase):
    @patch("core.channel_processor.generate_affiliate_link")
    async def test_generates_one_link_for_each_unique_source_url(self, generate):
        from core.channel_processor import _generate_affiliate_replacements

        generate.side_effect = lambda url: f"affiliate:{url.rsplit('/', 1)[-1]}"
        result = await _generate_affiliate_replacements([
            "https://a.aliexpress.com/one",
            "https://a.aliexpress.com/two",
        ])
        self.assertEqual(
            result,
            {
                "https://a.aliexpress.com/one": "affiliate:one",
                "https://a.aliexpress.com/two": "affiliate:two",
            },
        )


if __name__ == "__main__":
    unittest.main()