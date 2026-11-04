"""Tipli indirme hataları ve sınıflandırma testleri."""

from __future__ import annotations

import errno
import os
import unittest

os.environ["ABREK_LANG"] = "tr"

import requests

from core.errors import (
    AuthenticationError,
    DiskSpaceError,
    DownloadError,
    DrmProtectedError,
    ErrorKind,
    PermanentDownloadError,
    ResourceNotFoundError,
    TransientDownloadError,
    classify_exception,
    classify_http_status,
    classify_message,
    error_from_http,
    error_from_message,
    error_from_os,
    error_from_request,
    is_transient,
)
from core.utils import is_transient_error


class TypedErrorTests(unittest.TestCase):
    def test_subclass_kind_overrides_ambiguous_message(self):
        self.assertTrue(is_transient(TransientDownloadError("video unavailable")))
        self.assertFalse(is_transient(PermanentDownloadError("timed out")))
        self.assertFalse(is_transient_error(PermanentDownloadError("timed out")))

    def test_text_classification_permanent_wins(self):
        self.assertFalse(is_transient_error("video unavailable due to connection?"))
        self.assertFalse(is_transient_error("HTTP 404 Not Found"))
        self.assertTrue(is_transient_error("HTTP 503 Service Unavailable"))

    def test_classify_http_status(self):
        self.assertEqual(classify_http_status(429), ErrorKind.TRANSIENT)
        self.assertEqual(classify_http_status(404), ErrorKind.PERMANENT)
        self.assertEqual(classify_http_status("not-a-status"), ErrorKind.UNKNOWN)

    def test_error_from_http(self):
        transient = error_from_http(503, "geçici", retry_after=12)
        self.assertIsInstance(transient, TransientDownloadError)
        self.assertEqual(transient.retry_after, 12.0)
        permanent = error_from_http(404, "bulunamadı")
        self.assertIsInstance(permanent, PermanentDownloadError)
        self.assertNotIsInstance(permanent, ResourceNotFoundError)
        self.assertEqual(permanent.code, "http_404")

    def test_error_from_http_retry_after_capped_by_manager(self):
        from core.manager import AUTO_RETRY_RETRY_AFTER_CAP

        self.assertGreaterEqual(AUTO_RETRY_RETRY_AFTER_CAP, 12)

    def test_error_from_os(self):
        disk = error_from_os(OSError(errno.ENOSPC, "no space left on device"))
        self.assertIsInstance(disk, DiskSpaceError)
        auth = error_from_os(OSError(errno.EACCES, "permission denied"))
        self.assertNotIsInstance(auth, AuthenticationError)
        self.assertEqual(auth.code, "permission")
        transient = error_from_os(OSError(errno.EAGAIN, "resource temporarily unavailable"))
        self.assertIsInstance(transient, TransientDownloadError)

    def test_error_from_request(self):
        self.assertIsInstance(
            error_from_request(requests.exceptions.Timeout("timed out")),
            TransientDownloadError,
        )
        self.assertIsInstance(
            error_from_request(requests.exceptions.SSLError("ssl")),
            PermanentDownloadError,
        )

    def test_error_from_message(self):
        drm = error_from_message("DRM protected content")
        self.assertIsInstance(drm, DrmProtectedError)
        self.assertFalse(is_transient(drm))
        not_found = error_from_message("HTTP 404 Not Found")
        self.assertEqual(not_found.code, "http_404")
        self.assertFalse(is_transient(not_found))

    def test_classify_exception(self):
        self.assertEqual(
            classify_exception(TransientDownloadError("x", retry_after=5)),
            (ErrorKind.TRANSIENT, "transient"),
        )
        self.assertEqual(
            classify_exception(requests.exceptions.ConnectionError("boom")),
            (ErrorKind.TRANSIENT, "connection"),
        )

    def test_classify_message(self):
        kind, code = classify_message("HTTP error 503")
        self.assertEqual((kind, code), (ErrorKind.TRANSIENT, "http_503"))
        kind, code = classify_message("HTTP 403")
        self.assertEqual((kind, code), (ErrorKind.PERMANENT, "http_403"))
        kind, code = classify_message("")
        self.assertEqual((kind, code), (ErrorKind.UNKNOWN, ""))

    def test_retry_after_negative_becomes_zero(self):
        error = DownloadError("x", retry_after=-5)
        self.assertEqual(error.retry_after, 0.0)


if __name__ == "__main__":
    unittest.main()