"""Küçük yardımcı fonksiyonlar."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import tempfile
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse

# Tarayıcı benzeri kullanıcı ajanı; bazı CDN'ler varsayılan UA'yı reddediyor.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

MEDIA_EXTENSIONS = {
    ".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi", ".flv",
    ".mpg", ".mpeg", ".ogv", ".3gp", ".ts", ".m2ts",
}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"}
MANIFEST_EXTENSIONS = {".m3u8", ".mpd"}

MIME_EXTENSION = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/mpeg": ".mpg",
    "video/ogg": ".ogv",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "application/vnd.apple.mpegurl": ".m3u8",
    "application/x-mpegurl": ".m3u8",
    "application/dash+xml": ".mpd",
}

_ILLEGAL_FILENAME = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')
_WS = re.compile(r"\s+")


def now() -> float:
    return time.time()


def human_size(value: int | float | None) -> str:
    if value is None:
        return "—"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    if value <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    if index == 0:
        return f"{int(value)} B"
    if value >= 100:
        return f"{value:.0f} {units[index]}"
    if value >= 10:
        return f"{value:.1f} {units[index]}"
    return f"{value:.2f} {units[index]}"


def human_speed(value: int | float | None) -> str:
    if not value or value <= 0:
        return "—"
    return human_size(value) + "/s"


def human_eta(seconds: int | float | None) -> str:
    if seconds is None or seconds <= 0 or seconds > 86400 * 7:
        return "—"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def human_duration(seconds: int | float | None) -> str:
    if not seconds or seconds <= 0:
        return ""
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def hostname(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def normalize_url(value: str) -> str:
    value = (value or "").strip().strip('"\'')
    if not value:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value
    return value


def is_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def url_extension(url: str) -> str:
    try:
        path = urlparse(url).path
        ext = os.path.splitext(path)[1].lower()
        return ext
    except Exception:
        return ""


def is_manifest_url(url: str) -> bool:
    return url_extension(url) in MANIFEST_EXTENSIONS


def is_media_url(url: str) -> bool:
    return url_extension(url) in MEDIA_EXTENSIONS | AUDIO_EXTENSIONS


def guess_kind(url: str, content_type: str | None = None) -> str:
    ct = (content_type or "").lower()
    ext = url_extension(url)
    if ext == ".m3u8" or "mpegurl" in ct:
        return "hls"
    if ext == ".mpd" or "dash+xml" in ct:
        return "dash"
    if ct.startswith("video/") or ct.startswith("audio/") or ext in MEDIA_EXTENSIONS | AUDIO_EXTENSIONS:
        return "direct"
    return "page"


def sanitize_filename(name: str, max_len: int = 180) -> str:
    name = unquote(name or "").strip()
    name = unicodedata.normalize("NFC", name)
    name = _ILLEGAL_FILENAME.sub(" ", name)
    name = _WS.sub(" ", name).strip(" .")
    if not name:
        name = "video"
    if len(name) > max_len:
        stem, ext = os.path.splitext(name)
        keep = max(1, max_len - len(ext))
        name = stem[:keep].rstrip() + ext
    return name


def parse_content_disposition(value: str | None) -> str:
    if not value:
        return ""
    # RFC 5987 filename*=UTF-8''...
    match = re.search(r"filename\*\s*=\s*([^;]+)", value, re.IGNORECASE)
    if match:
        raw = match.group(1).strip().strip('"')
        if "''" in raw:
            charset, _, encoded = raw.partition("''")
            try:
                return unquote(encoded, encoding=charset or "utf-8", errors="replace")
            except Exception:
                return unquote(encoded)
        return unquote(raw)
    match = re.search(r'filename\s*=\s*("([^"]*)"|([^;]+))', value, re.IGNORECASE)
    if match:
        raw = (match.group(2) or match.group(3) or "").strip()
        return unquote(raw)
    return ""


def filename_from_url(
    url: str,
    content_disposition: str | None = None,
    content_type: str | None = None,
    fallback_title: str = "",
) -> str:
    name = parse_content_disposition(content_disposition)
    if not name:
        try:
            name = unquote(os.path.basename(urlparse(url).path))
        except Exception:
            name = ""
    name = sanitize_filename(name) if name else ""

    ext = os.path.splitext(name)[1].lower()
    mime = (content_type or "").split(";")[0].strip().lower()
    if not ext:
        guessed = MIME_EXTENSION.get(mime) or mimetypes.guess_extension(mime) or ""
        if not guessed and fallback_title:
            guessed = ""
        ext = guessed
    if not ext:
        # URL uzantısı yoksa makul bir varsayılan seç.
        if mime.startswith("audio/"):
            ext = ".mp3"
        else:
            ext = ".mp4"

    if not name:
        base = sanitize_filename(fallback_title or "video")
    else:
        base = os.path.splitext(name)[0]
        if not base:
            base = sanitize_filename(fallback_title or "video")
    return sanitize_filename(base + ext)


def unique_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / sanitize_filename(filename)
    if not candidate.exists():
        return candidate
    stem, ext = os.path.splitext(candidate.name)
    for index in range(1, 10000):
        candidate = directory / f"{stem} ({index}){ext}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem} ({int(time.time())}){ext}"


def atomic_write_json(path: Path, data, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=indent)
        os.replace(temp_name, path)
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except OSError:
            pass


def load_json(path: Path, default=None):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text or "")


def clean_error(text: str, limit: int = 500) -> str:
    text = strip_ansi(text or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "Bilinmeyen hata"
    # yt-dlp hataları genellikle ERROR: ile başlar; son anlamlı satırı seç.
    preferred = [line for line in lines if line.startswith("ERROR:")]
    message = preferred[-1] if preferred else lines[-1]
    if message.startswith("ERROR:"):
        message = message[6:].strip()
    return message[:limit]


def parse_eta_text(value: str | None) -> int:
    if not value:
        return 0
    value = value.strip()
    if not value or value.upper() in {"NA", "N/A", "UNKNOWN", "—"}:
        return 0
    parts = value.split(":")
    try:
        parts = [int(float(p)) for p in parts]
    except ValueError:
        return 0
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 1:
        return parts[0]
    return 0


def parse_number(value: str | None) -> int:
    if value is None:
        return 0
    value = value.strip()
    if not value or value.upper() in {"NA", "N/A", "NONE", "UNKNOWN"}:
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0


def parse_percent(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return max(0.0, min(100.0, float(value.strip().replace("%", ""))))
    except ValueError:
        return 0.0


def parse_speed(value: str | None) -> float:
    if not value:
        return 0.0
    text = value.strip().replace(",", ".")
    if not text or "unknown" in text.lower() or text in {"—", "NA", "N/A"}:
        return 0.0
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]?i?B)(?:/s)?", text, re.IGNORECASE)
    if not match:
        return 0.0
    amount = float(match.group(1))
    unit = match.group(2).lower()
    factors = {
        "b": 1,
        "kb": 1024,
        "kib": 1024,
        "mb": 1024 ** 2,
        "mib": 1024 ** 2,
        "gb": 1024 ** 3,
        "gib": 1024 ** 3,
        "tb": 1024 ** 4,
        "tib": 1024 ** 4,
        "pb": 1024 ** 5,
        "pib": 1024 ** 5,
    }
    return amount * factors.get(unit, 0)


def file_size(path: str | Path | None) -> int:
    try:
        return os.path.getsize(path) if path else 0
    except OSError:
        return 0


def open_in_file_manager(path: str | Path) -> None:
    import subprocess

    path = str(path)
    if os.path.isfile(path):
        subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])
    else:
        Path(path).mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", path])


def open_path(path: str | Path) -> None:
    import subprocess

    subprocess.Popen(["xdg-open", str(path)])
