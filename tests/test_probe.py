"""Yerleşik HLS/DASH/MP4/TS/WebM analiz testleri."""

from __future__ import annotations

import os
import struct
import unittest

os.environ["ABREK_LANG"] = "tr"

from core.probe import (
    MediaProbe,
    hls_first_segment,
    probe_bytes,
    probe_dash,
    probe_hls,
    probe_mpeg_ts,
    probe_mp4,
    probe_webm,
)


def box(kind: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


class HlsProbeTests(unittest.TestCase):
    def test_master_manifest(self):
        text = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="tr",URI="audio.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
video.m3u8
"""
        probe = probe_hls(text)
        self.assertIsNotNone(probe)
        self.assertTrue(probe.has_video)
        self.assertTrue(probe.has_audio)
        self.assertEqual((probe.width, probe.height), (1920, 1080))
        self.assertTrue(probe.complete)
        self.assertFalse(probe.drm)

    def test_sample_aes_is_drm(self):
        text = (
            "#EXTM3U\n"
            '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key.bin"\n'
            "#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1280x720,CODECS=\"avc1.64001f,mp4a.40.2\"\n"
            "video.m3u8\n"
        )
        probe = probe_hls(text)
        self.assertTrue(probe.drm)

    def test_media_playlist_is_incomplete(self):
        text = "#EXTM3U\n#EXTINF:10,\nsegment.ts\n"
        probe = probe_hls(text)
        self.assertFalse(probe.video_known)
        self.assertFalse(probe.audio_known)
        self.assertFalse(probe.complete)

    def test_first_segment_helper(self):
        text = "#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4\"\n#EXTINF:10,\nsegment.ts\n"
        self.assertEqual(hls_first_segment(text), ("init.mp4", "segment.ts"))


class DashProbeTests(unittest.TestCase):
    def test_manifest(self):
        text = """<?xml version="1.0"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period>
    <AdaptationSet mimeType="video/mp4" codecs="avc1.640028" width="1920" height="1080">
      <Representation id="v" bandwidth="1000"/>
    </AdaptationSet>
    <AdaptationSet mimeType="audio/mp4" codecs="mp4a.40.2">
      <Representation id="a" bandwidth="128"/>
    </AdaptationSet>
  </Period>
</MPD>
"""
        probe = probe_dash(text)
        self.assertIsNotNone(probe)
        self.assertTrue(probe.has_video)
        self.assertTrue(probe.has_audio)
        self.assertEqual((probe.width, probe.height), (1920, 1080))
        self.assertTrue(probe.complete)
        self.assertFalse(probe.drm)

    def test_content_protection_is_drm(self):
        text = """<?xml version="1.0"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period>
    <AdaptationSet mimeType="video/mp4" codecs="avc1.640028" width="1280" height="720">
      <Representation id="v" bandwidth="1000"/>
      <ContentProtection schemeIdUri="urn:uuid:123"/>
    </AdaptationSet>
  </Period>
</MPD>
"""
        probe = probe_dash(text)
        self.assertTrue(probe.drm)


class Mp4ProbeTests(unittest.TestCase):
    def _mp4(self, extra_moov: bytes = b"") -> bytes:
        tkhd = bytearray(84)
        struct.pack_into(">I", tkhd, 76, 1920 << 16)
        struct.pack_into(">I", tkhd, 80, 1080 << 16)
        trak = box(
            b"trak",
            box(b"tkhd", bytes(tkhd))
            + box(b"mdia", box(b"hdlr", b"\0" * 8 + b"vide")),
        )
        moov = box(b"moov", extra_moov + trak)
        ftyp = box(b"ftyp", b"isom" + b"\0" * 4 + b"isom")
        return ftyp + moov + b"\x00" * 16

    def test_faststart(self):
        probe = probe_mp4(self._mp4())
        self.assertIsNotNone(probe)
        self.assertTrue(probe.has_video)
        self.assertFalse(probe.has_audio)
        self.assertEqual((probe.width, probe.height), (1920, 1080))
        self.assertTrue(probe.complete)

    def test_tail_search_finds_moov(self):
        probe = probe_mp4(b"\x00" * 64 + self._mp4()[16:])
        self.assertIsNotNone(probe)
        self.assertEqual(probe.height, 1080)

    def test_pssh_is_drm(self):
        probe = probe_mp4(self._mp4(box(b"pssh", b"\x00" * 16)))
        self.assertTrue(probe.drm)

    def test_probe_bytes(self):
        probe = probe_bytes(self._mp4())
        self.assertIsNotNone(probe)
        self.assertEqual(probe.height, 1080)


class MpegTsProbeTests(unittest.TestCase):
    def _ts(self) -> bytes:
        def packet(pid: int, payload: bytes) -> bytes:
            header = bytes([0x47, 0x40 | ((pid >> 8) & 0x1F), pid & 0xFF, 0x10])
            body = bytes([0]) + payload
            return (header + body).ljust(188, b"\xff")

        def section(table_id: int, body: bytes) -> bytes:
            length = len(body) + 4
            return (
                bytes([table_id, 0xB0 | (length >> 8), length & 0xFF])
                + body
                + b"\x00\x00\x00\x00"
            )

        pat_body = struct.pack(">H", 1) + b"\xc1\x00\x00" + struct.pack(">H", 1) + b"\xe1\x00"
        pmt_body = (
            struct.pack(">H", 1)
            + b"\xc1\x00\x00"
            + b"\xe1\x00"
            + b"\xf0\x00"
            + bytes([0x1B])
            + b"\xe1\x01"
            + b"\xf0\x00"
            + bytes([0x0F])
            + b"\xe1\x02"
            + b"\xf0\x00"
        )
        return (
            packet(0, section(0x00, pat_body))
            + packet(0x100, section(0x02, pmt_body))
            + packet(0x100, b"data")
        )

    def test_detects_audio_and_video(self):
        probe = probe_mpeg_ts(self._ts())
        self.assertIsNotNone(probe)
        self.assertTrue(probe.has_video)
        self.assertTrue(probe.has_audio)


class WebmProbeTests(unittest.TestCase):
    def _ebml(self, element_id: bytes, payload: bytes) -> bytes:
        assert len(payload) < 127
        return element_id + bytes([0x80 | len(payload)]) + payload

    def _webm(self, drm: bool = False) -> bytes:
        video = self._ebml(b"\xe0", self._ebml(b"\xb0", struct.pack(">H", 1920)) + self._ebml(b"\xba", struct.pack(">H", 1080)))
        track_payload = self._ebml(b"\x83", b"\x01") + video
        if drm:
            track_payload += self._ebml(b"\x6d\x80", self._ebml(b"\x50\x35", b"\x01"))
        track = self._ebml(b"\xae", track_payload)
        tracks = self._ebml(b"\x16\x54\xae\x6b", track)
        segment = self._ebml(b"\x18\x53\x80\x67", tracks)
        return b"\x1aE\xdf\xa3" + b"\x80" + segment

    def test_video_dimensions(self):
        probe = probe_webm(self._webm())
        self.assertIsNotNone(probe)
        self.assertTrue(probe.has_video)
        self.assertEqual((probe.width, probe.height), (1920, 1080))

    def test_content_encryption_is_drm(self):
        probe = probe_webm(self._webm(drm=True))
        self.assertTrue(probe.drm)

    def test_probe_bytes(self):
        probe = probe_bytes(self._webm())
        self.assertIsNotNone(probe)
        self.assertEqual(probe.height, 1080)


if __name__ == "__main__":
    unittest.main()