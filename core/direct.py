"""Çok parçalı, duraklatılabilir doğrudan dosya indirici."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

import requests

from .config import PARTS_DIR
from .i18n import t
from .utils import (
    USER_AGENT,
    filename_from_url,
    human_size,
    is_media_url,
    load_json,
    sanitize_filename,
    unique_path,
)

ProgressCallback = Callable[[int, int, float, float, int], None]
StatusCallback = Callable[[str, str], None]
TitleCallback = Callable[[str, str, int], None]
LogCallback = Callable[[str], None]


class DownloadPaused(Exception):
    pass


class DownloadCanceled(Exception):
    pass


class DownloadError(Exception):
    pass


class NotDirectError(DownloadError):
    """URL bir web sayfası; yt-dlp ile denenmeli."""


def plan_segments(total: int, count: int) -> list[dict]:
    """Dosya boyutunu istenen sayıda bitişik bayt aralığına böler."""
    total = max(0, int(total or 0))
    count = max(1, int(count or 1))
    if total <= 0:
        return [{"start": 0, "end": -1}]
    # Dosyadan fazla parça istemek boş aralıklar üretir; sayıyı sınırla.
    count = min(count, total)
    segments = []
    for index in range(count):
        start = total * index // count
        end = total * (index + 1) // count - 1
        segments.append({"start": start, "end": end})
    return segments


class RateLimiter:
    def __init__(self, kbps: int):
        self.rate = max(0, int(kbps)) * 1024
        self.lock = threading.Lock()
        self.next_time = time.monotonic()

    def consume(self, amount: int, should_stop: Callable[[], bool]) -> None:
        if not self.rate or amount <= 0:
            return
        with self.lock:
            now = time.monotonic()
            self.next_time = max(self.next_time, now) + amount / self.rate
            wait = self.next_time - now
        end = time.monotonic() + wait
        while True:
            if should_stop():
                return
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))


class DirectDownloader:
    """Sunucunun desteklediği ölçüde Range istekleriyle parçalı indirir."""

    def __init__(
        self,
        task,
        config,
        progress_cb: ProgressCallback,
        status_cb: StatusCallback,
        title_cb: TitleCallback,
        log_cb: LogCallback | None = None,
    ):
        self.task = task
        self.config = config
        self.progress_cb = progress_cb
        self.status_cb = status_cb
        self.title_cb = title_cb
        self.log_cb = log_cb or (lambda _line: None)

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.pause_event = threading.Event()
        self.cancel_event = threading.Event()
        self.range_failed = threading.Event()

        self.part_dir = PARTS_DIR / task.id
        self.meta_path = self.part_dir / "meta.json"
        self.meta: dict = {}

        self.final_url = task.url
        self.total = 0
        self.ranges_supported = False
        self.filename = ""
        self.etag = ""
        self.last_modified = ""
        self.segments: list[dict] = []

        self._lock = threading.Lock()
        self._downloaded = 0
        self._speed = 0.0
        self._speed_bytes = 0
        self._speed_time = time.monotonic()
        self._last_emit = 0.0
        self._error: str | None = None
        self._error_lock = threading.Lock()
        self.limiter = RateLimiter(int(config.get("speed_limit_kbps", 0) or 0))

    # ------------------------------------------------------------------ events
    def pause(self) -> None:
        self.pause_event.set()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.pause_event.set()

    def should_stop(self) -> bool:
        return self.pause_event.is_set() or self.cancel_event.is_set()

    def _check_stop(self) -> None:
        if self.cancel_event.is_set():
            raise DownloadCanceled()
        if self.pause_event.is_set():
            raise DownloadPaused()

    # ------------------------------------------------------------------- probe
    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "tr,en;q=0.9",
            # Sıkıştırılmış yanıtlar Content-Length ile yazılan bayt sayısını
            # uyumsuzlaştırabilir; Range hesapları için sıkıştırmayı kapat.
            "Accept-Encoding": "identity",
        }
        if self.task.referer:
            headers["Referer"] = self.task.referer
        return headers

    def probe(self) -> None:
        self._check_stop()
        headers = self._headers()
        response = None
        try:
            try:
                response = self.session.head(
                    self.task.url,
                    headers=headers,
                    allow_redirects=True,
                    timeout=(20, 45),
                )
                status = response.status_code
                content_type = (response.headers.get("Content-Type") or "").lower()
                content_length = response.headers.get("Content-Length")
                accept_ranges = (response.headers.get("Accept-Ranges") or "").lower()
                # HEAD bazen boş/yanıltıcı olur; boyut yoksa veya HTML dönerse GET ile doğrula.
                need_probe = (
                    status >= 400
                    or not content_length
                    or "text/html" in content_type
                    or status in (403, 405, 501)
                )
                if need_probe:
                    response.close()
                    response = self.session.get(
                        self.task.url,
                        headers={**headers, "Range": "bytes=0-0"},
                        allow_redirects=True,
                        stream=True,
                        timeout=(20, 45),
                    )
                    status = response.status_code
                    content_type = (response.headers.get("Content-Type") or "").lower()
                    content_length = response.headers.get("Content-Length")
                    accept_ranges = (response.headers.get("Accept-Ranges") or "").lower()
            except requests.RequestException:
                response = self.session.get(
                    self.task.url,
                    headers={**headers, "Range": "bytes=0-0"},
                    allow_redirects=True,
                    stream=True,
                    timeout=(20, 45),
                )
                status = response.status_code
                content_type = (response.headers.get("Content-Type") or "").lower()
                content_length = response.headers.get("Content-Length")
                accept_ranges = (response.headers.get("Accept-Ranges") or "").lower()

            if status in (401, 403):
                raise DownloadError(
                    f"Sunucu erişimi reddetti (HTTP {status}). Site oturum/çerez istiyor olabilir."
                )
            if status == 404:
                raise DownloadError("Video bulunamadı (HTTP 404). Bağlantı eski olabilir.")
            if status >= 400 and status != 416:
                raise DownloadError(f"Sunucu HTTP {status} döndürdü.")

            content_type_main = content_type.split(";")[0].strip()
            if "text/html" in content_type_main or "application/xhtml" in content_type_main:
                raise NotDirectError("Bağlantı bir web sayfası; yt-dlp ile denenecek.")

            content_range = response.headers.get("Content-Range") or ""
            range_total = 0
            match = re.search(r"/\s*(\d+)\s*$", content_range)
            if match:
                range_total = int(match.group(1))
            total = range_total
            if not total and content_length and status != 206:
                try:
                    total = int(content_length)
                except ValueError:
                    total = 0
            if status == 206:
                self.ranges_supported = True
            elif "bytes" in accept_ranges:
                self.ranges_supported = True
            elif total and total > 0:
                # HEAD 200 + Accept-Ranges yok; Range desteklemediğini varsay.
                self.ranges_supported = False

            self.final_url = response.url or self.task.url
            self.total = max(0, total)
            self.etag = str(response.headers.get("ETag") or "").strip()
            self.last_modified = str(response.headers.get("Last-Modified") or "").strip()
            disposition = response.headers.get("Content-Disposition")
            filename = filename_from_url(
                self.final_url,
                disposition,
                content_type_main,
                fallback_title=self.task.title or "video",
            )
            # "video", "watch", "index" gibi genel adlarda sayfa başlığını kullan.
            generic = {"video", "watch", "play", "index", "master", "manifest", "stream", "media", "download"}
            base = os.path.splitext(filename)[0].lower()
            if self.task.title and base in generic:
                ext = os.path.splitext(filename)[1] or ".mp4"
                filename = sanitize_filename(self.task.title + ext)
            self.filename = filename
            self.title_cb(self.task.title or os.path.splitext(filename)[0], filename, self.total)
        except requests.RequestException as exc:
            raise DownloadError(f"Bağlantı kurulamadı: {exc}") from exc
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

        self._check_stop()
        self.log_cb(
            f"Probe: {self.final_url} | {self.total} bayt | range={self.ranges_supported} | {self.filename}"
        )

    # -------------------------------------------------------------- meta/parts
    def _load_or_create_meta(self) -> None:
        existing = load_json(self.meta_path, None)
        reset = True
        if isinstance(existing, dict):
            same_url = existing.get("url") == self.task.url
            same_total = not self.total or int(existing.get("total") or 0) == self.total
            saved_filename = str(existing.get("filename") or "")
            same_filename = bool(saved_filename) and (
                not self.filename or saved_filename == self.filename
            )
            # Sunucu içeriği değiştiyse yarım parçaları birleştirmeyelim.
            saved_etag = str(existing.get("etag") or "")
            saved_modified = str(existing.get("last_modified") or "")
            same_content = (
                (not self.etag or not saved_etag or self.etag == saved_etag)
                and (
                    not self.last_modified
                    or not saved_modified
                    or self.last_modified == saved_modified
                )
            )
            if same_url and same_total and same_filename and same_content:
                segments = existing.get("segments") or []
                if isinstance(segments, list) and segments:
                    # Sınırlar mevcut toplamla uyuşuyor mu?
                    valid = True
                    for index, segment in enumerate(segments):
                        try:
                            if int(segment["start"]) < 0 or int(segment["end"]) < int(segment["start"]):
                                valid = False
                                break
                            part = self.part_dir / f"part_{index}"
                            if part.exists() and part.stat().st_size > int(segment["end"]) - int(segment["start"]) + 1:
                                valid = False
                                break
                        except (KeyError, TypeError, ValueError):
                            valid = False
                            break
                    if valid:
                        self.meta = existing
                        # Yeni yanıttaki doğrulama bilgilerini meta'ya işle.
                        if self.etag:
                            existing["etag"] = self.etag
                        if self.last_modified:
                            existing["last_modified"] = self.last_modified
                        self.segments = segments
                        self.filename = str(existing.get("filename") or self.filename)
                        self.total = int(existing.get("total") or self.total)
                        self.final_url = str(existing.get("final_url") or self.final_url)
                        reset = False

        if reset:
            if self.part_dir.exists():
                shutil.rmtree(self.part_dir, ignore_errors=True)
            self.part_dir.mkdir(parents=True, exist_ok=True)
            if self.ranges_supported and self.total >= 1024 * 1024:
                count = int(self.config.get("connections", 4) or 4)
                count = max(1, min(count, max(1, self.total // (2 * 1024 * 1024))))
                count = min(count, 8)
            else:
                count = 1
            self.segments = plan_segments(self.total, count)
            self.meta = {
                "url": self.task.url,
                "final_url": self.final_url,
                "total": self.total,
                "filename": self.filename,
                "etag": self.etag,
                "last_modified": self.last_modified,
                "ranges_supported": self.ranges_supported,
                "segments": self.segments,
                "created_at": time.time(),
            }
            self._write_meta()

        self._write_meta()
        self._downloaded = sum(self._part_size(index) for index in range(len(self.segments)))
        self._speed_bytes = self._downloaded

    def _write_meta(self) -> None:
        try:
            self.part_dir.mkdir(parents=True, exist_ok=True)
            temp = self.meta_path.with_suffix(".json.tmp")
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(self.meta, handle, ensure_ascii=False, indent=2)
            os.replace(temp, self.meta_path)
        except OSError as exc:
            self.log_cb(f"Meta yazılamadı: {exc}")

    def _part_path(self, index: int) -> Path:
        return self.part_dir / f"part_{index}"

    def _part_size(self, index: int) -> int:
        try:
            return self._part_path(index).stat().st_size
        except OSError:
            return 0

    # ---------------------------------------------------------------- progress
    def _add_bytes(self, amount: int) -> None:
        with self._lock:
            self._downloaded += amount

    def _adjust_bytes(self, amount: int) -> None:
        with self._lock:
            self._downloaded = max(0, self._downloaded + amount)

    def _emit_progress(self, force: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            downloaded = self._downloaded
        if not force and now - self._last_emit < 0.25:
            return
        elapsed = now - self._speed_time
        if elapsed >= 0.35:
            instant = max(0.0, (downloaded - self._speed_bytes) / elapsed)
            if self._speed <= 0:
                self._speed = instant
            else:
                self._speed = self._speed * 0.65 + instant * 0.35
            self._speed_bytes = downloaded
            self._speed_time = now
        total = self.total
        percent = (downloaded / total * 100.0) if total > 0 else 0.0
        eta = int((total - downloaded) / self._speed) if total > 0 and self._speed > 0 else 0
        self._last_emit = now
        try:
            self.progress_cb(downloaded, total, percent, self._speed, eta)
        except Exception:
            pass

    def _set_error(self, message: str) -> None:
        with self._error_lock:
            if not self._error:
                self._error = message

    def _get_error(self) -> str | None:
        with self._error_lock:
            return self._error

    # ----------------------------------------------------------------- workers
    def _worker(self, index: int, segment: dict) -> None:
        start = int(segment["start"])
        end = int(segment["end"])
        expected = end - start + 1 if end >= start else 0
        part = self._part_path(index)
        part.parent.mkdir(parents=True, exist_ok=True)
        existing = self._part_size(index)
        if expected and existing > expected:
            try:
                part.unlink()
            except OSError:
                pass
            existing = 0
        if expected and existing >= expected:
            return

        attempt = 0
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        try:
            while not self.should_stop():
                try:
                    request_start = start + existing
                    if expected and request_start > end:
                        return
                    headers = self._headers()
                    if self.ranges_supported or existing:
                        headers["Range"] = f"bytes={request_start}-{end if end >= 0 else ''}"
                    with session.get(
                        self.final_url,
                        headers=headers,
                        stream=True,
                        allow_redirects=True,
                        timeout=(20, 90),
                    ) as response:
                        if self.should_stop():
                            return
                        if response.status_code == 416:
                            if expected and existing >= expected:
                                return
                            raise DownloadError("Sunucu istenen bayt aralığını reddetti (416).")
                        if response.status_code not in (200, 206):
                            raise DownloadError(f"Parça isteği HTTP {response.status_code} döndürdü.")
                        if response.status_code == 200:
                            if len(self.segments) > 1 or existing > 0:
                                # Sunucu Range'i yok saydı; tek akışa düş.
                                self.range_failed.set()
                                return
                            mode = "wb"
                        else:
                            content_range = response.headers.get("Content-Range") or ""
                            match = re.match(r"bytes\s+(\d+)-", content_range)
                            if match and int(match.group(1)) != request_start:
                                self.range_failed.set()
                                return
                            mode = "ab" if existing > 0 else "wb"
                        if mode == "wb" and existing:
                            self._adjust_bytes(-existing)
                            existing = 0
                        with part.open(mode) as handle:
                            for chunk in response.iter_content(chunk_size=128 * 1024):
                                if self.should_stop():
                                    return
                                if not chunk:
                                    continue
                                handle.write(chunk)
                                self._add_bytes(len(chunk))
                                self.limiter.consume(len(chunk), self.should_stop)
                                self._emit_progress()
                                if self.range_failed.is_set():
                                    return
                    size = self._part_size(index)
                    if expected and size >= expected:
                        return
                    if size == existing:
                        # Sunucu ilerleme vermeden bağlantıyı kapattı.
                        raise DownloadError("İndirme beklenmedik şekilde durdu.")
                    existing = size
                    attempt = 0
                except (requests.RequestException, DownloadError, OSError) as exc:
                    if self.should_stop():
                        return
                    if self.range_failed.is_set():
                        return
                    attempt += 1
                    if attempt > 3:
                        self._set_error(f"Parça {index + 1}: {exc}")
                        return
                    self.log_cb(f"Parça {index + 1} yeniden deneniyor ({attempt}/3): {exc}")
                    end_time = time.monotonic() + min(8, 2 ** attempt)
                    while time.monotonic() < end_time:
                        if self.should_stop():
                            return
                        time.sleep(0.1)
                    existing = self._part_size(index)
        finally:
            session.close()

    def _run_segmented(self) -> None:
        self.status_cb(
            "downloading",
            t("task.detail.downloading_connections", count=len(self.segments)),
        )
        threads = []
        for index, segment in enumerate(self.segments):
            thread = threading.Thread(
                target=self._worker,
                args=(index, segment),
                name=f"videoavci-part-{index}",
                daemon=True,
            )
            thread.start()
            threads.append(thread)
        while any(thread.is_alive() for thread in threads):
            if self.should_stop():
                for thread in threads:
                    thread.join(timeout=1)
                self._write_meta()
                self._check_stop()
                return
            for thread in threads:
                thread.join(timeout=0.15)
        self._write_meta()
        self._check_stop()
        if self.range_failed.is_set():
            # Range desteklenmiyormuş; baştan tek akış indir.
            self.log_cb("Sunucu çok parçalı indirmeyi desteklemiyor; tek bağlantıya geçiliyor.")
            shutil.rmtree(self.part_dir, ignore_errors=True)
            self.part_dir.mkdir(parents=True, exist_ok=True)
            self.ranges_supported = False
            self.segments = [{"start": 0, "end": self.total - 1 if self.total else -1}]
            self._downloaded = 0
            self._speed = 0.0
            self._speed_bytes = 0
            self._speed_time = time.monotonic()
            self.meta.update(
                {
                    "ranges_supported": False,
                    "segments": self.segments,
                    "total": self.total,
                }
            )
            self._write_meta()
            self._run_single()
            return
        error = self._get_error()
        if error:
            raise DownloadError(error)
        # Tüm parçaların boyutlarını doğrula.
        for index, segment in enumerate(self.segments):
            expected = int(segment["end"]) - int(segment["start"]) + 1
            size = self._part_size(index)
            if expected > 0 and size < expected:
                raise DownloadError(
                    f"Parça {index + 1} eksik kaldı ({human_size(size)} / {human_size(expected)})."
                )

    def _run_single(self) -> None:
        self.status_cb("downloading", t("task.status.downloading"))
        part = self._part_path(0)
        part.parent.mkdir(parents=True, exist_ok=True)
        existing = self._part_size(0)
        if self.total and existing > self.total:
            try:
                part.unlink()
            except OSError:
                pass
            existing = 0
            self._downloaded = 0
        if self.total and existing >= self.total:
            return
        attempt = 0
        while not self.should_stop():
            try:
                headers = self._headers()
                if existing and self.ranges_supported:
                    headers["Range"] = f"bytes={existing}-"
                with self.session.get(
                    self.final_url,
                    headers=headers,
                    stream=True,
                    allow_redirects=True,
                    timeout=(20, 90),
                ) as response:
                    if self.should_stop():
                        return
                    if response.status_code == 416:
                        if self.total and existing >= self.total:
                            return
                        raise DownloadError("Sunucu istenen bayt aralığını reddetti (416).")
                    if response.status_code not in (200, 206):
                        raise DownloadError(f"Sunucu HTTP {response.status_code} döndürdü.")
                    if response.status_code == 200:
                        if existing:
                            self._adjust_bytes(-existing)
                            existing = 0
                        mode = "wb"
                        content_length = response.headers.get("Content-Length")
                        if content_length and not self.total:
                            try:
                                self.total = int(content_length)
                                self.meta["total"] = self.total
                                self._write_meta()
                            except ValueError:
                                pass
                    else:
                        content_range = response.headers.get("Content-Range") or ""
                        match = re.search(r"/\s*(\d+)\s*$", content_range)
                        if match and not self.total:
                            self.total = int(match.group(1))
                            self.meta["total"] = self.total
                            self._write_meta()
                        start_match = re.match(r"bytes\s+(\d+)-", content_range)
                        if start_match and int(start_match.group(1)) != existing:
                            # Sunucu beklenen konumdan başlamadı; dosyayı baştan yaz.
                            if existing:
                                self._adjust_bytes(-existing)
                            existing = 0
                            mode = "wb"
                        else:
                            mode = "ab" if existing > 0 else "wb"
                    with part.open(mode) as handle:
                        for chunk in response.iter_content(chunk_size=128 * 1024):
                            if self.should_stop():
                                return
                            if not chunk:
                                continue
                            handle.write(chunk)
                            self._add_bytes(len(chunk))
                            self.limiter.consume(len(chunk), self.should_stop)
                            self._emit_progress()
                size = self._part_size(0)
                if not self.total:
                    # Boyut bilinmeyen akışta bağlantının düzgün kapanması tamamlanma sayılır.
                    return
                if size >= self.total:
                    return
                if size == existing:
                    raise DownloadError("İndirme beklenmedik şekilde durdu.")
                existing = size
                attempt = 0
            except (requests.RequestException, DownloadError, OSError) as exc:
                if self.should_stop():
                    return
                attempt += 1
                if attempt > 3:
                    raise DownloadError(str(exc)) from exc
                self.log_cb(f"Yeniden deneniyor ({attempt}/3): {exc}")
                end_time = time.monotonic() + min(8, 2 ** attempt)
                while time.monotonic() < end_time:
                    if self.should_stop():
                        return
                    time.sleep(0.1)
                existing = self._part_size(0)

    # ------------------------------------------------------------------- merge
    def _merge_parts(self) -> str:
        self.status_cb("processing", t("task.detail.merging"))
        output_dir = Path(self.config.download_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        final_path = unique_path(output_dir, self.filename or f"video-{self.task.id}.mp4")
        if len(self.segments) == 1:
            part = self._part_path(0)
            try:
                os.replace(part, final_path)
            except OSError:
                shutil.move(str(part), str(final_path))
        else:
            temp_path = final_path.with_name(final_path.name + ".videoavci.tmp")
            try:
                with temp_path.open("wb") as out_handle:
                    for index in range(len(self.segments)):
                        with self._part_path(index).open("rb") as in_handle:
                            shutil.copyfileobj(in_handle, out_handle, length=1024 * 1024)
                        if self.should_stop():
                            raise DownloadCanceled()
                os.replace(temp_path, final_path)
            except Exception:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
                raise
        shutil.rmtree(self.part_dir, ignore_errors=True)
        return str(final_path)

    # --------------------------------------------------------------------- run
    def run(self) -> str:
        self.status_cb("analyzing", t("task.detail.probing"))
        self.probe()
        self._check_stop()
        self._load_or_create_meta()
        self._emit_progress(force=True)
        if self.total and self._downloaded >= self.total:
            self._check_stop()
            return self._merge_parts()
        if len(self.segments) > 1:
            self._run_segmented()
        else:
            self._run_single()
        self._check_stop()
        if self.total:
            downloaded = sum(self._part_size(i) for i in range(len(self.segments)))
            if downloaded < self.total:
                raise DownloadError(
                    f"İndirme tamamlanmadı ({human_size(downloaded)} / {human_size(self.total)})."
                )
        return self._merge_parts()

    def cleanup(self) -> None:
        shutil.rmtree(self.part_dir, ignore_errors=True)
