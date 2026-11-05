"""Yapılandırılmış indirme hataları ve hata sınıflandırması.

İndirme motorları hataları mümkün olduğunca burada tanımlı tiplerle üretir.
Böylece otomatik yeniden deneme kararı, hata mesajındaki kelimelere bakmak
yerine ``ErrorKind`` alanına göre verilir. Yalnızca dış araçlardan (ör. yt-dlp
alt süreci) gelen metinler için sınırlı ve deterministik bir eşleme kullanılır.
"""

from __future__ import annotations

import errno
import re
from enum import Enum

import requests


class ErrorKind(str, Enum):
    """Hatanın yeniden denenebilirliği."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class DownloadError(Exception):
    """Uygulama genelinde kullanılan taban indirme hatası."""

    kind: ErrorKind = ErrorKind.UNKNOWN
    code: str = "download_error"

    def __init__(
        self,
        message: str = "",
        *,
        kind: ErrorKind | str | None = None,
        code: str | None = None,
        retry_after: float = 0.0,
    ):
        super().__init__(str(message))
        if kind is not None:
            try:
                self.kind = ErrorKind(kind)
            except ValueError:
                self.kind = ErrorKind.UNKNOWN
        if code:
            self.code = str(code)
        try:
            self.retry_after = max(0.0, float(retry_after or 0.0))
        except (TypeError, ValueError):
            self.retry_after = 0.0


class TransientDownloadError(DownloadError):
    """Ağ, zaman aşımı veya sunucu yoğunluğu gibi geçici hata."""

    kind = ErrorKind.TRANSIENT
    code = "transient"


class PermanentDownloadError(DownloadError):
    """Aynı istekle düzelmeyecek kalıcı hata."""

    kind = ErrorKind.PERMANENT
    code = "permanent"


class NotDirectError(DownloadError):
    """URL doğrudan medya değil; yt-dlp ile denenmeli."""

    code = "not_direct"


class DrmProtectedError(PermanentDownloadError):
    code = "drm"


class DiskSpaceError(PermanentDownloadError):
    code = "disk_space"


class PermissionDeniedError(PermanentDownloadError):
    code = "permission"


class AuthenticationError(PermanentDownloadError):
    code = "auth"


class ResourceNotFoundError(PermanentDownloadError):
    code = "not_found"


TRANSIENT_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

_PERMANENT_ERRNOS = {
    errno.ENOSPC: "disk_space",
    getattr(errno, "EDQUOT", errno.ENOSPC): "disk_space",
    errno.EACCES: "permission",
    errno.EPERM: "permission",
    errno.EROFS: "read_only",
}

_TRANSIENT_ERRNOS = {
    errno.EAGAIN: "resource_busy",
    getattr(errno, "EWOULDBLOCK", errno.EAGAIN): "resource_busy",
    errno.EMFILE: "resource_busy",
    errno.ENFILE: "resource_busy",
    errno.EIO: "io",
}

_DRM_HINTS = (
    "drm",
    "widevine",
    "playready",
    "fairplay",
    "sample-aes",
    "encrypted media",
    "content protection",
)

_AUTH_HINTS = (
    "sign in",
    "login required",
    "log in to",
    "authentication required",
    "members-only",
    "members only",
    "private video",
    "premium",
    "oturum aç",
    "giriş yap",
    "özel video",
)

_PERMANENT_HINTS = (
    "not available in your country",
    "geo restricted",
    "geo-restricted",
    "region locked",
    "video unavailable",
    "this video is not available",
    "removed by the uploader",
    "http 400",
    "http 401",
    "http 403",
    "http 404",
    "forbidden",
    "not found",
    "copyright",
    "unsupported url",
    "invalid url",
    "no video formats found",
    "requested format is not available",
    "no suitable format",
    "not supported",
    "certificate verify failed",
    "sslcertverificationerror",
    "no space left",
    "disk full",
    "permission denied",
    "read-only file system",
    "ffmpeg not found",
    "ffprobe not found",
    "bu video kullanılamıyor",
    "bulunamadı",
    "geçersiz bağlantı",
    "desteklenmiyor",
)

_TRANSIENT_HINTS = (
    "timed out",
    "timeout",
    "temporary failure in name resolution",
    "temporary failure",
    "connection reset",
    "connection refused",
    "connection aborted",
    "connection error",
    "connection closed",
    "remote end closed",
    "incomplete read",
    "unexpected eof",
    "broken pipe",
    "network is unreachable",
    "network error",
    "try again later",
    "http 408",
    "http 425",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "bağlantı kesildi",
    "bağlantı kurulamadı",
    "bağlantı hatası",
    "zaman aşımı",
    "ağ hatası",
    "geçici",
    "yeniden den",
)

_HTTP_STATUS_RE = re.compile(r"http(?:[\s_-]*error)?[\s:]+(\d{3})", re.IGNORECASE)


def classify_http_status(status: int | str | None) -> ErrorKind:
    """HTTP durum kodunu geçici/kalıcı olarak sınıflandırır."""
    try:
        value = int(status)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ErrorKind.UNKNOWN
    if value in TRANSIENT_HTTP_STATUS:
        return ErrorKind.TRANSIENT
    if 400 <= value < 600:
        return ErrorKind.PERMANENT
    return ErrorKind.UNKNOWN


def error_from_http(
    status: int,
    message: str,
    *,
    retry_after: float = 0.0,
) -> DownloadError:
    kind = classify_http_status(status)
    if kind is ErrorKind.TRANSIENT:
        return TransientDownloadError(
            message,
            code=f"http_{int(status)}",
            retry_after=retry_after,
        )
    if kind is ErrorKind.PERMANENT:
        return PermanentDownloadError(message, code=f"http_{int(status)}")
    return DownloadError(message)


def error_from_request(exc: BaseException, prefix: str = "") -> DownloadError:
    """``requests`` istisnasını tipli indirme hatasına çevirir."""
    message = f"{prefix}: {exc}" if prefix else str(exc)
    if isinstance(exc, requests.exceptions.SSLError):
        return PermanentDownloadError(message, code="ssl")
    if isinstance(exc, requests.exceptions.Timeout):
        return TransientDownloadError(message, code="timeout")
    if isinstance(exc, requests.exceptions.TooManyRedirects):
        return PermanentDownloadError(message, code="redirect")
    if isinstance(
        exc,
        (
            requests.exceptions.InvalidURL,
            requests.exceptions.MissingSchema,
            requests.exceptions.InvalidSchema,
        ),
    ):
        return PermanentDownloadError(message, code="invalid_url")
    if isinstance(exc, requests.exceptions.ConnectionError):
        return TransientDownloadError(message, code="connection")
    if isinstance(
        exc,
        (
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ContentDecodingError,
        ),
    ):
        return TransientDownloadError(message, code="incomplete")
    if isinstance(exc, requests.exceptions.RequestException):
        return DownloadError(message, code="request")
    return DownloadError(message)


def error_from_os(exc: OSError, prefix: str = "") -> DownloadError:
    """Dosya sistemi hatasını tipli indirme hatasına çevirir."""
    message = f"{prefix}: {exc}" if prefix else str(exc)
    code = _PERMANENT_ERRNOS.get(getattr(exc, "errno", None))
    if code:
        if code == "disk_space":
            return DiskSpaceError(message, code=code)
        return PermanentDownloadError(message, code=code)
    code = _TRANSIENT_ERRNOS.get(getattr(exc, "errno", None))
    if code:
        return TransientDownloadError(message, code=code)
    kind, mapped_code = classify_message(str(exc))
    if kind is ErrorKind.PERMANENT:
        return PermanentDownloadError(message, code=mapped_code or "os_error")
    if kind is ErrorKind.TRANSIENT:
        return TransientDownloadError(message, code=mapped_code or "os_error")
    return DownloadError(message, code="os_error")


def classify_message(message: str | None) -> tuple[ErrorKind, str]:
    """Dış araç metinlerini deterministik biçimde sınıflandırır.

    Bu fonksiyon yalnızca yt-dlp gibi metin üreten alt süreçler ve eski
    çağrılar için geri uyumluluk amacıyla kullanılır. Uygulama içi hatalar
    doğrudan ``TransientDownloadError`` / ``PermanentDownloadError`` olarak
    üretilir.
    """
    text = str(message or "").strip().lower()
    if not text:
        return ErrorKind.UNKNOWN, ""

    if any(hint in text for hint in _DRM_HINTS):
        return ErrorKind.PERMANENT, "drm"

    # "HTTP 503", "HTTP error 503" ve "http_error_503" biçimlerini yakala.
    for match in _HTTP_STATUS_RE.finditer(text):
        status = int(match.group(1))
        kind = classify_http_status(status)
        if kind is not ErrorKind.UNKNOWN:
            return kind, f"http_{status}"

    if any(hint in text for hint in _AUTH_HINTS):
        return ErrorKind.PERMANENT, "auth"
    if any(hint in text for hint in _PERMANENT_HINTS):
        return ErrorKind.PERMANENT, "permanent"
    if any(hint in text for hint in _TRANSIENT_HINTS):
        return ErrorKind.TRANSIENT, "transient"
    return ErrorKind.UNKNOWN, ""


def error_from_message(message: str, *, prefix: str = "") -> DownloadError:
    """Metni uygun tipli indirme hatasına dönüştürür."""
    text = f"{prefix}: {message}" if prefix else str(message)
    kind, code = classify_message(text)
    if kind is ErrorKind.TRANSIENT:
        return TransientDownloadError(text, code=code or "transient")
    if kind is ErrorKind.PERMANENT:
        if code == "drm":
            return DrmProtectedError(text)
        if code == "disk_space":
            return DiskSpaceError(text)
        if code == "permission":
            return PermissionDeniedError(text)
        return PermanentDownloadError(text, code=code or "permanent")
    return DownloadError(text, code=code or "unknown")


def classify_exception(error: BaseException | str | None) -> tuple[ErrorKind, str]:
    """Bir istisna veya metni ``(kind, code)`` çiftine çevirir."""
    if error is None:
        return ErrorKind.UNKNOWN, ""
    if isinstance(error, DownloadError):
        return error.kind, error.code
    if isinstance(error, requests.exceptions.RequestException):
        mapped = error_from_request(error)
        return mapped.kind, mapped.code
    if isinstance(error, OSError):
        mapped = error_from_os(error)
        return mapped.kind, mapped.code
    return classify_message(str(error))


def is_transient(error: BaseException | str | None) -> bool:
    """Hatanın otomatik yeniden denenebilir olup olmadığını söyler."""
    kind, _code = classify_exception(error)
    return kind is ErrorKind.TRANSIENT
