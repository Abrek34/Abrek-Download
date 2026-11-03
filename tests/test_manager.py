"""İndirme yöneticisi yardımcıları testleri."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ["ABREK_LANG"] = "tr"

from core.manager import DownloadManager, prune_orphan_parts
from core.models import DownloadTask


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
    def capture(url, media_kind="manifest"):
        return SimpleNamespace(
            url=url,
            page_url="https://site.test/watch/1",
            kind="hls",
            media_kind=media_kind,
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
