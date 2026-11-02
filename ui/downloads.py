"""İndirilenler sayfası: yeni indirme, filtreler ve görev kartları."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from core.i18n import t
from core.models import QUALITY_LABELS

from . import theme
from .theme import (
    ACCENT,
    ACCENT_SOFT,
    BG,
    BORDER,
    CARD,
    CARD_HOVER,
    MUTED,
    TEXT,
    TEXT_DIM,
    font,
    make_button,
)
from .widgets import EmptyState, PlaceholderEntry, ScrollFrame, TaskCard

QUALITY_ORDER = ["best", "2160", "1440", "1080", "720", "480", "audio"]
QUALITY_TO_LABEL = {code: QUALITY_LABELS[code] for code in QUALITY_ORDER}
LABEL_TO_QUALITY = {label: code for code, label in QUALITY_TO_LABEL.items()}

FILTER_KEYS = [
    ("all", "downloads.filter.all"),
    ("active", "downloads.filter.active"),
    ("completed", "downloads.filter.completed"),
    ("error", "downloads.filter.error"),
]

STATUS_PRIORITY = {
    "starting": 0,
    "analyzing": 0,
    "downloading": 0,
    "processing": 0,
    "pausing": 0,
    "canceling": 0,
    "queued": 1,
    "paused": 2,
    "error": 3,
    "completed": 4,
    "canceled": 5,
}


class DownloadsPage(tk.Frame):
    def __init__(self, parent: tk.Misc, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self.cards: dict[str, TaskCard] = {}
        self._order: tuple[str, ...] = ()
        self._filter = "all"
        self._filter_buttons: dict[str, tk.Button] = {}
        self._tasks: list[dict] = []
        self._search_query = ""
        self._checking_playlist = False
        self._build()

    # ------------------------------------------------------------------ kurulum
    def _build(self) -> None:
        self._build_add_card()
        self._build_filter_bar()

        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True, pady=(14, 0))

        self.empty = EmptyState(
            self.scroll.inner,
            "↓",
            t("downloads.empty_title"),
            t("downloads.empty_message"),
            t("downloads.empty_action_captures"),
            lambda: self.app.show_page("captures"),
        )
        self.empty.pack(fill="x")

    def _build_add_card(self) -> None:
        card = tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x")

        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=18, pady=(15, 16))

        head = tk.Frame(inner, bg=CARD)
        head.pack(fill="x", pady=(0, 10))
        tk.Label(head, text=t("downloads.new_download"), bg=CARD, fg=TEXT, font=font(12, "bold")).pack(side="left")
        tk.Label(
            head,
            text=t("downloads.new_download_subtitle"),
            bg=CARD,
            fg=MUTED,
            font=font(9),
        ).pack(side="left", padx=(10, 0), pady=(3, 0))

        paste = make_button(head, t("downloads.paste"), self.paste_from_clipboard, kind="link", size=9, bg=CARD, pady=2)
        paste.pack(side="right")

        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x")

        self.url_entry = PlaceholderEntry(
            row,
            placeholder=t("downloads.url_placeholder"),
            bg=theme.CARD_ALT,
            font=font(11),
        )
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.url_entry.bind("<Return>", lambda _event: self.add_download())

        self.quality_combo = ttk.Combobox(
            row,
            state="readonly",
            values=[QUALITY_TO_LABEL[code] for code in QUALITY_ORDER],
            width=17,
            font=font(9),
        )
        self.quality_combo.pack(side="left", padx=(10, 0), ipady=2)
        default_quality = str(self.app.cfg.get("default_quality", "best") or "best")
        self.quality_combo.set(QUALITY_TO_LABEL.get(default_quality, QUALITY_TO_LABEL["best"]))

        self.add_button = make_button(
            row,
            t("downloads.download"),
            self.add_download,
            kind="primary",
            size=10,
            padx=22,
            pady=9,
        )
        self.add_button.pack(side="left", padx=(10, 0))

    def _build_filter_bar(self) -> None:
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", pady=(16, 0))

        chips = tk.Frame(bar, bg=BG)
        chips.pack(side="left")
        for key, text_key in FILTER_KEYS:
            button = tk.Button(
                chips,
                text=t(text_key),
                command=lambda k=key: self.set_filter(k),
                bg=BG,
                fg=TEXT_DIM,
                activebackground=CARD_HOVER,
                activeforeground=TEXT,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=BORDER,
                cursor="hand2",
                font=font(9, "bold"),
                padx=12,
                pady=5,
                takefocus=0,
            )
            button.pack(side="left", padx=(0, 7))
            self._filter_buttons[key] = button

        self.search_entry = PlaceholderEntry(
            chips,
            placeholder=t("downloads.search_placeholder"),
            bg=CARD,
            fg=TEXT,
            width=20,
            font=font(9),
        )
        self.search_entry.pack(side="left", padx=(10, 0), ipady=3)
        self.search_entry.bind("<KeyRelease>", lambda _e: self._on_search_change())

        actions = tk.Frame(bar, bg=BG)
        actions.pack(side="right")
        make_button(actions, t("downloads.pause_all"), self.pause_all, kind="ghost", size=8, bg=BG).pack(side="left", padx=(0, 6))
        make_button(actions, t("downloads.resume_all"), self.resume_all, kind="ghost", size=8, bg=BG).pack(side="left", padx=(0, 6))
        make_button(actions, t("downloads.retry_failed"), self.retry_failed, kind="ghost", size=8, bg=BG).pack(side="left", padx=(0, 6))
        make_button(actions, t("downloads.clear_finished"), self.clear_finished, kind="ghost", size=8, bg=BG).pack(side="left", padx=(0, 6))
        make_button(actions, t("downloads.clear_all"), self.clear_all, kind="danger", size=8, bg=BG).pack(side="left")

        self._paint_filters()

    # ------------------------------------------------------------------ eylemler
    def add_download(self) -> None:
        if self._checking_playlist:
            return
        url = self.url_entry.value()
        if not url:
            self.app.toast(t("downloads.toast.no_url"), "warning")
            self.url_entry.focus_set()
            return
        label = self.quality_combo.get()
        quality = LABEL_TO_QUALITY.get(label, "best")

        # Ağ isteği Tk ana iş parçacığını kilitlememeli; liste kontrolünü
        # arka planda yapıp sonucu ``app.post`` ile arayüze taşı.
        if "list=" in url or "playlist" in url.lower():
            self._check_playlist_async(url, quality)
            return
        self._queue_url(url, quality)

    def _check_playlist_async(self, url: str, quality: str) -> None:
        self._checking_playlist = True
        self.add_button.configure(state="disabled", text=t("downloads.checking_playlist"))

        def worker() -> None:
            try:
                info = self.app.manager.check_playlist(url)
            except Exception:
                info = None
            self.app.post(lambda: self._playlist_result(url, quality, info))

        threading.Thread(
            target=worker,
            name="videoavci-playlist-check",
            daemon=True,
        ).start()

    def _playlist_result(self, url: str, quality: str, info: dict | None) -> None:
        self._checking_playlist = False
        try:
            self.add_button.configure(state="normal", text=t("downloads.download"))
        except tk.TclError:
            return
        try:
            items = list((info or {}).get("items") or [])
            if len(items) > 1:
                title = (info or {}).get("title") or t("downloads.playlist_default_title")
                ans = messagebox.askyesnocancel(
                    t("downloads.playlist_dialog_title"),
                    t("downloads.playlist_dialog_msg", title=title, count=len(items)),
                    parent=self,
                )
                if ans is True:
                    added = self.app.manager.add_playlist_items(items, quality=quality)
                    self.app.toast(t("downloads.toast.playlist_queued", count=added), "success")
                    self.url_entry.clear()
                    self.app.refresh_now()
                    return
                if ans is None:
                    return
        except Exception:
            pass
        self._queue_url(url, quality)

    def _queue_url(self, url: str, quality: str) -> None:
        try:
            task, duplicate = self.app.manager.add_url(url, quality=quality)
        except ValueError as exc:
            self.app.toast(str(exc), "error")
            return
        except Exception as exc:
            self.app.toast(t("downloads.toast.add_failed", error=exc), "error")
            return
        if duplicate:
            self.app.toast(t("downloads.toast.already_queued"), "warning")
        else:
            self.app.toast(t("downloads.toast.queued", title=task.display_title()), "success")
            self.url_entry.clear()
        self.app.refresh_now()

    def paste_from_clipboard(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            self.app.toast(t("downloads.toast.no_clipboard"), "warning")
            return
        text = (text or "").strip()
        if not text:
            self.app.toast(t("downloads.toast.no_clipboard"), "warning")
            return
        self.url_entry.set_value(text)
        self.url_entry.icursor("end")
        self.url_entry.focus_set()

    def set_filter(self, key: str) -> None:
        if key == self._filter:
            return
        self._filter = key
        self._paint_filters()
        self._order = ()
        self.update_tasks(self._tasks)

    def _paint_filters(self) -> None:
        for key, button in self._filter_buttons.items():
            if key == self._filter:
                button.configure(bg=ACCENT_SOFT, fg=ACCENT, highlightbackground="#33477d")
            else:
                button.configure(bg=BG, fg=TEXT_DIM, highlightbackground=BORDER)

    def pause_all(self) -> None:
        self.app.manager.pause_all()
        self.app.toast(t("downloads.toast.all_paused"), "info")
        self.app.refresh_now()

    def resume_all(self) -> None:
        self.app.manager.resume_all()
        self.app.toast(t("downloads.toast.all_resumed"), "success")
        self.app.refresh_now()

    def retry_failed(self) -> None:
        count = self.app.manager.retry_failed()
        if count:
            self.app.toast(t("downloads.toast.retry_failed", count=count), "success")
        else:
            self.app.toast(t("downloads.toast.no_failed"), "info")
        self.app.refresh_now()

    def clear_finished(self) -> None:
        if not messagebox.askyesno(
            t("downloads.confirm_clear_title"),
            t("downloads.confirm_clear_message"),
            parent=self,
        ):
            return
        self.app.manager.clear_finished()
        self.app.refresh_now()

    def clear_all(self) -> None:
        if not messagebox.askyesno(
            t("downloads.confirm_clear_all_title"),
            t("downloads.confirm_clear_all_message"),
            parent=self,
        ):
            return
        self.app.manager.clear_queue()
        self.app.toast(t("downloads.toast.cleared_all"), "info")
        self.app.refresh_now()

    def focus_url(self) -> None:
        self.url_entry.focus_set()
        self.url_entry.select_range(0, "end")

    def _on_search_change(self) -> None:
        self._search_query = self.search_entry.value().strip()
        self.update_tasks(self._tasks)

    # ------------------------------------------------------------------ güncelle
    def update_snapshot(self, snapshot: dict) -> None:
        self._tasks = list(snapshot.get("tasks") or [])
        self.update_tasks(self._tasks)

    def update_tasks(self, tasks: list[dict]) -> None:
        counts = {
            "all": len(tasks),
            "active": sum(1 for t_item in tasks if t_item.get("status") not in {"completed", "error", "canceled"}),
            "completed": sum(1 for t_item in tasks if t_item.get("status") == "completed"),
            "error": sum(1 for t_item in tasks if t_item.get("status") == "error"),
        }
        for key, text_key in FILTER_KEYS:
            self._filter_buttons[key].configure(text=f"{t(text_key)}  {counts[key]}")

        filtered = tasks
        if self._search_query:
            q = self._search_query.lower()
            filtered = [
                t_item for t_item in filtered
                if q in (t_item.get("display_title") or "").lower() or q in (t_item.get("url") or "").lower()
            ]

        if self._filter == "active":
            filtered = [
                t_item for t_item in filtered
                if t_item.get("status") not in {"completed", "error", "canceled"}
            ]
        elif self._filter == "completed":
            filtered = [t_item for t_item in filtered if t_item.get("status") == "completed"]
        elif self._filter == "error":
            filtered = [t_item for t_item in filtered if t_item.get("status") == "error"]

        filtered = sorted(
            filtered,
            key=lambda t_item: (
                STATUS_PRIORITY.get(str(t_item.get("status")), 9),
                -float(t_item.get("created_at") or 0),
            ),
        )
        desired = tuple(str(t_item.get("id")) for t_item in filtered)

        for task_id in list(self.cards):
            if task_id not in desired:
                self.cards.pop(task_id).destroy()

        for task in filtered:
            task_id = str(task.get("id"))
            card = self.cards.get(task_id)
            if card is None:
                card = TaskCard(self.scroll.inner, self.app, task)
                self.cards[task_id] = card
            else:
                card.update_data(task)

        if desired != self._order:
            for task_id in desired:
                self.cards[task_id].pack_forget()
            for task_id in desired:
                self.cards[task_id].pack(fill="x", pady=(0, 10))
            self._order = desired

        if filtered:
            self.empty.pack_forget()
        else:
            if tasks:
                self.empty.title_label.configure(text=t("downloads.empty_filtered_title"))
                self.empty.message_label.configure(
                    text=t("downloads.empty_filtered_message")
                )
            else:
                self.empty.title_label.configure(text=t("downloads.empty_title"))
                self.empty.message_label.configure(
                    text=t("downloads.empty_message")
                )
            self.empty.pack(fill="x")
