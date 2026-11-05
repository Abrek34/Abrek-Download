"""Yerel API güvenlik kontrolleri testleri."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ["ABREK_LANG"] = "tr"

from core.models import DownloadTask
from core.server import ApiHandler, host_allowed, origin_allowed


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
            "chrome-extension://abcdefghijklmnop",
            "moz-extension://abcdefghijklmnop",
            "safari-web-extension://abcdefghijklmnop",
            "http://127.0.0.1:8765",
            "http://localhost:8765",
        ):
            with self.subTest(value=value):
                self.assertTrue(origin_allowed(value))

    def test_rejects_empty_and_null_and_foreign_origins(self):
        for value in (
            None,
            "",
            "null",
            "https://evil.example",
            "http://127.0.0.1:9999",
            "chrome-extension://",
        ):
            with self.subTest(value=value):
                self.assertFalse(origin_allowed(value))


class ApiRouteTests(unittest.TestCase):
    def make_handler(self, path: str, manager) -> ApiHandler:
        handler = ApiHandler.__new__(ApiHandler)
        handler.path = path
        handler.headers = {}
        handler.manager = manager
        handler._check_host = lambda: True
        handler._check_origin = lambda: True
        handler._send_json = mock.Mock()
        handler._send_html = mock.Mock()
        return handler

    def test_get_stats(self):
        manager = SimpleNamespace(
            stats=mock.Mock(return_value={"active": 1, "queued": 2, "retrying": 1})
        )
        handler = self.make_handler("/api/stats", manager)
        handler.do_GET()
        handler._send_json.assert_called_once_with(
            200, {"ok": True, "active": 1, "queued": 2, "retrying": 1}
        )

    def test_get_task_detail(self):
        task = DownloadTask(url="https://x.test/a.mp4", retry_count=1)
        manager = SimpleNamespace(get_task=mock.Mock(return_value=task))
        handler = self.make_handler(f"/api/tasks/{task.id}", manager)
        handler.do_GET()
        status, payload = handler._send_json.call_args.args
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["task"]["retry_count"], 1)

    def test_get_missing_task_returns_404(self):
        manager = SimpleNamespace(get_task=mock.Mock(return_value=None))
        handler = self.make_handler("/api/tasks/yok", manager)
        handler.do_GET()
        self.assertEqual(handler._send_json.call_args.args[0], 404)

    def test_capture_download_endpoint(self):
        task = DownloadTask(url="https://x.test/a.mp4")
        manager = SimpleNamespace(
            download_capture=mock.Mock(return_value=(task, False))
        )
        handler = self.make_handler("/api/captures/c1/download", manager)
        handler._read_json = lambda: {}
        handler.do_POST()
        manager.download_capture.assert_called_once_with("c1")
        status, payload = handler._send_json.call_args.args
        self.assertEqual(status, 200)
        self.assertFalse(payload["duplicate"])

    def test_private_network_preflight_header(self):
        handler = ApiHandler.__new__(ApiHandler)
        handler.headers = {
            "Origin": "chrome-extension://abcdefghijklmnop",
            "Access-Control-Request-Private-Network": "true",
        }
        headers = handler._cors_headers()
        self.assertEqual(headers["Access-Control-Allow-Private-Network"], "true")
        self.assertEqual(
            headers["Access-Control-Allow-Origin"],
            "chrome-extension://abcdefghijklmnop",
        )


if __name__ == "__main__":
    unittest.main()
