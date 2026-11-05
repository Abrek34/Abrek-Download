"""İndirme yöneticisi probe entegrasyon testleri."""

from __future__ import annotations

import os
import threading
import time
import unittest
from unittest import mock

os.environ["ABREK_LANG"] = "tr"

from core.manager import DownloadManager, _ProbeSample
from core.models import Capture
from core.probe import MediaProbe, probe_hls


class ManagerProbeTests(unittest.TestCase):
    def make_manager(self, capture):
        manager = DownloadManager.__new__(DownloadManager)
        manager.lock = threading.RLock()
        manager.captures = [capture]
        manager._probe_pending = set()
        manager._save_locked = mock.Mock()
        return manager

    def test_native_complete_probe_skips_fallbacks(self):
        hls = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="tr",URI="audio.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
video.m3u8
"""
        capture = Capture(url="https://cdn.test/video.m3u8", kind="hls")
        manager = self.make_manager(capture)
        sample = _ProbeSample(
            data=b"",
            text=hls,
            final_url="https://cdn.test/video.m3u8",
            content_type="application/vnd.apple.mpegurl",
            manifest=probe_hls(hls),
        )
        with mock.patch.object(manager, "_fetch_probe_sample", return_value=sample):
            with mock.patch.object(manager, "_probe_with_ffprobe") as ffprobe:
                with mock.patch.object(manager, "_probe_with_ytdlp") as ytdlp:
                    manager._probe_capture(capture.id)
                    ffprobe.assert_not_called()
                    ytdlp.assert_not_called()
        self.assertEqual(capture.media_kind, "av")
        self.assertEqual(capture.media_info, "1080p")
        self.assertFalse(capture.drm)
        manager._save_locked.assert_called()

    def test_audio_only_manifest(self):
        hls = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="tr",URI="audio.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=1000,CODECS="mp4a.40.2"
audio.m3u8
"""
        capture = Capture(url="https://cdn.test/audio.m3u8", kind="hls")
        manager = self.make_manager(capture)
        sample = _ProbeSample(
            data=b"",
            text=hls,
            final_url="https://cdn.test/audio.m3u8",
            content_type="application/vnd.apple.mpegurl",
            manifest=probe_hls(hls),
        )
        with mock.patch.object(manager, "_fetch_probe_sample", return_value=sample):
            with mock.patch.object(manager, "_probe_with_ytdlp") as ytdlp:
                manager._probe_capture(capture.id)
                ytdlp.assert_not_called()
        self.assertEqual(capture.media_kind, "audio")
        self.assertEqual(capture.media_info, "ses")

    def test_incomplete_probe_uses_ytdlp_fallback(self):
        capture = Capture(url="https://cdn.test/segment.ts", kind="direct")
        manager = self.make_manager(capture)
        sample = _ProbeSample(data=b"\x47" * 188, final_url="https://cdn.test/segment.ts")
        with mock.patch.object(manager, "_fetch_probe_sample", return_value=sample):
            with mock.patch.object(manager, "_probe_with_ffprobe", return_value=None):
                with mock.patch.object(
                    manager,
                    "_probe_with_ytdlp",
                    return_value=MediaProbe(has_video=True, height=720, source="yt-dlp"),
                ) as ytdlp:
                    manager._probe_capture(capture.id)
                    ytdlp.assert_called_once()
        self.assertEqual(capture.media_kind, "video")
        self.assertEqual(capture.media_info, "720p")

    def test_drm_is_recorded(self):
        hls = """#EXTM3U
#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key.bin"
#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2"
video.m3u8
"""
        capture = Capture(url="https://cdn.test/drm.m3u8", kind="hls")
        manager = self.make_manager(capture)
        sample = _ProbeSample(
            data=b"",
            text=hls,
            final_url="https://cdn.test/drm.m3u8",
            content_type="application/vnd.apple.mpegurl",
            manifest=probe_hls(hls),
        )
        with mock.patch.object(manager, "_fetch_probe_sample", return_value=sample):
            with mock.patch.object(manager, "_probe_with_ytdlp") as ytdlp:
                manager._probe_capture(capture.id)
                ytdlp.assert_not_called()
        self.assertTrue(capture.drm)

    def test_download_capture_blocks_drm(self):
        capture = Capture(url="https://cdn.test/drm.m3u8", kind="hls", drm=True)
        manager = DownloadManager.__new__(DownloadManager)
        manager.lock = threading.RLock()
        manager.captures = [capture]
        manager.tasks = {}
        manager.config = {}
        with self.assertRaises(ValueError):
            DownloadManager.download_capture(manager, capture.id)


if __name__ == "__main__":
    unittest.main()