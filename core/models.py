"""İndirme görevleri ve yakalanan medya veri modelleri."""

from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .i18n import t
from .utils import AUDIO_EXTENSIONS, MEDIA_EXTENSIONS, hostname, now, url_extension

ACTIVE_STATUSES = {"starting", "analyzing", "downloading", "processing", "pausing", "canceling"}
FINISHED_STATUSES = {"completed", "error", "canceled"}
ALL_STATUSES = ACTIVE_STATUSES | FINISHED_STATUSES | {"queued", "paused"}
TASK_KINDS = {"auto", "page", "direct", "hls", "dash"}
CAPTURE_KINDS = {"direct", "hls", "dash", "page"}
MEDIA_KINDS = {"", "audio", "video", "av", "manifest"}


def _as_text(value: Any, default: str = "") -> str:
    return value.strip() if isinstance(value, str) else default


def _as_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "evet"}:
            return True
        if text in {"0", "false", "no", "off", "hayır", "hayir", ""}:
            return False
    return default


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
        source = data if isinstance(data, dict) else {}
        clean = {key: value for key, value in source.items() if key in allowed}
        task = cls(**clean)

        task.id = _as_text(task.id).strip() or uuid.uuid4().hex[:12]
        task.url = _as_text(task.url).strip()
        task.audio_url = _as_text(task.audio_url).strip()
        task.title = _as_text(task.title)
        task.page_url = _as_text(task.page_url).strip()
        task.kind = _as_text(task.kind, "auto").strip().lower()
        if task.kind not in TASK_KINDS:
            task.kind = "auto"
        task.quality = _as_text(task.quality, "best").strip().lower()
        if task.quality not in QUALITY_LABEL_KEYS:
            task.quality = "best"
        task.status = _as_text(task.status, "paused").strip().lower()
        if task.status not in ALL_STATUSES:
            # Bilinmeyen durumdaki görevi otomatik başlatmak yerine duraklat.
            task.status = "paused"
        task.progress = min(100.0, max(0.0, _as_float(task.progress, 0.0)))
        task.speed = max(0.0, _as_float(task.speed, 0.0))
        task.eta = max(0, _as_int(task.eta, 0))
        task.downloaded = max(0, _as_int(task.downloaded, 0))
        task.total = max(0, _as_int(task.total, 0))
        task.error = _as_text(task.error)
        task.filepath = _as_text(task.filepath)
        task.extractor = _as_text(task.extractor)
        task.duration = max(0, _as_int(task.duration, 0))
        task.thumbnail = _as_text(task.thumbnail)
        task.format_note = _as_text(task.format_note)
        task.referer = _as_text(task.referer).strip()
        task.created_at = max(0.0, _as_float(task.created_at, now()))
        task.updated_at = max(0.0, _as_float(task.updated_at, task.created_at or now()))
        task.auto_resume = _as_bool(task.auto_resume, True)
        task.connections = max(0, min(8, _as_int(task.connections, 0)))
        task.analyzed = _as_bool(task.analyzed, False)
        task.log_tail = _as_text(task.log_tail)[-8000:]
        task.detail = _as_text(task.detail)
        task.retry_count = max(0, _as_int(task.retry_count, 0))
        task.available_at = max(0.0, _as_float(task.available_at, 0.0))
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
        source = data if isinstance(data, dict) else {}
        clean = {key: value for key, value in source.items() if key in allowed}
        capture = cls(**clean)

        capture.id = _as_text(capture.id).strip() or uuid.uuid4().hex[:12]
        capture.url = _as_text(capture.url).strip()
        capture.page_url = _as_text(capture.page_url).strip()
        capture.page_title = _as_text(capture.page_title)
        capture.title = _as_text(capture.title)
        capture.content_type = _as_text(capture.content_type).strip()
        capture.size = max(0, _as_int(capture.size, 0))
        capture.kind = _as_text(capture.kind, "direct").strip().lower()
        if capture.kind not in CAPTURE_KINDS:
            capture.kind = "direct"
        capture.media_kind = _as_text(capture.media_kind).strip().lower()
        if capture.media_kind not in MEDIA_KINDS:
            capture.media_kind = ""
        if not capture.media_kind:
            capture.media_kind = capture._guess_media_kind()
        capture.media_info = _as_text(capture.media_info).strip()
        capture.referer = _as_text(capture.referer).strip()
        capture.tab_id = _as_int(capture.tab_id, -1)
        if capture.tab_id < -1:
            capture.tab_id = -1
        capture.drm = _as_bool(capture.drm, False)
        capture.created_at = max(0.0, _as_float(capture.created_at, now()))
        capture.probed_at = max(0.0, _as_float(capture.probed_at, 0.0))
        if not capture.title:
            capture.title = capture.page_title
        if not capture.referer:
            capture.referer = capture.page_url
        return capture


def make_capture(payload: dict[str, Any]) -> Capture:
    payload = payload if isinstance(payload, dict) else {}
    raw_tab_id = payload.get("tab_id")
    if raw_tab_id is None:
        raw_tab_id = payload.get("tabId")
    capture = Capture(
        url=_as_text(payload.get("url") or "").strip(),
        page_url=_as_text(payload.get("page_url") or payload.get("pageUrl") or "").strip(),
        page_title=_as_text(payload.get("page_title") or payload.get("pageTitle") or "").strip(),
        title=_as_text(payload.get("title") or "").strip(),
        content_type=_as_text(
            payload.get("content_type") or payload.get("contentType") or ""
        ).strip(),
        size=max(0, _as_int(payload.get("size"), 0)),
        kind=_as_text(payload.get("kind") or "direct", "direct").strip().lower(),
        media_kind="",
        referer=_as_text(payload.get("referer") or "").strip(),
        tab_id=_as_int(raw_tab_id, -1),
        drm=_as_bool(payload.get("drm"), False),
    )
    if capture.kind not in CAPTURE_KINDS:
        capture.kind = "direct"
    if capture.tab_id < -1:
        capture.tab_id = -1
    capture.media_kind = capture._guess_media_kind()
    if not capture.title:
        capture.title = capture.page_title
    if not capture.referer:
        capture.referer = capture.page_url
    return capture
