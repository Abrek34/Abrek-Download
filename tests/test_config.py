"""Yapılandırma yolları ve değer doğrulama testleri."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.config import (
    DEFAULT_DOWNLOAD_DIR,
    Config,
    _xdg_dir,
    _xdg_download_dir,
)


class XdgPathTests(unittest.TestCase):
    def test_absolute_environment_path_wins(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(os.environ, {"XDG_DATA_HOME": directory}),
        ):
            self.assertEqual(_xdg_dir("XDG_DATA_HOME", ".local/share"), Path(directory))

    def test_relative_environment_path_is_ignored(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(os.environ, {"XDG_DATA_HOME": "relative/path"}),
        ):
            home = Path(directory)
            self.assertEqual(
                _xdg_dir("XDG_DATA_HOME", ".local/share", home),
                home / ".local/share",
            )

    def test_download_dir_is_read_from_user_dirs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            config_home = root / "config"
            config_home.mkdir()
            (config_home / "user-dirs.dirs").write_text(
                'XDG_DOWNLOAD_DIR="$HOME/İndirilenler"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                _xdg_download_dir(home=home, config_home=config_home),
                home / "İndirilenler",
            )

    def test_download_dir_falls_back_to_existing_localized_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "İndirilenler").mkdir()
            self.assertEqual(
                _xdg_download_dir(home=home, config_home=home / ".config"),
                home / "İndirilenler",
            )

    def test_download_dir_falls_back_to_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.assertEqual(
                _xdg_download_dir(home=home, config_home=home / ".config"),
                home / "Downloads",
            )


class ConfigValidationTests(unittest.TestCase):
    def test_load_coerces_types_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "auto_retry": "false",
                        "auto_resume": "0",
                        "notify_captures": "no",
                        "notify_downloads": 0,
                        "capture_paused": "true",
                        "watch_clipboard": "yes",
                        "download_subtitles": "off",
                        "theme": "neon",
                        "shutdown_on_finish": "reboot",
                        "language": "de",
                        "cookies_browser": "edge",
                        "default_quality": "8k",
                        "max_concurrent": "99",
                        "connections": 0,
                        "speed_limit_kbps": -4,
                        "auto_retry_limit": 42,
                        "download_dir": None,
                        "subtitle_langs": 123,
                        "window_geometry": ["x"],
                    }
                ),
                encoding="utf-8",
            )

            config = Config(path)

        self.assertFalse(config.get("auto_retry"))
        self.assertFalse(config.get("auto_resume"))
        self.assertFalse(config.get("notify_captures"))
        self.assertFalse(config.get("notify_downloads"))
        self.assertTrue(config.get("capture_paused"))
        self.assertTrue(config.get("watch_clipboard"))
        self.assertFalse(config.get("download_subtitles"))
        self.assertEqual(config.get("theme"), "dark")
        self.assertEqual(config.get("shutdown_on_finish"), "none")
        self.assertEqual(config.get("language"), "tr")
        self.assertEqual(config.get("cookies_browser"), "none")
        self.assertEqual(config.get("default_quality"), "best")
        self.assertEqual(config.get("max_concurrent"), 5)
        self.assertEqual(config.get("connections"), 1)
        self.assertEqual(config.get("speed_limit_kbps"), 0)
        self.assertEqual(config.get("auto_retry_limit"), 5)
        self.assertEqual(config.get("download_dir"), str(DEFAULT_DOWNLOAD_DIR))
        self.assertEqual(config.get("subtitle_langs"), "tr,en")
        self.assertEqual(config.get("window_geometry"), "")

    def test_load_handles_infinite_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                '{"max_concurrent": 1e999, "connections": -1e999}',
                encoding="utf-8",
            )

            config = Config(path)

        self.assertEqual(config.get("max_concurrent"), 2)
        self.assertEqual(config.get("connections"), 4)

    def test_update_normalizes_before_saving(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = Config(path)
            config.update(
                {
                    "theme": "light",
                    "auto_retry": "false",
                    "max_concurrent": 9,
                    "download_dir": str(Path(directory) / "indirmeler"),
                }
            )

            stored = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(config.get("theme"), "light")
        self.assertFalse(config.get("auto_retry"))
        self.assertEqual(config.get("max_concurrent"), 5)
        self.assertEqual(stored["theme"], "light")
        self.assertFalse(stored["auto_retry"])

    def test_download_dir_property_creates_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "yeni" / "klasör"
            config = Config(Path(directory) / "config.json")
            config.update({"download_dir": str(target)})
            self.assertEqual(config.download_dir, target)
            self.assertTrue(target.is_dir())


if __name__ == "__main__":
    unittest.main()
