"""Yakalananlar sayfası: tarayıcıdan gelen medya listesi."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from .theme import BG, BORDER, CARD, MUTED, TEXT, font, make_button
from core.i18n import t
from .widgets import CaptureCard, EmptyState, ScrollFrame


class CapturesPage(tk.Frame):
    def __init__(self, parent: tk.Misc, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self._signature: tuple | None = None
        self._captures: list[dict] = []
        self._build()

    def _build(self) -> None:
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x")

        left = tk.Frame(bar, bg=BG)
        left.pack(side="left")
        self.count_label = tk.Label(
            left,
            text=t("captures.none"),
            bg=BG,
            fg=TEXT,
            font=font(11, "bold"),
        )
        self.count_label.pack(side="left")
        tk.Label(
            left,
            text=t("captures.subtitle"),
            bg=BG,
            fg=MUTED,
            font=font(9),
        ).pack(side="left", padx=(10, 0), pady=(2, 0))

        self.clear_button = make_button(
            bar,
            t("captures.clear_all"),
            self.clear_all,
            kind="ghost",
            size=8,
            bg=BG,
        )
        self.clear_button.pack(side="right")

        self.download_all_button = make_button(
            bar,
            t("captures.download_all"),
            self.download_all,
            kind="primary",
            size=8,
            bg=BG,
        )
        self.download_all_button.pack(side="right", padx=(0, 8))

        self.capture_pause_button = make_button(
            bar,
            t("captures.pause"),
            self.toggle_capture_pause,
            kind="ghost",
            size=8,
            bg=BG,
        )
        self.capture_pause_button.pack(side="right", padx=(0, 8))

        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True, pady=(14, 0))

        self.empty = EmptyState(
            self.scroll.inner,
            "◎",
            t("captures.empty_title"),
            t("captures.empty_message"),
            t("captures.empty_action"),
            lambda: self.app.show_page("extension"),
        )
        self.empty.pack(fill="x")

        self.list_frame = tk.Frame(self.scroll.inner, bg=BG)
        self.list_frame.pack(fill="x")

    # ------------------------------------------------------------------ eylemler
    def toggle_capture_pause(self) -> None:
        paused = not bool(self.app.cfg.get("capture_paused", False))
        self.app.cfg.set("capture_paused", paused)
        self.app.cfg.save()
        self.app.toast(
            t("captures.paused_toast" if paused else "captures.resumed_toast"),
            "info",
        )
        self.app.refresh_now()

    def clear_all(self) -> None:
        if not self._captures:
            return
        if not messagebox.askyesno(
            t("captures.clear_all"),
            t("captures.clear_confirm"),
            parent=self,
        ):
            return
        self.app.manager.clear_captures()
        self.app.toast(t("captures.cleared"), "info")
        self.app.refresh_now()

    def download_all(self) -> None:
        if not self._captures:
            return
        added, duplicates = self.app.manager.download_all_captures()
        if added:
            self.app.toast(t("captures.toast.download_all", count=added), "success")
            self.app.show_page("downloads")
        elif duplicates:
            self.app.toast(t("captures.toast.all_queued"), "info")
        self.app.refresh_now()

    # ------------------------------------------------------------------ güncelle
    def update_snapshot(self, snapshot: dict) -> None:
        captures = list(snapshot.get("captures") or [])
        self._captures = captures
        paused = bool(snapshot.get("capture_paused"))
        self.capture_pause_button.configure(
            text=t("captures.resume") if paused else t("captures.pause"),
        )
        self.count_label.configure(
            text=t("captures.count", count=len(captures)) if captures else t("captures.none")
        )
        self.clear_button.configure(state="normal" if captures else "disabled")
        self.download_all_button.configure(state="normal" if captures else "disabled")
        if not captures:
            self.clear_button.configure(fg=MUTED, cursor="arrow")
            self.download_all_button.configure(cursor="arrow")
        else:
            self.clear_button.configure(fg=MUTED, cursor="hand2")
            self.download_all_button.configure(cursor="hand2")

        signature = tuple(
            (
                str(item.get("id")),
                str(item.get("title")),
                str(item.get("page_title")),
                str(item.get("kind")),
                str(item.get("media_kind")),
                str(item.get("media_info")),
                bool(item.get("drm")),
                int(item.get("size") or 0),
            )
            for item in captures
        )
        if signature == self._signature:
            return
        self._signature = signature

        for child in self.list_frame.winfo_children():
            child.destroy()

        if not captures:
            self.list_frame.pack_forget()
            self.empty.pack(fill="x")
            return

        self.empty.pack_forget()
        self.list_frame.pack(fill="x")
        for item in captures:
            card = CaptureCard(self.list_frame, self.app, item)
            card.pack(fill="x", pady=(0, 10))

        self.scroll.to_top()
