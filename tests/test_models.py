"""Veri modelleri ve format seçici testleri."""

from __future__ import annotations

import os
import unittest

os.environ["ABREK_LANG"] = "tr"

from core.models import (
    QUALITY_LABELS,
    Capture,
    DownloadTask,
    make_capture,
    quality_label,
    status_label,
)
from core.ytdlp import build_format_selector, youtube_extra_args, ytdlp_version


class DownloadTaskTests(unittest.TestCase):
    def test_display_title_falls_back_to_url(self):
        task = DownloadTask(url="https://x.test/video.mp4?token=1")
        self.assertEqual(task.display_title(), "video.mp4")
        task.title = "Kedi videosu"
        self.assertEqual(task.display_title(), "Kedi videosu")

    def test_snapshot_labels(self):
        task = DownloadTask(
            url="https://x.test/video.mp4",
            page_url="https://www.example.com/watch",
            quality="1080",
            status="downloading",
        )
        snapshot = task.snapshot()
        self.assertEqual(snapshot["host"], "example.com")
        self.assertEqual(snapshot["status_label"], "İndiriliyor")
        self.assertEqual(snapshot["quality_label"], "1080p")

    def test_roundtrip_ignores_unknown_keys(self):
        task = DownloadTask(url="https://x.test/a.mp4", title="A")
        data = task.to_dict()
        data["unknown"] = "ignored"
        restored = DownloadTask.from_dict(data)
        self.assertEqual(restored.url, task.url)
        self.assertEqual(restored.title, task.title)
        self.assertFalse(hasattr(restored, "unknown"))

    def test_empty_id_is_regenerated(self):
        restored = DownloadTask.from_dict({"id": "", "url": "https://x.test/a.mp4"})
        self.assertTrue(restored.id)

    def test_retry_fields_roundtrip(self):
        task = DownloadTask(
            url="https://x.test/a.mp4",
            retry_count=2,
            available_at=1234.5,
        )
        restored = DownloadTask.from_dict(task.to_dict())
        self.assertEqual(restored.retry_count, 2)
        self.assertEqual(restored.available_at, 1234.5)

    def test_status_and_quality_helpers(self):
        self.assertEqual(status_label("queued"), "Sırada")
        self.assertEqual(status_label("bilinmeyen"), "bilinmeyen")
        self.assertEqual(quality_label("best"), QUALITY_LABELS["best"])
        self.assertEqual(quality_label("bilinmeyen"), "bilinmeyen")


class CaptureTests(unittest.TestCase):
    def test_manifest_labels(self):
        capture = Capture(kind="hls", media_kind="manifest", media_info="1080p")
        data = capture.to_dict()
        self.assertEqual(data["kind_label"], "HLS")
        self.assertEqual(data["media_label"], "AKIŞ 1080p")

    def test_audio_labels(self):
        capture = Capture(kind="direct", media_kind="audio")
        self.assertEqual(capture.media_label(), "SES (SADECE)")

    def test_make_capture_defaults(self):
        capture = make_capture(
            {
                "url": "https://x.test/video.mp4",
                "page_url": "https://x.test/watch",
                "pageTitle": "Başlık",
                "contentType": "video/mp4",
            }
        )
        self.assertEqual(capture.page_title, "Başlık")
        self.assertEqual(capture.title, "Başlık")
        self.assertEqual(capture.referer, "https://x.test/watch")
        self.assertEqual(capture.media_kind, "video")

    def test_probe_timestamp_roundtrip(self):
        capture = Capture(url="https://x.test/video.mp4", probed_at=987.5)
        restored = Capture.from_dict(capture.to_dict())
        self.assertEqual(restored.probed_at, 987.5)


class YoutubeArgsTests(unittest.TestCase):
    def test_youtube_extra_args(self):
        expected = ["--remote-components", "ejs:github"]
        self.assertEqual(youtube_extra_args("https://youtu.be/abc"), expected)
        self.assertEqual(youtube_extra_args("https://www.youtube.com/watch?v=abc"), expected)
        self.assertEqual(youtube_extra_args("https://example.com/video.mp4"), [])


class FormatSelectorTests(unittest.TestCase):
    def test_audio_selector(self):
        self.assertIn("ba", build_format_selector("audio"))

    def test_height_selector(self):
        selector = build_format_selector("1080")
        self.assertIn("height<=1080", selector)

    def test_ytdlp_version_available(self):
        version = ytdlp_version()
        self.assertTrue(version)
        self.assertNotEqual(version, "bilinmiyor")


if __name__ == "__main__":
    unittest.main()
