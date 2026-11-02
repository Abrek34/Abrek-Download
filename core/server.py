"""Tarayıcı eklentisi ile uygulama arasındaki yerel HTTP köprüsü."""

from __future__ import annotations

import json
import logging
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse

from .config import API_HOST, API_PORT
from .manager import DownloadManager

log = logging.getLogger("videoavci.api")

MAX_BODY = 1024 * 1024
ALLOWED_ORIGIN_PREFIXES = (
    "chrome-extension://",
    "moz-extension://",
    "safari-web-extension://",
    "safari-extension://",
)
ALLOWED_HOSTS = {
    API_HOST,
    "localhost",
    f"{API_HOST}:{API_PORT}",
    f"localhost:{API_PORT}",
}


def host_allowed(value: str | None) -> bool:
    """Yalnızca yerel köprü adresine yapılan istekleri kabul et.

    Host başlığını doğrulamak, DNS yeniden bağlama (rebinding) saldırılarına
    karşı ek bir koruma katmanı sağlar.
    """
    if not value:
        return True
    return value.strip().lower() in ALLOWED_HOSTS


class ApiHandler(BaseHTTPRequestHandler):
    manager: DownloadManager
    server_version = "VideoAvciAPI/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------------ helpers
    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _origin(self) -> str | None:
        return self.headers.get("Origin")

    def _origin_allowed(self, origin: str | None) -> bool:
        if not origin or origin == "null":
            return True
        if origin.startswith(ALLOWED_ORIGIN_PREFIXES):
            return True
        if origin in {
            f"http://{API_HOST}:{API_PORT}",
            f"http://localhost:{API_PORT}",
        }:
            return True
        return False

    def _cors_headers(self) -> dict[str, str]:
        origin = self._origin()
        if origin and self._origin_allowed(origin):
            allow_origin = origin
        else:
            allow_origin = "*"
        return {
            "Access-Control-Allow-Origin": allow_origin,
            "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "86400",
            "Vary": "Origin",
        }

    def _send_json(self, status: int, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_html(self, status: int, html: str) -> None:
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _check_origin(self) -> bool:
        origin = self._origin()
        if self._origin_allowed(origin):
            return True
        self._send_json(403, {"ok": False, "error": "Bu kaynaktan erişim izinli değil."})
        return False

    def _check_host(self) -> bool:
        if host_allowed(self.headers.get("Host")):
            return True
        self._send_json(403, {"ok": False, "error": "Geçersiz Host başlığı."})
        return False

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > MAX_BODY:
            self._send_json(413, {"ok": False, "error": "İstek çok büyük."})
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"ok": False, "error": "Geçersiz JSON."})
            return None
        if not isinstance(data, dict):
            self._send_json(400, {"ok": False, "error": "JSON nesnesi bekleniyor."})
            return None
        return data

    # -------------------------------------------------------------------- routes
    def do_OPTIONS(self) -> None:
        if not self._check_host() or not self._check_origin():
            return
        self.send_response(204)
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if not self._check_host() or not self._check_origin():
            return
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/health" or path == "/api/ping":
            self._send_json(200, self.manager.health())
            return
        if path == "/api/captures":
            snapshot = self.manager.snapshot()
            self._send_json(200, {"ok": True, "captures": snapshot["captures"]})
            return
        if path == "/api/tasks":
            snapshot = self.manager.snapshot()
            self._send_json(200, {"ok": True, "tasks": snapshot["tasks"], **{k: v for k, v in snapshot.items() if k not in {"tasks", "captures"}}})
            return
        if path == "/":
            self._send_html(200, self._dashboard_html())
            return
        self._send_json(404, {"ok": False, "error": "Bulunamadı."})

    def do_POST(self) -> None:
        if not self._check_host() or not self._check_origin():
            return
        path = urlparse(self.path).path.rstrip("/")
        payload = self._read_json()
        if payload is None:
            return

        if path == "/api/captures":
            if self.manager.config.get("capture_paused"):
                self._send_json(200, {"ok": True, "paused": True, "duplicate": True})
                return
            try:
                capture, duplicate = self.manager.add_capture(payload)
            except ValueError as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return
            except Exception as exc:
                log.exception("Yakalama eklenemedi")
                self._send_json(500, {"ok": False, "error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "duplicate": duplicate,
                    "capture": capture.to_dict(),
                },
            )
            return

        if path == "/api/download":
            url = str(payload.get("url") or "").strip()
            try:
                task, duplicate = self.manager.add_url(
                    url,
                    quality=payload.get("quality"),
                    kind=str(payload.get("kind") or "auto"),
                    title=str(payload.get("title") or ""),
                    page_url=str(payload.get("page_url") or payload.get("pageUrl") or ""),
                    referer=str(payload.get("referer") or ""),
                )
            except ValueError as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return
            except Exception as exc:
                log.exception("İndirme eklenemedi")
                self._send_json(500, {"ok": False, "error": str(exc)})
                return
            self._send_json(200, {"ok": True, "duplicate": duplicate, "task": task.snapshot()})
            return

        self._send_json(404, {"ok": False, "error": "Bulunamadı."})

    def do_DELETE(self) -> None:
        if not self._check_host() or not self._check_origin():
            return
        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/captures":
            self.manager.clear_captures()
            self._send_json(200, {"ok": True})
            return
        if path.startswith("/api/captures/"):
            capture_id = unquote(path.split("/")[-1])
            self.manager.remove_capture(capture_id)
            self._send_json(200, {"ok": True})
            return
        if path.startswith("/api/tasks/"):
            task_id = unquote(path.split("/")[-1])
            removed = self.manager.remove_task(task_id)
            self._send_json(200, {"ok": removed})
            return
        self._send_json(404, {"ok": False, "error": "Bulunamadı."})

    # ------------------------------------------------------------------ dashboard
    def _dashboard_html(self) -> str:
        health = self.manager.health()
        version = escape(str(health.get("version") or ""))
        ytdlp = escape(str(health.get("ytdlp") or ""))
        active = escape(str(health.get("active") or 0))
        captures = escape(str(health.get("captures") or 0))
        download_dir = escape(str(health.get("download_dir") or ""))
        return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Abrek Download Yerel Köprü</title>
<style>
body{{margin:0;background:#0f1117;color:#e8ecf5;font:15px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh}}
.card{{background:#171b24;border:1px solid #2a3040;border-radius:18px;padding:34px 38px;max-width:560px;box-shadow:0 20px 60px #0007}}
h1{{margin:0 0 6px;font-size:26px}} .ok{{color:#52d68a}} .muted{{color:#8b93a7;line-height:1.6}}
code{{background:#0f1117;border:1px solid #2a3040;border-radius:7px;padding:3px 7px;color:#8fb4ff}}
.row{{display:flex;justify-content:space-between;border-top:1px solid #242a37;padding:9px 0}}
</style></head><body><div class="card">
<h1>▶ Abrek Download</h1>
<p class="ok">● Yerel köprü çalışıyor</p>
<p class="muted">Tarayıcı eklentisi bu adrese bağlanarak videoları uygulamaya gönderir.
Bu sayfayı kapatabilirsiniz.</p>
<div class="row"><span>Sürüm</span><b>{version}</b></div>
<div class="row"><span>yt-dlp</span><b>{ytdlp}</b></div>
<div class="row"><span>Aktif indirme</span><b>{active}</b></div>
<div class="row"><span>Yakalanan video</span><b>{captures}</b></div>
<div class="row"><span>İndirme klasörü</span><b style="max-width:320px;overflow:hidden;text-overflow:ellipsis">{download_dir}</b></div>
<p class="muted">API: <code>http://{escape(API_HOST)}:{escape(str(API_PORT))}/api/health</code></p>
</div></body></html>"""


class ApiServer:
    def __init__(self, manager: DownloadManager, host: str = API_HOST, port: int = API_PORT):
        self.manager = manager
        self.host = host
        self.port = port
        handler = type("BoundApiHandler", (ApiHandler,), {"manager": manager})
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.httpd.daemon_threads = True
        self.httpd.allow_reuse_address = True
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            kwargs={"poll_interval": 0.3},
            name="videoavci-api",
            daemon=True,
        )

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        self.thread.start()
        log.info("Yerel API başladı: %s", self.url)

    def stop(self) -> None:
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        try:
            self.httpd.server_close()
        except Exception:
            pass
        log.info("Yerel API durdu")
