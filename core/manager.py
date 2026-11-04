"""İndirme kuyruğu, görev yaşam döngüsü ve tarayıcı yakalamaları."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

import requests

from .config import (
    API_HOST,
    API_PORT,
    CAPTURES_FILE,
    PARTS_DIR,
    QUEUE_FILE,
    VERSION,
    Config,
)
from .direct import (
    DirectDownloader,
    DownloadCanceled as DirectCanceled,
    DownloadPaused as DirectPaused,
    NotDirectError,
)
from .errors import DownloadError, PermanentDownloadError
from .i18n import t
from .models import (
    ACTIVE_STATUSES,
    Capture,
    DownloadTask,
    FINISHED_STATUSES,
    make_capture,
)
from .probe import MediaProbe, hls_first_segment, probe_bytes
from .utils import (
    USER_AGENT,
    atomic_write_json,
    file_size,
    is_http_url,
    is_manifest_url,
    is_transient_error,
    is_youtube_url,
    load_json,
    normalize_url,
    now,
    unique_path,
)
from .ytdlp import (
    DownloadCanceled as YtCanceled,
    DownloadPaused as YtPaused,
    YtDlpDownloader,
    youtube_extra_args,
    ytdlp_base_command,
    ytdlp_version,
)

log = logging.getLogger("videoavci.manager")

# ffprobe ile ilk parçayı incelerken belleğe en fazla bu kadar veri alınır.
# HLS/DASH parçaları genellikle birkaç yüz KB'tır; bozuk/çok büyük parçalar
# uygulamanın belleğini şişirmesin.
PROBE_MAX_BYTES = 4 * 1024 * 1024

# Yakalama analizleri sınırlı sayıda işçiyle yürütülür. Her yakalama için ayrı
# iş parçacığı açmak, yüzlerce yakalama biriktiğinde uygulamayı yoruyordu.
PROBE_WORKERS = 2
PROBE_MAX_AGE = 24 * 60 * 60

# Geçici ağ hatalarında görev otomatik olarak yeniden kuyruğa alınır.
AUTO_RETRY_BASE_DELAY = 15
AUTO_RETRY_MAX_DELAY = 120
AUTO_RETRY_RETRY_AFTER_CAP = 300

# Yerleşik probe için indirilen azami örnek boyutu ve range ile okunacak kuyruk.
PROBE_TAIL_BYTES = 4 * 1024 * 1024
PROBE_MAX_REDIRECTS = 5


@dataclass
class _ProbeSample:
    """Yakalama analizi için indirilen sınırlı medya örneği."""

    data: bytes = b""
    text: str = ""
    final_url: str = ""
    content_type: str = ""
    manifest: MediaProbe | None = None
    tail: bytes = b""


def capture_needs_probe(capture: Capture, now_value: float | None = None) -> bool:
    """Yakalamanın çözünürlük/ses analizine ihtiyacı olup olmadığını söyler."""
    if capture.media_kind not in {"", "video", "manifest"}:
        return False
    probed_at = float(getattr(capture, "probed_at", 0.0) or 0.0)
    if probed_at <= 0:
        return True
    current = time.time() if now_value is None else float(now_value)
    return (current - probed_at) >= PROBE_MAX_AGE


def auto_retry_delay(attempt: int) -> int:
    """Yeniden deneme sayısına göre üstel geri çekilme süresi (saniye)."""
    attempt = max(1, int(attempt))
    return min(AUTO_RETRY_MAX_DELAY, AUTO_RETRY_BASE_DELAY * (2 ** (attempt - 1)))


def prune_orphan_parts(
    parts_dir: Path,
    known_ids: set[str],
    min_age_seconds: float = 0.0,
) -> list[str]:
    """Kuyrukta karşılığı olmayan geçici indirme klasörlerini siler.

    Uygulama çökerse veya görev kuyruktan kaldırılırsa ``parts`` altında
    sahipsiz parçalar kalabilir. Yalnızca bilinen görev kimliklerine ait
    olmayan klasörlere dokunulur; çok yeni klasörler yarış koşullarına karşı
    ``min_age_seconds`` ile korunabilir.
    """
    removed: list[str] = []
    try:
        entries = list(Path(parts_dir).iterdir())
    except FileNotFoundError:
        return removed
    except OSError:
        return removed
    cutoff = time.time() - max(0.0, float(min_age_seconds))
    for entry in entries:
        try:
            if not entry.is_dir() or entry.is_symlink():
                continue
            if entry.name in known_ids:
                continue
            if min_age_seconds and entry.stat().st_mtime > cutoff:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry.name)
        except OSError:
            continue
    return removed


class TaskPaused(Exception):
    pass


class TaskCanceled(Exception):
    pass


class DownloadManager:
    def __init__(self, config: Config):
        self.config = config
        self.lock = threading.RLock()
        self.tasks: dict[str, DownloadTask] = {}
        self.captures: list[Capture] = []
        self.controllers: dict[str, Any] = {}
        self.active_ids: set[str] = set()
        self.threads: dict[str, threading.Thread] = {}
        self.pause_requested: set[str] = set()
        self.cancel_requested: set[str] = set()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._last_save = 0.0
        self._shutting_down = False
        self._finish_action_done = False
        self._ytdlp_version_cache: str | None = None
        self._probe_queue: queue.Queue[str] = queue.Queue()
        self._probe_enqueued: set[str] = set()
        self._probe_pending: set[str] = set()
        self._load()
        for index in range(PROBE_WORKERS):
            threading.Thread(
                target=self._probe_worker,
                name=f"videoavci-probe-{index + 1}",
                daemon=True,
            ).start()
        for _capture in list(self.captures):
            self._schedule_probe(_capture.id)
        self._scheduler = threading.Thread(
            target=self._scheduler_loop,
            name="videoavci-scheduler",
            daemon=True,
        )
        self._scheduler.start()

    # ------------------------------------------------------------------ load/save
    def _load(self) -> None:
        stored_tasks = load_json(QUEUE_FILE, [])
        if isinstance(stored_tasks, dict):
            stored_tasks = stored_tasks.get("tasks", [])
        if isinstance(stored_tasks, list):
            for item in stored_tasks:
                if not isinstance(item, dict):
                    continue
                try:
                    task = DownloadTask.from_dict(item)
                except Exception:
                    continue
                if not is_http_url(task.url):
                    continue
                if task.status in ACTIVE_STATUSES or task.status == "starting":
                    task.status = "paused"
                    task.auto_resume = True
                if task.status == "paused" and task.auto_resume and self.config.get("auto_resume", True):
                    task.status = "queued"
                try:
                    task.retry_count = max(0, int(task.retry_count or 0))
                except (TypeError, ValueError):
                    task.retry_count = 0
                try:
                    task.available_at = max(0.0, float(task.available_at or 0.0))
                except (TypeError, ValueError):
                    task.available_at = 0.0
                task.speed = 0.0
                task.eta = 0
                task.updated_at = now()
                self.tasks[task.id] = task

        stored_captures = load_json(CAPTURES_FILE, [])
        if isinstance(stored_captures, list):
            seen: set[str] = set()
            for item in stored_captures:
                if not isinstance(item, dict):
                    continue
                try:
                    capture = Capture.from_dict(item)
                except Exception:
                    continue
                if not is_http_url(capture.url) or capture.url in seen:
                    continue
                try:
                    capture.probed_at = max(0.0, float(capture.probed_at or 0.0))
                except (TypeError, ValueError):
                    capture.probed_at = 0.0
                seen.add(capture.url)
                self.captures.append(capture)
            self.captures.sort(key=lambda capture: capture.created_at, reverse=True)
            self.captures = self.captures[:200]

        # Kuyrukta artık bulunmayan görevlerin yarım parçalarını temizle.
        removed = prune_orphan_parts(PARTS_DIR, set(self.tasks), min_age_seconds=60.0)
        if removed:
            log.info("Sahipsiz indirme parçaları temizlendi: %s", ", ".join(sorted(removed)))

    def _save_locked(self, throttle: bool = False) -> None:
        if self._shutting_down:
            throttle = False
        if throttle and time.monotonic() - self._last_save < 6.0:
            return
        try:
            tasks = [task.to_dict() for task in self.tasks.values()]
            atomic_write_json(QUEUE_FILE, tasks)
            captures = [capture.to_dict() for capture in self.captures]
            atomic_write_json(CAPTURES_FILE, captures)
            self._last_save = time.monotonic()
        except Exception as exc:
            log.exception("Durum kaydedilemedi: %s", exc)

    def save_now(self) -> None:
        with self.lock:
            self._save_locked(throttle=False)

    # ------------------------------------------------------------------- helpers
    def _snapshot_locked(self, task: DownloadTask) -> dict[str, Any]:
        return task.snapshot()

    def get_task(self, task_id: str) -> DownloadTask | None:
        with self.lock:
            return self.tasks.get(task_id)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            tasks = [task.snapshot() for task in self.tasks.values()]
            captures = [capture.to_dict() for capture in self.captures]
            active = sum(1 for task in self.tasks.values() if task.status in ACTIVE_STATUSES)
            queued = sum(1 for task in self.tasks.values() if task.status == "queued")
            completed = sum(1 for task in self.tasks.values() if task.status == "completed")
            errors = sum(1 for task in self.tasks.values() if task.status == "error")
            speed = sum(task.speed for task in self.tasks.values() if task.status in ACTIVE_STATUSES)
            current = time.time()
            retrying = sum(
                1
                for task in self.tasks.values()
                if task.status == "queued" and float(task.available_at or 0.0) > current
            )
            return {
                "tasks": tasks,
                "captures": captures,
                "active": active,
                "queued": queued,
                "completed": completed,
                "errors": errors,
                "retrying": retrying,
                "speed": speed,
                "capture_count": len(captures),
                "capture_paused": bool(self.config.get("capture_paused", False)),
            }

    def stats(self) -> dict[str, Any]:
        with self.lock:
            current = time.time()
            return {
                "active": sum(1 for task in self.tasks.values() if task.status in ACTIVE_STATUSES),
                "queued": sum(1 for task in self.tasks.values() if task.status == "queued"),
                "retrying": sum(
                    1
                    for task in self.tasks.values()
                    if task.status == "queued" and float(task.available_at or 0.0) > current
                ),
                "completed": sum(1 for task in self.tasks.values() if task.status == "completed"),
                "errors": sum(1 for task in self.tasks.values() if task.status == "error"),
                "captures": len(self.captures),
                "speed": sum(task.speed for task in self.tasks.values() if task.status in ACTIVE_STATUSES),
            }

    def health(self) -> dict[str, Any]:
        stats = self.stats()
        return {
            "ok": True,
            "app": "VideoAvci",
            "version": VERSION,
            "ytdlp": self.ytdlp_version(),
            "api": f"http://{API_HOST}:{API_PORT}",
            "download_dir": str(self.config.download_dir),
            "capture_paused": bool(self.config.get("capture_paused", False)),
            **stats,
        }

    def ytdlp_version(self) -> str:
        if self._ytdlp_version_cache is None:
            self._ytdlp_version_cache = ytdlp_version()
        return self._ytdlp_version_cache

    def update_ytdlp(self, callback: Callable[[bool, str], None]) -> None:
        def worker() -> None:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    env=None,
                )
                output = (result.stdout or "") + "\n" + (result.stderr or "")
                output = output.strip()[-1500:]
                self._ytdlp_version_cache = None
                callback(result.returncode == 0, output)
            except Exception as exc:
                callback(False, str(exc))

        threading.Thread(target=worker, name="videoavci-ytdlp-update", daemon=True).start()

    # --------------------------------------------------------------- task actions
    def _add_task_locked(
        self,
        url: str,
        quality: str | None = None,
        kind: str = "auto",
        title: str = "",
        page_url: str = "",
        referer: str = "",
    ) -> DownloadTask:
        quality = quality or str(self.config.get("default_quality", "best") or "best")
        task = DownloadTask(
            url=url,
            title=title.strip(),
            page_url=page_url.strip(),
            kind=kind if kind in {"auto", "page", "direct", "hls", "dash"} else "auto",
            quality=quality,
            status="queued",
            referer=referer.strip(),
            auto_resume=True,
        )
        self.tasks[task.id] = task
        # Yeni görev geldiğinde bitiş eylemi yeniden tetiklenebilir olmalı.
        self._finish_action_done = False
        return task

    def add_url(
        self,
        url: str,
        quality: str | None = None,
        kind: str = "auto",
        title: str = "",
        page_url: str = "",
        referer: str = "",
    ) -> tuple[DownloadTask, bool]:
        url = normalize_url(url)
        if not is_http_url(url):
            raise ValueError("Geçerli bir http/https bağlantısı girin.")
        with self.lock:
            for existing in self.tasks.values():
                if existing.url == url and existing.status not in {"completed", "canceled"}:
                    return existing, True
            task = self._add_task_locked(url, quality, kind, title, page_url, referer)
            self._save_locked()
            self._wake.set()
            log.info("Görev eklendi: %s %s", task.id, url)
            return task, False

    def add_urls(self, urls: list[str], quality: str | None = None) -> tuple[int, int, int]:
        """Birden çok bağlantıyı tek kilitle kuyruğa ekler.

        Dönen değer: ``(eklenen, zaten kuyrukta, geçersiz)``. Toplu eklemede
        her URL için ayrı kuyruk dosyası yazılmaz; tek kayıt yapılır.
        """
        added = duplicate = invalid = 0
        with self.lock:
            existing_urls = {
                task.url
                for task in self.tasks.values()
                if task.status not in {"completed", "canceled"}
            }
            for raw in urls:
                url = normalize_url(str(raw or ""))
                if not is_http_url(url):
                    invalid += 1
                    continue
                if url in existing_urls:
                    duplicate += 1
                    continue
                self._add_task_locked(url, quality=quality)
                existing_urls.add(url)
                added += 1
            if added:
                self._save_locked()
                self._wake.set()
        if added:
            log.info("Toplu ekleme: %s yeni görev", added)
        return added, duplicate, invalid

    def add_capture(self, payload: dict[str, Any]) -> tuple[Capture, bool]:
        capture = make_capture(payload)
        capture.url = normalize_url(capture.url)
        if not is_http_url(capture.url):
            raise ValueError("Geçerli bir medya bağlantısı yok.")
        if capture.page_url and not is_http_url(capture.page_url):
            capture.page_url = ""
        page_url_norm = (capture.page_url or "").lower()
        # Instagram tekil medya sayfalarında (Reels/gönderi) onlarca varyant
        # isteği yakalanır. Aynı sayfa için daha önce yakalama varsa yenisini
        # ekleme; böylece "Yakalananlar" listesi aynı sayfa ile dolmaz.
        is_instagram_single = (
            "instagram.com" in page_url_norm
            and ("/reels/" in page_url_norm or "/reel/" in page_url_norm or "/p/" in page_url_norm)
        )
        with self.lock:
            if is_instagram_single:
                for existing in self.captures:
                    if existing.page_url == capture.page_url:
                        if capture.title and not existing.title:
                            existing.title = capture.title
                        if capture.page_title and not existing.page_title:
                            existing.page_title = capture.page_title
                        if capture.size and not existing.size:
                            existing.size = capture.size
                        self._save_locked()
                        return existing, True
            for existing in self.captures:
                if existing.url == capture.url:
                    # Daha iyi başlık/boyut bilgisi geldiyse güncelle.
                    if capture.title and not existing.title:
                        existing.title = capture.title
                    if capture.page_title and not existing.page_title:
                        existing.page_title = capture.page_title
                    if capture.size and not existing.size:
                        existing.size = capture.size
                    if capture.kind and existing.kind == "direct":
                        existing.kind = capture.kind
                    if not existing.media_kind:
                        existing.media_kind = capture.media_kind
                    self._save_locked()
                    self._schedule_probe(existing.id)
                    return existing, True
            self.captures.insert(0, capture)
            self.captures = self.captures[:200]
            self._save_locked()
            log.info("Yakalama eklendi: %s", capture.url[:160])
            self._schedule_probe(capture.id)
            return capture, False

    @staticmethod
    def _resolution_from_url(url: str) -> str:
        match = re.search(r"(2160|1440|1080|720|480|360|240)", url or "")
        if match:
            return f"{match.group(1)}p"
        return ""

    def _read_probe_response(
        self,
        session: requests.Session,
        url: str,
        headers: dict[str, str],
        *,
        byte_range: str = "",
    ):
        """Tek bir probe yanıtını sınırlı boyutta okur."""
        request_headers = dict(headers)
        if byte_range:
            request_headers["Range"] = byte_range
        with session.get(
            url,
            headers=request_headers,
            timeout=(10, 20),
            allow_redirects=True,
            stream=True,
        ) as response:
            if response.status_code not in (200, 206):
                return None
            response_headers = getattr(response, "headers", {}) or {}
            content_type = str(response_headers.get("Content-Type") or "")
            content_length = str(response_headers.get("Content-Length") or "")
            content_range = str(response_headers.get("Content-Range") or "")
            total = 0
            match = re.search(r"/\s*(\d+)\s*$", content_range)
            if match:
                total = int(match.group(1))
            elif content_length:
                try:
                    total = int(content_length)
                except ValueError:
                    total = 0
            data = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                data.extend(chunk)
                if len(data) > PROBE_MAX_BYTES:
                    # Beklenenden büyük parçayı belleğe almayalım.
                    return None
            return (
                bytes(data),
                str(getattr(response, "url", "") or url),
                content_type,
                total,
            )

    def _fetch_probe_sample(
        self, url: str, referer: str = ""
    ) -> _ProbeSample | None:
        """HLS/DASH/MP4/TS/WebM için sınırlı bir analiz örneği indirir."""
        headers = {
            "Referer": referer or url,
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        }
        session = requests.Session()
        current = url
        visited: set[str] = set()
        init_data = b""
        manifest: MediaProbe | None = None
        try:
            for _ in range(PROBE_MAX_REDIRECTS):
                if current in visited:
                    return None
                visited.add(current)
                result = self._read_probe_response(session, current, headers)
                if result is None:
                    return _ProbeSample(init_data, "", current, "", manifest)
                data, final_url, content_type, total = result
                text = data.decode("utf-8", errors="replace") if data else ""

                if data.lstrip().startswith(b"#EXTM3U") or "mpegurl" in content_type.lower():
                    manifest = probe_bytes(data, text, final_url) or manifest
                    if "#EXT-X-STREAM-INF:" in text.upper():
                        return _ProbeSample(b"", text, final_url, content_type, manifest)
                    init_uri, segment_uri = hls_first_segment(text)
                    if init_uri:
                        init_result = self._read_probe_response(
                            session, urljoin(final_url, init_uri), headers
                        )
                        if init_result is not None:
                            init_data = init_result[0]
                    if not segment_uri:
                        return _ProbeSample(
                            init_data, "", final_url, content_type, manifest
                        )
                    current = urljoin(final_url, segment_uri)
                    continue

                if b"<MPD" in data[:4096]:
                    manifest = probe_bytes(data, text, final_url) or manifest
                    return _ProbeSample(data, text, final_url, content_type, manifest)

                # Doğrudan dosya: moov/kuyruk bilgisi için son baytları da al.
                tail = b""
                if total > len(data) and total > 0:
                    tail_start = max(0, total - PROBE_TAIL_BYTES)
                    tail_result = self._read_probe_response(
                        session,
                        final_url,
                        headers,
                        byte_range=f"bytes={tail_start}-",
                    )
                    if tail_result is not None:
                        tail = tail_result[0]
                payload = init_data + data if init_data else data
                return _ProbeSample(
                    payload,
                    text if not init_data else "",
                    final_url,
                    content_type,
                    manifest,
                    tail,
                )
            return _ProbeSample(init_data, "", current, "", manifest)
        except Exception:
            return None
        finally:
            session.close()

    def _fetch_first_segment(self, url: str, referer: str = "") -> bytes | None:
        """Geriye uyumluluk için ilk analiz örneğinin baytlarını döner."""
        sample = self._fetch_probe_sample(url, referer)
        return sample.data if sample and sample.data else None

    def _schedule_probe(self, capture_id: str) -> None:
        """Yakalamayı sınırlı işçi havuzuna ekler; aynı kimliği iki kez eklemez."""
        with self.lock:
            if capture_id in self._probe_enqueued or capture_id in self._probe_pending:
                return
            capture = next((item for item in self.captures if item.id == capture_id), None)
            if capture is None or not capture_needs_probe(capture):
                return
            self._probe_enqueued.add(capture_id)
            self._probe_queue.put(capture_id)

    def _probe_worker(self) -> None:
        while not self._stop.is_set():
            try:
                capture_id = self._probe_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            with self.lock:
                self._probe_enqueued.discard(capture_id)
                self._probe_pending.add(capture_id)
            try:
                self._probe_capture(capture_id)
            except Exception:
                log.exception("Yakalama analizi beklenmedik şekilde durdu: %s", capture_id)
            finally:
                self._probe_queue.task_done()

    @staticmethod
    def _probe_with_ffprobe(data: bytes) -> MediaProbe | None:
        """Son çare olarak ffprobe ile akış bilgisi çıkarır."""
        if not data or not shutil.which("ffprobe"):
            return None
        fd, tmp_path = tempfile.mkstemp(prefix="va_probe_", suffix=".bin")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-of",
                    "json",
                    tmp_path,
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            info = json.loads(result.stdout)
        except Exception:
            return None
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        streams = info.get("streams") or []
        has_video = any(str(stream.get("codec_type")) == "video" for stream in streams)
        has_audio = any(str(stream.get("codec_type")) == "audio" for stream in streams)
        width = height = 0
        for stream in streams:
            if str(stream.get("codec_type")) != "video":
                continue
            try:
                stream_height = int(stream.get("height") or 0)
                stream_width = int(stream.get("width") or 0)
            except (TypeError, ValueError):
                stream_height = stream_width = 0
            if stream_height > height:
                height = stream_height
                width = stream_width
        return MediaProbe(
            has_video=has_video,
            has_audio=has_audio,
            width=width,
            height=height,
            heights=(height,) if height else (),
            source="ffprobe",
        )

    @staticmethod
    def _probe_file_streams(path: str) -> tuple[bool, bool] | None:
        """Yerel dosyadaki gerçek ses/görüntü akışlarını ffprobe ile döndürür.

        Kapak resmi gibi ``attached_pic`` görüntü akışları video sayılmaz.
        ffprobe yoksa veya dosya okunamazsa ``None`` döner.
        """
        if not path or not shutil.which("ffprobe"):
            return None
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type,disposition",
                    "-of",
                    "json",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        try:
            info = json.loads(result.stdout)
        except (TypeError, ValueError):
            return None
        streams = info.get("streams") or []
        has_video = False
        has_audio = False
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            codec_type = str(stream.get("codec_type") or "").lower()
            if codec_type == "audio":
                has_audio = True
            elif codec_type == "video":
                disposition = stream.get("disposition") or {}
                if not bool(disposition.get("attached_pic")):
                    has_video = True
        return has_video, has_audio

    @staticmethod
    def _probe_with_ytdlp(url: str, referer: str) -> MediaProbe | None:
        """Yerleşik ayrıştırıcı yetersizse yt-dlp meta verisini kullanır."""
        if not url:
            return None
        from .utils import USER_AGENT

        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--no-playlist",
            "--no-warnings",
            "--socket-timeout",
            "20",
            "--user-agent",
            USER_AGENT,
            "--dump-single-json",
        ]
        cmd += youtube_extra_args(url)
        if referer:
            cmd += ["--add-header", f"Referer:{referer}"]
        cmd += [url]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=45,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        try:
            info = json.loads(result.stdout)
        except (ValueError, TypeError):
            return None

        formats = info.get("formats") or [info]
        has_video = any(
            str(format_info.get("video_ext") or "").lower() not in ("", "none")
            for format_info in formats
        ) or str(info.get("video_ext") or "").lower() not in ("", "none")
        has_audio = any(
            str(format_info.get("audio_ext") or "").lower() not in ("", "none")
            for format_info in formats
        ) or str(info.get("audio_ext") or "").lower() not in ("", "none")
        heights = sorted(
            {
                int(format_info.get("height"))
                for format_info in formats
                if isinstance(format_info.get("height"), int)
                and format_info.get("height")
            },
            reverse=True,
        )
        drm = bool(info.get("_has_drm") or info.get("has_drm"))
        drm = drm or any(bool(format_info.get("has_drm")) for format_info in formats)
        return MediaProbe(
            has_video=has_video,
            has_audio=has_audio,
            height=heights[0] if heights else 0,
            heights=tuple(heights),
            drm=drm,
            source="yt-dlp",
        )

    def _apply_probe(
        self,
        capture_id: str,
        probe: MediaProbe | None,
        original_kind: str,
        original_media_kind: str,
        url: str,
    ) -> None:
        """Analiz sonucunu yakalamaya işler; bilinmeyen alanları korur."""
        if probe is None:
            return
        has_video = probe.has_video
        has_audio = probe.has_audio
        media_known = (
            probe.video_known
            or probe.audio_known
            or has_video
            or has_audio
        )
        if not media_known and not probe.drm:
            # Hiçbir bilgi çıkmadıysa yalnızca URL ipucunu kullan.
            media_info = self._resolution_from_url(url)
            new_kind = ""
        else:
            if original_kind in {"hls", "dash"}:
                new_kind = "manifest"
            elif has_video and has_audio:
                new_kind = "av"
            elif has_video:
                new_kind = "video"
            elif has_audio:
                new_kind = "audio"
            else:
                new_kind = original_media_kind or ""

            media_info = ""
            if probe.heights and len(probe.heights) > 1:
                media_info = f"çoklu ({probe.heights[0]}p)"
            elif probe.height:
                media_info = f"{probe.height}p"
            elif has_audio and not has_video:
                media_info = "ses"

            if original_kind in {"hls", "dash"}:
                if has_audio and not has_video:
                    media_info = "sesli"
                elif has_audio:
                    media_info = (
                        f"{media_info} · sesli".strip() if media_info else "sesli"
                    )
                elif probe.audio_known:
                    media_info = (
                        f"{media_info} · sessiz".strip() if media_info else "sessiz"
                    )
            if not media_info:
                media_info = self._resolution_from_url(url)

        with self.lock:
            capture = next((item for item in self.captures if item.id == capture_id), None)
            if capture is None:
                return
            changed = False
            if new_kind and capture.media_kind != new_kind:
                capture.media_kind = new_kind
                changed = True
            if media_info and capture.media_info != media_info:
                capture.media_info = media_info
                changed = True
            if probe.drm and not capture.drm:
                capture.drm = True
                changed = True
            if changed:
                self._save_locked()

    def _probe_capture(self, capture_id: str) -> None:
        try:
            with self.lock:
                capture = next((item for item in self.captures if item.id == capture_id), None)
                if capture is None:
                    return
                url = capture.url
                referer = capture.referer or capture.page_url
                original_kind = capture.kind
                original_media_kind = capture.media_kind
            if not url:
                return

            probe = MediaProbe(video_known=False, audio_known=False)
            sample = self._fetch_probe_sample(url, referer)
            if sample is not None:
                # Manifest ve indirilen örnek birbirini tamamlar (ör. HLS init
                # haritası ses/görüntü bilgisini, segment ise çözünürlüğü verir).
                probe = probe.merged(sample.manifest)
                if sample.data:
                    probe = probe.merged(
                        probe_bytes(sample.data, sample.text, sample.final_url or url)
                    )
                if sample.tail:
                    probe = probe.merged(probe_bytes(sample.tail))

            is_text_sample = False
            if sample is not None and sample.data:
                head = sample.data[:256].lstrip().lower()
                is_text_sample = head.startswith(b"#extm3u") or b"<mpd" in head

            if not probe.complete and sample is not None and not is_text_sample:
                probe = probe.merged(self._probe_with_ffprobe(sample.data))

            if not probe.complete:
                probe = probe.merged(self._probe_with_ytdlp(url, referer))

            self._apply_probe(
                capture_id,
                probe,
                original_kind,
                original_media_kind,
                url,
            )
        except Exception:
            log.debug("Medya sondası başarısız: %s", capture_id, exc_info=True)
        finally:
            with self.lock:
                capture = next((item for item in self.captures if item.id == capture_id), None)
                if capture is not None:
                    # Başarısız analizler de zaman damgası alır; böylece aynı
                    # yakalama her istekte yeniden denenip kaynak tüketmez.
                    capture.probed_at = now()
                self._probe_pending.discard(capture_id)
                self._save_locked()

    def download_capture(self, capture_id: str) -> tuple[DownloadTask, bool]:
        with self.lock:
            capture = next((item for item in self.captures if item.id == capture_id), None)
            if capture is None:
                raise ValueError("Yakalanan video bulunamadı.")
            if capture.drm:
                # DRM korumalı içerik indirilemez; korumayı aşmaya çalışmıyoruz.
                raise ValueError(t("error.drm"))
            for existing in self.tasks.values():
                if existing.url == capture.url and existing.status not in {"completed", "canceled"}:
                    return existing, True
            task = self._add_task_locked(
                capture.url,
                kind=capture.kind,
                title=capture.title or capture.page_title,
                page_url=capture.page_url,
                referer=capture.referer or capture.page_url,
            )
            self.captures = [item for item in self.captures if item.id != capture_id]
            self._save_locked()
            self._wake.set()
            return task, False

    def download_all_captures(self) -> tuple[int, int]:
        """Listedeki tüm yakalananları kuyruğa ekler.

        Dönen değer: (eklenen, zaten kuyrukta olan) sayısı.
        """
        with self.lock:
            capture_ids = [capture.id for capture in self.captures]
        added = duplicates = 0
        for capture_id in capture_ids:
            try:
                _, duplicate = self.download_capture(capture_id)
            except Exception:
                log.exception("Yakalanan video kuyruğa eklenemedi: %s", capture_id)
                continue
            if duplicate:
                duplicates += 1
            else:
                added += 1
        return added, duplicates

    def remove_capture(self, capture_id: str) -> None:
        with self.lock:
            self.captures = [item for item in self.captures if item.id != capture_id]
            self._save_locked()

    def clear_captures(self) -> None:
        with self.lock:
            self.captures = []
            self._save_locked()

    def pause_task(self, task_id: str) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            if task is None:
                return
            if task.status == "queued":
                task.status = "paused"
                task.auto_resume = False
                task.detail = t("task.status.paused")
                task.updated_at = now()
            elif task.status in ACTIVE_STATUSES:
                task.status = "pausing"
                task.detail = t("task.status.pausing")
                task.auto_resume = False
                self.pause_requested.add(task_id)
                controller = self.controllers.get(task_id)
                if controller is not None:
                    controller.pause()
            else:
                return
            self._save_locked()
            self._wake.set()

    def resume_task(self, task_id: str) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            if task is None or task.status not in {"paused", "error", "canceled"}:
                return
            task.status = "queued"
            task.error = ""
            task.speed = 0.0
            task.eta = 0
            task.retry_count = 0
            task.available_at = 0.0
            task.auto_resume = True
            task.detail = t("task.status.queued")
            task.updated_at = now()
            self.pause_requested.discard(task_id)
            self.cancel_requested.discard(task_id)
            self._finish_action_done = False
            self._save_locked()
            self._wake.set()

    def cancel_task(self, task_id: str) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            if task is None:
                return
            if task.status in {"queued", "paused", "error"}:
                task.status = "canceled"
                task.speed = 0.0
                task.eta = 0
                task.detail = t("task.status.canceled")
                task.auto_resume = False
                task.updated_at = now()
                self._cleanup_parts(task_id)
            elif task.status in ACTIVE_STATUSES:
                task.status = "canceling"
                task.detail = t("task.status.canceling")
                task.auto_resume = False
                self.cancel_requested.add(task_id)
                controller = self.controllers.get(task_id)
                if controller is not None:
                    controller.cancel()
            else:
                return
            self._save_locked()
            self._wake.set()

    def retry_task(self, task_id: str) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            if task is None:
                return
            if task.status not in {"error", "canceled", "paused"}:
                return
            task.status = "queued"
            task.error = ""
            task.progress = 0.0
            task.speed = 0.0
            task.eta = 0
            task.downloaded = 0
            task.total = 0
            task.retry_count = 0
            task.available_at = 0.0
            task.detail = t("task.status.queued")
            task.auto_resume = True
            task.updated_at = now()
            self.pause_requested.discard(task_id)
            self.cancel_requested.discard(task_id)
            self._finish_action_done = False
            self._save_locked()
            self._wake.set()

    def remove_task(self, task_id: str) -> bool:
        with self.lock:
            task = self.tasks.get(task_id)
            if task is None:
                return False
            if task.status in ACTIVE_STATUSES:
                return False
            self.tasks.pop(task_id, None)
            self._cleanup_parts(task_id)
            self._save_locked()
            return True

    def clear_completed(self) -> None:
        with self.lock:
            self.tasks = {
                task_id: task
                for task_id, task in self.tasks.items()
                if task.status != "completed"
            }
            self._save_locked()

    def clear_finished(self) -> None:
        with self.lock:
            keep: dict[str, DownloadTask] = {}
            for task_id, task in self.tasks.items():
                if task.status in FINISHED_STATUSES:
                    if task.status in {"canceled", "error"}:
                        self._cleanup_parts(task_id)
                    continue
                keep[task_id] = task
            self.tasks = keep
            self._save_locked()

    def clear_queue(self) -> int:
        """Tüm indirme görevlerini (aktif olanlar dahil) listeden kaldırır.

        Aktif görevlerin iş parçacıkları kendi ``finally`` bloklarında
        temizlenene kadar ``active_ids`` korunur. Böylece yeni kuyruk
        temizlendikten hemen sonra eşzamanlılık sınırı aşılmaz.
        """
        with self.lock:
            active_ids = {
                tid for tid, task in self.tasks.items() if task.status in ACTIVE_STATUSES
            }
            for task_id in active_ids:
                self.cancel_requested.add(task_id)
                controller = self.controllers.get(task_id)
                if controller is not None:
                    try:
                        controller.cancel()
                    except Exception:
                        pass
            removed = len(self.tasks)
            for task_id, task in self.tasks.items():
                if task_id not in active_ids:
                    self._cleanup_parts(task_id)
            self.tasks.clear()
            # aktif_ids/controllers/cancel_requested bilinçli olarak bırakılır:
            # çalışan görevlerin iş parçacıkları bunları kendileri temizler.
            self.pause_requested = {
                task_id for task_id in self.pause_requested if task_id in active_ids
            }
            self.cancel_requested = {
                task_id for task_id in self.cancel_requested if task_id in active_ids
            }
            self.controllers = {
                task_id: controller
                for task_id, controller in self.controllers.items()
                if task_id in active_ids
            }
            self._finish_action_done = False
            self._save_locked()
            self._wake.set()
        return removed

    def pause_all(self) -> None:
        with self.lock:
            ids = [task.id for task in self.tasks.values() if task.status in ACTIVE_STATUSES or task.status == "queued"]
        for task_id in ids:
            self.pause_task(task_id)

    def resume_all(self) -> None:
        with self.lock:
            ids = [task.id for task in self.tasks.values() if task.status in {"paused", "error", "canceled"}]
        for task_id in ids:
            self.resume_task(task_id)

    def retry_failed(self) -> int:
        """Hatalı görevleri yeniden kuyruğa alır ve sayısını döner."""
        with self.lock:
            ids = [task.id for task in self.tasks.values() if task.status == "error"]
        for task_id in ids:
            self.retry_task(task_id)
        return len(ids)

    def _cleanup_parts(self, task_id: str) -> None:
        shutil.rmtree(PARTS_DIR / task_id, ignore_errors=True)

    def _maybe_auto_retry_locked(self, task: DownloadTask, error: object) -> bool:
        """Geçici hatada görevi geri çekilme süresiyle yeniden kuyruğa alır.

        Kalıcı hatalar (DRM, 404, özel video vb.) yeniden denenmez. Dönüş
        değeri görevin otomatik yeniden denemeye alınıp alınmadığını belirtir.
        """
        if not bool(self.config.get("auto_retry", True)):
            return False
        try:
            limit = max(0, min(5, int(self.config.get("auto_retry_limit", 2) or 0)))
        except (TypeError, ValueError):
            limit = 2
        if limit <= 0 or task.retry_count >= limit:
            return False
        message = str(error or "")
        if not is_transient_error(error):
            return False

        task.retry_count += 1
        retry_after = float(getattr(error, "retry_after", 0.0) or 0.0)
        delay = max(
            auto_retry_delay(task.retry_count),
            min(AUTO_RETRY_RETRY_AFTER_CAP, int(retry_after)),
        )
        task.status = "queued"
        task.available_at = time.time() + delay
        task.error = message
        task.speed = 0.0
        task.eta = 0
        task.detail = t(
            "task.detail.auto_retry",
            count=task.retry_count,
            limit=limit,
            seconds=delay,
        )
        task.auto_resume = True
        task.updated_at = now()
        self._finish_action_done = False
        log.warning(
            "Görev geçici hatayla durdu, %s sn sonra yeniden denenecek "
            "(%s/%s): %s",
            delay,
            task.retry_count,
            limit,
            message,
        )
        return True

    # ------------------------------------------------------------------ scheduler
    def _scheduler_loop(self) -> None:
        while not self._stop.is_set():
            try:
                started = False
                with self.lock:
                    if not self._shutting_down:
                        max_concurrent = int(self.config.get("max_concurrent", 2) or 2)
                        if len(self.active_ids) < max_concurrent:
                            current = time.time()
                            for task in self.tasks.values():
                                if task.status != "queued" or task.id in self.active_ids:
                                    continue
                                if float(task.available_at or 0.0) > current:
                                    continue
                                task.available_at = 0.0
                                task.status = "starting"
                                task.detail = t("task.status.starting")
                                task.updated_at = now()
                                self.active_ids.add(task.id)
                                thread = threading.Thread(
                                    target=self._run_task,
                                    args=(task.id,),
                                    name=f"videoavci-task-{task.id}",
                                    daemon=True,
                                )
                                self.threads[task.id] = thread
                                thread.start()
                                started = True
                                break
                    if started:
                        self._save_locked()
            except Exception:
                log.exception("Zamanlayıcı hatası")
            self._wake.wait(0.35)
            self._wake.clear()

    # ------------------------------------------------------------------ run task
    def _mode_for(self, task: DownloadTask) -> str:
        if str(self.config.get("cookies_browser", "none")) != "none":
            return "ytdlp"
        if is_youtube_url(task.url):
            return "ytdlp"
        if task.kind in {"hls", "dash", "page"}:
            return "ytdlp"
        if task.kind == "direct":
            return "direct"
        if is_manifest_url(task.url):
            return "ytdlp"
        # Bilinmeyen uzantılar için önce doğrudan indirmeyi dene; HTML dönerse
        # _run_task içinde yt-dlp'ye otomatik geçilir.
        return "direct"

    def _progress_callback(self, task_id: str):
        def callback(downloaded: int, total: int, percent: float, speed: float, eta: int) -> None:
            with self.lock:
                task = self.tasks.get(task_id)
                if task is None:
                    return
                task.downloaded = max(0, int(downloaded or 0))
                if total:
                    task.total = int(total)
                task.progress = max(0.0, min(100.0, float(percent or 0)))
                task.speed = max(0.0, float(speed or 0))
                task.eta = max(0, int(eta or 0))
                task.updated_at = now()
                self._save_locked(throttle=True)

        return callback

    def _status_callback(self, task_id: str):
        def callback(status: str, text: str = "") -> None:
            with self.lock:
                task = self.tasks.get(task_id)
                if task is None:
                    return
                if text:
                    task.detail = text
                if status in {"starting", "analyzing", "downloading", "processing"}:
                    if task.status not in {"pausing", "canceling"}:
                        task.status = status
                task.updated_at = now()

        return callback

    def _title_callback(self, task_id: str):
        def callback(title: str, filename: str, total: int) -> None:
            with self.lock:
                task = self.tasks.get(task_id)
                if task is None:
                    return
                if title:
                    task.title = title
                if filename:
                    task.format_note = filename
                if total:
                    task.total = int(total)
                task.updated_at = now()

        return callback

    def _metadata_callback(self, task_id: str):
        def callback(metadata: dict) -> None:
            with self.lock:
                task = self.tasks.get(task_id)
                if task is None:
                    return
                if metadata.get("title"):
                    task.title = str(metadata["title"])
                task.duration = int(metadata.get("duration") or 0)
                task.thumbnail = str(metadata.get("thumbnail") or "")
                task.extractor = str(metadata.get("extractor") or "")
                task.analyzed = True
                if metadata.get("format_note"):
                    task.format_note = str(metadata["format_note"])
                task.updated_at = now()

        return callback

    def _log_callback(self, task_id: str):
        def callback(line: str) -> None:
            with self.lock:
                task = self.tasks.get(task_id)
                if task is None:
                    return
                text = (task.log_tail or "") + str(line).strip() + "\n"
                task.log_tail = text[-8000:]

        return callback

    def _probe_av(self, url: str, referer: str = "") -> tuple[bool, bool]:
        """URL'nin ses ve görüntü içerip içermediğini yt-dlp ile hızlıca sınar."""
        cmd = ytdlp_base_command() + [
            "--no-playlist",
            "--no-warnings",
            "--dump-single-json",
            "--socket-timeout",
            "20",
            "--user-agent",
            USER_AGENT,
        ]
        cmd += youtube_extra_args(url)
        if referer:
            cmd += ["--add-header", f"Referer:{referer}"]
        cmd.append(url)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=45,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except Exception:
            return False, False
        if result.returncode != 0 or not result.stdout.strip():
            return False, False
        info: dict[str, Any] | None = None
        for line in reversed(result.stdout.strip().splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                parsed = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                info = parsed
                break
        if info is None:
            return False, False

        formats = [fmt for fmt in (info.get("formats") or [info]) if isinstance(fmt, dict)]
        if not formats:
            formats = [info]
        audio = False
        video = False
        for fmt in formats:
            if str(fmt.get("acodec") or "").lower() not in ("", "none"):
                audio = True
            if str(fmt.get("vcodec") or "").lower() not in ("", "none"):
                video = True
            if str(fmt.get("audio_ext") or "").lower() not in ("", "none"):
                audio = True
            if str(fmt.get("video_ext") or "").lower() not in ("", "none"):
                video = True
        return audio, video

    @staticmethod
    def _needs_av_merge(task: "DownloadTask") -> bool:
        """Görev için ayrı ses akışı indirip birleştirmek gerekiyor mu?

        Kullanıcı "sadece ses" kalitesini seçtiyse yt-dlp zaten MP3 üretir;
        ayrıca ses akışı indirmek ve birleştirmeye çalışmak gereksizdir.
        """
        return (
            task.kind in {"hls", "dash"}
            and task.quality != "audio"
            and not task.audio_url
        )

    def _find_matching_audio(self, task: "DownloadTask") -> str:
        """Aynı sayfadaki ses-only HLS/DASH yakalamasını bulur.

        Etiketi zaten ``audio`` olan adaylar önce denenir; her probe yt-dlp alt
        süreci başlattığı için en fazla birkaç aday incelenir. Yalnızca gerçekten
        ses içeren ve görüntü içermeyen bir akış döner; aksi halde boş dize.
        """
        if not task.page_url:
            return ""
        with self.lock:
            candidates = [
                capture
                for capture in self.captures
                if capture.page_url == task.page_url
                and capture.kind in {"hls", "dash"}
                and not getattr(capture, "drm", False)
                and capture.url != task.url
            ]
        candidates.sort(key=lambda capture: capture.media_kind != "audio")
        for capture in candidates[:3]:
            if capture.media_kind == "audio":
                return capture.url
            audio, video = self._probe_av(capture.url, task.page_url or capture.page_url)
            if audio and not video:
                return capture.url
        return ""

    def _find_combined_stream(self, task: "DownloadTask", probe: bool = False) -> str:
        """Ses-only akış bulunamazsa aynı sayfadaki sesli/birleşik akışı döner.

        ``probe`` yalnızca birleştirme başarısız olduğunda kullanılır; bu
        durumda medya etiketi güvenilir değilse adayların gerçekten iki akış
        içerdiği yt-dlp ile sınırlı sayıda denenir.
        """
        if not task.page_url:
            return ""
        with self.lock:
            candidates = [
                capture
                for capture in self.captures
                if capture.page_url == task.page_url
                and capture.kind in {"hls", "dash"}
                and not getattr(capture, "drm", False)
                and capture.url != task.url
            ]
        for capture in (candidates[:3] if probe else candidates):
            info = (capture.media_info or "").lower()
            # "1080p · sesli" gibi hem çözünürlük hem ses içeren kayıtlar
            # birleşik akıştır; sadece "sesli" olanlar ses-only'dir.
            if "sessiz" in info:
                continue
            if "sesli" in info and any(char.isdigit() for char in info):
                return capture.url
            if probe:
                audio, video = self._probe_av(
                    capture.url,
                    task.page_url or capture.page_url,
                )
                if audio and video:
                    return capture.url
        return ""

    def _download_one(
        self,
        task: "DownloadTask",
        url: str,
        task_id: str,
        audio_only: bool = False,
    ) -> str:
        orig_url = task.url
        task.url = url
        downloader = YtDlpDownloader(
            task,
            self.config,
            self._progress_callback(task_id),
            self._status_callback(task_id),
            self._log_callback(task_id),
            self._metadata_callback(task_id),
            audio_only=audio_only,
        )
        try:
            with self.lock:
                self.controllers[task_id] = downloader
                if task_id in self.pause_requested:
                    downloader.pause()
                if task_id in self.cancel_requested:
                    downloader.cancel()
            return downloader.run()
        finally:
            # Hata olsa da URL'yi orijinaline geri yükle.
            task.url = orig_url

    def _validate_final_media(self, task: DownloadTask, path: str) -> None:
        """Tamamlanan dosyada beklenen ses/görüntü akışlarını doğrular.

        Video indirmelerinde iki akış da yoksa görev tamamlanmış sayılmaz;
        böylece "sesi olmayan video" veya "görüntüsü olmayan ses" dosyası
        sessizce başarılı görünmez. Doğrudan ses dosyaları (ör. MP3) için
        yalnızca ses akışı yeterlidir.
        """
        streams = self._probe_file_streams(path)
        if streams is None:
            # ffprobe yoksa indirmeyi engelleme; kullanıcıyı bilgilendir.
            self._log_callback(task.id)(
                "Uyarı: ffprobe bulunamadığı için ses/görüntü doğrulanamadı."
            )
            return
        has_video, has_audio = streams
        quality = str(task.quality or "best")
        if quality == "audio":
            if not has_audio:
                raise PermanentDownloadError(
                    "İndirilen dosyada ses akışı bulunamadı; dosya tamamlanmış sayılmadı.",
                    code="missing_audio",
                )
            return
        if str(task.kind or "") in {"page", "hls", "dash"}:
            missing = []
            if not has_video:
                missing.append("görüntü")
            if not has_audio:
                missing.append("ses")
            if missing:
                raise PermanentDownloadError(
                    "İndirilen dosyada "
                    + " ve ".join(missing)
                    + " akışı yok; eksik dosya tamamlanmış sayılmadı.",
                    code="missing_stream",
                )
            return
        # Doğrudan bağlantı: video varsa sesi de olmalı. Yalnızca ses içeren
        # dosyalar (MP3/M4A vb.) geçerli kabul edilir.
        if has_video and not has_audio:
            raise PermanentDownloadError(
                "İndirilen videoda ses akışı yok; dosya tamamlanmış sayılmadı.",
                code="missing_audio",
            )
        if not has_video and not has_audio:
            raise PermanentDownloadError(
                "İndirilen dosyada ses veya görüntü akışı bulunamadı.",
                code="missing_media",
            )

    def _merge_av(self, video_path: str, audio_path: str) -> str:
        """Video ve ses dosyalarını ffmpeg ile tek dosyada birleştirir.

        Metadata temizlenir; böylece site bağlantıları/etiketleri dosyaya
        yapışmaz. Önce MP4, olmazsa MKV kabı denenir. Birleştirme başarısız
        olursa kaynak dosyalar silinmez ve hata yukarı iletilir.
        """
        video_p = Path(video_path)
        audio_p = Path(audio_path)
        if not video_p.is_file() or not audio_p.is_file():
            raise FileNotFoundError("Birleştirilecek video veya ses dosyası bulunamadı.")

        errors: list[str] = []
        for suffix in (".mp4", ".mkv"):
            target = unique_path(video_p.parent, f"{video_p.stem}_merged{suffix}")
            cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(video_p),
                "-i",
                str(audio_p),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-map_metadata",
                "-1",
                "-c",
                "copy",
                str(target),
            ]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(str(exc))
                continue
            if result.returncode == 0 and target.is_file() and target.stat().st_size > 0:
                for source in (video_p, audio_p):
                    try:
                        source.unlink(missing_ok=True)
                    except OSError:
                        pass
                return str(target)
            errors.append((result.stderr or "").strip()[-500:])
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass

        detail = next((error for error in reversed(errors) if error), "bilinmeyen hata")
        raise RuntimeError(f"FFmpeg birleştirme başarısız: {detail}")

    def _run_task(self, task_id: str) -> None:
        downloader = None
        task = self.get_task(task_id)
        if task is None:
            with self.lock:
                self.active_ids.discard(task_id)
                self.controllers.pop(task_id, None)
            return
        try:
            if task_id in self.cancel_requested:
                raise TaskCanceled()
            if task_id in self.pause_requested:
                raise TaskPaused()

            mode = self._mode_for(task)
            log.info("Görev başlıyor: %s mod=%s", task_id, mode)

            # Ses+görüntü birleştirme: video-only HLS için aynı sayfadaki
            # başka bir HLS yakalamasını bul ve tek dosyada birleştir.
            # yt-dlp audio_ext/video_ext reliably ayrılamadığı için, sayfa URL'si
            # ve URL farklılığıyla eşleşen başka bir hls yakalama yeterli.
            if mode != "direct" and self._needs_av_merge(task):
                try:
                    audio_url = self._find_matching_audio(task)
                    if audio_url:
                        task.audio_url = audio_url
                        self._save_locked()
                        log.info("Eşleşen ses akışı bulundu: %s", audio_url[:160])
                    else:
                        # Ses-only akış bulunamazsa/son kullanma tarihi geçmişse,
                        # aynı sayfadaki sesli (birleşik) akışa geç; böylece video
                        # sessiz inmez.
                        combined_url = self._find_combined_stream(task)
                        if combined_url and combined_url != task.url:
                            task.url = combined_url
                            task.audio_url = ""
                            self._save_locked()
                            log.info("Sesli birleşik akışa geçildi: %s", combined_url[:160])
                except Exception:
                    pass

            if mode != "direct" and task.audio_url:
                # Birleştirilmiş indirme: önce video, sonra ses, sonra ffmpeg merge.
                video_path = self._download_one(task, task.url, task_id)
                audio_path = self._download_one(task, task.audio_url, task_id, audio_only=True)
                try:
                    path = self._merge_av(video_path, audio_path)
                    task.audio_url = ""  # tekrar birleştirme yapma
                except Exception as exc:
                    if not os.path.isfile(video_path):
                        raise
                    log.warning("Ses/video birleştirilemedi: %s", exc)
                    self._log_callback(task_id)(f"Birleştirme hatası: {exc}")
                    # Video-only dosyayı başarılı sayma. Aynı sayfada sesli
                    # birleşik bir akış varsa onu dene; yoksa görevi hata yap.
                    combined_url = self._find_combined_stream(task, probe=True)
                    if combined_url and combined_url != task.url:
                        log.info(
                            "Birleştirme yerine sesli birleşik akış deneniyor: %s",
                            combined_url[:160],
                        )
                        path = self._download_one(task, combined_url, task_id)
                        for source in (video_path, audio_path):
                            try:
                                Path(source).unlink(missing_ok=True)
                            except OSError:
                                pass
                    else:
                        task.audio_url = ""
                        self._log_callback(task_id)(
                            f"Birleştirilemeyen dosyalar: {video_path}, {audio_path}"
                        )
                        raise PermanentDownloadError(
                            "Ses ve görüntü birleştirilemedi; eksik dosya "
                            "tamamlanmış sayılmadı.",
                            code="merge_failed",
                        ) from exc
                    task.audio_url = ""
            else:
                if mode == "direct":
                    downloader = DirectDownloader(
                        task,
                        self.config,
                        self._progress_callback(task_id),
                        self._status_callback(task_id),
                        self._title_callback(task_id),
                        self._log_callback(task_id),
                    )
                else:
                    downloader = YtDlpDownloader(
                        task,
                        self.config,
                        self._progress_callback(task_id),
                        self._status_callback(task_id),
                        self._log_callback(task_id),
                        self._metadata_callback(task_id),
                    )

                with self.lock:
                    self.controllers[task_id] = downloader
                    if task_id in self.pause_requested:
                        downloader.pause()
                    if task_id in self.cancel_requested:
                        downloader.cancel()

                try:
                    path = downloader.run()
                except NotDirectError:
                    if mode != "direct":
                        raise
                    log.info("Doğrudan indirme başarısız, yt-dlp'ye geçiliyor: %s", task_id)
                    with self.lock:
                        task.kind = "page"
                        task.detail = t("task.detail.trying_page")
                    downloader = YtDlpDownloader(
                        task,
                        self.config,
                        self._progress_callback(task_id),
                        self._status_callback(task_id),
                        self._log_callback(task_id),
                        self._metadata_callback(task_id),
                    )
                    with self.lock:
                        self.controllers[task_id] = downloader
                        if task_id in self.pause_requested:
                            downloader.pause()
                        if task_id in self.cancel_requested:
                            downloader.cancel()
                    path = downloader.run()

            # Son güvenlik kontrolü: video indirmelerinde hem ses hem görüntü
            # akışı bulunmalı. Eksik dosya "tamamlandı" olarak işaretlenmez.
            self._validate_final_media(task, path)

            with self.lock:
                if task_id in self.cancel_requested:
                    raise TaskCanceled()
                task.status = "completed"
                task.progress = 100.0
                task.filepath = path
                task.speed = 0.0
                task.eta = 0
                task.error = ""
                task.detail = t("task.status.completed")
                task.auto_resume = False
                size = file_size(path)
                if size:
                    task.total = size
                    task.downloaded = size
                task.updated_at = now()
                self._save_locked()
                log.info("Görev tamamlandı: %s -> %s", task_id, path)
                self._check_finish_action_locked()

        except (TaskPaused, DirectPaused, YtPaused):
            with self.lock:
                task = self.tasks.get(task_id)
                if task is not None:
                    task.status = "paused"
                    task.speed = 0.0
                    task.eta = 0
                    task.detail = t("task.status.paused")
                    task.updated_at = now()
                self._save_locked()
            log.info("Görev duraklatıldı: %s", task_id)

        except (TaskCanceled, DirectCanceled, YtCanceled):
            if downloader is not None:
                try:
                    downloader.cleanup()
                except Exception:
                    log.exception("İptal temizliği başarısız")
            with self.lock:
                task = self.tasks.get(task_id)
                if task is not None:
                    task.status = "canceled"
                    task.speed = 0.0
                    task.eta = 0
                    task.detail = t("task.status.canceled")
                    task.auto_resume = False
                    task.updated_at = now()
                self._cleanup_parts(task_id)
                self._save_locked()
            log.info("Görev iptal edildi: %s", task_id)

        except DownloadError as exc:
            with self.lock:
                task = self.tasks.get(task_id)
                retried = False
                if task is not None:
                    if task_id in self.cancel_requested:
                        task.status = "canceled"
                        task.detail = t("task.status.canceled")
                    elif task_id in self.pause_requested:
                        task.status = "paused"
                        task.detail = t("task.status.paused")
                    else:
                        retried = self._maybe_auto_retry_locked(task, exc)
                    task.error = str(exc)
                    task.speed = 0.0
                    task.eta = 0
                    if not retried and task.status not in {"canceled", "paused"}:
                        task.status = "error"
                        task.detail = t("task.status.error")
                    task.updated_at = now()
                self._save_locked()
            if retried:
                log.warning("Görev otomatik yeniden denemeye alındı %s: %s", task_id, exc)
            else:
                log.warning("Görev hatası %s: %s", task_id, exc)

        except Exception as exc:
            log.exception("Beklenmeyen görev hatası: %s", task_id)
            with self.lock:
                task = self.tasks.get(task_id)
                if task is not None:
                    task.status = "error"
                    task.error = f"Beklenmeyen hata: {exc}"
                    task.speed = 0.0
                    task.eta = 0
                    task.detail = t("task.status.error")
                    task.updated_at = now()
                self._save_locked()

        finally:
            with self.lock:
                self.active_ids.discard(task_id)
                self.controllers.pop(task_id, None)
                self.threads.pop(task_id, None)
                self.pause_requested.discard(task_id)
                self.cancel_requested.discard(task_id)
                if task_id not in self.tasks:
                    # Kuyruk temizlendiyse çalışan görevin geçici parçaları
                    # sonraki açılışı beklemeden silinir.
                    self._cleanup_parts(task_id)
                self._save_locked(throttle=False)
            self._wake.set()

    # -------------------------------------------------------------------- shutdown
    def _check_finish_action_locked(self) -> None:
        action = str(self.config.get("shutdown_on_finish", "none") or "none")
        if action not in {"shutdown", "suspend"}:
            return
        if self._finish_action_done:
            return
        remaining = [
            t for t in self.tasks.values()
            if t.status in ACTIVE_STATUSES or t.status in {"queued", "paused"}
        ]
        if not remaining:
            self._finish_action_done = True
            log.info("Tüm indirmeler tamamlandı, kapanış eylemi uygulanıyor: %s", action)
            cmd = ["systemctl", "poweroff"] if action == "shutdown" else ["systemctl", "suspend"]
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as exc:
                log.error("Kapanış eylemi başarısız: %s", exc)

    def check_playlist(self, url: str) -> dict | None:
        from .ytdlp import extract_playlist_info
        cookies = str(self.config.get("cookies_browser", "none") or "none")
        return extract_playlist_info(url, cookies_browser=cookies)

    def add_playlist_items(self, items: list[dict], quality: str | None = None) -> int:
        count = 0
        for item in items:
            item_url = item.get("url")
            if not item_url:
                continue
            try:
                _, dup = self.add_url(
                    item_url,
                    quality=quality,
                    title=item.get("title", ""),
                )
                if not dup:
                    count += 1
            except Exception:
                pass
        return count

    def shutdown(self, timeout: float = 6.0) -> None:
        log.info("İndirme yöneticisi kapatılıyor")
        self._shutting_down = True
        with self.lock:
            self._stop.set()
            self._wake.set()
            for task in self.tasks.values():
                if task.status in ACTIVE_STATUSES or task.status == "queued":
                    task.auto_resume = True
                    if task.status == "queued":
                        task.status = "paused"
                        task.detail = t("task.detail.app_closed")
                    elif task.status in ACTIVE_STATUSES:
                        task.status = "pausing"
                        task.detail = t("task.detail.app_closing")
                        self.pause_requested.add(task.id)
                        controller = self.controllers.get(task.id)
                        if controller is not None:
                            try:
                                controller.pause()
                            except Exception:
                                pass
            self._save_locked(throttle=False)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if not self.active_ids:
                    break
            time.sleep(0.1)
        self.save_now()
