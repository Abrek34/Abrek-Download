"""İndirme kuyruğu, görev yaşam döngüsü ve tarayıcı yakalamaları."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from urllib.parse import urljoin
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

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
    DownloadError as DirectError,
    DownloadPaused as DirectPaused,
    NotDirectError,
)
from .i18n import t
from .models import (
    ACTIVE_STATUSES,
    Capture,
    DownloadTask,
    FINISHED_STATUSES,
    make_capture,
)
import requests

from .utils import (
    atomic_write_json,
    file_size,
    is_http_url,
    is_manifest_url,
    is_media_url,
    is_youtube_url,
    load_json,
    normalize_url,
    now,
)


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
from .ytdlp import (
    DownloadCanceled as YtCanceled,
    DownloadError as YtError,
    DownloadPaused as YtPaused,
    YtDlpDownloader,
    youtube_extra_args,
    ytdlp_version,
)

log = logging.getLogger("videoavci.manager")


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
        self._probe_pending: set[str] = set()
        self._load()
        for _capture in list(self.captures):
            if _capture.media_kind in ("", "video") or (_capture.media_kind == "manifest" and not _capture.media_info):
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
                seen.add(capture.url)
                # Eski etiketleri yeniden analiz et.
                if capture.media_kind == "manifest":
                    capture.media_info = ""
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
            return {
                "tasks": tasks,
                "captures": captures,
                "active": active,
                "queued": queued,
                "completed": completed,
                "errors": errors,
                "speed": speed,
                "capture_count": len(captures),
            }

    def stats(self) -> dict[str, Any]:
        with self.lock:
            return {
                "active": sum(1 for task in self.tasks.values() if task.status in ACTIVE_STATUSES),
                "queued": sum(1 for task in self.tasks.values() if task.status == "queued"),
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

    def add_capture(self, payload: dict[str, Any]) -> tuple[Capture, bool]:
        capture = make_capture(payload)
        capture.url = normalize_url(capture.url)
        if not is_http_url(capture.url):
            raise ValueError("Geçerli bir medya bağlantısı yok.")
        if capture.page_url and not is_http_url(capture.page_url):
            capture.page_url = ""
        with self.lock:
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
        import re

        match = re.search(r"(2160|1440|1080|720|480|360|240)", url or "")
        if match:
            return f"{match.group(1)}p"
        return ""

    def _fetch_first_segment(self, url: str, referer: str = "") -> bytes | None:
        headers = {
            "Referer": referer or url,
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
        s = requests.Session()
        current = url
        visited: set[str] = set()
        try:
            while True:
                if current in visited:
                    return None
                visited.add(current)
                response = s.get(current, headers=headers, timeout=(10, 20), allow_redirects=True)
                if response.status_code != 200:
                    return None
                text = response.text
                if not text.lstrip().startswith("#EXTM3U"):
                    return response.content
                segments = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
                if not segments:
                    return None
                current = urljoin(current, segments[0])
        except Exception:
            return None

    def _schedule_probe(self, capture_id: str) -> None:
        with self.lock:
            if capture_id in self._probe_pending:
                return
            capture = next((item for item in self.captures if item.id == capture_id), None)
            if capture is None:
                return
            if capture.media_kind not in ("", "video", "manifest"):
                return
            if capture.media_kind == "manifest" and capture.media_info:
                return
            self._probe_pending.add(capture_id)
        thread = threading.Thread(
            target=self._probe_capture,
            args=(capture_id,),
            name=f"videoavci-probe-{capture_id}",
            daemon=True,
        )
        thread.start()

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

            # Önce segment indirip ffprobe ile analiz et (HLS/DASH için daha güvenilir).
            segment_data = self._fetch_first_segment(url, referer)
            if segment_data:
                fd, tmp_path = tempfile.mkstemp(prefix="va_probe_", suffix=".bin")
                try:
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(segment_data)
                    cmd = ["ffprobe", "-v", "error", "-show_streams", "-of", "json", tmp_path]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                    if result.returncode == 0 and result.stdout.strip():
                        info = json.loads(result.stdout)
                        streams = info.get("streams") or []
                        has_video = any(str(s.get("codec_type")) == "video" for s in streams)
                        has_audio = any(str(s.get("codec_type")) == "audio" for s in streams)
                        height = 0
                        for s in streams:
                            if str(s.get("codec_type")) == "video":
                                try:
                                    height = int(s.get("height") or 0)
                                except (TypeError, ValueError):
                                    height = 0
                                break
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
                        if height:
                            media_info = f"{height}p"
                        elif has_audio and not has_video:
                            media_info = "ses"
                        if original_kind in {"hls", "dash"}:
                            if has_audio:
                                media_info = (media_info + " · sesli").strip() if media_info else "sesli"
                            else:
                                media_info = (media_info + " · sessiz").strip() if media_info else "sessiz"
                        with self.lock:
                            capture = next((item for item in self.captures if item.id == capture_id), None)
                            if capture is not None:
                                changed = False
                                if new_kind and capture.media_kind != new_kind:
                                    capture.media_kind = new_kind
                                    changed = True
                                if media_info and capture.media_info != media_info:
                                    capture.media_info = media_info
                                    changed = True
                                if changed:
                                    self._save_locked()
                        return
                except Exception:
                    pass
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
            if not url:
                return
            cmd = [
                sys.executable,
                "-m",
                "yt_dlp",
                "--ignore-config",
                "--no-playlist",
                "--no-warnings",
                "--socket-timeout",
                "20",
                "--dump-single-json",
            ]
            cmd += youtube_extra_args(url)
            if referer:
                cmd += ["--referer", referer]
            cmd += [url]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=45,
            )
            if result.returncode != 0 or not result.stdout.strip():
                # yt-dlp başarısız olursa URL'den çözünürlük çıkarmayı dene.
                media_info = self._resolution_from_url(url)
                with self.lock:
                    capture = next((item for item in self.captures if item.id == capture_id), None)
                    if capture is not None and media_info and capture.media_info != media_info:
                        capture.media_info = media_info
                        self._save_locked()
                return
            try:
                info = json.loads(result.stdout)
            except (ValueError, TypeError):
                return

            formats = info.get("formats") or [info]
            has_video = any(str(f.get("video_ext") or "").lower() not in ("", "none", None) for f in formats) or str(info.get("video_ext") or "").lower() not in ("", "none", None)
            has_audio = any(str(f.get("audio_ext") or "").lower() not in ("", "none", None) for f in formats) or str(info.get("audio_ext") or "").lower() not in ("", "none", None)

            heights = sorted(
                {int(f.get("height")) for f in formats if isinstance(f.get("height"), int) and f.get("height")},
                reverse=True,
            )
            if has_audio and not has_video:
                media_info = "sesli"
            elif heights:
                if len(heights) > 1:
                    media_info = f"çoklu ({heights[0]}p)"
                else:
                    media_info = f"{heights[0]}p"
            else:
                media_info = self._resolution_from_url(url)

            if original_kind in {"hls", "dash"}:
                if has_audio and has_video:
                    media_info = (media_info + " · sesli").strip() if media_info and media_info != "sesli" else "sesli"
                elif has_audio and not has_video:
                    media_info = "sesli"
                elif has_video and not has_audio:
                    media_info = (media_info + " · sessiz").strip() if media_info else "sessiz"
                else:
                    media_info = media_info or "sessiz"

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
                if changed:
                    self._save_locked()
        except Exception:
            log.debug("Medya sondası başarısız: %s", capture_id, exc_info=True)
        finally:
            with self.lock:
                self._probe_pending.discard(capture_id)

    def download_capture(self, capture_id: str) -> tuple[DownloadTask, bool]:
        with self.lock:
            capture = next((item for item in self.captures if item.id == capture_id), None)
            if capture is None:
                raise ValueError("Yakalanan video bulunamadı.")
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

    # ------------------------------------------------------------------ scheduler
    def _scheduler_loop(self) -> None:
        while not self._stop.is_set():
            try:
                started = False
                with self.lock:
                    if not self._shutting_down:
                        max_concurrent = int(self.config.get("max_concurrent", 2) or 2)
                        if len(self.active_ids) < max_concurrent:
                            for task in self.tasks.values():
                                if task.status == "queued" and task.id not in self.active_ids:
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

        except (DirectError, YtError) as exc:
            with self.lock:
                task = self.tasks.get(task_id)
                if task is not None:
                    task.status = "error"
                    task.error = str(exc)
                    task.speed = 0.0
                    task.eta = 0
                    task.detail = t("task.status.error")
                    task.updated_at = now()
                self._save_locked()
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
