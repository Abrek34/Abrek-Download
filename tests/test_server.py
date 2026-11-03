"""Yerel API güvenlik kontrolleri testleri."""

from __future__ import annotations

import os
import unittest

os.environ["ABREK_LANG"] = "tr"

from core.server import host_allowed, origin_allowed


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


class OriginAllowedTests(unittest.TestCase):
    def test_allows_extensions_and_local_dashboard(self):
        for value in (
            None,
            "",
            "chrome-extension://abcdefghijklmnop",
            "moz-extension://abcdefghijklmnop",
            "safari-web-extension://abcdefghijklmnop",
            "http://127.0.0.1:8765",
            "http://localhost:8765",
        ):
            with self.subTest(value=value):
                self.assertTrue(origin_allowed(value))

    def test_rejects_null_and_foreign_origins(self):
        for value in (
            "null",
            "https://evil.example",
            "http://127.0.0.1:9999",
            "chrome-extension://",
        ):
            with self.subTest(value=value):
                self.assertFalse(origin_allowed(value))


if __name__ == "__main__":
    unittest.main()
