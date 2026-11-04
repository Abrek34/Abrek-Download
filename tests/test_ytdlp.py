"""yt-dlp indiricisinin son dosya çözümleme testleri."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ["ABREK_LANG"] = "tr"

from core.ytdlp import YtDlpDownloader, playlist_entry_url


class PlaylistEntryUrlTests(unittest.TestCase):
    def test_prefers_full_webpage_url(self):
        self.assertEqual(
            playlist_entry_url(
                {},
                {
                    "url": "https://www.youtube.com/watch?v=abc",
                    "webpage_url": "https://www.youtube.com/watch?v=abc",
                },
            ),
            "https://www.youtube.com/watch?v=abc",
        )

    def test_builds_youtube_url_from_bare_id(self):
        self.assertEqual(
            playlist_entry_url(
                {"extractor_key": "Youtube"},
                {"id": "abc123", "url": "abc123"},
            ),
            "https://www.youtube.com/watch?v=abc123",
        )

    def test_rejects_unknown_bare_id(self):
        self.assertEqual(
            playlist_entry_url({}, {"id": "abc123", "url": "abc123"}),
            "",
        )


class FinalPathTests(unittest.TestCase):
    def make_downloader(self, directory: str, video_id: str = "abc123") -> YtDlpDownloader:
        downloader = YtDlpDownloader.__new__(YtDlpDownloader)
        downloader.config = SimpleNamespace(download_dir=Path(directory))
        downloader.final_file = Path(directory) / "missing_path.txt"
        downloader._final_hint = ""
        downloader._dest_paths = []
        downloader._start_time = time.time() - 30
        downloader.audio_only = False
        downloader._video_id = video_id
        return downloader

    def test_final_marker_is_captured(self):
        downloader = YtDlpDownloader.__new__(YtDlpDownloader)
        downloader._tail = []
        downloader._final_hint = ""
        downloader._handle_line("@@VA_FINAL@@/tmp/Video [abc123].mp4")
        self.assertEqual(downloader._final_hint, "/tmp/Video [abc123].mp4")

    def test_fallback_prefers_matching_video_id(self):
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / "Baska [zzz999].mp4"
            right = Path(directory) / "Video [abc123].mp4"
            wrong.write_bytes(b"wrong")
            right.write_bytes(b"right")
            downloader = self.make_downloader(directory)
            self.assertEqual(downloader._read_final_path(), str(right))

    def test_fallback_without_video_id_does_not_guess(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "Video [abc123].mp4").write_bytes(b"data")
            downloader = self.make_downloader(directory, video_id="")
            self.assertEqual(downloader._read_final_path(), "")


if __name__ == "__main__":
    unittest.main()
