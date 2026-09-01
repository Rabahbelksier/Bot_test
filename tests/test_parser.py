import unittest
from unittest.mock import patch

from utils.parser import extract_product_id


class FakeResponse:
    def __init__(self, status_code, url, location=None, text=''):
        self.status_code = status_code
        self.url = url
        self.text = text
        self.headers = {}
        if location:
            self.headers['location'] = location


class ExtractProductIdTests(unittest.TestCase):
    def test_resolves_short_link_before_cookie_sync_loop(self):
        short_url = 'https://s.click.aliexpress.com/e/_EHzAJZs'
        responses = [
            FakeResponse(
                302,
                short_url,
                'https://www.aliexpress.com/item/1005012952862461.html?aff_fcid=tracking',
            ),
        ]

        with patch('utils.parser._http_session.get', side_effect=responses):
            self.assertEqual(extract_product_id(short_url), '1005012952862461')

    def test_resolves_nested_cookie_sync_destination(self):
        short_url = 'https://s.click.aliexpress.com/e/_EzO68OQ'
        cookie_sync = (
            'https://login.aliexpress.us/sync_cookie_write.htm?'
            'xman_goto=https%3A%2F%2Fwww.aliexpress.us%2Fitem%2F3256808639431520.html'
        )
        responses = [FakeResponse(302, short_url, cookie_sync)]

        with patch('utils.parser._http_session.get', side_effect=responses):
            self.assertEqual(extract_product_id(short_url), '3256808639431520')

    def test_keeps_direct_product_id_path_without_network_request(self):
        product_url = 'https://www.aliexpress.com/item/1005008825746272.html'

        with patch('utils.parser._http_session.get') as get:
            self.assertEqual(extract_product_id(product_url), '1005008825746272')
            get.assert_not_called()


if __name__ == '__main__':
    unittest.main()