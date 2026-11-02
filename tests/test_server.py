"""Yerel API güvenlik kontrolleri testleri."""

from __future__ import annotations

import os
import unittest

os.environ["ABREK_LANG"] = "tr"

from core.server import host_allowed


class HostAllowedTests(unittest.TestCase):
    def test_allows_local_addresses(self):
        for value in (
            None,
            "",
            "127.0.0.1",
            "127.0.0.1:8765",
            "localhost",
            "localhost:8765",
            "LOCALHOST:8765",
        ):
            with self.subTest(value=value):
                self.assertTrue(host_allowed(value))

    def test_rejects_foreign_hosts(self):
        for value in (
            "evil.example",
            "127.0.0.1.evil.example",
            "192.168.1.10:8765",
            "localhost.evil.example",
            "0.0.0.0:8765",
        ):
            with self.subTest(value=value):
                self.assertFalse(host_allowed(value))


if __name__ == "__main__":
    unittest.main()
