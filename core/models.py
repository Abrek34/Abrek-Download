"""İndirme görevleri ve yakalanan medya veri modelleri."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .i18n import t
from .utils import AUDIO_EXTENSIONS, MEDIA_EXTENSIONS, hostname, now, url_extension

ACTIVE_STATUSES = {"starting", "analyzing", "downloading", "processing", "pausing", "canceling"}
FINISHED_STATUSES = {"completed", "error", "canceled"}

STATUS_LABELS = {
    "queued": "Sırada",
    "starting": "Başlatılıyor",
    "analyzing": "Analiz ediliyor",
    "downloading": "İndiriliyor",
    "processing": "İşleniyor",
    "pausing": "Duraklatılıyor",
    "canceling": "İptal ediliyor",
    "paused": "Duraklatıldı",
    "completed": "Tamamlandı",
    "error": "Hata",
    "canceled": "İptal edildi",
}

QUALITY_LABEL_KEYS = {
    "best": "quality.best",
    "2160": "quality.2160",
    "1440": "quality.1440",
    "1080": "quality.1080",
    "720": "quality.720",
    "480": "quality.480",
    "audio": "quality.audio",
}

def _translated(key: str, fallback: str) -> str:
    value = t(key)
    return value if value != key else fallback


QUALITY_LABELS = {
    "best": _translated("quality.best", "En iyi kalite"),
    "2160": _translated("quality.2160", "2160p (4K)"),
    "1440": _translated("quality.1440", "1440p (2K)"),
    "1080": _translated("quality.1080", "1080p"),
    "720": _translated("quality.720", "720p"),
    "480": _translated("quality.480", "480p"),
    "audio": _translated("quality.audio", "Sadece ses (MP3)"),
}


def status_label(status: str) -> str:
    key = f"task.status.{status}"
    translated = t(key)
    if translated != key:
        return translated
    return STATUS_LABELS.get(status, status)


def quality_label(quality: str) -> str:
    key = QUALITY_LABEL_KEYS.get(quality)
    if not key:
        return quality
    translated = t(key)
    return translated if translated != key else QUALITY_LABELS.get(quality, quality)


@dataclass
class DownloadTask:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    url: str = ""
    audio_url: str = ""
    title: str = ""
    page_url: str = ""
    kind: str = "auto"  # auto | page | direct | hls | dash
    quality: str = "best"
    status: str = "queued"
    progress: float = 0.0
    speed: float = 0.0
    eta: int = 0
    downloaded: int = 0
    total: int = 0
    error: str = ""
    filepath: str = ""
    extractor: str = ""
    duration: int = 0
    thumbnail: str = ""
    format_note: str = ""
    referer: str = ""
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    auto_resume: bool = True
    connections: int = 0
    analyzed: bool = False
    log_tail: str = ""
    detail: str = ""
    retry_count: int = 0
    available_at: float = 0.0

    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.url:
            path = self.url.split("?", 1)[0].rstrip("/").split("/")[-1]
            return path or hostname(self.url) or "Video"
        return "Video"

    def host(self) -> str:
        return hostname(self.page_url or self.url)

    def status_label(self) -> str:
        if self.status == "error" and self.error:
            return status_label("error")
        return status_label(self.status)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DownloadTask":
        allowed = set(cls.__dataclass_fields__.keys())
        clean = {key: value for key, value in (data or {}).items() if key in allowed}
        task = cls(**clean)
        if not task.id:
            task.id = uuid.uuid4().hex[:12]
        return task

    def snapshot(self) -> dict[str, Any]:
        data = self.to_dict()
        data["display_title"] = self.display_title()
        data["host"] = self.host()
        data["status_label"] = self.status_label()
        data["quality_label"] = quality_label(self.quality)
        return data


@dataclass
class Capture:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    url: str = ""
    page_url: str = ""
    page_title: str = ""
    title: str = ""
    content_type: str = ""
    size: int = 0
    kind: str = "direct"  # direct | hls | dash | page
    media_kind: str = ""  # audio | video | av | manifest | ""
    media_info: str = ""  # çözünürlük/bitrate gibi ek bilgi
    referer: str = ""
    tab_id: int = -1
    drm: bool = False
    created_at: float = field(default_factory=now)
    probed_at: float = 0.0

    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.page_title:
            return self.page_title
        if self.url:
            name = self.url.split("?", 1)[0].rstrip("/").split("/")[-1]
            return name or "Video"
        return "Video"

    def host(self) -> str:
        return hostname(self.page_url or self.url)

    def kind_label(self) -> str:
        key = f"capture.kind.{self.kind}"
        fallback = {
            "hls": "HLS",
            "dash": "DASH",
            "page": "SAYFA",
            "direct": "MEDYA",
        }.get(self.kind, "MEDYA")
        return _translated(key, fallback).upper()

    def media_label(self) -> str:
        kind = self.media_kind or self._guess_media_kind()
        info = (self.media_info or "").strip()
        if kind == "manifest":
            label = _translated("capture.media.stream", "AKIŞ")
            return f"{label} {info}".strip()
        if kind == "audio":
            return _translated("capture.media.audio_only", "SES (sadece)").upper()
        if kind == "video":
            label = _translated("capture.media.video", "GÖRÜNTÜ")
            return f"{label} {info}".strip()
        if kind == "av":
            label = _translated("capture.media.av", "SES + GÖRÜNTÜ")
            return f"{label} {info}".strip()
        return _translated("capture.media.media", "MEDYA").upper()

    def _guess_media_kind(self) -> str:
        if self.kind in {"hls", "dash"}:
            return "manifest"
        ct = (self.content_type or "").lower()
        ext = url_extension(self.url)
        if ct.startswith("audio/") or ext in AUDIO_EXTENSIONS:
            return "audio"
        if ct.startswith("video/") or ext in MEDIA_EXTENSIONS:
            return "video"
        return ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["display_title"] = self.display_title()
        data["host"] = self.host()
        data["kind_label"] = self.kind_label()
        data["media_label"] = self.media_label()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Capture":
        allowed = set(cls.__dataclass_fields__.keys())
        clean = {key: value for key, value in (data or {}).items() if key in allowed}
        capture = cls(**clean)
        if not capture.id:
            capture.id = uuid.uuid4().hex[:12]
        return capture


def make_capture(payload: dict[str, Any]) -> Capture:
    capture = Capture(
        url=str(payload.get("url") or "").strip(),
        page_url=str(payload.get("page_url") or payload.get("pageUrl") or "").strip(),
        page_title=str(payload.get("page_title") or payload.get("pageTitle") or "").strip(),
        title=str(payload.get("title") or "").strip(),
        content_type=str(payload.get("content_type") or payload.get("contentType") or "").strip(),
        size=int(payload.get("size") or 0),
        kind=str(payload.get("kind") or "direct").strip().lower(),
        media_kind="",
        referer=str(payload.get("referer") or "").strip(),
        tab_id=int(payload.get("tab_id") or payload.get("tabId") or -1),
        drm=bool(payload.get("drm") or False),
    )
    if capture.kind not in {"direct", "hls", "dash", "page"}:
        capture.kind = "direct"
    capture.media_kind = capture._guess_media_kind()
    if not capture.title:
        capture.title = capture.page_title
    if not capture.referer:
        capture.referer = capture.page_url
    return capture
