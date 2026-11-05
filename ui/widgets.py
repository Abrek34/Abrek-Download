"""Yeniden kullanılabilir arayüz parçaları: kaydırma, kartlar, giriş alanı."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

from core.i18n import t
from core.utils import human_duration, human_eta, human_size, human_speed

from . import theme
from .theme import (
    ACCENT,
    ACCENT_SOFT,
    BG,
    BG_SOFT,
    BORDER,
    BORDER_LIGHT,
    CARD,
    CARD_ALT,
    CARD_HOVER,
    GREEN,
    MUTED,
    RED,
    TEXT,
    TEXT_DIM,
    YELLOW,
    draw_progress,
    draw_status_icon,
    ellipsize,
    font,
    make_badge,
    make_button,
    mono,
    status_color,
    status_tint,
)


class ScrollFrame(tk.Frame):
    """Dikey kaydırılabilen içerik alanı."""

    def __init__(self, parent: tk.Misc, bg: str = BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_inner_configure(self, _event=None) -> None:
        bbox = self.canvas.bbox("all")
        if bbox:
            self.canvas.configure(scrollregion=bbox)

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._on_inner_configure()

    def scroll_by(self, units: int) -> None:
        self.canvas.yview_scroll(units, "units")

    def to_top(self) -> None:
        self.canvas.yview_moveto(0)


class PlaceholderEntry(tk.Entry):
    """Odaklanınca temizlenen ipucu metinli giriş alanı."""

    def __init__(
        self,
        parent: tk.Misc,
        placeholder: str = "",
        bg: str = CARD_ALT,
        fg: str = TEXT,
        **kwargs,
    ):
        kwargs.setdefault("font", font(11))
        super().__init__(
            parent,
            bg=bg,
            fg=fg,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            **kwargs,
        )
        self.placeholder = placeholder
        self._normal_fg = fg
        self._showing = False
        self.bind("<FocusIn>", self._on_focus_in, add="+")
        self.bind("<FocusOut>", self._on_focus_out, add="+")
        self._show_placeholder()

    def _show_placeholder(self) -> None:
        if not super().get():
            self._showing = True
            self.configure(fg=MUTED)
            self.insert(0, self.placeholder)

    def _on_focus_in(self, _event=None) -> None:
        if self._showing:
            self.delete(0, "end")
            self.configure(fg=self._normal_fg)
            self._showing = False

    def _on_focus_out(self, _event=None) -> None:
        if not super().get():
            self._show_placeholder()

    def value(self) -> str:
        if self._showing:
            return ""
        return super().get().strip()

    def set_value(self, value: str) -> None:
        self._showing = False
        self.configure(fg=self._normal_fg)
        self.delete(0, "end")
        self.insert(0, value)

    def clear(self) -> None:
        self._showing = False
        self.delete(0, "end")
        self.configure(fg=self._normal_fg)
        if self.focus_get() is not self:
            self._show_placeholder()


class TaskCard(tk.Frame):
    """Tek bir indirme görevinin kartı. Veriler yerinde güncellenir."""

    def __init__(self, parent: tk.Misc, app, data: dict):
        super().__init__(
            parent,
            bg=CARD,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        self.app = app
        self.data = data
        self._signature: tuple | None = None
        self._percent = 0.0
        self._progress_color = ACCENT
        self._ui_cache: dict[str, dict] = {}
        self._drawn_progress: tuple | None = None
        self._icon_status = ""

        header = tk.Frame(self, bg=CARD)
        header.pack(fill="x", padx=16, pady=(14, 0))

        self.icon = tk.Canvas(header, width=40, height=40, bg=CARD, highlightthickness=0, bd=0)
        self.icon.pack(side="left", padx=(0, 12))

        texts = tk.Frame(header, bg=CARD)
        texts.pack(side="left", fill="x", expand=True)

        title_row = tk.Frame(texts, bg=CARD)
        title_row.pack(fill="x")
        self.title_label = tk.Label(
            title_row,
            text="Video",
            bg=CARD,
            fg=TEXT,
            font=font(11, "bold"),
            anchor="w",
        )
        self.title_label.pack(side="left", fill="x", expand=True)
        self.title_label.bind("<Double-Button-1>", self._on_open_file)

        self.status_label = tk.Label(
            header,
            text=t("task.status.queued"),
            bg=status_tint("queued"),
            fg=status_color("queued"),
            font=font(8, "bold"),
            padx=9,
            pady=3,
        )
        self.status_label.pack(side="right", padx=(12, 0), anchor="n")

        self.meta_label = tk.Label(
            texts,
            text="",
            bg=CARD,
            fg=MUTED,
            font=font(9),
            anchor="w",
        )
        self.meta_label.pack(fill="x", pady=(2, 0))

        self.progress = tk.Canvas(self, height=8, bg=CARD, highlightthickness=0, bd=0)
        self.progress.pack(fill="x", padx=16, pady=(12, 0))
        self.progress.bind("<Configure>", lambda _event: self._draw_progress())

        info_row = tk.Frame(self, bg=CARD)
        info_row.pack(fill="x", padx=16, pady=(7, 0))
        self.info_label = tk.Label(
            info_row,
            text="",
            bg=CARD,
            fg=TEXT_DIM,
            font=font(9),
            anchor="w",
        )
        self.info_label.pack(side="left", fill="x", expand=True)
        self.percent_label = tk.Label(
            info_row,
            text="%0",
            bg=CARD,
            fg=ACCENT,
            font=font(9, "bold"),
            anchor="e",
        )
        self.percent_label.pack(side="right", padx=(10, 0))

        self.buttons = tk.Frame(self, bg=CARD)
        self.buttons.pack(fill="x", padx=16, pady=(10, 14))

        self.update_data(data)

    # ------------------------------------------------------------------ güncelle
    def _configure(self, widget: tk.Widget, key: str, **options) -> None:
        """Yalnızca değeri değişen seçenekleri uygula (gereksiz çizimi önler)."""
        if self._ui_cache.get(key) == options:
            return
        widget.configure(**options)
        self._ui_cache[key] = options

    def update_data(self, data: dict) -> None:
        self.data = data
        status = str(data.get("status") or "queued")
        color = status_color(status)

        if status != self._icon_status:
            self._icon_status = status
            draw_status_icon(self.icon, status)

        title = ellipsize(data.get("display_title") or "Video", 84)
        cursor = "hand2" if status == "completed" and data.get("filepath") else ""
        self._configure(self.title_label, "title", text=title, cursor=cursor)

        meta_parts = [
            data.get("host") or "",
            data.get("quality_label") or "",
            human_duration(data.get("duration")) or "",
            data.get("extractor") or "",
        ]
        self._configure(
            self.meta_label,
            "meta",
            text="   ·   ".join(part for part in meta_parts if part),
        )

        status_text = data.get("status_label") or t(f"task.status.{status}")
        self._configure(
            self.status_label,
            "status",
            text=status_text,
            bg=status_tint(status),
            fg=color,
        )

        self._percent = float(data.get("progress") or 0.0)
        if status == "completed":
            self._percent = 100.0
        self._progress_color = color
        self._draw_progress()

        self._configure(
            self.info_label,
            "info",
            text=self._info_text(data, status),
            fg=RED if status == "error" else TEXT_DIM,
        )
        self._configure(
            self.percent_label,
            "percent",
            text=f"%{self._percent:.0f}",
            fg=color,
        )
        self._update_buttons(status, bool(data.get("filepath")), bool(data.get("error")))

    def _info_text(self, data: dict, status: str) -> str:
        downloaded = int(data.get("downloaded") or 0)
        total = int(data.get("total") or 0)
        speed = float(data.get("speed") or 0.0)
        eta = int(data.get("eta") or 0)
        detail = str(data.get("detail") or "")

        if status in {"starting", "analyzing", "downloading", "processing", "pausing", "canceling"}:
            parts: list[str] = []
            if total:
                parts.append(f"{human_size(downloaded)} / {human_size(total)}")
            elif downloaded:
                parts.append(human_size(downloaded))
            if speed and status not in {"pausing", "canceling"}:
                parts.append(human_speed(speed))
            if eta and status not in {"pausing", "canceling"}:
                parts.append(t("task.info.eta_left", eta=human_eta(eta)))
            if detail:
                parts.append(detail)
            return ellipsize("   ·   ".join(parts) or detail or t("task.info.working"), 120)
        if status == "queued":
            return ellipsize(detail or t("task.info.waiting"), 120)
        if status == "paused":
            parts = []
            if total:
                parts.append(f"{human_size(downloaded)} / {human_size(total)}")
            elif downloaded:
                parts.append(human_size(downloaded))
            parts.append(detail or t("task.status.paused"))
            return ellipsize("   ·   ".join(parts), 120)
        if status == "completed":
            parts = []
            if total:
                parts.append(human_size(total))
            if data.get("filepath"):
                parts.append(os.path.basename(str(data["filepath"])))
            return ellipsize("   ·   ".join(parts) or t("task.status.completed"), 130)
        if status == "error":
            return ellipsize(data.get("error") or t("task.info.unknown_error"), 150)
        return ellipsize(detail or t("task.status.canceled"), 120)

    def _draw_progress(self) -> None:
        percent = round(self._percent, 1)
        key = (
            percent,
            self._progress_color,
            max(1, self.progress.winfo_width()),
            max(1, self.progress.winfo_height()),
        )
        if key == self._drawn_progress:
            return
        self._drawn_progress = key
        draw_progress(self.progress, percent, self._progress_color)

    def _update_buttons(self, status: str, has_file: bool, has_error: bool) -> None:
        signature = (status, has_file, has_error)
        if signature == self._signature:
            return
        self._signature = signature
        for child in self.buttons.winfo_children():
            child.destroy()

        actions: list[tuple[str, str, str]] = []
        if status in {"queued", "starting", "analyzing", "downloading", "processing"}:
            actions.append((t("downloads.action.pause"), "pause", "ghost"))
            actions.append((t("downloads.action.cancel"), "cancel", "danger"))
        elif status in {"pausing", "canceling"}:
            label = t("task.action.pausing") if status == "pausing" else t("task.action.canceling")
            actions.append((label, "", "subtle"))
        elif status == "paused":
            actions.append((t("downloads.action.resume"), "resume", "primary"))
            actions.append((t("downloads.action.cancel"), "cancel", "danger"))
        elif status in {"error", "canceled"}:
            actions.append((t("downloads.action.retry"), "retry", "primary"))
            if has_error:
                actions.append((t("downloads.action.details"), "details", "ghost"))
            actions.append((t("downloads.action.remove"), "remove", "ghost"))
        elif status == "completed":
            if has_file:
                actions.append((t("downloads.action.play"), "open", "primary"))
                actions.append((t("downloads.action.folder"), "folder", "ghost"))
                actions.append((t("downloads.action.extract_audio"), "audio", "ghost"))
            actions.append((t("downloads.action.redownload"), "redownload", "ghost"))
            actions.append((t("downloads.action.remove"), "remove", "ghost"))

        for text, action, kind in reversed(actions):
            if action:
                command = lambda a=action: self._run_action(a)
            else:
                command = None
            button = make_button(self.buttons, text, command, kind=kind, size=9)
            if command is None:
                button.configure(state="disabled", cursor="arrow", fg=MUTED)
            button.pack(side="right", padx=(8, 0))

    def _run_action(self, action: str) -> None:
        task_id = self.data.get("id", "")
        if not task_id:
            return
        if action == "pause":
            self.app.pause_task(task_id)
        elif action == "resume":
            self.app.resume_task(task_id)
        elif action == "cancel":
            self.app.cancel_task(task_id)
        elif action == "retry":
            self.app.retry_task(task_id)
        elif action == "remove":
            self.app.remove_task(task_id)
        elif action == "open":
            self.app.open_task_file(task_id)
        elif action == "folder":
            self.app.open_task_folder(task_id)
        elif action == "redownload":
            self.app.redownload_task(task_id)
        elif action == "audio":
            self.app.extract_audio(task_id)
        elif action == "details":
            self.app.show_task_details(task_id)

    def _on_open_file(self, _event=None) -> None:
        if self.data.get("status") == "completed" and self.data.get("filepath"):
            self.app.open_task_file(self.data["id"])


class CaptureCard(tk.Frame):
    """Tarayıcıdan yakalanan tek bir medya kartı."""

    def __init__(self, parent: tk.Misc, app, data: dict):
        super().__init__(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        self.app = app
        self.data = data

        body = tk.Frame(self, bg=CARD)
        body.pack(fill="x", padx=16, pady=13)

        kind = str(data.get("kind") or "direct")
        color = theme.kind_color(kind)
        tint = {
            "hls": theme.PURPLE_SOFT,
            "dash": theme.BLUE_SOFT,
            "page": theme.YELLOW_SOFT,
            "direct": ACCENT_SOFT,
        }.get(kind, CARD_ALT)

        icon = tk.Canvas(body, width=40, height=40, bg=CARD, highlightthickness=0, bd=0)
        icon.pack(side="left", padx=(0, 12))
        icon.create_oval(1, 1, 39, 39, fill=tint, outline="")
        icon.create_polygon(16, 12, 16, 28, 29, 20, fill=color, outline="")

        texts = tk.Frame(body, bg=CARD)
        texts.pack(side="left", fill="x", expand=True)

        title_row = tk.Frame(texts, bg=CARD)
        title_row.pack(fill="x")
        title = tk.Label(
            title_row,
            text=ellipsize(data.get("display_title") or "Video", 80),
            bg=CARD,
            fg=TEXT,
            font=font(11, "bold"),
            anchor="w",
        )
        title.pack(side="left", fill="x", expand=True)

        meta_row = tk.Frame(texts, bg=CARD)
        meta_row.pack(fill="x", pady=(3, 0))
        make_badge(meta_row, data.get("media_label") or data.get("kind_label") or "MEDYA", color, tint).pack(side="left", padx=(0, 8))
        if data.get("drm"):
            make_badge(
                meta_row,
                t("capture.media.drm"),
                theme.RED,
                theme.RED_SOFT,
            ).pack(side="left", padx=(0, 8))
        meta_parts = [data.get("host") or ""]
        if data.get("size"):
            meta_parts.append(human_size(data.get("size")))
        if data.get("page_title") and data.get("page_title") != data.get("title"):
            meta_parts.append(t("captures.source_page") + ellipsize(data.get("page_title"), 42))
        tk.Label(
            meta_row,
            text="   ·   ".join(part for part in meta_parts if part),
            bg=CARD,
            fg=MUTED,
            font=font(9),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        url = str(data.get("url") or "")
        tk.Label(
            texts,
            text=ellipsize(url, 112),
            bg=CARD,
            fg="#65708a",
            font=mono(8),
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

        buttons = tk.Frame(body, bg=CARD)
        buttons.pack(side="right", padx=(12, 0), anchor="n")
        download_button = make_button(
            buttons,
            t("captures.download"),
            lambda: self.app.download_capture(str(data.get("id") or "")),
            kind="primary",
            size=9,
            padx=16,
        )
        if data.get("drm"):
            download_button.configure(
                state="disabled",
                text=t("captures.drm_button"),
                bg=CARD_ALT,
                fg=MUTED,
                activebackground=CARD_ALT,
                activeforeground=MUTED,
                cursor="arrow",
            )
            download_button.unbind("<Enter>")
            download_button.unbind("<Leave>")
        download_button.pack(side="right")
        make_button(
            buttons,
            t("captures.remove"),
            lambda: self.app.remove_capture(str(data.get("id") or "")),
            kind="ghost",
            size=9,
        ).pack(side="right", padx=(0, 8))
        make_button(
            buttons,
            t("captures.copy"),
            self.copy_url,
            kind="ghost",
            size=9,
        ).pack(side="right", padx=(0, 8))

    def copy_url(self) -> None:
        url = str(self.data.get("url") or "")
        if not url:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(url)
        except tk.TclError:
            return
        self.app.toast(t("captures.copied"), "success")


class EmptyState(tk.Frame):
    """Liste boşken gösterilen yönlendirici alan."""

    def __init__(
        self,
        parent: tk.Misc,
        symbol: str,
        title: str,
        message: str,
        action_text: str | None = None,
        command=None,
    ):
        super().__init__(parent, bg=BG)
        box = tk.Frame(self, bg=BG)
        box.pack(expand=True, pady=70)

        icon = tk.Canvas(box, width=76, height=76, bg=BG, highlightthickness=0, bd=0)
        icon.pack(pady=(0, 14))
        icon.create_oval(4, 4, 72, 72, fill=BG_SOFT, outline=BORDER)
        icon.create_text(38, 37, text=symbol, fill=BORDER_LIGHT, font=font(26, "bold"))

        self.title_label = tk.Label(box, text=title, bg=BG, fg=TEXT, font=font(14, "bold"))
        self.title_label.pack()
        self.message_label = tk.Label(
            box,
            text=message,
            bg=BG,
            fg=MUTED,
            font=font(10),
            justify="center",
            wraplength=460,
            pady=6,
        )
        self.message_label.pack()
        if action_text and command:
            make_button(box, action_text, command, kind="primary", size=10, padx=18, pady=8).pack(pady=(12, 0))


def show_details_dialog(parent: tk.Misc, data: dict) -> None:
    """Hata ve günlük ayrıntılarını gösteren koyu pencere."""
    window = tk.Toplevel(parent)
    window.title(t("details.title"))
    window.configure(bg=BG)
    window.geometry("760x520")
    window.minsize(560, 360)
    window.transient(parent)

    header = tk.Frame(window, bg=BG)
    header.pack(fill="x", padx=22, pady=(20, 12))
    tk.Label(
        header,
        text=ellipsize(data.get("display_title") or t("details.default_title"), 70),
        bg=BG,
        fg=TEXT,
        font=font(14, "bold"),
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        header,
        text=f"{data.get('status_label') or ''}   ·   {data.get('host') or ''}",
        bg=BG,
        fg=status_color(str(data.get("status") or "")),
        font=font(9, "bold"),
        anchor="w",
    ).pack(fill="x", pady=(4, 0))

    text_frame = tk.Frame(window, bg=BG)
    text_frame.pack(fill="both", expand=True, padx=22, pady=(0, 12))
    scrollbar = ttk.Scrollbar(text_frame, orient="vertical")
    scrollbar.pack(side="right", fill="y")
    body = tk.Text(
        text_frame,
        bg=BG_SOFT,
        fg=TEXT_DIM,
        insertbackground=TEXT,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        wrap="word",
        font=mono(9),
        padx=14,
        pady=12,
        yscrollcommand=scrollbar.set,
    )
    body.pack(side="left", fill="both", expand=True)
    scrollbar.configure(command=body.yview)

    status_label_str = data.get('status_label') or ''
    status_raw = data.get('status') or ''
    lines = [
        f"{t('details.status'):10}: {status_label_str} ({status_raw})",
        f"{t('details.url'):10}: {data.get('url') or ''}",
    ]
    if data.get("page_url"):
        lines.append(f"{t('details.page'):10}: {data.get('page_url')}")
    if data.get("filepath"):
        lines.append(f"{t('details.file'):10}: {data.get('filepath')}")
    if data.get("extractor"):
        lines.append(f"{t('details.source'):10}: {data.get('extractor')}")
    if data.get("error"):
        lines.append("")
        lines.append(t("details.error_heading"))
        lines.append(str(data.get("error")))
    if data.get("log_tail"):
        lines.append("")
        lines.append(t("details.log_heading"))
        lines.append(str(data.get("log_tail")).strip())
    body.insert("1.0", "\n".join(lines))
    body.configure(state="disabled")

    footer = tk.Frame(window, bg=BG)
    footer.pack(fill="x", padx=22, pady=(0, 20))
    make_button(footer, t("details.close"), window.destroy, kind="subtle", size=9).pack(side="right")

    copy_button = make_button(footer, t("details.copy_url"), None, kind="ghost", size=9, bg=BG)
    copy_button.pack(side="right", padx=(0, 8))

    def copy_url() -> None:
        url = str(data.get("url") or "")
        if not url:
            return
        try:
            window.clipboard_clear()
            window.clipboard_append(url)
            copy_button.configure(text=t("details.copied"))
            window.after(1800, lambda: copy_button.configure(text=t("details.copy_url")))
        except tk.TclError:
            pass

    copy_button.configure(command=copy_url)
    window.bind("<Escape>", lambda _event: window.destroy())

    window.update_idletasks()
    try:
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - 760) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - 520) // 2)
        window.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass
    window.grab_set()
    window.focus_set()
