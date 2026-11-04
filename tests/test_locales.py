"""Dil dosyalarının eksiksiz ve tutarlı olduğunu doğrular."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"


class LocaleParityTests(unittest.TestCase):
    def test_languages_have_same_keys(self):
        translations = {}
        for language in ("tr", "en"):
            path = LOCALES_DIR / f"{language}.json"
            translations[language] = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            set(translations["tr"]),
            set(translations["en"]),
            "Türkçe ve İngilizce dil dosyalarındaki anahtarlar eşleşmiyor.",
        )

    def test_new_ui_keys_exist(self):
        required = {
            "downloads.open_folder",
            "captures.pause",
            "captures.resume",
            "captures.copy",
            "captures.copied",
            "settings.restart_required",
            "stats.capture_paused",
            "cli.help",
            "cli.version",
            "downloads.batch",
            "downloads.batch_title",
            "downloads.toast.batch_summary",
            "settings.auto_retry",
            "settings.auto_retry_limit",
            "task.detail.auto_retry",
        }
        for language in ("tr", "en"):
            data = json.loads((LOCALES_DIR / f"{language}.json").read_text(encoding="utf-8"))
            with self.subTest(language=language):
                self.assertTrue(required <= set(data))


if __name__ == "__main__":
    unittest.main()
