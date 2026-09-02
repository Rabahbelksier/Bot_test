import unittest

from telethon.tl.types import PeerChannel

from services.channel_monitor import _channel_reference


class ChannelMonitorTests(unittest.TestCase):
    def test_resolves_public_channel_url_to_username(self):
        self.assertEqual(
            _channel_reference("https://t.me/rabahcopons"),
            "rabahcopons",
        )

    def test_resolves_private_channel_link_to_peer_channel(self):
        reference = _channel_reference("https://t.me/c/1234567890/42")
        self.assertIsInstance(reference, PeerChannel)
        self.assertEqual(reference.channel_id, 1234567890)


if __name__ == "__main__":
    unittest.main()