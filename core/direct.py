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
from .errors import (
    AuthenticationError,
    DiskSpaceError,
    DownloadError,
    NotDirectError,
    PermanentDownloadError,
    ResourceNotFoundError,
    TransientDownloadError,
    error_from_http,
    error_from_os,
    error_from_request,
)
from .i18n import t
from .utils import (
    USER_AGENT,
    filename_from_url,
    free_space,
    human_size,
    is_transient_error,
    load_json,
    parse_retry_after,
    sanitize_filename,
    unique_path,
)

ProgressCallback = Callable[[int, int, float, float, int], None]
StatusCallback = Callable[[str, str], None]
TitleCallback = Callable[[str, str, int], None]
LogCallback = Callable[[str], None]

# Sunucu tarafındaki geçici hatalar; otomatik geri çekilme ile yeniden denenir.
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
MAX_PART_RETRIES = 4
SPACE_MARGIN = 64 * 1024 * 1024


class DownloadPaused(Exception):
    pass


class DownloadCanceled(Exception):
    pass


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
        self._error: DownloadError | None = None
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

    def _request_probe(self, headers: dict[str, str]):
        """HEAD ile hızlıca dener, gerekiyorsa Range destekli GET'e düşer."""
        try:
            head = self.session.head(
                self.task.url,
                headers=headers,
                allow_redirects=True,
                timeout=(20, 45),
            )
        except requests.RequestException:
            head = None

        if head is not None:
            status = head.status_code
            content_type = (head.headers.get("Content-Type") or "").lower()
            content_length = head.headers.get("Content-Length")
            accept_ranges = (head.headers.get("Accept-Ranges") or "").lower()
            try:
                numeric_length = int(content_length or 0)
            except (TypeError, ValueError):
                numeric_length = 0
            # HEAD bazen boş/yanıltıcı olur. Boyut yoksa, HTML dönerse veya
            # Range desteği doğrulanamadıysa küçük bir GET ile kontrol et.
            needs_get = (
                status >= 400
                or not content_length
                or "text/html" in content_type
                or status in (403, 405, 501)
                or (
                    status == 200
                    and "bytes" not in accept_ranges
                    and numeric_length >= 1024 * 1024
                )
            )
            if not needs_get:
                return head
            try:
                head.close()
            except Exception:
                pass

        # Range: bytes=0-0 yanıtı hem gerçek boyutu hem de çok parçalı desteği
        # gösterir; sunucu 200 dönerse tek akışa düşülür.
        return self.session.get(
            self.task.url,
            headers={**headers, "Range": "bytes=0-0"},
            allow_redirects=True,
            stream=True,
            timeout=(20, 45),
        )

    def _wait_before_retry(self, seconds: float, attempt: int) -> None:
        """Duraklat/iptal sinyallerine saygılı geri çekilme beklemesi."""
        end_time = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end_time:
            if self.should_stop():
                return
            time.sleep(min(0.2, max(0.0, end_time - time.monotonic())))

    @staticmethod
    def _as_download_error(exc: BaseException, prefix: str = "") -> DownloadError:
        """Alt katmandan gelen hatayı tür bilgisini koruyarak sarmalar."""
        if isinstance(exc, DownloadError):
            message = f"{prefix}: {exc}" if prefix else str(exc)
            return DownloadError(
                message,
                kind=exc.kind,
                code=exc.code,
                retry_after=getattr(exc, "retry_after", 0.0),
            )
        if isinstance(exc, OSError):
            return error_from_os(exc, prefix)
        if isinstance(exc, requests.RequestException):
            return error_from_request(exc, prefix)
        message = f"{prefix}: {exc}" if prefix else str(exc)
        return DownloadError(message)

    def probe(self) -> None:
        self._check_stop()
        headers = self._headers()
        last_error: DownloadError | None = None
        for attempt in range(3):
            response = None
            try:
                response = self._request_probe(headers)
                status = response.status_code
                content_type = (response.headers.get("Content-Type") or "").lower()
                content_length = response.headers.get("Content-Length")
                accept_ranges = (response.headers.get("Accept-Ranges") or "").lower()

                if status in RETRYABLE_STATUS or 500 <= status < 600:
                    retry_after = min(
                        120,
                        parse_retry_after(
                            response.headers.get("Retry-After"),
                            default=min(30, 2 ** attempt),
                        ),
                    )
                    message = (
                        f"Sunucu geçici olarak yanıt vermiyor (HTTP {status})."
                        if status in RETRYABLE_STATUS
                        else f"Sunucu HTTP {status} döndürdü."
                    )
                    raise error_from_http(status, message, retry_after=retry_after)

                if status in (401, 403):
                    raise AuthenticationError(
                        f"Sunucu erişimi reddetti (HTTP {status}). Site oturum/çerez istiyor olabilir."
                    )
                if status == 404:
                    raise ResourceNotFoundError("Video bulunamadı (HTTP 404). Bağlantı eski olabilir.")
                if status >= 400 and status != 416:
                    raise error_from_http(status, f"Sunucu HTTP {status} döndürdü.")

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
                generic = {
                    "video", "watch", "play", "index", "master", "manifest",
                    "stream", "media", "download",
                }
                base = os.path.splitext(filename)[0].lower()
                if self.task.title and base in generic:
                    ext = os.path.splitext(filename)[1] or ".mp4"
                    filename = sanitize_filename(self.task.title + ext)
                self.filename = filename
                self.title_cb(self.task.title or os.path.splitext(filename)[0], filename, self.total)
                self.log_cb(
                    f"Probe: {self.final_url} | {self.total} bayt | "
                    f"range={self.ranges_supported} | {self.filename}"
                )
                return
            except NotDirectError:
                raise
            except DownloadError as exc:
                last_error = exc
                if attempt < 2 and is_transient_error(exc):
                    wait = min(120, max(exc.retry_after, min(30, 2 ** attempt)))
                    self._wait_before_retry(wait, attempt)
                    continue
                raise
            except requests.RequestException as exc:
                last_error = error_from_request(exc, "Bağlantı kurulamadı")
                if attempt < 2 and is_transient_error(last_error):
                    self.log_cb(
                        f"Bağlantı yeniden denenecek ({attempt + 1}/3): {last_error}"
                    )
                    self._wait_before_retry(min(30, 2 ** attempt), attempt)
                    continue
                raise last_error from exc
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
        if last_error is not None:
            raise last_error
        raise DownloadError("Bağlantı incelenemedi.", code="probe_failed")

    def _same_device(self, first: Path, second: Path) -> bool:
        try:
            return os.stat(first).st_dev == os.stat(second).st_dev
        except OSError:
            return False

    def _output_dir(self) -> Path:
        output_dir = Path(self.config.download_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _ensure_space(self, required: int, phase: str) -> None:
        """Disk doluysa indirmeyi yarım bırakmadan önce anlaşılır hata ver."""
        required = max(0, int(required or 0))
        if required <= 0:
            return
        output_dir = self._output_dir()
        available = free_space(output_dir)
        if available <= 0:
            return
        if required > available:
            raise DiskSpaceError(
                f"Yeterli disk alanı yok ({phase}): {human_size(required)} gerekli, "
                f"{human_size(available)} boş. Klasör: {output_dir}"
            )

    def _check_initial_space(self) -> None:
        if not self.total:
            return
        remaining = max(0, self.total - self._downloaded)
        same_device = self._same_device(self.part_dir, self._output_dir())
        if len(self.segments) > 1:
            # Parçalar tamamlandıktan sonra birleştirme sırasında final dosya
            # için bir kat daha yer gerekir (parçalar silinmeden yazılır).
            required = (remaining + self.total if same_device else self.total) + SPACE_MARGIN
        elif same_device:
            required = remaining + SPACE_MARGIN
        else:
            required = self.total + SPACE_MARGIN
        self._ensure_space(required, "indirme")

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

    def _set_error(self, error: DownloadError) -> None:
        with self._error_lock:
            if not self._error:
                self._error = error

    def _get_error(self) -> DownloadError | None:
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
        retry_after = 0.0
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        try:
            while not self.should_stop():
                retry_after = 0.0
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
                        if response.status_code in RETRYABLE_STATUS:
                            retry_after = parse_retry_after(
                                response.headers.get("Retry-After"),
                                default=min(30, 2 ** attempt),
                            )
                            raise error_from_http(
                                response.status_code,
                                f"Sunucu geçici hata döndürdü (HTTP {response.status_code}).",
                                retry_after=retry_after,
                            )
                        if response.status_code == 416:
                            if expected and existing >= expected:
                                return
                            raise PermanentDownloadError(
                                "Sunucu istenen bayt aralığını reddetti (416).",
                                code="http_416",
                            )
                        if response.status_code not in (200, 206):
                            raise error_from_http(
                                response.status_code,
                                f"Parça isteği HTTP {response.status_code} döndürdü.",
                            )
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
                        raise TransientDownloadError(
                            "İndirme beklenmedik şekilde durdu.",
                            code="stalled",
                        )
                    existing = size
                    attempt = 0
                except (requests.RequestException, DownloadError, OSError) as exc:
                    if self.should_stop():
                        return
                    if self.range_failed.is_set():
                        return
                    error = self._as_download_error(exc, f"Parça {index + 1}")
                    if not is_transient_error(error):
                        # 403/404, SSL ve disk hatalarında boşuna geri çekilme.
                        self._set_error(error)
                        return
                    attempt += 1
                    if attempt > MAX_PART_RETRIES:
                        self._set_error(error)
                        return
                    wait = min(
                        60.0,
                        max(
                            float(retry_after),
                            float(getattr(error, "retry_after", 0.0) or 0.0),
                            float(2 ** attempt),
                        ),
                    )
                    self.log_cb(
                        f"Parça {index + 1} yeniden deneniyor "
                        f"({attempt}/{MAX_PART_RETRIES}, {wait:.0f} sn): {error}"
                    )
                    self._wait_before_retry(wait, attempt)
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
            raise error
        # Tüm parçaların boyutlarını doğrula.
        for index, segment in enumerate(self.segments):
            expected = int(segment["end"]) - int(segment["start"]) + 1
            size = self._part_size(index)
            if expected > 0 and size < expected:
                raise TransientDownloadError(
                    f"Parça {index + 1} eksik kaldı ({human_size(size)} / {human_size(expected)}).",
                    code="incomplete_part",
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
        retry_after = 0.0
        while not self.should_stop():
            retry_after = 0.0
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
                    if response.status_code in RETRYABLE_STATUS:
                        retry_after = parse_retry_after(
                            response.headers.get("Retry-After"),
                            default=min(30, 2 ** attempt),
                        )
                        raise error_from_http(
                            response.status_code,
                            f"Sunucu geçici hata döndürdü (HTTP {response.status_code}).",
                            retry_after=retry_after,
                        )
                    if response.status_code == 416:
                        if self.total and existing >= self.total:
                            return
                        raise PermanentDownloadError(
                            "Sunucu istenen bayt aralığını reddetti (416).",
                            code="http_416",
                        )
                    if response.status_code not in (200, 206):
                        raise error_from_http(
                            response.status_code,
                            f"Sunucu HTTP {response.status_code} döndürdü.",
                        )
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
                    raise TransientDownloadError(
                        "İndirme beklenmedik şekilde durdu.",
                        code="stalled",
                    )
                existing = size
                attempt = 0
            except (requests.RequestException, DownloadError, OSError) as exc:
                if self.should_stop():
                    return
                error = self._as_download_error(exc)
                if not is_transient_error(error):
                    raise error from exc
                attempt += 1
                if attempt > MAX_PART_RETRIES:
                    raise error from exc
                wait = min(
                    60.0,
                    max(
                        float(retry_after),
                        float(getattr(error, "retry_after", 0.0) or 0.0),
                        float(2 ** attempt),
                    ),
                )
                self.log_cb(
                    f"Yeniden deneniyor ({attempt}/{MAX_PART_RETRIES}, {wait:.0f} sn): {error}"
                )
                self._wait_before_retry(wait, attempt)
                existing = self._part_size(0)

    # ------------------------------------------------------------------- merge
    def _merge_parts(self) -> str:
        self.status_cb("processing", t("task.detail.merging"))
        output_dir = self._output_dir()
        final_path = unique_path(output_dir, self.filename or f"video-{self.task.id}.mp4")
        copy_required = len(self.segments) > 1 or not self._same_device(
            self._part_path(0), output_dir
        )
        if copy_required and self.total:
            self._ensure_space(self.total + SPACE_MARGIN, "birleştirme")
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
            except Exception as exc:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
                if isinstance(exc, OSError):
                    raise error_from_os(exc, "Birleştirme başarısız") from exc
                raise
        shutil.rmtree(self.part_dir, ignore_errors=True)
        return str(final_path)

    # --------------------------------------------------------------------- run
    def run(self) -> str:
        self.status_cb("analyzing", t("task.detail.probing"))
        self.probe()
        self._check_stop()
        self._load_or_create_meta()
        self._check_initial_space()
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
                raise TransientDownloadError(
                    f"İndirme tamamlanmadı ({human_size(downloaded)} / {human_size(self.total)}).",
                    code="incomplete_download",
                )
        return self._merge_parts()

    def cleanup(self) -> None:
        shutil.rmtree(self.part_dir, ignore_errors=True)
