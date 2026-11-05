"""Ayarlar sayfası: indirme tercihleri, bakım ve hakkında."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from core.config import (
    DATA_DIR,
    DEFAULT_DOWNLOAD_DIR,
    LOG_DIR,
    PROJECT_DIR,
    VERSION,
)
from core.models import QUALITY_LABELS
from core.utils import open_path
from core.i18n import available_languages, current_language, t

from .theme import (
    BG,
    BG_SOFT,
    BORDER,
    CARD,
    GREEN,
    MUTED,
    RED,
    TEXT,
    TEXT_DIM,
    YELLOW,
    font,
    make_button,
    mono,
)
from .widgets import ScrollFrame

QUALITY_ORDER = ["best", "2160", "1440", "1080", "720", "480", "audio"]
QUALITY_TO_LABEL = {code: QUALITY_LABELS[code] for code in QUALITY_ORDER}
LABEL_TO_QUALITY = {label: code for code, label in QUALITY_TO_LABEL.items()}


def get_cookie_options() -> list[tuple[str, str]]:
    return [
        (t("settings.cookies.none"), "none"),
        ("Brave", "brave"),
        ("Firefox", "firefox"),
        ("Chrome", "chrome"),
        ("Chromium", "chromium"),
    ]


def get_finish_options() -> list[tuple[str, str]]:
    return [
        (t("settings.finish_action.none"), "none"),
        (t("settings.finish_action.shutdown"), "shutdown"),
        (t("settings.finish_action.suspend"), "suspend"),
    ]


class SettingsPage(tk.Frame):
    def __init__(self, parent: tk.Misc, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self._build()
        self.load_values()

    # ------------------------------------------------------------------ kurulum
    def _build(self) -> None:
        bottom = tk.Frame(self, bg=BG)
        bottom.pack(side="bottom", fill="x", pady=(12, 0))
        self.save_status = tk.Label(
            bottom,
            text="",
            bg=BG,
            fg=GREEN,
            font=font(9),
            anchor="w",
        )
        self.save_status.pack(side="left")
        self.save_button = make_button(
            bottom,
            t("settings.save_button"),
            self.save,
            kind="primary",
            size=10,
            padx=20,
            pady=8,
        )
        self.save_button.pack(side="right")

        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True)
        content = self.scroll.inner

        self._build_download_section(content)
        self._build_behavior_section(content)
        self._build_maintenance_section(content)
        self._build_about_section(content)

    def _section(self, parent: tk.Misc, title: str, subtitle: str = "") -> tk.Frame:
        card = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", pady=(0, 14))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=18, pady=16)

        tk.Label(inner, text=title, bg=CARD, fg=TEXT, font=font(12, "bold"), anchor="w").pack(fill="x")
        if subtitle:
            tk.Label(
                inner,
                text=subtitle,
                bg=CARD,
                fg=MUTED,
                font=font(9),
                anchor="w",
                justify="left",
                wraplength=760,
            ).pack(fill="x", pady=(3, 0))

        body = tk.Frame(inner, bg=CARD)
        body.pack(fill="x", pady=(14, 0))
        return body

    def _row(self, parent: tk.Misc, label: str, hint: str = "") -> tk.Frame:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(0, 12))
        left = tk.Frame(row, bg=CARD)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=label, bg=CARD, fg=TEXT, font=font(10), anchor="w").pack(fill="x")
        if hint:
            tk.Label(
                left,
                text=hint,
                bg=CARD,
                fg=MUTED,
                font=font(8),
                anchor="w",
                justify="left",
                wraplength=520,
            ).pack(fill="x", pady=(2, 0))
        return row

    def _entry(self, parent: tk.Misc, width: int = 10, justify: str = "left") -> tk.Entry:
        return tk.Entry(
            parent,
            bg=BG_SOFT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor="#6d8dff",
            font=font(10),
            width=width,
            justify=justify,
        )

    def _build_download_section(self, parent: tk.Misc) -> None:
        body = self._section(
            parent,
            t("settings.section.download"),
            t("settings.section.download_subtitle"),
        )

        row = self._row(body, t("settings.download_folder"), t("settings.download_folder_hint"))
        controls = tk.Frame(row, bg=CARD)
        controls.pack(side="right", padx=(16, 0))
        self.folder_entry = self._entry(controls, width=34)
        self.folder_entry.pack(side="left", ipady=6, ipadx=4)
        make_button(controls, t("settings.browse"), self.browse_folder, kind="ghost", size=8, bg=CARD).pack(
            side="left", padx=(6, 0)
        )
        make_button(controls, t("settings.open"), self.open_download_folder, kind="ghost", size=8, bg=CARD).pack(
            side="left", padx=(4, 0)
        )

        row = self._row(body, t("settings.concurrent"), t("settings.concurrent_hint"))
        self.concurrent_combo = ttk.Combobox(
            row, state="readonly", values=[str(i) for i in range(1, 6)], width=6, font=font(10)
        )
        self.concurrent_combo.pack(side="right", padx=(16, 0), ipady=2)

        row = self._row(body, t("settings.connections"), t("settings.connections_hint"))
        self.connections_combo = ttk.Combobox(
            row, state="readonly", values=[str(i) for i in range(1, 9)], width=6, font=font(10)
        )
        self.connections_combo.pack(side="right", padx=(16, 0), ipady=2)

        row = self._row(body, t("settings.quality"), t("settings.quality_hint"))
        self.quality_combo = ttk.Combobox(
            row,
            state="readonly",
            values=[QUALITY_TO_LABEL[code] for code in QUALITY_ORDER],
            width=18,
            font=font(10),
        )
        self.quality_combo.pack(side="right", padx=(16, 0), ipady=2)

        row = self._row(body, t("settings.speed_limit"), t("settings.speed_limit_hint"))
        controls = tk.Frame(row, bg=CARD)
        controls.pack(side="right", padx=(16, 0))
        self.speed_entry = self._entry(controls, width=8, justify="center")
        self.speed_entry.pack(side="left", ipady=6)
        tk.Label(controls, text="KB/s", bg=CARD, fg=MUTED, font=font(9)).pack(side="left", padx=(6, 0))

        row = self._row(body, t("settings.proxy"), t("settings.proxy_hint"))
        self.proxy_entry = self._entry(row, width=30)
        self.proxy_entry.pack(side="right", padx=(16, 0), ipady=6, ipadx=4)

        row = self._row(body, t("settings.cookies_file"), t("settings.cookies_file_hint"))
        controls = tk.Frame(row, bg=CARD)
        controls.pack(side="right", padx=(16, 0))
        self.cookies_file_entry = self._entry(controls, width=26)
        self.cookies_file_entry.pack(side="left", ipady=6, ipadx=4)
        make_button(
            controls,
            t("settings.browse"),
            self.browse_cookies_file,
            kind="ghost",
            size=8,
            bg=CARD,
        ).pack(side="left", padx=(6, 0))

        row = self._row(body, t("settings.api_token"), t("settings.api_token_hint"))
        self.api_token_entry = self._entry(row, width=30)
        self.api_token_entry.pack(side="right", padx=(16, 0), ipady=6, ipadx=4)

    def _build_behavior_section(self, parent: tk.Misc) -> None:
        body = self._section(
            parent,
            t("settings.behavior"),
            t("settings.section.behavior_subtitle"),
        )
        self.auto_resume_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            body,
            text=t("settings.auto_resume"),
            variable=self.auto_resume_var,
            style="TCheckbutton",
        ).pack(fill="x", pady=(0, 6))

        auto_retry_box = tk.Frame(body, bg=CARD)
        auto_retry_box.pack(fill="x", pady=(0, 6))
        self.auto_retry_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            auto_retry_box,
            text=t("settings.auto_retry"),
            variable=self.auto_retry_var,
            style="TCheckbutton",
            command=self._sync_auto_retry_controls,
        ).pack(anchor="w")
        tk.Label(
            auto_retry_box,
            text=t("settings.auto_retry_hint"),
            bg=CARD,
            fg=MUTED,
            font=font(8),
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x", padx=(24, 0), pady=(2, 0))

        retry_row = self._row(
            body,
            t("settings.auto_retry_limit"),
            t("settings.auto_retry_limit_hint"),
        )
        self.auto_retry_limit_combo = ttk.Combobox(
            retry_row,
            state="readonly",
            values=[str(index) for index in range(6)],
            width=6,
            font=font(10),
        )
        self.auto_retry_limit_combo.pack(side="right", padx=(16, 0), ipady=2)

        history_row = self._row(body, t("settings.history_limit"), t("settings.history_limit_hint"))
        self.history_combo = ttk.Combobox(
            history_row,
            state="readonly",
            values=["50", "100", "200", "500", "0"],
            width=6,
            font=font(10),
        )
        self.history_combo.pack(side="right", padx=(16, 0), ipady=2)

        self.notify_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            body,
            text=t("settings.notify_captures"),
            variable=self.notify_var,
            style="TCheckbutton",
        ).pack(fill="x", pady=(0, 6))
        self.notify_downloads_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            body,
            text=t("settings.notify_downloads"),
            variable=self.notify_downloads_var,
            style="TCheckbutton",
        ).pack(fill="x", pady=(0, 6))

        self.capture_paused_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            body,
            text=t("settings.capture_paused"),
            variable=self.capture_paused_var,
            style="TCheckbutton",
        ).pack(fill="x", pady=(0, 6))

        self.clipboard_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            body,
            text=t("settings.watch_clipboard"),
            variable=self.clipboard_var,
            style="TCheckbutton",
        ).pack(fill="x", pady=(0, 6))

        self.subtitles_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            body,
            text=t("settings.download_subtitles"),
            variable=self.subtitles_var,
            style="TCheckbutton",
        ).pack(fill="x", pady=(0, 12))

        finish_row = self._row(body, t("settings.finish_action.label"), t("settings.finish_action.hint"))
        finish_opts = get_finish_options()
        self.finish_combo = ttk.Combobox(
            finish_row,
            state="readonly",
            values=[label for label, _code in finish_opts],
            width=16,
            font=font(10),
        )
        self.finish_combo.pack(side="right")

        theme_row = self._row(body, t("settings.theme"), t("settings.theme_hint"))
        self.theme_combo = ttk.Combobox(
            theme_row,
            state="readonly",
            values=[t("settings.theme.dark"), t("settings.theme.light")],
            width=12,
            font=font(10),
        )
        self.theme_combo.pack(side="right")

        language_row = self._row(body, t("language.label"), t("language.hint"))
        self.language_combo = ttk.Combobox(
            language_row,
            state="readonly",
            values=list(available_languages().values()),
            width=12,
            font=font(10),
        )
        self.language_combo.pack(side="right")

        row = self._row(
            body,
            t("settings.cookies"),
            t("settings.cookies_hint"),
        )
        cookie_opts = get_cookie_options()
        self.cookies_combo = ttk.Combobox(
            row,
            state="readonly",
            values=[label for label, _code in cookie_opts],
            width=14,
            font=font(10),
        )
        self.cookies_combo.pack(side="right", padx=(16, 0), ipady=2)

    def _build_maintenance_section(self, parent: tk.Misc) -> None:
        body = self._section(
            parent,
            t("settings.section.maintenance"),
            t("settings.section.maintenance_subtitle"),
        )

        row = self._row(body, t("settings.ytdlp_version"), t("settings.ytdlp_version_hint"))
        self.ytdlp_version_label = tk.Label(
            row,
            text="—",
            bg=CARD,
            fg=TEXT_DIM,
            font=mono(9),
        )
        self.ytdlp_version_label.pack(side="right", padx=(16, 0))
        self.update_button = make_button(
            row,
            t("settings.ytdlp_btn"),
            self.update_ytdlp,
            kind="subtle",
            size=8,
            bg=CARD,
        )
        self.update_button.pack(side="right", padx=(10, 0))
        self.ytdlp_status = tk.Label(body, text="", bg=CARD, fg=MUTED, font=font(8), anchor="w")
        self.ytdlp_status.pack(fill="x", pady=(0, 10))

        row = self._row(body, t("settings.app_data"), str(DATA_DIR))
        make_button(row, t("settings.open"), lambda: self._open(DATA_DIR), kind="ghost", size=8, bg=CARD).pack(
            side="right", padx=(16, 0)
        )

        row = self._row(body, t("settings.logs"), str(LOG_DIR))
        make_button(row, t("settings.open"), lambda: self._open(LOG_DIR), kind="ghost", size=8, bg=CARD).pack(
            side="right", padx=(16, 0)
        )

    def _build_about_section(self, parent: tk.Misc) -> None:
        body = self._section(parent, t("settings.section.about"), "")
        tk.Label(
            body,
            text=f"Abrek Download  v{VERSION}",
            bg=CARD,
            fg=TEXT,
            font=font(10, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            body,
            text=t("settings.project_folder", path=PROJECT_DIR),
            bg=CARD,
            fg=MUTED,
            font=mono(8),
            anchor="w",
        ).pack(fill="x", pady=(4, 0))
        tk.Label(
            body,
            text=t("settings.about_text"),
            bg=BG_SOFT,
            fg=TEXT_DIM,
            font=font(9),
            anchor="w",
            justify="left",
            wraplength=780,
            padx=12,
            pady=10,
        ).pack(fill="x", pady=(10, 0))

    # ------------------------------------------------------------------ değerler
    def load_values(self) -> None:
        config = self.app.cfg
        self.folder_entry.delete(0, "end")
        self.folder_entry.insert(0, str(config.get("download_dir") or DEFAULT_DOWNLOAD_DIR))
        self.concurrent_combo.set(str(config.get("max_concurrent", 2)))
        self.connections_combo.set(str(config.get("connections", 4)))
        quality = str(config.get("default_quality", "best") or "best")
        self.quality_combo.set(QUALITY_TO_LABEL.get(quality, QUALITY_TO_LABEL["best"]))
        self.speed_entry.delete(0, "end")
        self.speed_entry.insert(0, str(config.get("speed_limit_kbps", 0)))
        self.proxy_entry.delete(0, "end")
        self.proxy_entry.insert(0, str(config.get("proxy") or ""))
        self.cookies_file_entry.delete(0, "end")
        self.cookies_file_entry.insert(0, str(config.get("cookies_file") or ""))
        self.api_token_entry.delete(0, "end")
        self.api_token_entry.insert(0, str(config.get("api_token") or ""))
        try:
            history_limit = max(0, min(2000, int(config.get("history_limit", 200))))
        except (TypeError, ValueError):
            history_limit = 200
        self.history_combo.set(str(history_limit))
        self.auto_resume_var.set(bool(config.get("auto_resume", True)))
        self.auto_retry_var.set(bool(config.get("auto_retry", True)))
        try:
            retry_limit = max(0, min(5, int(config.get("auto_retry_limit", 2) or 0)))
        except (TypeError, ValueError):
            retry_limit = 2
        self.auto_retry_limit_combo.set(str(retry_limit))
        self._sync_auto_retry_controls()
        self.notify_var.set(bool(config.get("notify_captures", True)))
        self.notify_downloads_var.set(bool(config.get("notify_downloads", True)))
        self.capture_paused_var.set(bool(config.get("capture_paused", False)))
        self.clipboard_var.set(bool(config.get("watch_clipboard", False)))
        self.subtitles_var.set(bool(config.get("download_subtitles", False)))
        finish_action = str(config.get("shutdown_on_finish", "none") or "none")
        finish_map = {code: label for label, code in get_finish_options()}
        self.finish_combo.set(finish_map.get(finish_action, t("settings.finish_action.none")))

        self.theme_combo.set(
            t("settings.theme.light") if str(config.get("theme", "dark")) == "light" else t("settings.theme.dark")
        )
        langs = available_languages()
        saved_lang = str(config.get("language") or current_language())
        self.language_combo.set(langs.get(saved_lang, langs.get("tr", "Türkçe")))

        cookies = str(config.get("cookies_browser", "none") or "none")
        cookie_map = {code: label for label, code in get_cookie_options()}
        self.cookies_combo.set(cookie_map.get(cookies, t("settings.cookies.none")))
        self.refresh_ytdlp_version()

    def refresh_ytdlp_version(self) -> None:
        try:
            version = self.app.manager.ytdlp_version()
        except Exception:
            version = t("settings.ytdlp_not_found")
        self.ytdlp_version_label.configure(text=version or t("settings.ytdlp_not_found"))

    # ------------------------------------------------------------------ eylemler
    def browse_folder(self) -> None:
        initial = self.folder_entry.get().strip() or str(DEFAULT_DOWNLOAD_DIR)
        folder = filedialog.askdirectory(parent=self, initialdir=initial, title=t("settings.dialog.browse_title"))
        if folder:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, folder)

    def browse_cookies_file(self) -> None:
        current = self.cookies_file_entry.get().strip()
        initial = str(Path(os.path.expanduser(current)).parent) if current else str(Path.home())
        path = filedialog.askopenfilename(
            parent=self,
            initialdir=initial,
            title=t("settings.cookies_file_dialog"),
            filetypes=[("cookies.txt", "*.txt"), (t("settings.all_files"), "*")],
        )
        if path:
            self.cookies_file_entry.delete(0, "end")
            self.cookies_file_entry.insert(0, path)

    def open_download_folder(self) -> None:
        folder = self.folder_entry.get().strip() or str(DEFAULT_DOWNLOAD_DIR)
        self._open(Path(folder).expanduser())

    def _open(self, path) -> None:
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            open_path(path)
        except Exception as exc:
            self.app.toast(t("settings.err.open_failed", error=exc), "error")

    def save(self) -> None:
        folder_text = self.folder_entry.get().strip()
        if not folder_text:
            self.app.toast(t("settings.err.folder_empty"), "warning")
            return
        folder = Path(os.path.expanduser(folder_text))
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.app.toast(t("settings.err.folder_create", error=exc), "error")
            return
        if not os.access(folder, os.W_OK):
            self.app.toast(t("settings.err.folder_no_write"), "error")
            return

        old_theme = str(self.app.cfg.get("theme", "dark") or "dark")
        old_language = str(self.app.cfg.get("language") or current_language())

        try:
            max_concurrent = self._parse_int(self.concurrent_combo.get(), t("settings.concurrent"), 1, 5)
            connections = self._parse_int(self.connections_combo.get(), t("settings.connections"), 1, 8)
            speed_limit = self._parse_int(self.speed_entry.get().strip(), t("settings.speed_limit"), 0, 1_000_000)
        except ValueError as exc:
            self.app.toast(str(exc), "error")
            return

        proxy_text = self.proxy_entry.get().strip()
        if "://" in proxy_text:
            scheme = proxy_text.split("://", 1)[0].lower()
            if scheme not in {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}:
                self.app.toast(t("settings.err.proxy_scheme"), "error")
                return

        cookies_file_text = self.cookies_file_entry.get().strip()
        if cookies_file_text:
            expanded = Path(os.path.expanduser(cookies_file_text))
            if not expanded.is_file():
                self.app.toast(t("settings.err.cookies_file"), "error")
                return
            cookies_file_text = str(expanded)

        api_token_text = self.api_token_entry.get().strip()
        if api_token_text and len(api_token_text) < 8:
            self.app.toast(t("settings.err.api_token_short"), "error")
            return

        try:
            history_limit = self._parse_int(
                self.history_combo.get(), t("settings.history_limit"), 0, 2000
            )
        except ValueError as exc:
            self.app.toast(str(exc), "error")
            return

        try:
            auto_retry_limit = self._parse_int(
                self.auto_retry_limit_combo.get(),
                t("settings.auto_retry_limit"),
                0,
                5,
            )
        except ValueError as exc:
            self.app.toast(str(exc), "error")
            return

        quality = LABEL_TO_QUALITY.get(self.quality_combo.get(), "best")
        cookie_label_to_code = {label: code for label, code in get_cookie_options()}
        cookies = cookie_label_to_code.get(self.cookies_combo.get(), "none")

        finish_label_to_code = {label: code for label, code in get_finish_options()}
        finish_action = finish_label_to_code.get(self.finish_combo.get(), "none")

        selected_lang_name = self.language_combo.get()
        selected_lang_code = "tr"
        for code, name in available_languages().items():
            if name == selected_lang_name:
                selected_lang_code = code
                break

        theme_val = "light" if self.theme_combo.get() == t("settings.theme.light") else "dark"

        self.app.cfg.update(
            {
                "download_dir": str(folder),
                "max_concurrent": max_concurrent,
                "connections": connections,
                "speed_limit_kbps": speed_limit,
                "default_quality": quality,
                "cookies_browser": cookies,
                "cookies_file": cookies_file_text,
                "proxy": proxy_text,
                "history_limit": history_limit,
                "api_token": api_token_text,
                "language": selected_lang_code,
                "auto_resume": bool(self.auto_resume_var.get()),
                "auto_retry": bool(self.auto_retry_var.get()),
                "auto_retry_limit": auto_retry_limit,
                "notify_captures": bool(self.notify_var.get()),
                "notify_downloads": bool(self.notify_downloads_var.get()),
                "capture_paused": bool(self.capture_paused_var.get()),
                "watch_clipboard": bool(self.clipboard_var.get()),
                "download_subtitles": bool(self.subtitles_var.get()),
                "shutdown_on_finish": finish_action,
                "theme": theme_val,
            }
        )
        self.save_status.configure(text=t("settings.saved"), fg=GREEN)
        self.after(3200, lambda: self.save_status.configure(text=""))
        self.app.pages["downloads"].sync_default_quality()
        if theme_val != old_theme or selected_lang_code != old_language:
            self.app.toast(t("settings.restart_required"), "warning")
        else:
            self.app.toast(t("settings.saved_toast"), "success")

    def _sync_auto_retry_controls(self) -> None:
        try:
            self.auto_retry_limit_combo.configure(
                state="readonly" if self.auto_retry_var.get() else "disabled"
            )
        except (AttributeError, tk.TclError):
            pass

    def _parse_int(self, value: str, name: str, low: int, high: int) -> int:
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError(t("settings.err.enter_number", name=name))
        if not low <= number <= high:
            raise ValueError(t("settings.err.range", name=name, low=low, high=high))
        return number

    def update_ytdlp(self) -> None:
        self.update_button.configure(state="disabled", text=t("settings.ytdlp_updating_btn"))
        self.ytdlp_status.configure(text=t("settings.ytdlp_updating"), fg=YELLOW)

        def callback(ok: bool, output: str) -> None:
            self.app.post(lambda: self._finish_update(ok, output))

        self.app.manager.update_ytdlp(callback)

    def _finish_update(self, ok: bool, output: str) -> None:
        self.update_button.configure(state="normal", text=t("settings.ytdlp_btn"))
        self.refresh_ytdlp_version()
        if ok:
            self.ytdlp_status.configure(text=t("settings.ytdlp_updated"), fg=GREEN)
            self.app.toast(t("settings.ytdlp_updated"), "success")
        else:
            message = (output or t("settings.ytdlp_failed")).strip().splitlines()[-1:]
            detail = message[0] if message else t("settings.ytdlp_failed")
            self.ytdlp_status.configure(text=f"{t('settings.ytdlp_failed')}: {detail[:180]}", fg=RED)
            self.app.toast(t("settings.ytdlp_failed"), "error")

    def on_show(self) -> None:
        self.refresh_ytdlp_version()
        self.capture_paused_var.set(bool(self.app.cfg.get("capture_paused", False)))
