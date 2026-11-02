"""Eklenti sayfası: tarayıcı kurulum adımları ve bağlantı testi."""

from __future__ import annotations

import json
import threading
import tkinter as tk
import urllib.error
import urllib.request

from core.config import PROJECT_DIR
from core.i18n import t
from core.utils import open_path

from .theme import (
    ACCENT,
    ACCENT_SOFT,
    BG,
    BG_SOFT,
    BLUE,
    BLUE_SOFT,
    BORDER,
    CARD,
    GREEN,
    GREEN_SOFT,
    MUTED,
    PURPLE,
    PURPLE_SOFT,
    RED,
    RED_SOFT,
    TEXT,
    TEXT_DIM,
    YELLOW,
    font,
    make_button,
    mono,
)
from .widgets import ScrollFrame

CHROME_DIR = PROJECT_DIR / "extension" / "chrome"
FIREFOX_DIR = PROJECT_DIR / "extension" / "firefox"


class ExtensionPage(tk.Frame):
    def __init__(self, parent: tk.Misc, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self._testing = False
        self._build()

    # ------------------------------------------------------------------ kurulum
    def _build(self) -> None:
        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True)
        content = self.scroll.inner

        self._build_hero(content)
        self._build_browser_card(
            content,
            t("extension.brave_title"),
            t("extension.brave_badge"),
            ACCENT,
            ACCENT_SOFT,
            CHROME_DIR,
            [
                t("extension.brave_step1"),
                t("extension.brave_step2"),
                t("extension.brave_step3"),
                t("extension.brave_step4"),
            ],
            t("extension.brave_tip"),
        )
        self._build_browser_card(
            content,
            t("extension.firefox_title"),
            t("extension.firefox_badge"),
            PURPLE,
            PURPLE_SOFT,
            FIREFOX_DIR,
            [
                t("extension.firefox_step1"),
                t("extension.firefox_step2"),
                t("extension.firefox_step3"),
            ],
            t("extension.firefox_note"),
        )
        self._build_test_card(content)
        self._build_note(content)

    def _build_hero(self, parent: tk.Misc) -> None:
        card = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", pady=(0, 14))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=18, pady=16)

        left = tk.Frame(inner, bg=CARD)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(
            left,
            text=t("extension.hero_title"),
            bg=CARD,
            fg=TEXT,
            font=font(15, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            left,
            text=t("extension.hero_desc"),
            bg=CARD,
            fg=MUTED,
            font=font(9),
            anchor="w",
            justify="left",
            wraplength=600,
        ).pack(fill="x", pady=(5, 0))

        self.status_chip = tk.Label(
            inner,
            text=t("extension.bridge_working"),
            bg=GREEN_SOFT,
            fg=GREEN,
            font=font(9, "bold"),
            padx=11,
            pady=5,
        )
        self.status_chip.pack(side="right", anchor="n", padx=(16, 0))

    def _build_browser_card(
        self,
        parent: tk.Misc,
        title: str,
        badge_text: str,
        color: str,
        tint: str,
        path,
        steps: list[str],
        note: str,
    ) -> None:
        card = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", pady=(0, 14))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=18, pady=16)

        head = tk.Frame(inner, bg=CARD)
        head.pack(fill="x")
        tk.Label(
            head,
            text=badge_text,
            bg=tint,
            fg=color,
            font=font(8, "bold"),
            padx=8,
            pady=3,
        ).pack(side="left")
        tk.Label(head, text=title, bg=CARD, fg=TEXT, font=font(13, "bold")).pack(side="left", padx=(10, 0))

        path_row = tk.Frame(inner, bg=CARD)
        path_row.pack(fill="x", pady=(12, 10))
        entry = tk.Entry(
            path_row,
            bg=BG_SOFT,
            fg=TEXT_DIM,
            readonlybackground=BG_SOFT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            font=mono(9),
        )
        entry.insert(0, str(path))
        entry.configure(state="readonly")
        entry.pack(side="left", fill="x", expand=True, ipady=7)

        make_button(
            path_row,
            t("extension.copy"),
            lambda p=str(path): self.copy_path(p),
            kind="ghost",
            size=8,
            bg=CARD,
        ).pack(side="left", padx=(8, 0))
        make_button(
            path_row,
            t("extension.open_folder"),
            lambda p=str(path): self.open_folder(p),
            kind="subtle",
            size=8,
            bg=CARD,
        ).pack(side="left", padx=(6, 0))

        steps_frame = tk.Frame(inner, bg=CARD)
        steps_frame.pack(fill="x")
        for index, step in enumerate(steps, start=1):
            self._step(steps_frame, index, step)

        tk.Label(
            inner,
            text=note,
            bg=BG_SOFT,
            fg=MUTED,
            font=font(8),
            anchor="w",
            justify="left",
            wraplength=760,
            padx=10,
            pady=7,
        ).pack(fill="x", pady=(10, 0))

    def _step(self, parent: tk.Misc, number: int, text: str) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(0, 6))
        marker = tk.Canvas(row, width=22, height=22, bg=CARD, highlightthickness=0, bd=0)
        marker.pack(side="left", padx=(0, 9))
        marker.create_oval(1, 1, 21, 21, fill=ACCENT_SOFT, outline="")
        marker.create_text(11, 11, text=str(number), fill=ACCENT, font=font(8, "bold"))
        tk.Label(
            row,
            text=text,
            bg=CARD,
            fg=TEXT_DIM,
            font=font(9),
            anchor="w",
            justify="left",
            wraplength=760,
        ).pack(side="left", fill="x", expand=True)

    def _build_test_card(self, parent: tk.Misc) -> None:
        card = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", pady=(0, 14))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=18, pady=16)

        tk.Label(inner, text=t("extension.test_title"), bg=CARD, fg=TEXT, font=font(12, "bold"), anchor="w").pack(fill="x")
        tk.Label(
            inner,
            text=t("extension.test_desc"),
            bg=CARD,
            fg=MUTED,
            font=font(9),
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(12, 0))
        self.test_button = make_button(row, t("extension.test_button"), self.test_connection, kind="primary", size=9, padx=16)
        self.test_button.pack(side="left")
        self.test_result = tk.Label(
            row,
            text=t("extension.test_not_tested"),
            bg=CARD,
            fg=MUTED,
            font=font(9),
            anchor="w",
        )
        self.test_result.pack(side="left", padx=(12, 0), fill="x", expand=True)

        tk.Label(
            inner,
            text="http://127.0.0.1:8765/api/health",
            bg=BG_SOFT,
            fg="#65708a",
            font=mono(8),
            anchor="w",
            padx=10,
            pady=6,
        ).pack(fill="x", pady=(10, 0))

    def _build_note(self, parent: tk.Misc) -> None:
        tk.Label(
            parent,
            text=t("extension.disclaimer"),
            bg=BG,
            fg=MUTED,
            font=font(8),
            anchor="w",
            justify="left",
            wraplength=780,
        ).pack(fill="x", pady=(0, 16))

    # ------------------------------------------------------------------ eylemler
    def copy_path(self, path: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(path)
            self.app.toast(t("extension.path_copied"), "success")
        except tk.TclError:
            self.app.toast(t("extension.path_copy_failed"), "error")

    def open_folder(self, path: str) -> None:
        try:
            open_path(path)
        except Exception as exc:
            self.app.toast(t("extension.folder_open_failed", error=exc), "error")

    def test_connection(self) -> None:
        if self._testing:
            return
        self._testing = True
        self.test_button.configure(state="disabled", text=t("extension.test_testing"))
        self.test_result.configure(text=t("extension.test_connecting"), fg=YELLOW)

        def worker() -> None:
            result: tuple[bool, str]
            try:
                request = urllib.request.Request(
                    "http://127.0.0.1:8765/api/health",
                    headers={"Accept": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("ok"):
                    result = (True, t("extension.test_connected", version=payload.get("ytdlp") or "—"))
                else:
                    result = (False, t("extension.test_invalid_resp"))
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                result = (False, t("extension.test_failed", error=exc))
            self.app.post(lambda: self._finish_test(result))

        threading.Thread(target=worker, name="videoavci-test", daemon=True).start()

    def _finish_test(self, result: tuple[bool, str]) -> None:
        self._testing = False
        ok, message = result
        self.test_button.configure(state="normal", text=t("extension.test_button"))
        self.test_result.configure(text=message, fg=GREEN if ok else RED)

    def refresh_status(self, server_ok: bool, error: str = "") -> None:
        if server_ok:
            self.status_chip.configure(text=t("extension.bridge_working"), bg=GREEN_SOFT, fg=GREEN)
        else:
            self.status_chip.configure(text=t("extension.bridge_offline"), bg=RED_SOFT, fg=RED)
            if error:
                self.test_result.configure(text=t("extension.bridge_failed", error=error), fg=RED)
