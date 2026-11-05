"""Uygulama yolları ve kalıcı ayarlar."""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
from typing import Any

from .utils import atomic_write_json, load_json

APP_NAME = "Abrek Download"
APP_SLUG = "videoavci"
VERSION = "1.12.1"

if getattr(sys, "frozen", False):
    PROJECT_DIR = Path(sys._MEIPASS)
else:
    PROJECT_DIR = Path(__file__).resolve().parent.parent


def _xdg_dir(env_name: str, fallback: str, home: Path | None = None) -> Path:
    """XDG ortam değişkenini (geçerliyse) yoksa ev dizinindeki yedeği döner."""
    home = Path.home() if home is None else Path(home)
    value = os.environ.get(env_name, "").strip()
    if value:
        candidate = Path(value).expanduser()
        # XDG belirtimine göre göreli yollar yok sayılır.
        if candidate.is_absolute():
            return candidate
    return home / fallback


def _xdg_download_dir(
    home: Path | None = None,
    config_home: Path | None = None,
) -> Path:
    """Kullanıcının XDG İndirilenler klasörünü bulur.

    ``~/.config/user-dirs.dirs`` dosyasındaki ``XDG_DOWNLOAD_DIR`` değeri
    kullanılır. Dosya yoksa yaygın Türkçe/İngilizce klasör adlarına, o da
    yoksa ``~/Downloads`` yoluna düşülür.
    """
    home = Path.home() if home is None else Path(home)
    config_home = (
        _xdg_dir("XDG_CONFIG_HOME", ".config", home)
        if config_home is None
        else Path(config_home)
    )
    try:
        lines = (config_home / "user-dirs.dirs").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if key.strip() != "XDG_DOWNLOAD_DIR" or not separator:
            continue
        value = value.strip().strip('"').strip("'")
        value = value.replace("${HOME}", str(home)).replace("$HOME", str(home))
        candidate = Path(os.path.expanduser(value))
        if candidate.is_absolute():
            return candidate
    for name in ("Downloads", "İndirilenler"):
        candidate = home / name
        if candidate.is_dir():
            return candidate
    return home / "Downloads"


CONFIG_DIR = _xdg_dir("XDG_CONFIG_HOME", ".config") / APP_SLUG
DATA_DIR = _xdg_dir("XDG_DATA_HOME", ".local/share") / APP_SLUG
STATE_DIR = _xdg_dir("XDG_STATE_HOME", ".local/state") / APP_SLUG
LOG_DIR = STATE_DIR / "logs"
PARTS_DIR = DATA_DIR / "parts"
DEFAULT_DOWNLOAD_DIR = _xdg_download_dir() / "VideoAvci"
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
    "cookies_file": "",
    "proxy": "",
    "history_limit": 200,
    "auto_resume": True,
    "auto_retry": True,
    "auto_retry_limit": 2,
    "notify_captures": True,
    "notify_downloads": True,
    "capture_paused": False,
    "window_geometry": "",
    "theme": "dark",
    "language": "tr",
    "watch_clipboard": False,
    "download_subtitles": False,
    "subtitle_langs": "tr,en",
    "shutdown_on_finish": "none",  # none | shutdown | suspend
    "api_token": "",  # Yerel köprüye erişim için isteğe bağlı eşleştirme tokeni
}

QUALITIES = {"best", "2160", "1440", "1080", "720", "480", "audio"}
COOKIE_BROWSERS = {"none", "brave", "firefox", "chrome", "chromium"}
LANGUAGES = {"tr", "en"}
THEMES = {"dark", "light"}
FINISH_ACTIONS = {"none", "shutdown", "suspend"}

_TRUE_VALUES = {"1", "true", "yes", "on", "evet", "açık", "acik"}
_FALSE_VALUES = {"0", "false", "no", "off", "hayır", "hayir", "kapalı", "kapali"}


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE_VALUES:
            return True
        if text in _FALSE_VALUES:
            return False
    return default


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        # JSON'daki 1e999 gibi değerler float('inf') olarak çözülür; int()
        # OverflowError verir ve ayarların yüklenmesini engellememelidir.
        number = default
    return max(minimum, min(maximum, number))


def _coerce_text(value: Any, default: str = "") -> str:
    return value.strip() if isinstance(value, str) else default


def ensure_dirs() -> None:
    for directory in (CONFIG_DIR, DATA_DIR, STATE_DIR, LOG_DIR, PARTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


class Config:
    def __init__(self, path: Path = CONFIG_FILE):
        self.path = Path(path)
        self.data: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
        self.load()

    def _normalize(self) -> None:
        """Bozuk/eski JSON değerlerini güvenli tiplere dönüştürür."""
        self.data["max_concurrent"] = _coerce_int(
            self.data.get("max_concurrent"), 2, 1, 5
        )
        self.data["connections"] = _coerce_int(
            self.data.get("connections"), 4, 1, 8
        )
        self.data["speed_limit_kbps"] = _coerce_int(
            self.data.get("speed_limit_kbps"), 0, 0, 1_000_000
        )
        self.data["auto_retry_limit"] = _coerce_int(
            self.data.get("auto_retry_limit"), 2, 0, 5
        )

        for key in (
            "auto_resume",
            "auto_retry",
            "notify_captures",
            "notify_downloads",
            "capture_paused",
            "watch_clipboard",
            "download_subtitles",
        ):
            self.data[key] = _coerce_bool(self.data.get(key), bool(DEFAULT_CONFIG[key]))

        quality = _coerce_text(self.data.get("default_quality"), "best").lower()
        self.data["default_quality"] = quality if quality in QUALITIES else "best"

        browser = _coerce_text(self.data.get("cookies_browser"), "none").lower()
        self.data["cookies_browser"] = browser if browser in COOKIE_BROWSERS else "none"

        language = _coerce_text(self.data.get("language"), "tr").lower()
        self.data["language"] = language if language in LANGUAGES else "tr"

        theme = _coerce_text(self.data.get("theme"), "dark").lower()
        self.data["theme"] = theme if theme in THEMES else "dark"

        action = _coerce_text(self.data.get("shutdown_on_finish"), "none").lower()
        self.data["shutdown_on_finish"] = action if action in FINISH_ACTIONS else "none"

        langs = _coerce_text(self.data.get("subtitle_langs"), "tr,en")
        self.data["subtitle_langs"] = langs[:200] if langs else "tr,en"

        geometry = _coerce_text(self.data.get("window_geometry"))
        self.data["window_geometry"] = geometry[:100]

        directory = _coerce_text(self.data.get("download_dir"), str(DEFAULT_DOWNLOAD_DIR))
        self.data["download_dir"] = os.path.expanduser(directory or str(DEFAULT_DOWNLOAD_DIR))

        self.data["proxy"] = _coerce_text(self.data.get("proxy"))
        self.data["cookies_file"] = _coerce_text(self.data.get("cookies_file"))
        self.data["history_limit"] = _coerce_int(
            self.data.get("history_limit"), 200, 0, 2000
        )
        self.data["api_token"] = _coerce_text(self.data.get("api_token"))

    def load(self) -> None:
        stored = load_json(self.path, {})
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULT_CONFIG:
                    self.data[key] = value
        self._normalize()

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
        self._normalize()
        self.save()

    @property
    def download_dir(self) -> Path:
        path = Path(self.data.get("download_dir") or DEFAULT_DOWNLOAD_DIR).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
