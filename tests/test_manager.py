"""İndirme yöneticisi yardımcıları testleri."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ["ABREK_LANG"] = "tr"

from core.errors import PermanentDownloadError
from core.manager import (
    DownloadManager,
    auto_retry_delay,
    capture_needs_probe,
    prune_orphan_parts,
)
from core.models import Capture, DownloadTask


class PruneOrphanPartsTests(unittest.TestCase):
    def test_removes_only_unknown_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            known = root / "known-task"
            known.mkdir()
            (known / "part_0").write_text("veri", encoding="utf-8")
            orphan = root / "orphan-task"
            orphan.mkdir()
            (orphan / "part_0").write_text("veri", encoding="utf-8")
            plain_file = root / "not-a-directory.txt"
            plain_file.write_text("veri", encoding="utf-8")

            removed = prune_orphan_parts(root, {"known-task"})

            self.assertEqual(removed, ["orphan-task"])
            self.assertTrue(known.is_dir())
            self.assertFalse(orphan.exists())
            self.assertTrue(plain_file.exists())

    def test_min_age_protects_recent_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recent = root / "recent"
            recent.mkdir()
            old = root / "old"
            old.mkdir()
            old_time = time.time() - 7200
            os.utime(old, (old_time, old_time))

            removed = prune_orphan_parts(root, set(), min_age_seconds=3600)

            self.assertEqual(removed, ["old"])
            self.assertTrue(recent.is_dir())
            self.assertFalse(old.exists())

    def test_missing_directory_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                prune_orphan_parts(Path(directory) / "missing", set()),
                [],
            )


class FinishActionTests(unittest.TestCase):
    @staticmethod
    def make_manager(tasks: dict[str, DownloadTask], action: str = "suspend"):
        return SimpleNamespace(
            tasks=tasks,
            config={"shutdown_on_finish": action},
            _finish_action_done=False,
        )

    def test_paused_task_blocks_finish_action(self):
        manager = self.make_manager(
            {"a": DownloadTask(url="https://x.test/a.mp4", status="paused")}
        )
        with mock.patch("core.manager.subprocess.Popen") as popen:
            DownloadManager._check_finish_action_locked(manager)
        popen.assert_not_called()
        self.assertFalse(manager._finish_action_done)

    def test_queued_task_blocks_finish_action(self):
        manager = self.make_manager(
            {"a": DownloadTask(url="https://x.test/a.mp4", status="queued")}
        )
        with mock.patch("core.manager.subprocess.Popen") as popen:
            DownloadManager._check_finish_action_locked(manager)
        popen.assert_not_called()

    def test_completed_tasks_trigger_action_once(self):
        manager = self.make_manager(
            {"a": DownloadTask(url="https://x.test/a.mp4", status="completed")}
        )
        with mock.patch("core.manager.subprocess.Popen") as popen:
            DownloadManager._check_finish_action_locked(manager)
            DownloadManager._check_finish_action_locked(manager)
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["systemctl", "suspend"])
        self.assertTrue(manager._finish_action_done)

    def test_new_task_resets_action_guard(self):
        manager = SimpleNamespace(
            tasks={},
            config={"default_quality": "best"},
            _finish_action_done=True,
        )
        task = DownloadManager._add_task_locked(manager, "https://x.test/a.mp4")
        self.assertFalse(manager._finish_action_done)
        self.assertIn(task.id, manager.tasks)


if __name__ == "__main__":
    unittest.main()


class ProbeAvTests(unittest.TestCase):
    def setUp(self):
        self.manager = DownloadManager.__new__(DownloadManager)

    def test_detects_audio_only_hls(self):
        import json

        payload = json.dumps(
            {
                "formats": [
                    {
                        "acodec": "aac",
                        "vcodec": "none",
                        "audio_ext": "m4a",
                        "video_ext": "none",
                    }
                ]
            }
        )
        completed = SimpleNamespace(returncode=0, stdout=payload, stderr="")
        with mock.patch("core.manager.subprocess.run", return_value=completed) as run:
            self.assertEqual(
                self.manager._probe_av("https://cdn.test/audio.m3u8"),
                (True, False),
            )
        command = run.call_args.args[0]
        self.assertIn("-m", command)
        self.assertIn("yt_dlp", command)

    def test_reports_video_only_format(self):
        import json

        payload = json.dumps(
            {
                "formats": [
                    {
                        "acodec": "none",
                        "vcodec": "h264",
                        "audio_ext": "none",
                        "video_ext": "mp4",
                    }
                ]
            }
        )
        completed = SimpleNamespace(returncode=0, stdout=payload, stderr="")
        with mock.patch("core.manager.subprocess.run", return_value=completed):
            self.assertEqual(
                self.manager._probe_av("https://cdn.test/video.m3u8"),
                (False, True),
            )

    def test_invalid_output_is_safe(self):
        completed = SimpleNamespace(returncode=1, stdout="", stderr="boom")
        with mock.patch("core.manager.subprocess.run", return_value=completed):
            self.assertEqual(
                self.manager._probe_av("https://cdn.test/broken.m3u8"),
                (False, False),
            )


class FindMatchingAudioTests(unittest.TestCase):
    def make_manager(self, captures):
        return SimpleNamespace(
            lock=__import__("threading").RLock(),
            captures=captures,
            _probe_av=mock.Mock(return_value=(False, True)),
        )

    @staticmethod
    def capture(url, media_kind="manifest", drm=False):
        return SimpleNamespace(
            url=url,
            page_url="https://site.test/watch/1",
            kind="hls",
            media_kind=media_kind,
            drm=drm,
        )

    @staticmethod
    def task():
        return SimpleNamespace(
            url="https://cdn.test/video.m3u8",
            page_url="https://site.test/watch/1",
        )

    def test_prefers_capture_labeled_audio(self):
        audio = self.capture("https://cdn.test/audio.m3u8", "audio")
        manager = self.make_manager([self.capture("https://cdn.test/other.m3u8"), audio])
        self.assertEqual(
            DownloadManager._find_matching_audio(manager, self.task()),
            audio.url,
        )
        manager._probe_av.assert_not_called()

    def test_does_not_return_video_only_candidate(self):
        manager = self.make_manager([self.capture("https://cdn.test/video2.m3u8")])
        manager._probe_av.return_value = (True, True)
        self.assertEqual(DownloadManager._find_matching_audio(manager, self.task()), "")

    def test_probes_are_bounded(self):
        manager = self.make_manager(
            [self.capture(f"https://cdn.test/{index}.m3u8") for index in range(6)]
        )
        manager._probe_av.return_value = (False, True)
        self.assertEqual(DownloadManager._find_matching_audio(manager, self.task()), "")
        self.assertEqual(manager._probe_av.call_count, 3)

    def test_drm_candidates_are_ignored(self):
        manager = self.make_manager(
            [self.capture("https://cdn.test/audio.m3u8", "audio", drm=True)]
        )
        self.assertEqual(DownloadManager._find_matching_audio(manager, self.task()), "")
        manager._probe_av.assert_not_called()


class MergeAvTests(unittest.TestCase):
    def setUp(self):
        self.manager = DownloadManager.__new__(DownloadManager)
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.video = Path(self.tempdir.name) / "video.mp4"
        self.audio = Path(self.tempdir.name) / "audio.m4a"
        self.video.write_bytes(b"video")
        self.audio.write_bytes(b"audio")

    def test_failed_merge_keeps_source_files(self):
        failed = SimpleNamespace(returncode=1, stdout="", stderr="ffmpeg failed")
        with mock.patch("core.manager.subprocess.run", return_value=failed):
            with self.assertRaises(RuntimeError):
                self.manager._merge_av(str(self.video), str(self.audio))
        self.assertTrue(self.video.exists())
        self.assertTrue(self.audio.exists())
        self.assertEqual(list(Path(self.tempdir.name).glob("*_merged*")), [])

    def test_falls_back_to_mkv_and_clears_metadata(self):
        commands = []

        def fake_run(command, **_kwargs):
            commands.append(command)
            target = Path(command[-1])
            if target.suffix == ".mp4":
                return SimpleNamespace(returncode=1, stdout="", stderr="mp4 fail")
            target.write_bytes(b"merged")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch("core.manager.subprocess.run", side_effect=fake_run):
            result = self.manager._merge_av(str(self.video), str(self.audio))

        self.assertTrue(result.endswith("_merged.mkv"))
        self.assertTrue(Path(result).exists())
        self.assertFalse(self.video.exists())
        self.assertFalse(self.audio.exists())
        self.assertIn("-map_metadata", commands[0])
        index = commands[0].index("-map_metadata")
        self.assertEqual(commands[0][index + 1], "-1")


class AudioOnlyDownloadTests(unittest.TestCase):
    def test_audio_only_command_uses_audio_stream(self):
        from core.ytdlp import YtDlpDownloader

        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(
                download_dir=Path(directory),
                get=lambda _key, default=None: default,
            )
            task = SimpleNamespace(
                id="audio-task",
                quality="best",
                url="https://cdn.test/audio.m3u8",
                referer="",
            )
            with mock.patch("core.ytdlp.PARTS_DIR", Path(directory) / "parts"):
                downloader = YtDlpDownloader(
                    task,
                    config,
                    lambda *_args: None,
                    lambda *_args: None,
                    audio_only=True,
                )
                command = downloader._build_download_command()

        self.assertIn("ba[ext=m4a]/ba/b", command)
        self.assertTrue(
            any(item.endswith("%(title).150B [%(id)s].audio.%(ext)s") for item in command)
        )
        self.assertNotIn("--extract-audio", command)
        self.assertNotIn("--write-subs", command)


class AvMergeDecisionTests(unittest.TestCase):
    def test_audio_quality_skips_separate_audio_merge(self):
        task = DownloadTask(
            url="https://cdn.test/video.m3u8",
            kind="hls",
            quality="audio",
        )
        self.assertFalse(DownloadManager._needs_av_merge(task))

    def test_hls_video_quality_needs_audio_merge(self):
        task = DownloadTask(
            url="https://cdn.test/video.m3u8",
            kind="hls",
            quality="best",
        )
        self.assertTrue(DownloadManager._needs_av_merge(task))

    def test_direct_and_already_matched_tasks_do_not_merge(self):
        direct = DownloadTask(
            url="https://cdn.test/video.mp4",
            kind="direct",
            quality="best",
        )
        matched = DownloadTask(
            url="https://cdn.test/video.m3u8",
            kind="hls",
            quality="best",
            audio_url="https://cdn.test/audio.m3u8",
        )
        self.assertFalse(DownloadManager._needs_av_merge(direct))
        self.assertFalse(DownloadManager._needs_av_merge(matched))


class SnapshotTests(unittest.TestCase):
    def test_snapshot_includes_capture_pause_state(self):
        manager = SimpleNamespace(
            lock=__import__("threading").RLock(),
            tasks={},
            captures=[],
            config={"capture_paused": True},
        )
        snapshot = DownloadManager.snapshot(manager)
        self.assertTrue(snapshot["capture_paused"])


class FetchFirstSegmentTests(unittest.TestCase):
    def test_rejects_oversized_probe_data(self):
        manager = DownloadManager.__new__(DownloadManager)

        class Response:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def iter_content(self, chunk_size=0):
                del chunk_size
                for _ in range(8):
                    yield b"x" * (1024 * 1024)

        class Session:
            def get(self, *_args, **_kwargs):
                return Response()

            def close(self):
                pass

        with mock.patch("core.manager.requests.Session", return_value=Session()):
            self.assertIsNone(
                manager._fetch_first_segment("https://cdn.test/segment.ts")
            )


class CaptureProbeTests(unittest.TestCase):
    def test_new_capture_needs_probe(self):
        self.assertTrue(capture_needs_probe(Capture(media_kind="")))

    def test_audio_and_av_captures_are_not_probed(self):
        for kind in ("audio", "av"):
            with self.subTest(kind=kind):
                self.assertFalse(capture_needs_probe(Capture(media_kind=kind)))

    def test_recent_probe_is_skipped(self):
        capture = Capture(media_kind="manifest", media_info="1080p", probed_at=1000.0)
        self.assertFalse(capture_needs_probe(capture, now_value=1000.0 + 3600))

    def test_stale_probe_is_refreshed(self):
        capture = Capture(media_kind="manifest", media_info="1080p", probed_at=1000.0)
        self.assertTrue(capture_needs_probe(capture, now_value=1000.0 + 90000))


class AutoRetryTests(unittest.TestCase):
    @staticmethod
    def make_manager(**config):
        values = {"auto_retry": True, "auto_retry_limit": 2, **config}
        return SimpleNamespace(config=values, _finish_action_done=True)

    def test_delay_uses_exponential_backoff(self):
        self.assertEqual(auto_retry_delay(1), 15)
        self.assertEqual(auto_retry_delay(2), 30)
        self.assertEqual(auto_retry_delay(3), 60)
        self.assertEqual(auto_retry_delay(6), 120)

    def test_transient_error_is_requeued(self):
        manager = self.make_manager()
        task = DownloadTask(url="https://x.test/a.mp4", status="downloading")
        retried = DownloadManager._maybe_auto_retry_locked(
            manager, task, Exception("HTTP 503 Service Unavailable")
        )
        self.assertTrue(retried)
        self.assertEqual(task.status, "queued")
        self.assertEqual(task.retry_count, 1)
        self.assertGreater(task.available_at, time.time())
        self.assertFalse(manager._finish_action_done)

    def test_permanent_error_is_not_retried(self):
        manager = self.make_manager()
        task = DownloadTask(url="https://x.test/a.mp4", status="downloading")
        self.assertFalse(
            DownloadManager._maybe_auto_retry_locked(
                manager, task, Exception("HTTP 404 Not Found")
            )
        )
        self.assertEqual(task.status, "downloading")
        self.assertEqual(task.retry_count, 0)

    def test_limit_and_disable_are_respected(self):
        task = DownloadTask(
            url="https://x.test/a.mp4",
            status="downloading",
            retry_count=2,
        )
        self.assertFalse(
            DownloadManager._maybe_auto_retry_locked(
                self.make_manager(), task, Exception("timed out")
            )
        )
        task.retry_count = 0
        self.assertFalse(
            DownloadManager._maybe_auto_retry_locked(
                self.make_manager(auto_retry=False), task, Exception("timed out")
            )
        )


class BatchAddTests(unittest.TestCase):
    def make_manager(self):
        manager = DownloadManager.__new__(DownloadManager)
        manager.lock = __import__("threading").RLock()
        manager.tasks = {}
        manager.config = {"default_quality": "best"}
        manager._finish_action_done = True
        manager._save_locked = mock.Mock()
        manager._wake = mock.Mock()
        return manager

    def test_add_urls_counts_added_duplicate_and_invalid(self):
        manager = self.make_manager()
        added, duplicate, invalid = DownloadManager.add_urls(
            manager,
            [
                "https://x.test/a.mp4",
                "https://x.test/a.mp4",
                "ftp://x.test/b.mp4",
                "x.test/c.mp4",
            ],
        )
        self.assertEqual((added, duplicate, invalid), (2, 1, 1))
        self.assertEqual(len(manager.tasks), 2)
        manager._save_locked.assert_called_once()
        manager._wake.set.assert_called_once()


class ClearQueueTests(unittest.TestCase):
    def test_active_workers_keep_concurrency_and_cancel_state(self):
        active = DownloadTask(url="https://x.test/a.mp4", status="downloading")
        queued = DownloadTask(url="https://x.test/b.mp4", status="queued")
        controller = mock.Mock()
        manager = SimpleNamespace(
            lock=__import__("threading").RLock(),
            tasks={active.id: active, queued.id: queued},
            active_ids={active.id},
            controllers={active.id: controller},
            pause_requested={active.id},
            cancel_requested=set(),
            _finish_action_done=True,
            _cleanup_parts=mock.Mock(),
            _save_locked=mock.Mock(),
            _wake=mock.Mock(),
        )
        removed = DownloadManager.clear_queue(manager)
        self.assertEqual(removed, 2)
        self.assertEqual(manager.tasks, {})
        self.assertEqual(manager.active_ids, {active.id})
        self.assertIn(active.id, manager.controllers)
        self.assertIn(active.id, manager.cancel_requested)
        controller.cancel.assert_called_once()
        manager._cleanup_parts.assert_called_once_with(queued.id)


class FileStreamProbeTests(unittest.TestCase):
    def setUp(self):
        self.manager = DownloadManager.__new__(DownloadManager)

    @staticmethod
    def payload(*streams):
        return json.dumps({"streams": list(streams)})

    def probe(self, payload):
        completed = SimpleNamespace(returncode=0, stdout=payload, stderr="")
        with (
            mock.patch("core.manager.shutil.which", return_value="/usr/bin/ffprobe"),
            mock.patch("core.manager.subprocess.run", return_value=completed),
        ):
            return self.manager._probe_file_streams("video.mp4")

    def test_detects_video_and_audio(self):
        self.assertEqual(
            self.probe(
                self.payload(
                    {"codec_type": "video", "disposition": {"attached_pic": 0}},
                    {"codec_type": "audio"},
                )
            ),
            (True, True),
        )

    def test_attached_picture_is_not_video(self):
        self.assertEqual(
            self.probe(
                self.payload(
                    {"codec_type": "video", "disposition": {"attached_pic": 1}},
                    {"codec_type": "audio"},
                )
            ),
            (False, True),
        )

    def test_missing_ffprobe_returns_none(self):
        with mock.patch("core.manager.shutil.which", return_value=None):
            self.assertIsNone(self.manager._probe_file_streams("video.mp4"))

    def test_failed_probe_returns_none(self):
        completed = SimpleNamespace(returncode=1, stdout="", stderr="boom")
        with (
            mock.patch("core.manager.shutil.which", return_value="/usr/bin/ffprobe"),
            mock.patch("core.manager.subprocess.run", return_value=completed),
        ):
            self.assertIsNone(self.manager._probe_file_streams("video.mp4"))


class FinalMediaValidationTests(unittest.TestCase):
    def setUp(self):
        self.manager = DownloadManager.__new__(DownloadManager)
        self.manager._log_callback = lambda _task_id: (lambda _message: None)
        self.path = "/tmp/abrek-test-video.mp4"

    @staticmethod
    def task(kind="page", quality="best", url="https://x.test/video"):
        return SimpleNamespace(id="task-1", kind=kind, quality=quality, url=url)

    def validate(self, streams, task):
        with mock.patch.object(
            DownloadManager,
            "_probe_file_streams",
            return_value=streams,
        ):
            self.manager._validate_final_media(task, self.path)

    def test_page_video_with_audio_passes(self):
        self.validate((True, True), self.task())

    def test_page_video_without_audio_fails(self):
        with self.assertRaises(PermanentDownloadError) as context:
            self.validate((True, False), self.task())
        self.assertIn("ses", str(context.exception))

    def test_page_audio_without_video_fails(self):
        with self.assertRaises(PermanentDownloadError) as context:
            self.validate((False, True), self.task())
        self.assertIn("görüntü", str(context.exception))

    def test_audio_quality_accepts_audio_only(self):
        self.validate((False, True), self.task(quality="audio"))

    def test_audio_quality_rejects_missing_audio(self):
        with self.assertRaises(PermanentDownloadError):
            self.validate((True, False), self.task(quality="audio"))

    def test_direct_video_without_audio_fails(self):
        with self.assertRaises(PermanentDownloadError):
            self.validate((True, False), self.task(kind="direct"))

    def test_direct_audio_only_is_allowed(self):
        self.validate(
            (False, True),
            self.task(kind="direct", url="https://x.test/song.mp3"),
        )

    def test_direct_file_without_media_fails(self):
        with self.assertRaises(PermanentDownloadError):
            self.validate((False, False), self.task(kind="direct"))

    def test_missing_ffprobe_does_not_block(self):
        self.validate(None, self.task())


class FindCombinedStreamProbeTests(unittest.TestCase):
    @staticmethod
    def task():
        return SimpleNamespace(
            url="https://cdn.test/video.m3u8",
            page_url="https://site.test/watch/1",
        )

    @staticmethod
    def capture(media_info=""):
        return SimpleNamespace(
            url="https://cdn.test/combined.m3u8",
            page_url="https://site.test/watch/1",
            kind="hls",
            drm=False,
            media_info=media_info,
        )

    def make_manager(self, capture):
        return SimpleNamespace(
            lock=__import__("threading").RLock(),
            captures=[capture],
            _probe_av=mock.Mock(return_value=(True, True)),
        )

    def test_probe_finds_combined_candidate_without_label(self):
        capture = self.capture()
        manager = self.make_manager(capture)
        self.assertEqual(
            DownloadManager._find_combined_stream(manager, self.task(), probe=True),
            capture.url,
        )
        manager._probe_av.assert_called_once()

    def test_without_probe_does_not_start_ytdlp(self):
        manager = self.make_manager(self.capture())
        self.assertEqual(
            DownloadManager._find_combined_stream(manager, self.task()),
            "",
        )
        manager._probe_av.assert_not_called()

    def test_silent_candidate_is_skipped(self):
        manager = self.make_manager(self.capture("1080p · sessiz"))
        self.assertEqual(
            DownloadManager._find_combined_stream(manager, self.task(), probe=True),
            "",
        )
        manager._probe_av.assert_not_called()
