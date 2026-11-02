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
