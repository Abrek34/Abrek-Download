"""Yardımcı fonksiyonlar için birim testleri."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ["ABREK_LANG"] = "tr"

from core.utils import (
    atomic_write_json,
    clean_error,
    filename_from_url,
    first_url_argument,
    human_duration,
    human_eta,
    human_size,
    human_speed,
    is_http_url,
    is_manifest_url,
    is_youtube_url,
    load_json,
    normalize_url,
    parse_eta_text,
    parse_number,
    parse_percent,
    parse_speed,
    sanitize_filename,
    unique_path,
    url_extension,
)


class HumanFormatTests(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(1024), "1.00 KB")
        self.assertEqual(human_size(10 * 1024 * 1024), "10.0 MB")

    def test_human_speed(self):
        self.assertEqual(human_speed(0), "—")
        self.assertEqual(human_speed(2048), "2.00 KB/s")

    def test_human_eta_and_duration(self):
        self.assertEqual(human_eta(61), "01:01")
        self.assertEqual(human_eta(3661), "01:01:01")
        self.assertEqual(human_duration(0), "")
        self.assertEqual(human_duration(3661), "1:01:01")


class UrlTests(unittest.TestCase):
    def test_normalize_url(self):
        self.assertEqual(normalize_url("example.com/video"), "https://example.com/video")
        self.assertEqual(normalize_url("//cdn.example.com/a.mp4"), "https://cdn.example.com/a.mp4")
        self.assertEqual(normalize_url(" https://x.test/a "), "https://x.test/a")

    def test_url_checks(self):
        self.assertTrue(is_http_url("https://x.test/a.mp4"))
        self.assertFalse(is_http_url("ftp://x.test/a.mp4"))
        self.assertEqual(url_extension("https://x.test/A.MP4?token=1"), ".mp4")
        self.assertTrue(is_manifest_url("https://x.test/live.m3u8?x=1"))
        self.assertFalse(is_manifest_url("https://x.test/video.mp4"))

    def test_is_youtube_url(self):
        self.assertTrue(is_youtube_url("https://www.youtube.com/watch?v=abc"))
        self.assertTrue(is_youtube_url("https://youtu.be/abc"))
        self.assertTrue(is_youtube_url("https://music.youtube.com/watch?v=abc"))
        self.assertTrue(is_youtube_url("https://www.youtube-nocookie.com/embed/abc"))
        self.assertFalse(is_youtube_url("https://notyoutube.com/watch?v=abc"))
        self.assertFalse(is_youtube_url("https://example.com/youtube.com"))

    def test_first_url_argument(self):
        self.assertEqual(
            first_url_argument(["--verbose", "https://x.test/a.mp4"]),
            "https://x.test/a.mp4",
        )
        self.assertEqual(
            first_url_argument(["'http://x.test/b.mp4'", "https://x.test/c.mp4"]),
            "http://x.test/b.mp4",
        )
        self.assertEqual(first_url_argument(["--help", "video.mp4"]), "")

    def test_filename_from_url(self):
        self.assertEqual(
            filename_from_url("https://x.test/video.mp4?token=1", content_type="video/mp4"),
            "video.mp4",
        )
        # Medya olmayan URL uzantısı MIME türüyle düzeltilmeli.
        self.assertEqual(
            filename_from_url("https://x.test/stream.php?token=1", content_type="video/mp4"),
            "stream.mp4",
        )
        self.assertEqual(
            filename_from_url("https://x.test/audio.php", content_type="audio/mpeg"),
            "audio.mp3",
        )

    def test_sanitize_filename(self):
        cleaned = sanitize_filename('  a/b:c*?  ')
        self.assertNotIn("/", cleaned)
        self.assertNotIn(":", cleaned)
        self.assertNotIn("*", cleaned)


class ParseTests(unittest.TestCase):
    def test_parse_speed(self):
        self.assertAlmostEqual(parse_speed("1.5MiB/s"), 1.5 * 1024 ** 2)
        self.assertAlmostEqual(parse_speed("2.5 MB/s"), 2.5 * 1024 ** 2)
        self.assertEqual(parse_speed("unknown"), 0.0)

    def test_parse_eta(self):
        self.assertEqual(parse_eta_text("01:02:03"), 3723)
        self.assertEqual(parse_eta_text("02:03"), 123)
        self.assertEqual(parse_eta_text("N/A"), 0)

    def test_parse_number_and_percent(self):
        self.assertEqual(parse_number("1.5"), 1)
        self.assertEqual(parse_number("N/A"), 0)
        self.assertAlmostEqual(parse_percent("99.5%"), 99.5)
        self.assertEqual(parse_percent("150%"), 100.0)

    def test_clean_error(self):
        text = "WARNING: bir şey\nERROR: asıl hata\nson satır"
        self.assertEqual(clean_error(text), "asıl hata")


class FileTests(unittest.TestCase):
    def test_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nested" / "data.json"
            payload = {"başlık": "Türkçe", "sayı": 3}
            atomic_write_json(path, payload)
            self.assertEqual(load_json(path), payload)
            self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["başlık"])

    def test_unique_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            first = unique_path(directory, "video.mp4")
            first.write_text("x", encoding="utf-8")
            second = unique_path(directory, "video.mp4")
            self.assertNotEqual(first, second)
            self.assertEqual(second.name, "video (1).mp4")


if __name__ == "__main__":
    unittest.main()
