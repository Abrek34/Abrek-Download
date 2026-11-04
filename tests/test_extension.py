"""Tarayıcı eklentisi sözleşme testleri."""

from __future__ import annotations

import json
import os
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"


class ExtensionContractTests(unittest.TestCase):
    def _manifest(self, browser: str) -> dict:
        return json.loads((EXT / browser / "manifest.json").read_text(encoding="utf-8"))

    def test_manifests_share_core_contract(self):
        chrome = self._manifest("chrome")
        firefox = self._manifest("firefox")
        self.assertEqual(chrome["manifest_version"], 3)
        self.assertEqual(firefox["manifest_version"], 3)
        self.assertEqual(chrome["name"], firefox["name"])
        self.assertEqual(chrome["version"], firefox["version"])
        self.assertEqual(chrome["permissions"], firefox["permissions"])
        self.assertEqual(chrome["host_permissions"], firefox["host_permissions"])
        self.assertEqual(chrome["icons"], firefox["icons"])
        self.assertEqual(chrome["content_scripts"], firefox["content_scripts"])
        self.assertEqual(chrome["action"], firefox["action"])
        self.assertEqual(chrome["background"]["service_worker"], "background.js")
        self.assertEqual(firefox["background"]["scripts"], ["background.js"])

    def test_assets_exist_and_icons_are_sized(self):
        expected_assets = {
            "background.js",
            "content.js",
            "popup.js",
            "popup.html",
            "popup.css",
            "manifest.json",
            "icon16.png",
            "icon32.png",
            "icon48.png",
            "icon128.png",
        }
        for browser in ("chrome", "firefox"):
            base = EXT / browser
            self.assertTrue(expected_assets.issubset({path.name for path in base.iterdir()}))
            for size, filename in (
                (16, "icon16.png"),
                (32, "icon32.png"),
                (48, "icon48.png"),
                (128, "icon128.png"),
            ):
                with (base / filename).open("rb") as handle:
                    header = handle.read(24)
                self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
                width, height = struct.unpack(">II", header[16:24])
                self.assertEqual((width, height), (size, size))

    def test_quality_options_are_consistent(self):
        content = (EXT / "chrome" / "content.js").read_text(encoding="utf-8")
        popup_html = (EXT / "chrome" / "popup.html").read_text(encoding="utf-8")
        popup_js = (EXT / "chrome" / "popup.js").read_text(encoding="utf-8")
        for browser in ("chrome", "firefox"):
            self.assertEqual(
                (EXT / browser / "content.js").read_text(encoding="utf-8"),
                content,
            )
            self.assertEqual(
                (EXT / browser / "popup.html").read_text(encoding="utf-8"),
                popup_html,
            )
            self.assertEqual(
                (EXT / browser / "popup.js").read_text(encoding="utf-8"),
                popup_js,
            )
        for quality in ("best", "2160", "1440", "1080", "720", "480", "audio"):
            self.assertIn(f"q: '{quality}'", content)
            self.assertIn(f'value="{quality}"', popup_html)
        for quality in ("2160", "1440", "1080", "720", "480"):
            self.assertIn(f"'{quality}': '{quality}p'", popup_js)

    def test_api_contract(self):
        for browser in ("chrome", "firefox"):
            background = (EXT / browser / "background.js").read_text(encoding="utf-8")
            self.assertIn("http://127.0.0.1:8765", background)
            for endpoint in ("/api/health", "/api/captures", "/api/download"):
                self.assertIn(endpoint, background)
        server = (ROOT / "core" / "server.py").read_text(encoding="utf-8")
        for endpoint in (
            "/api/health",
            "/api/captures",
            "/api/tasks",
            "/api/stats",
            "/api/download",
        ):
            self.assertIn(endpoint, server)


if __name__ == "__main__":
    unittest.main()