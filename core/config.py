"""Uygulama yolları ve kalıcı ayarlar."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

from .utils import atomic_write_json, load_json

APP_NAME = "Abrek Download"
APP_SLUG = "videoavci"
VERSION = "1.0.0"

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path.home() / ".config" / APP_SLUG
DATA_DIR = Path.home() / ".local" / "share" / APP_SLUG
STATE_DIR = Path.home() / ".local" / "state" / APP_SLUG
LOG_DIR = STATE_DIR / "logs"
PARTS_DIR = DATA_DIR / "parts"
DEFAULT_DOWNLOAD_DIR = Path.home() / "İndirilenler" / "VideoAvci"
CONFIG_FILE = CONFIG_DIR / "config.json"
QUEUE_FILE = DATA_DIR / "queue.json"
CAPTURES_FILE = DATA_DIR / "captures.json"
API_HOST = "127.0.0.1"
API_PORT = 8765

DEFAULT_CONFIG: dict[str, Any] = {
    "download_dir": str(DEFAULT_DOWNLOAD_DIR),
    "max_concurrent": 2,
    "connections": 4,
    "default_quality": "best",
    "speed_limit_kbps": 0,
    "cookies_browser": "none",
    "auto_resume": True,
    "auto_send_captures": True,
    "notify_captures": True,
    "notify_downloads": True,
    "window_geometry": "",
}


def ensure_dirs() -> None:
    for directory in (CONFIG_DIR, DATA_DIR, STATE_DIR, LOG_DIR, PARTS_DIR, DEFAULT_DOWNLOAD_DIR):
        directory.mkdir(parents=True, exist_ok=True)


class Config:
    def __init__(self, path: Path = CONFIG_FILE):
        self.path = path
        self.data: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        stored = load_json(self.path, {})
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULT_CONFIG:
                    self.data[key] = value
        # Eski/bozuk değerleri düzelt.
        try:
            self.data["max_concurrent"] = max(1, min(5, int(self.data.get("max_concurrent", 2))))
        except (TypeError, ValueError):
            self.data["max_concurrent"] = 2
        try:
            self.data["connections"] = max(1, min(8, int(self.data.get("connections", 4))))
        except (TypeError, ValueError):
            self.data["connections"] = 4
        try:
            self.data["speed_limit_kbps"] = max(0, int(self.data.get("speed_limit_kbps", 0)))
        except (TypeError, ValueError):
            self.data["speed_limit_kbps"] = 0
        quality = str(self.data.get("default_quality", "best"))
        if quality not in {"best", "2160", "1440", "1080", "720", "480", "audio"}:
            quality = "best"
        self.data["default_quality"] = quality
        if self.data.get("cookies_browser") not in {"none", "brave", "firefox", "chrome", "chromium"}:
            self.data["cookies_browser"] = "none"
        directory = str(self.data.get("download_dir") or DEFAULT_DOWNLOAD_DIR)
        self.data["download_dir"] = os.path.expanduser(directory)

    def save(self) -> None:
        atomic_write_json(self.path, self.data)

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if key in DEFAULT_CONFIG:
                self.data[key] = value
        self.save()

    @property
    def download_dir(self) -> Path:
        path = Path(self.data.get("download_dir") or DEFAULT_DOWNLOAD_DIR).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
