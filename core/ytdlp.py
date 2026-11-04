"""yt-dlp tabanlı site/akış indirici."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from .config import PARTS_DIR
from .errors import (
    DownloadError,
    DrmProtectedError,
    PermanentDownloadError,
    TransientDownloadError,
    error_from_message,
    error_from_os,
)
from .i18n import t
from .utils import (
    USER_AGENT,
    clean_error,
    human_duration,
    is_http_url,
    is_youtube_url,
    parse_eta_text,
    parse_number,
    parse_percent,
    parse_speed,
    strip_ansi,
)

ProgressCallback = Callable[[int, int, float, float, int], None]
StatusCallback = Callable[[str, str], None]
LogCallback = Callable[[str], None]
MetadataCallback = Callable[[dict], None]


class DownloadPaused(Exception):
    pass


class DownloadCanceled(Exception):
    pass


QUALITY_HEIGHTS = {"2160": 2160, "1440": 1440, "1080": 1080, "720": 720, "480": 480}


def build_format_selector(quality: str) -> str:
    if quality == "audio":
        return "ba[ext=m4a]/ba/b"
    if quality == "best":
        return "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
    height = QUALITY_HEIGHTS.get(quality)
    if not height:
        return "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
    return (
        f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
        f"b[height<={height}][ext=mp4]/"
        f"bv*[height<={height}]+ba/b[height<={height}]"
    )


def ytdlp_base_command() -> list[str]:
    return [sys.executable, "-m", "yt_dlp", "--ignore-config"]


def youtube_extra_args(url: str) -> list[str]:
    """YouTube için JS challenge çözücü bileşenlerini etkinleştirir."""
    if is_youtube_url(url):
        return ["--remote-components", "ejs:github"]
    return []


def ytdlp_version() -> str:
    # Önce kurulu paket meta verisini oku; alt süreç başlatmadan hızlıca döner.
    try:
        from importlib.metadata import version

        return version("yt-dlp")
    except Exception:
        pass
    try:
        from yt_dlp.version import __version__

        return str(__version__)
    except Exception:
        pass
    try:
        result = subprocess.run(
            ytdlp_base_command() + ["--version"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return (result.stdout or result.stderr or "").strip().splitlines()[0]
    except Exception:
        return "bilinmiyor"


def playlist_entry_url(data: dict, entry: dict) -> str:
    """Oynatma listesi girdisinden geçerli bir video sayfası URL'si üretir.

    Bazı yt-dlp çıktılarında ``url`` alanı yalnızca video kimliğidir. Bu
    değeri doğrudan kuyruğa eklemek ``https://<kimlik>`` gibi geçersiz bir
    görev oluşturur. Yalnızca açık http(s) adreslerini veya YouTube
    kimliklerini kabul et.
    """
    if not isinstance(entry, dict):
        return ""
    for key in ("webpage_url", "url"):
        value = entry.get(key)
        if isinstance(value, str) and is_http_url(value.strip()):
            return value.strip()

    entry_id = str(entry.get("id") or "").strip()
    if not entry_id:
        return ""
    markers = " ".join(
        str(entry.get(key) or "") for key in ("ie_key", "extractor_key", "extractor")
    )
    markers += " " + " ".join(
        str(data.get(key) or "") for key in ("extractor_key", "extractor")
    )
    if "youtube" in markers.lower():
        return f"https://www.youtube.com/watch?v={entry_id}"
    return ""


def extract_playlist_info(url: str, cookies_browser: str = "none", referer: str = "") -> dict | None:
    """Verilen URL'nin oynatma listesi olup olmadığını ve içindeki videoları döner."""
    cmd = ytdlp_base_command() + [
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        "--socket-timeout", "20",
    ]
    cmd += youtube_extra_args(url)
    if cookies_browser in {"brave", "firefox", "chrome", "chromium"}:
        cmd += ["--cookies-from-browser", cookies_browser]
    cmd += ["--user-agent", USER_AGENT]
    if referer:
        cmd += ["--add-header", f"Referer:{referer}"]
    cmd.append(url)
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if res.returncode != 0:
            return None
        data = json.loads((res.stdout or "").strip())
        if not isinstance(data, dict):
            return None
        entries = data.get("entries")
        if isinstance(entries, list) and len(entries) > 1:
            items = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                item_url = playlist_entry_url(data, entry)
                if item_url:
                    try:
                        duration = max(0, int(entry.get("duration") or 0))
                    except (TypeError, ValueError):
                        duration = 0
                    items.append({
                        "id": str(entry.get("id") or ""),
                        "title": str(entry.get("title") or "Video").strip(),
                        "url": item_url,
                        "duration": duration,
                    })
            if len(items) > 1:
                return {
                    "is_playlist": True,
                    "title": str(data.get("title") or "Oynatma Listesi").strip(),
                    "items": items,
                }
    except Exception:
        pass
    return None


class YtDlpDownloader:
    def __init__(
        self,
        task,
        config,
        progress_cb: ProgressCallback,
        status_cb: StatusCallback,
        log_cb: LogCallback | None = None,
        metadata_cb: MetadataCallback | None = None,
        audio_only: bool = False,
    ):
        self.task = task
        self.config = config
        self.progress_cb = progress_cb
        self.status_cb = status_cb
        self.log_cb = log_cb or (lambda _line: None)
        self.metadata_cb = metadata_cb or (lambda _meta: None)
        self.audio_only = audio_only

        self.pause_event = threading.Event()
        self.cancel_event = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()
        self._tail: list[str] = []
        self._dest_paths: list[str] = []
        self._final_hint = ""
        self._video_id = ""
        self._playlist_items = 1
        self.part_dir = PARTS_DIR / task.id
        self.final_file = self.part_dir / "final_path.txt"
        self._start_time = time.time()

    # ------------------------------------------------------------------ events
    def pause(self) -> None:
        self.pause_event.set()
        self._terminate()

    def cancel(self) -> None:
        self.cancel_event.set()
        self._terminate()

    def _terminate(self) -> None:
        with self._proc_lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
        except OSError:
            return

        def killer() -> None:
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass

        threading.Thread(target=killer, name="videoavci-ytdlp-killer", daemon=True).start()

    def _check_stop(self) -> None:
        if self.cancel_event.is_set():
            raise DownloadCanceled()
        if self.pause_event.is_set():
            raise DownloadPaused()

    # ----------------------------------------------------------------- analyze
    def _cookies_args(self) -> list[str]:
        browser = str(self.config.get("cookies_browser", "none") or "none")
        if browser in {"brave", "firefox", "chrome", "chromium"}:
            return ["--cookies-from-browser", browser]
        return []

    def _header_args(self) -> list[str]:
        args: list[str] = ["--user-agent", USER_AGENT]
        referer = (self.task.referer or "").strip().replace("\n", "").replace("\r", "")
        if referer:
            args += ["--add-header", f"Referer:{referer}"]
        return args

    def _with_youtube_hint(self, message: str) -> str:
        if is_youtube_url(self.task.url) and "This video is not available" in message:
            return f"{message} — {t('ytdlp.youtube_unavailable_hint')}"
        return message

    def analyze(self) -> dict:
        self.status_cb("analyzing", t("task.detail.analyzing"))
        self._check_stop()
        cmd = ytdlp_base_command() + [
            "--no-playlist",
            "--no-warnings",
            "--dump-single-json",
            "--socket-timeout",
            "30",
            "--retries",
            "3",
        ]
        cmd += youtube_extra_args(self.task.url)
        cmd += self._cookies_args()
        cmd += self._header_args()
        cmd.append(self.task.url)
        self.log_cb("Analiz: " + " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=150,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except subprocess.TimeoutExpired as exc:
            raise TransientDownloadError(
                "Video bilgisi alınamadı (zaman aşımı).",
                code="analyze_timeout",
            ) from exc
        except OSError as exc:
            raise error_from_os(exc, "yt-dlp çalıştırılamadı") from exc

        self._check_stop()
        if result.returncode != 0:
            message = clean_error(result.stderr or result.stdout)
            raise error_from_message(
                self._with_youtube_hint(message or "Video bilgisi alınamadı."),
                prefix="",
            )

        stdout = (result.stdout or "").strip()
        if not stdout:
            raise DownloadError("Video bilgisi boş döndü.", code="empty_analyze_output")
        try:
            info = json.loads(stdout)
        except json.JSONDecodeError:
            # Bazı durumlarda stdout'un başında uyarı olabilir; son JSON satırını dene.
            info = None
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        info = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
            if info is None:
                raise DownloadError("Video bilgisi okunamadı (geçersiz JSON).")

        if not isinstance(info, dict):
            raise DownloadError("Beklenmeyen video bilgisi.")
        if info.get("entries"):
            entries = [entry for entry in info["entries"] if isinstance(entry, dict)]
            if not entries:
                raise DownloadError("Oynatma listesinde video bulunamadı.")
            info = entries[0]
            self._playlist_items = 1
        if info.get("_has_drm") or info.get("has_drm"):
            raise DrmProtectedError(
                t("error.drm") if t("error.drm") != "error.drm" else
                "Bu video DRM korumalı; indirilemez."
            )
        if info.get("is_live"):
            self.log_cb("Canlı yayın algılandı; yayın bitene kadar indirilecek.")

        metadata = {
            "title": str(info.get("title") or self.task.title or "").strip(),
            "duration": int(info.get("duration") or 0),
            "thumbnail": str(info.get("thumbnail") or ""),
            "extractor": str(info.get("extractor_key") or info.get("extractor") or ""),
            "webpage_url": str(info.get("webpage_url") or self.task.url),
            "id": str(info.get("id") or ""),
            "live": bool(info.get("is_live")),
            "format_note": "",
        }
        self._video_id = metadata["id"]
        height = info.get("height")
        if height:
            metadata["format_note"] = f"{height}p"
        self.metadata_cb(metadata)
        self.log_cb(
            f"Analiz tamam: {metadata['title']} ({human_duration(metadata['duration'])}) "
            f"[{metadata['extractor']}]"
        )
        return metadata

    # ---------------------------------------------------------------- download
    def _build_download_command(self) -> list[str]:
        output_dir = Path(self.config.download_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self.part_dir.mkdir(parents=True, exist_ok=True)
        try:
            if self.final_file.exists():
                self.final_file.unlink()
        except OSError:
            pass

        template = str(output_dir / "%(title).150B [%(id)s].%(ext)s")
        if self.audio_only:
            # Aynı video kimliğiyle indirilen ses dosyası video dosyasının
            # üzerine yazmasın diye ayrı bir ad kullan.
            template = str(output_dir / "%(title).150B [%(id)s].audio.%(ext)s")
        try:
            fragments = max(1, min(8, int(self.config.get("connections", 4) or 4)))
        except (TypeError, ValueError):
            fragments = 4
        cmd = ytdlp_base_command() + [
            "--no-playlist",
            "--newline",
            "--no-colors",
            "--progress",
            "--progress-template",
            "download:@@VA_PROGRESS@@%(progress._percent_str)s|%(progress._speed_str)s|"
            "%(progress._eta_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
            "%(progress.total_bytes_estimate)s",
            "--print",
            "after_move:@@VA_FINAL@@%(filepath)s",
            "--print-to-file",
            "after_move:%(filepath)s",
            str(self.final_file),
            "--output",
            template,
            "--socket-timeout",
            "30",
            "--retries",
            "10",
            "--fragment-retries",
            "10",
            "--file-access-retries",
            "3",
            "--extractor-retries",
            "3",
            "--retry-sleep",
            "2",
            "--concurrent-fragments",
            str(fragments),
            "--trim-filenames",
            "180",
        ]
        if self._playlist_items:
            cmd += ["--playlist-items", str(self._playlist_items)]
        quality = self.task.quality or "best"
        if self.audio_only:
            # Birleştirme için yeniden kodlamadan ses akışının kendisini al.
            cmd += ["--format", "ba[ext=m4a]/ba/b"]
        else:
            cmd += ["--format", build_format_selector(quality)]
            if quality == "audio":
                cmd += ["--extract-audio", "--audio-format", "mp3", "--audio-quality", "0"]
            else:
                cmd += ["--merge-output-format", "mp4/mkv"]
                if bool(self.config.get("download_subtitles", False)):
                    langs = str(self.config.get("subtitle_langs", "tr,en") or "tr,en")
                    cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", langs, "--embed-subs"]
        limit = int(self.config.get("speed_limit_kbps", 0) or 0)
        if limit > 0:
            cmd += ["--limit-rate", f"{limit}K"]
        cmd += youtube_extra_args(self.task.url)
        cmd += self._cookies_args()
        cmd += self._header_args()
        cmd.append(self.task.url)
        return cmd

    def _handle_line(self, line: str) -> None:
        line = strip_ansi(line).rstrip()
        if not line:
            return
        self._tail.append(line)
        if len(self._tail) > 60:
            self._tail = self._tail[-60:]

        if line.startswith("@@VA_PROGRESS@@"):
            payload = line[len("@@VA_PROGRESS@@") :]
            parts = payload.split("|")
            if len(parts) >= 6:
                percent = parse_percent(parts[0])
                speed = parse_speed(parts[1])
                eta = parse_eta_text(parts[2])
                downloaded = parse_number(parts[3])
                total = parse_number(parts[4]) or parse_number(parts[5])
                if total and downloaded > total:
                    downloaded = total
                self.progress_cb(downloaded, total, percent, speed, eta)
            return

        if line.startswith("@@VA_FINAL@@"):
            final = line[len("@@VA_FINAL@@") :].strip().strip('"')
            if final:
                self._final_hint = final
            return

        if line.startswith("[download] Destination:"):
            dest = line.split("Destination:", 1)[1].strip()
            if dest and dest not in self._dest_paths:
                self._dest_paths.append(dest)
            self.status_cb("downloading", t("task.status.downloading"))
            return
        if line.startswith("[download]") and "has already been downloaded" in line:
            self.status_cb("processing", t("task.detail.already_downloaded"))
            return
        if any(token in line for token in ("[Merger]", "[ExtractAudio]", "[FixupM3u8]", "[VideoRemuxer]", "[VideoConvertor]")):
            self.status_cb("processing", t("task.status.processing"))
            match = re.search(r'into "([^"]+)"', line)
            if match:
                self._final_hint = match.group(1)
            match = re.search(r"Destination:\s*(.+)$", line)
            if match:
                self._final_hint = match.group(1).strip()
            return
        if line.startswith("ERROR:"):
            self.log_cb(line)
            return
        if line.startswith("WARNING:"):
            self.log_cb(line)
            return
        self.log_cb(line)

    def _read_final_path(self) -> str:
        candidates = []
        try:
            content = self.final_file.read_text(encoding="utf-8").strip()
            candidates.extend(line.strip() for line in content.splitlines() if line.strip())
        except OSError:
            pass
        if self._final_hint:
            candidates.append(self._final_hint)
        candidates.extend(reversed(self._dest_paths))
        for candidate in candidates:
            candidate = candidate.strip().strip('"')
            if candidate and os.path.isfile(candidate):
                return candidate
        # Son çare: çıktı klasöründeki en yeni medya dosyası. Aynı klasörde
        # eşzamanlı indirme varsa yanlış dosyayı seçmemek için yalnızca bu
        # videonun kimliğini taşıyan dosyalara bak.
        try:
            output_dir = Path(self.config.download_dir)
            allowed = (
                {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac", ".webm", ".mp4"}
                if self.audio_only
                else {".mp4", ".mkv", ".webm", ".mov", ".mp3", ".m4a", ".opus"}
            )
            if not self._video_id:
                return ""
            id_marker = f"[{self._video_id}]"
            files = [
                path
                for path in output_dir.iterdir()
                if path.is_file()
                and id_marker in path.name
                and path.suffix.lower() in allowed
                and path.stat().st_mtime >= self._start_time - 5
                and (not self.audio_only or ".audio." in path.name)
            ]
            files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            if files:
                return str(files[0])
        except OSError:
            pass
        return ""

    def download(self) -> str:
        self.status_cb("downloading", t("task.status.downloading"))
        cmd = self._build_download_command()
        self.log_cb("İndirme: " + " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except OSError as exc:
            raise error_from_os(exc, "yt-dlp başlatılamadı") from exc

        with self._proc_lock:
            self._proc = proc
        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    self._handle_line(line)
                    if self.cancel_event.is_set() or self.pause_event.is_set():
                        self._terminate()
            returncode = proc.wait()
        finally:
            with self._proc_lock:
                self._proc = None

        if self.cancel_event.is_set():
            raise DownloadCanceled()
        if self.pause_event.is_set():
            raise DownloadPaused()
        if returncode != 0:
            message = clean_error("\n".join(self._tail[-25:]))
            raise error_from_message(
                self._with_youtube_hint(
                    message or f"yt-dlp hata koduyla çıktı ({returncode})."
                )
            )
        final_path = self._read_final_path()
        if not final_path:
            raise DownloadError(
                "İndirme tamamlandı ancak dosya yolu bulunamadı.",
                code="final_path_missing",
            )
        self.status_cb("completed", t("task.status.completed"))
        return final_path

    def run(self) -> str:
        self.analyze()
        self._check_stop()
        return self.download()

    # ----------------------------------------------------------------- cleanup
    def cleanup(self) -> None:
        # İptal edilen indirmelerin yarım dosyalarını temizle.
        for dest in self._dest_paths:
            path = Path(dest)
            try:
                if path.exists() and self.cancel_event.is_set():
                    path.unlink()
            except OSError:
                pass
            for suffix in (".part", ".ytdl", ".temp"):
                try:
                    candidate = Path(str(path) + suffix)
                    if candidate.exists():
                        candidate.unlink()
                except OSError:
                    pass
            try:
                parent = path.parent
                stem = path.stem
                for candidate in parent.glob(stem + "*.part*"):
                    try:
                        candidate.unlink()
                    except OSError:
                        pass
            except OSError:
                pass
        shutil.rmtree(self.part_dir, ignore_errors=True)
