"""Kurulum yardımcıları ve install.sh akışı testleri."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.config import PROJECT_DIR, VERSION
from core.installer import (
    data_home,
    desktop_dir,
    desktop_shortcut_path,
    detect_all,
    entry_points_to_project,
    install_script_args,
    launch_command,
    manual_install_command,
    menu_entry_path,
)


class InstallerPathTests(unittest.TestCase):
    def test_entry_points_to_project_true(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "videoavci.desktop"
            path.write_text(
                f'Exec="{PROJECT_DIR / "baslat.sh"}"\nIcon={PROJECT_DIR / "assets" / "icon.png"}\n',
                encoding="utf-8",
            )
            self.assertTrue(entry_points_to_project(path))

    def test_entry_points_to_project_false(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "videoavci.desktop"
            path.write_text('Exec="/usr/bin/other-app"\n', encoding="utf-8")
            self.assertFalse(entry_points_to_project(path))

    def test_entry_points_to_project_missing_file(self):
        self.assertFalse(entry_points_to_project(Path("/tmp/abrek-missing.desktop")))

    def test_data_home_respects_env(self):
        os.environ["XDG_DATA_HOME"] = "/tmp/opencode/abrek-data"
        try:
            self.assertEqual(data_home(), Path("/tmp/opencode/abrek-data"))
        finally:
            del os.environ["XDG_DATA_HOME"]

    def test_desktop_dir_respects_env(self):
        os.environ["XDG_DESKTOP_DIR"] = "/tmp/opencode/abrek-desktop"
        try:
            self.assertEqual(desktop_dir(), Path("/tmp/opencode/abrek-desktop"))
        finally:
            del os.environ["XDG_DESKTOP_DIR"]

    def test_path_helpers(self):
        os.environ["XDG_DATA_HOME"] = "/tmp/opencode/abrek-data"
        os.environ["XDG_DESKTOP_DIR"] = "/tmp/opencode/abrek-desktop"
        try:
            self.assertEqual(menu_entry_path(), Path("/tmp/opencode/abrek-data/applications/videoavci.desktop"))
            self.assertEqual(desktop_shortcut_path(), Path("/tmp/opencode/abrek-desktop/Abrek Download.desktop"))
        finally:
            del os.environ["XDG_DATA_HOME"]
            del os.environ["XDG_DESKTOP_DIR"]


class InstallerCommandTests(unittest.TestCase):
    def test_install_script_args(self):
        self.assertEqual(
            install_script_args(True, False, False),
            ["bash", str(PROJECT_DIR / "install.sh"), "--menu"],
        )
        self.assertEqual(
            install_script_args(False, True, True),
            ["bash", str(PROJECT_DIR / "install.sh"), "--desktop", "--prepare"],
        )
        self.assertEqual(
            install_script_args(True, True, True),
            ["bash", str(PROJECT_DIR / "install.sh"), "--menu", "--desktop", "--prepare"],
        )
        self.assertEqual(
            install_script_args(False, False, False, uninstall=True),
            ["bash", str(PROJECT_DIR / "install.sh"), "--uninstall"],
        )

    def test_launch_command(self):
        command = launch_command()
        self.assertEqual(command[0], "bash")
        self.assertTrue(command[1].endswith("baslat.sh"))

    def test_manual_install_command(self):
        self.assertIn("yt-dlp", manual_install_command(["yt-dlp"]))
        self.assertEqual(manual_install_command([]), "")


class InstallerDetectionTests(unittest.TestCase):
    def test_detect_all_shape(self):
        data = detect_all()
        self.assertEqual(data["version"], VERSION)
        self.assertIn("checks", data)
        expected = {
            "python",
            "tkinter",
            "venv",
            "packages",
            "ffmpeg",
            "ffprobe",
            "js_runtime",
            "menu_entry",
            "desktop_shortcut",
        }
        self.assertEqual(set(data["checks"]), expected)
        for check in data["checks"].values():
            self.assertIn(check["status"], {"ok", "warn", "missing", "off"})


class InstallScriptTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            data_home = Path(root) / "data"
            desktop = Path(root) / "desktop"
            env = {
                **os.environ,
                "XDG_DATA_HOME": str(data_home),
                "XDG_DESKTOP_DIR": str(desktop),
            }
            subprocess.run(
                ["bash", str(PROJECT_DIR / "install.sh"), "--all"],
                check=True,
                env=env,
                cwd=PROJECT_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            menu = data_home / "applications" / "videoavci.desktop"
            shortcut = desktop / "Abrek Download.desktop"
            self.assertTrue(menu.is_file())
            self.assertTrue(shortcut.is_file())
            self.assertTrue(entry_points_to_project(menu))
            self.assertTrue(entry_points_to_project(shortcut))

            subprocess.run(
                ["bash", str(PROJECT_DIR / "install.sh"), "--uninstall"],
                check=True,
                env=env,
                cwd=PROJECT_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.assertFalse(menu.exists())
            self.assertFalse(shortcut.exists())


if __name__ == "__main__":
    unittest.main()
