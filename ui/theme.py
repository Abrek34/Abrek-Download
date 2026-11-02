"""Koyu tema renkleri, yazı tipleri ve ttk stilleri."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# ------------------------------------------------------------------ palet
BG = "#0d1017"
BG_SOFT = "#11151e"
SIDEBAR = "#0a0d13"
CARD = "#151a24"
CARD_ALT = "#1a2130"
CARD_HOVER = "#1f2737"
BORDER = "#242c3b"
BORDER_LIGHT = "#323c50"
TEXT = "#edf1f8"
TEXT_DIM = "#a6afc1"
MUTED = "#77829a"
ACCENT = "#6d8dff"
ACCENT_HOVER = "#8aa3ff"
ACCENT_SOFT = "#1a2544"
GREEN = "#4bd6a0"
GREEN_SOFT = "#12352b"
YELLOW = "#f5bd66"
YELLOW_SOFT = "#392d1a"
RED = "#ff7288"
RED_SOFT = "#3a1a24"
BLUE = "#62b6ff"
BLUE_SOFT = "#152b40"
PURPLE = "#b18cff"
PURPLE_SOFT = "#291f42"

FONT = "Fira Sans"
MONO = "DejaVu Sans Mono"

STATUS_COLORS = {
    "queued": YELLOW,
    "starting": ACCENT,
    "analyzing": BLUE,
    "downloading": ACCENT,
    "processing": PURPLE,
    "pausing": YELLOW,
    "canceling": RED,
    "paused": MUTED,
    "completed": GREEN,
    "error": RED,
    "canceled": MUTED,
}

STATUS_TINTS = {
    "queued": YELLOW_SOFT,
    "starting": ACCENT_SOFT,
    "analyzing": BLUE_SOFT,
    "downloading": ACCENT_SOFT,
    "processing": PURPLE_SOFT,
    "pausing": YELLOW_SOFT,
    "canceling": RED_SOFT,
    "paused": CARD_ALT,
    "completed": GREEN_SOFT,
    "error": RED_SOFT,
    "canceled": CARD_ALT,
}

KIND_COLORS = {
    "hls": PURPLE,
    "dash": BLUE,
    "page": YELLOW,
    "direct": ACCENT,
}


def font(size: int = 10, weight: str = "normal", family: str = FONT):
    return (family, size, weight)


def mono(size: int = 9, weight: str = "normal"):
    return (MONO, size, weight)


def status_color(status: str) -> str:
    return STATUS_COLORS.get(status, TEXT_DIM)


def status_tint(status: str) -> str:
    return STATUS_TINTS.get(status, CARD_ALT)


def kind_color(kind: str) -> str:
    return KIND_COLORS.get(kind, ACCENT)


def ellipsize(text: str, limit: int = 90) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


# ------------------------------------------------------------------ stiller
def setup_style(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.option_add("*TCombobox*Listbox.background", CARD_ALT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#0b1020")
    root.option_add("*TCombobox*Listbox.font", font(10))

    style.configure(
        "TCombobox",
        fieldbackground=CARD_ALT,
        background=CARD_ALT,
        foreground=TEXT,
        arrowcolor=TEXT_DIM,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        insertcolor=TEXT,
        padding=(9, 6),
        relief="flat",
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", CARD_ALT), ("disabled", BG_SOFT)],
        foreground=[("disabled", MUTED)],
        background=[("active", CARD_ALT), ("pressed", CARD_ALT)],
        arrowcolor=[("active", TEXT), ("disabled", MUTED)],
        selectbackground=[("readonly", CARD_ALT)],
        selectforeground=[("readonly", TEXT)],
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
    )

    style.configure(
        "TCheckbutton",
        background=CARD,
        foreground=TEXT,
        focuscolor=CARD,
        indicatorbackground=CARD_ALT,
        indicatorforeground=ACCENT,
        upperbordercolor=BORDER,
        padding=(0, 4),
        font=font(10),
    )
    style.map(
        "TCheckbutton",
        background=[("active", CARD)],
        foreground=[("active", TEXT)],
        indicatorbackground=[("selected", ACCENT), ("active", CARD_HOVER)],
        indicatorforeground=[("selected", "#0b1020")],
    )

    style.configure(
        "Vertical.TScrollbar",
        gripcount=0,
        background=BORDER,
        darkcolor=BG,
        lightcolor=BG,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=MUTED,
        arrowsize=11,
        width=9,
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("active", BORDER_LIGHT), ("pressed", BORDER_LIGHT)],
        arrowcolor=[("active", TEXT_DIM)],
    )

    style.configure("TSeparator", background=BORDER)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("TSpinbox", fieldbackground=CARD_ALT, foreground=TEXT, arrowcolor=TEXT_DIM)
    return style


# ------------------------------------------------------------------ çizim
def rounded_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, r: float, **kwargs):
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def draw_progress(canvas: tk.Canvas, percent: float, color: str) -> None:
    canvas.delete("all")
    width = max(1, canvas.winfo_width())
    height = max(1, canvas.winfo_height())
    radius = min(4, height / 2)
    rounded_rect(canvas, 0, 0, width, height, radius, fill="#222a3a", outline="")
    percent = max(0.0, min(100.0, float(percent or 0)))
    if percent <= 0:
        return
    fill_width = width * percent / 100.0
    fill_width = max(fill_width, min(radius * 2, width))
    rounded_rect(canvas, 0, 0, fill_width, height, radius, fill=color, outline="")


def draw_status_icon(canvas: tk.Canvas, status: str) -> None:
    canvas.delete("all")
    color = status_color(status)
    tint = status_tint(status)
    canvas.create_oval(1, 1, 39, 39, fill=tint, outline="")
    if status == "completed":
        canvas.create_line(12, 20, 18, 26, 29, 14, fill=color, width=2, capstyle="round", joinstyle="round")
    elif status == "error":
        canvas.create_line(20, 11, 20, 23, fill=color, width=2, capstyle="round")
        canvas.create_oval(18, 27, 22, 31, fill=color, outline="")
    elif status in {"paused", "pausing"}:
        canvas.create_rectangle(14, 12, 20, 28, fill=color, outline="")
        canvas.create_rectangle(23, 12, 29, 28, fill=color, outline="")
    elif status == "canceled":
        canvas.create_line(14, 14, 26, 26, fill=color, width=2, capstyle="round")
        canvas.create_line(26, 14, 14, 26, fill=color, width=2, capstyle="round")
    elif status == "queued":
        canvas.create_oval(11, 11, 29, 29, outline=color, width=2)
        canvas.create_line(20, 16, 20, 21, 24, 23, fill=color, width=2, capstyle="round")
    elif status == "analyzing":
        canvas.create_oval(11, 11, 26, 26, outline=color, width=2)
        canvas.create_line(24, 24, 30, 30, fill=color, width=2, capstyle="round")
    else:
        canvas.create_line(20, 11, 20, 26, fill=color, width=2, capstyle="round")
        canvas.create_line(14, 20, 20, 26, 26, 20, fill=color, width=2, capstyle="round", joinstyle="round")


def make_button(
    parent: tk.Misc,
    text: str,
    command,
    kind: str = "ghost",
    size: int = 9,
    padx: int = 13,
    pady: int = 6,
    bg: str = CARD,
    bold: bool | None = None,
    width: int | None = None,
) -> tk.Button:
    palettes = {
        "primary": (ACCENT, "#0b1020", ACCENT_HOVER, "#0b1020", ACCENT_HOVER),
        "ghost": (bg, TEXT_DIM, CARD_HOVER, TEXT, BORDER_LIGHT),
        "subtle": (CARD_ALT, TEXT, CARD_HOVER, TEXT, BORDER_LIGHT),
        "danger": (RED_SOFT, RED, "#4a202c", "#ff98a9", "#5a2836"),
        "link": (bg, TEXT_DIM, bg, TEXT, bg),
    }
    normal_bg, normal_fg, hover_bg, hover_fg, hover_border = palettes.get(kind, palettes["ghost"])
    border = BORDER if kind in {"ghost", "subtle", "danger"} else normal_bg
    if bold is None:
        bold = kind == "primary"
    button = tk.Button(
        parent,
        text=text,
        command=command,
        bg=normal_bg,
        fg=normal_fg,
        activebackground=hover_bg,
        activeforeground=hover_fg,
        relief="flat",
        bd=0,
        highlightthickness=1 if kind in {"ghost", "subtle", "danger"} else 0,
        highlightbackground=border,
        highlightcolor=hover_border,
        cursor="hand2",
        font=font(size, "bold" if bold else "normal"),
        padx=padx,
        pady=pady,
        takefocus=0,
        width=width,
    )

    def on_enter(_event=None):
        button.configure(bg=hover_bg, fg=hover_fg, highlightbackground=hover_border)

    def on_leave(_event=None):
        button.configure(bg=normal_bg, fg=normal_fg, highlightbackground=border)

    button.bind("<Enter>", on_enter)
    button.bind("<Leave>", on_leave)
    return button


def make_badge(parent: tk.Misc, text: str, fg: str, bg: str, size: int = 8) -> tk.Label:
    return tk.Label(
        parent,
        text=text,
        bg=bg,
        fg=fg,
        font=font(size, "bold"),
        padx=8,
        pady=2,
    )
