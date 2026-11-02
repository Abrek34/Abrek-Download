#!/usr/bin/env python3
"""Abrek Download — tarayıcı eklentisiyle çalışan Linux video indirici."""

from __future__ import annotations

import fcntl
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox

try:
    import pystray
    from PIL import Image as PILImage
    TRAY_AVAILABLE = True
except Exception:
    pystray = None
    PILImage = None
    TRAY_AVAILABLE = False

from core.config import (
    API_HOST,
    API_PORT,
    APP_NAME,
    LOG_DIR,
    PROJECT_DIR,
    STATE_DIR,
    VERSION,
    Config,
    ensure_dirs,
)
from core.manager import DownloadManager
from core.server import ApiServer
from core.utils import human_speed, open_in_file_manager, open_path
from ui import theme
from ui.captures import CapturesPage
from ui.downloads import DownloadsPage
from ui.extension import ExtensionPage
from ui.settings import SettingsPage
from ui.theme import (
    ACCENT,
    ACCENT_SOFT,
    BG,
    BG_SOFT,
    BORDER,
    BORDER_LIGHT,
    CARD,
    CARD_ALT,
    GREEN,
    MUTED,
    RED,
    RED_SOFT,
    SIDEBAR,
    TEXT,
    TEXT_DIM,
    YELLOW,
    font,
    make_button,
    mono,
    rounded_rect,
    setup_style,
)
from ui.widgets import ScrollFrame, show_details_dialog

log = logging.getLogger("videoavci.app")

PAGE_META = {
    "downloads": ("İndirilenler", "İndirme kuyruğu ve tamamlanan dosyalar"),
    "captures": ("Yakalananlar", "Tarayıcı eklentisinin bulduğu videolar"),
    "extension": ("Eklenti", "Brave, Chrome ve Firefox kurulumu"),
    "settings": ("Ayarlar", "İndirme tercihleri ve bakım"),
}

NAV_ITEMS = [
    ("downloads", "İndirilenler", "↓"),
    ("captures", "Yakalananlar", "◎"),
    ("extension", "Eklenti", "◈"),
    ("settings", "Ayarlar", "⚙"),
]


def setup_logging() -> None:
    ensure_dirs()
    root_logger = logging.getLogger()
    if getattr(root_logger, "_videoavci_configured", False):
        return
    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root_logger.addHandler(console)
    root_logger._videoavci_configured = True


class VideoAvciApp(tk.Tk):
    def __init__(
        self,
        config: Config,
        manager: DownloadManager,
        server: ApiServer | None,
        server_error: str = "",
    ):
        super().__init__(className="AbrekDownload")
        self.cfg = config
        self.manager = manager
        self.server = server
        self.server_error = server_error
        self._closing = False
        self._closed_cleanly = False
        self._queue: queue.Queue = queue.Queue()
        self._last_snapshot: dict | None = None
        self._last_capture_count: int | None = None
        self._active_page = "downloads"
        self._nav_counts = {"downloads": 0, "captures": 0}
        self._toast_after = None
        self._notified_completed: set[str] = set()
        self._tray_icon = None

        self.title("Abrek Download — Video İndirici")
        self.configure(bg=BG)
        self.minsize(1020, 660)
        self._set_initial_geometry()
        self._load_icon()
        setup_style(self)

        self._build_layout()
        self._bind_events()
        self.show_page("downloads")
        self._start_tray()
        self._paint_api_status(server is not None)
        if server is None:
            self._update_banner()

        self.after(120, self._drain_queue)
        self.after(500, self._poll)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ pencere
    def _set_initial_geometry(self) -> None:
        geometry = str(self.cfg.get("window_geometry") or "").strip()
        if re.fullmatch(r"\d{3,5}x\d{3,5}([+-]-?\d+[+-]-?\d+)?", geometry):
            self.geometry(geometry)
            return
        self.update_idletasks()
        width, height = 1240, 820
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 16)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _load_icon(self) -> None:
        icon_path = PROJECT_DIR / "assets" / "icon-256.png"
        try:
            self._icon = tk.PhotoImage(file=str(icon_path))
            self.iconphoto(True, self._icon)
        except Exception:
            log.debug("Pencere simgesi yüklenemedi", exc_info=True)

    # ------------------------------------------------------------------ yerleşim
    def _build_layout(self) -> None:
        self._build_sidebar()

        self.main = tk.Frame(self, bg=BG)
        self.main.pack(side="left", fill="both", expand=True)

        self.header = tk.Frame(self.main, bg=BG)
        self.header.pack(fill="x", padx=26, pady=(20, 0))

        left = tk.Frame(self.header, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        self.page_title = tk.Label(left, text="İndirilenler", bg=BG, fg=TEXT, font=font(20, "bold"), anchor="w")
        self.page_title.pack(fill="x")
        self.page_subtitle = tk.Label(left, text="", bg=BG, fg=MUTED, font=font(9), anchor="w")
        self.page_subtitle.pack(fill="x", pady=(3, 0))

        self.stats_label = tk.Label(
            self.header,
            text="● 0 aktif",
            bg=CARD,
            fg=TEXT_DIM,
            font=font(9),
            padx=13,
            pady=8,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        self.stats_label.pack(side="right", anchor="n")

        self.header_sep = tk.Frame(self.main, bg=BORDER, height=1)
        self.header_sep.pack(fill="x", padx=26, pady=(16, 0))

        self.banner = tk.Frame(
            self.main,
            bg=RED_SOFT,
            highlightthickness=1,
            highlightbackground="#5a2836",
        )
        banner_inner = tk.Frame(self.banner, bg=RED_SOFT)
        banner_inner.pack(fill="x", padx=14, pady=9)
        self.banner_label = tk.Label(
            banner_inner,
            text="",
            bg=RED_SOFT,
            fg="#ffb3bf",
            font=font(9),
            anchor="w",
            justify="left",
            wraplength=760,
        )
        self.banner_label.pack(side="left", fill="x", expand=True)
        make_button(
            banner_inner,
            "Yeniden dene",
            self.retry_server,
            kind="ghost",
            size=8,
            bg=RED_SOFT,
        ).pack(side="right", padx=(12, 0))

        self.content = tk.Frame(self.main, bg=BG)
        self.content.pack(fill="both", expand=True, padx=26, pady=(14, 20))
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.pages = {
            "downloads": DownloadsPage(self.content, self),
            "captures": CapturesPage(self.content, self),
            "extension": ExtensionPage(self.content, self),
            "settings": SettingsPage(self.content, self),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        self._update_banner()

        self.toast_label = tk.Label(
            self,
            text="",
            bg=CARD_ALT,
            fg=TEXT,
            font=font(9),
            padx=14,
            pady=9,
            justify="left",
            wraplength=430,
            highlightthickness=1,
            highlightbackground=BORDER,
        )

    def _build_sidebar(self) -> None:
        sidebar = tk.Frame(self, bg=SIDEBAR, width=226)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self.sidebar = sidebar

        inner = tk.Frame(sidebar, bg=SIDEBAR)
        inner.pack(fill="both", expand=True, padx=14, pady=(22, 16))

        brand = tk.Frame(inner, bg=SIDEBAR)
        brand.pack(fill="x", padx=4)
        logo = tk.Canvas(brand, width=42, height=42, bg=SIDEBAR, highlightthickness=0, bd=0)
        logo.pack(side="left")
        rounded_rect(logo, 0, 0, 42, 42, 13, fill=ACCENT, outline="")
        logo.create_polygon(17, 12, 17, 30, 31, 21, fill="#0b1020", outline="")
        brand_text = tk.Frame(brand, bg=SIDEBAR)
        brand_text.pack(side="left", padx=(11, 0))
        tk.Label(brand_text, text=APP_NAME, bg=SIDEBAR, fg=TEXT, font=font(16, "bold"), anchor="w").pack(fill="x")
        tk.Label(brand_text, text="video indirici", bg=SIDEBAR, fg=MUTED, font=font(8), anchor="w").pack(fill="x")

        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=(20, 16), padx=4)
        tk.Label(
            inner,
            text="MENÜ",
            bg=SIDEBAR,
            fg="#59647a",
            font=font(7, "bold"),
            anchor="w",
        ).pack(fill="x", padx=6, pady=(0, 8))

        self.nav_rows: dict[str, dict] = {}
        for key, label, symbol in NAV_ITEMS:
            row = tk.Frame(inner, bg=SIDEBAR, cursor="hand2")
            row.pack(fill="x", pady=(0, 4))
            accent = tk.Frame(row, bg=SIDEBAR, width=3)
            accent.pack(side="left", fill="y")
            accent.pack_propagate(False)
            content = tk.Frame(row, bg=SIDEBAR, cursor="hand2")
            content.pack(side="left", fill="x", expand=True, padx=(11, 0), pady=9)

            icon = tk.Label(content, text=symbol, bg=SIDEBAR, fg=MUTED, font=font(13), width=2, anchor="w")
            icon.pack(side="left")
            text = tk.Label(content, text=label, bg=SIDEBAR, fg=TEXT_DIM, font=font(10), anchor="w")
            text.pack(side="left", fill="x", expand=True, padx=(5, 0))
            badge = tk.Label(
                content,
                text="",
                bg=CARD_ALT,
                fg=TEXT_DIM,
                font=font(8, "bold"),
                padx=6,
                pady=1,
            )
            badge.pack(side="right", padx=(6, 8))

            self.nav_rows[key] = {
                "row": row,
                "accent": accent,
                "content": content,
                "icon": icon,
                "text": text,
                "badge": badge,
            }
            for widget in (row, accent, content, icon, text, badge):
                widget.bind("<Button-1>", lambda _event, k=key: self.show_page(k))
                widget.bind("<Enter>", lambda _event, k=key: self._nav_hover(k, True))
                widget.bind("<Leave>", lambda _event, k=key: self._nav_hover(k, False))

        tk.Frame(inner, bg=SIDEBAR).pack(fill="both", expand=True)

        api_card = tk.Frame(inner, bg=BG_SOFT, highlightthickness=1, highlightbackground=BORDER)
        api_card.pack(fill="x", pady=(0, 12))
        api_inner = tk.Frame(api_card, bg=BG_SOFT)
        api_inner.pack(fill="x", padx=11, pady=9)
        dot_row = tk.Frame(api_inner, bg=BG_SOFT)
        dot_row.pack(fill="x")
        self.api_dot = tk.Canvas(dot_row, width=9, height=9, bg=BG_SOFT, highlightthickness=0, bd=0)
        self.api_dot.pack(side="left", pady=(3, 0))
        self.api_dot.create_oval(0, 0, 8, 8, fill=GREEN, outline="")
        self.api_label = tk.Label(
            dot_row,
            text="Yerel köprü",
            bg=BG_SOFT,
            fg=TEXT_DIM,
            font=font(9, "bold"),
            anchor="w",
        )
        self.api_label.pack(side="left", padx=(7, 0))
        tk.Label(
            api_inner,
            text=f"{API_HOST}:{API_PORT}",
            bg=BG_SOFT,
            fg=MUTED,
            font=mono(8),
            anchor="w",
        ).pack(fill="x", pady=(3, 0))

        tk.Label(
            inner,
            text=f"v{VERSION}  ·  Linux",
            bg=SIDEBAR,
            fg="#4d5669",
            font=font(8),
            anchor="center",
        ).pack(fill="x")

    # ------------------------------------------------------------------ olaylar
    def _bind_events(self) -> None:
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind("<Control-n>", lambda _event: self._focus_url())
        self.bind("<Control-l>", lambda _event: self._focus_url())
        self.bind("<Control-o>", lambda _event: self._open_download_folder())
        self.bind("<Control-q>", lambda _event: self.on_close())
        self.bind("<F5>", lambda _event: self.refresh_now())

    def _on_mousewheel(self, event):
        widget = getattr(event, "widget", None)
        while widget is not None:
            if isinstance(widget, ScrollFrame):
                if getattr(event, "num", None) == 4:
                    units = -3
                elif getattr(event, "num", None) == 5:
                    units = 3
                else:
                    units = -3 if getattr(event, "delta", 0) > 0 else 3
                widget.scroll_by(units)
                return "break"
            widget = getattr(widget, "master", None)
        return None

    def _focus_url(self) -> None:
        self.show_page("downloads")
        self.pages["downloads"].focus_url()

    def _open_download_folder(self) -> None:
        try:
            open_in_file_manager(self.cfg.download_dir)
        except Exception as exc:
            self.toast(f"Klasör açılamadı: {exc}", "error")

    def _start_tray(self) -> None:
        if not TRAY_AVAILABLE:
            return
        try:
            icon_path = PROJECT_DIR / "assets" / "icon.png"
            image = PILImage.open(icon_path)

            def on_show(icon, item):
                self.after(0, self._show_from_tray)

            def on_quit(icon, item):
                icon.stop()
                self.after(0, self.on_close)

            menu = pystray.Menu(
                pystray.MenuItem("Göster", on_show, default=True),
                pystray.MenuItem("Klasörü aç", lambda icon, item: self.after(0, lambda: open_in_file_manager(self.cfg.download_dir))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Çıkış", on_quit),
            )
            self._tray_icon = pystray.Icon("AbrekDownload", image, "Abrek Download", menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
        except Exception:
            log.exception("Sistem tepsisi başlatılamadı")

    def _show_from_tray(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _stop_tray(self) -> None:
        icon = self._tray_icon
        self._tray_icon = None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------ gezinme
    def show_page(self, key: str) -> None:
        if key not in self.pages:
            return
        self._active_page = key
        self.pages[key].tkraise()
        title, subtitle = PAGE_META[key]
        self.page_title.configure(text=title)
        self.page_subtitle.configure(text=subtitle)
        self._paint_nav()
        page = self.pages[key]
        on_show = getattr(page, "on_show", None)
        if callable(on_show):
            try:
                on_show()
            except Exception:
                log.exception("Sayfa hazırlanamadı: %s", key)
        if key == "extension":
            self.pages["extension"].refresh_status(self.server is not None, self.server_error)
        self.refresh_now()

    def _paint_nav(self) -> None:
        for key, widgets in self.nav_rows.items():
            active = key == self._active_page
            bg = "#151c2a" if active else SIDEBAR
            for name in ("row", "content", "icon", "text", "badge"):
                widgets[name].configure(bg=bg)
            widgets["accent"].configure(bg=ACCENT if active else SIDEBAR)
            widgets["icon"].configure(fg=ACCENT if active else MUTED)
            widgets["text"].configure(
                fg=TEXT if active else TEXT_DIM,
                font=font(10, "bold" if active else "normal"),
            )
            count = self._nav_counts.get(key, 0)
            badge = widgets["badge"]
            if count:
                badge.configure(
                    text=str(count),
                    bg=ACCENT if active else CARD_ALT,
                    fg="#0b1020" if active else TEXT_DIM,
                )
                if not badge.winfo_manager():
                    badge.pack(side="right", padx=(6, 8))
            else:
                if badge.winfo_manager():
                    badge.pack_forget()

    def _nav_hover(self, key: str, entering: bool) -> None:
        if key == self._active_page:
            return
        bg = "#10141d" if entering else SIDEBAR
        widgets = self.nav_rows[key]
        for name in ("row", "content", "icon", "text", "badge"):
            widgets[name].configure(bg=bg)

    # ------------------------------------------------------------------ durum
    def _poll(self) -> None:
        if self._closing:
            return
        try:
            snapshot = self.manager.snapshot()
        except Exception:
            log.exception("Durum alınamadı")
        else:
            self._last_snapshot = snapshot
            self._apply_snapshot(snapshot)
        self.after(700, self._poll)

    def refresh_now(self) -> None:
        if self._closing:
            return
        try:
            snapshot = self.manager.snapshot()
        except Exception:
            log.exception("Durum yenilenemedi")
            return
        self._last_snapshot = snapshot
        self._apply_snapshot(snapshot)

    def _apply_snapshot(self, snapshot: dict) -> None:
        page = self.pages.get(self._active_page)
        if page is not None and hasattr(page, "update_snapshot"):
            try:
                page.update_snapshot(snapshot)
            except Exception:
                log.exception("Sayfa güncellenemedi: %s", self._active_page)

        tasks = snapshot.get("tasks") or []
        active = int(snapshot.get("active") or 0)
        queued = int(snapshot.get("queued") or 0)
        speed = float(snapshot.get("speed") or 0.0)
        errors = int(snapshot.get("errors") or 0)
        parts = [f"{active} aktif"]
        if queued:
            parts.append(f"{queued} sırada")
        if speed:
            parts.append(human_speed(speed))
        if errors:
            parts.append(f"{errors} hata")
        self.stats_label.configure(text="●  " + "   ·   ".join(parts))

        active_tasks = sum(1 for task in tasks if task.get("status") not in {"completed", "canceled", "error"})
        self._nav_counts["downloads"] = active_tasks
        self._nav_counts["captures"] = int(snapshot.get("capture_count") or 0)
        self._paint_nav()
        self._maybe_notify(snapshot)
        self._maybe_notify_downloads(tasks)

    def _maybe_notify(self, snapshot: dict) -> None:
        count = int(snapshot.get("capture_count") or 0)
        previous = self._last_capture_count
        self._last_capture_count = count
        if previous is None or count <= previous:
            return
        if not self.cfg.get("notify_captures", True):
            return
        if not shutil.which("notify-send"):
            return
        captures = snapshot.get("captures") or []
        title = "Yeni video yakalandı"
        if captures:
            title = str(captures[0].get("display_title") or title)[:140]
        try:
            subprocess.Popen(
                ["notify-send", "-a", APP_NAME, "Yeni video yakalandı", title],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            log.debug("Bildirim gönderilemedi", exc_info=True)

    def _maybe_notify_downloads(self, tasks: list[dict]) -> None:
        if not self.cfg.get("notify_downloads", True):
            return
        if not shutil.which("notify-send"):
            return
        for task in tasks:
            task_id = str(task.get("id") or "")
            if not task_id or task.get("status") != "completed":
                continue
            if task_id in self._notified_completed:
                continue
            self._notified_completed.add(task_id)
            title = str(task.get("display_title") or task.get("title") or "İndirme")[:140]
            filepath = str(task.get("filepath") or "")
            body = filepath or "İndirme tamamlandı."
            try:
                subprocess.Popen(
                    ["notify-send", "-a", APP_NAME, "İndirme tamamlandı", f"{title}\n{body}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                log.debug("İndirme bildirimi gönderilemedi", exc_info=True)

    # ------------------------------------------------------------------ köprü
    def _paint_api_status(self, ok: bool) -> None:
        self.api_dot.delete("all")
        self.api_dot.create_oval(0, 0, 8, 8, fill=GREEN if ok else RED, outline="")
        self.api_label.configure(text="Yerel köprü" if ok else "Köprü kapalı")
        self.api_label.configure(fg=TEXT_DIM if ok else RED)

    def _update_banner(self) -> None:
        if self.server_error:
            self.banner_label.configure(
                text=(
                    f"Yerel köprü başlatılamadı: {self.server_error}  ·  "
                    f"{API_PORT} portu başka bir uygulama tarafından kullanılıyor olabilir. "
                    "Tarayıcı eklentisi bağlanamaz."
                )
            )
            self.banner.pack(fill="x", padx=26, pady=(12, 0), before=self.content)
        else:
            self.banner.pack_forget()

    def retry_server(self) -> None:
        if self.server is not None:
            self.toast("Yerel köprü zaten çalışıyor.", "info")
            return
        try:
            server = ApiServer(self.manager)
            server.start()
        except OSError as exc:
            self.server_error = str(exc)
            self._update_banner()
            self.toast(f"Köprü hâlâ başlatılamıyor: {exc}", "error")
            return
        except Exception as exc:
            self.server_error = str(exc)
            self._update_banner()
            self.toast(f"Köprü başlatılamadı: {exc}", "error")
            return
        self.server = server
        self.server_error = ""
        self._update_banner()
        self._paint_api_status(True)
        self.pages["extension"].refresh_status(True)
        self.toast("Yerel köprü yeniden başlatıldı.", "success")

    # ------------------------------------------------------------------ görevler
    def pause_task(self, task_id: str) -> None:
        self.manager.pause_task(task_id)
        self.refresh_now()

    def resume_task(self, task_id: str) -> None:
        self.manager.resume_task(task_id)
        self.refresh_now()

    def cancel_task(self, task_id: str) -> None:
        self.manager.cancel_task(task_id)
        self.refresh_now()

    def retry_task(self, task_id: str) -> None:
        self.manager.retry_task(task_id)
        self.refresh_now()

    def redownload_task(self, task_id: str) -> None:
        task = self.manager.get_task(task_id)
        if task is None:
            self.toast("Görev bulunamadı.", "warning")
            return
        try:
            new_task, duplicate = self.manager.add_url(
                task.url,
                quality=task.quality,
                kind=task.kind or "auto",
                title=task.title,
                page_url=task.page_url,
                referer=task.referer,
            )
        except Exception as exc:
            self.toast(f"Yeniden indirilemedi: {exc}", "error")
            return
        if duplicate:
            self.toast("Bu bağlantı zaten kuyrukta.", "warning")
        else:
            self.toast(f"Kuyruğa eklendi: {new_task.display_title()}", "success")
        self.refresh_now()

    def remove_task(self, task_id: str) -> None:
        if not self.manager.remove_task(task_id):
            self.toast("Aktif bir indirme kaldırılamaz; önce iptal edin.", "warning")
            return
        self.refresh_now()

    def open_task_file(self, task_id: str) -> None:
        task = self.manager.get_task(task_id)
        if task is None or not task.filepath:
            self.toast("Dosya yolu bulunamadı.", "warning")
            return
        if not Path(task.filepath).exists():
            self.toast("Dosya diskte bulunamadı.", "error")
            return
        try:
            open_path(task.filepath)
        except Exception as exc:
            self.toast(f"Dosya açılamadı: {exc}", "error")

    def open_task_folder(self, task_id: str) -> None:
        task = self.manager.get_task(task_id)
        target = task.filepath if task is not None and task.filepath else str(self.cfg.download_dir)
        try:
            open_in_file_manager(target)
        except Exception as exc:
            self.toast(f"Klasör açılamadı: {exc}", "error")

    def extract_audio(self, task_id: str) -> None:
        task = self.manager.get_task(task_id)
        if task is None or not task.filepath or not Path(task.filepath).exists():
            self.toast("Dosya bulunamadı.", "warning")
            return
        src = Path(task.filepath)
        dst = src.with_suffix(".mp3")
        if dst.exists():
            self.toast("MP3 zaten var.", "info")
            return
        self.toast("Ses çıkarılıyor…", "info")

        def worker():
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(src), "-vn", "-acodec", "libmp3lame", "-q:a", "2", str(dst)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
                self.post(lambda: self.toast(f"MP3 oluşturuldu: {dst.name}", "success"))
            except Exception as exc:
                self.post(lambda: self.toast(f"Ses çıkarılamadı: {exc}", "error"))

        threading.Thread(target=worker, daemon=True).start()

    def show_task_details(self, task_id: str) -> None:
        task = self.manager.get_task(task_id)
        if task is None:
            return
        show_details_dialog(self, task.snapshot())

    # ------------------------------------------------------------------ yakalananlar
    def download_capture(self, capture_id: str) -> None:
        try:
            task, duplicate = self.manager.download_capture(capture_id)
        except ValueError as exc:
            self.toast(str(exc), "error")
            return
        except Exception as exc:
            self.toast(f"İndirme başlatılamadı: {exc}", "error")
            return
        if duplicate:
            self.toast("Bu video zaten kuyrukta.", "warning")
        else:
            self.toast(f"İndirme başlatıldı: {task.display_title()}", "success")
        self.show_page("downloads")

    def remove_capture(self, capture_id: str) -> None:
        self.manager.remove_capture(capture_id)
        self.refresh_now()

    # ------------------------------------------------------------------ bildirim
    def toast(self, text: str, kind: str = "info") -> None:
        palette = {
            "success": (theme.GREEN_SOFT, theme.GREEN, "#2b6a54"),
            "error": (RED_SOFT, "#ff9aa8", "#5a2836"),
            "warning": (theme.YELLOW_SOFT, YELLOW, "#5c4724"),
            "info": (CARD_ALT, TEXT, BORDER_LIGHT),
        }
        bg, fg, border = palette.get(kind, palette["info"])
        self.toast_label.configure(text=text, bg=bg, fg=fg, highlightbackground=border)
        self.toast_label.place(relx=1.0, rely=1.0, x=-24, y=-64, anchor="se")
        self.toast_label.lift()
        if self._toast_after is not None:
            try:
                self.after_cancel(self._toast_after)
            except tk.TclError:
                pass
        self._toast_after = self.after(3800, self._hide_toast)

    def _hide_toast(self) -> None:
        self._toast_after = None
        try:
            self.toast_label.place_forget()
        except tk.TclError:
            pass

    def post(self, callback) -> None:
        self._queue.put(callback)

    def _drain_queue(self) -> None:
        if self._closing:
            return
        while True:
            try:
                callback = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                log.exception("Arka plan geri çağrısı başarısız")
        self.after(120, self._drain_queue)

    # ------------------------------------------------------------------ kapatma
    def on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.title("Abrek Download — kapatılıyor…")
        try:
            self.cfg.set("window_geometry", self.geometry())
            self.cfg.save()
        except Exception:
            log.exception("Pencere geometrisi kaydedilemedi")
        self.update_idletasks()
        try:
            self.manager.shutdown(timeout=5.0)
        except Exception:
            log.exception("İndirme yöneticisi kapatılamadı")
        if self.server is not None:
            try:
                self.server.stop()
            except Exception:
                log.exception("API sunucusu kapatılamadı")
            self.server = None
        self._closed_cleanly = True
        self._stop_tray()
        try:
            self.destroy()
        except tk.TclError:
            pass


def acquire_instance_lock():
    lock_path = STATE_DIR / "app.lock"
    try:
        handle = lock_path.open("w", encoding="utf-8")
    except OSError:
        log.exception("Kilit dosyası açılamadı")
        return None
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def show_already_running() -> None:
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            APP_NAME,
            f"{APP_NAME} zaten çalışıyor.\nAçık pencereyi görev çubuğundan veya uygulama menüsünden açabilirsiniz.",
            parent=root,
        )
        root.destroy()
    except Exception:
        print("Abrek Download zaten çalışıyor.", file=sys.stderr)


def main() -> int:
    setup_logging()
    log.info("Abrek Download başlatılıyor (sürüm %s)", VERSION)

    lock = acquire_instance_lock()
    if lock is False:
        show_already_running()
        return 0
    if lock is None:
        return 1

    config = Config()
    manager = DownloadManager(config)
    server: ApiServer | None = None
    server_error = ""
    try:
        server = ApiServer(manager)
        server.start()
    except OSError as exc:
        server_error = str(exc)
        log.error("Yerel API başlatılamadı: %s", exc)
    except Exception as exc:
        server_error = str(exc)
        log.exception("Yerel API başlatılırken beklenmeyen hata")

    app: VideoAvciApp | None = None
    exit_code = 0
    try:
        app = VideoAvciApp(config, manager, server, server_error)
        app.mainloop()
    except Exception:
        log.exception("Uygulama çöktü")
        exit_code = 1
        try:
            if app is not None:
                app.destroy()
        except Exception:
            pass
    finally:
        if app is None or not getattr(app, "_closed_cleanly", False):
            try:
                manager.shutdown(timeout=4.0)
            except Exception:
                log.exception("Kapanış temizliği başarısız")
            if server is not None:
                try:
                    server.stop()
                except Exception:
                    pass
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            lock.close()
        except Exception:
            pass
        log.info("Abrek Download kapandı")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
