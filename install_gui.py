#!/usr/bin/env python3
"""Abrek Download için basit kurulum arayüzü.

Kurulum işini ``install.sh`` yapar; bu arayüz ortamı denetler, seçenekleri
toplar, komutu çalıştırır ve çıktıyı canlı gösterir.
"""

from __future__ import annotations

import os
import queue
import shlex
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import PROJECT_DIR, VERSION
from core.installer import (
    detect_all,
    detect_json,
    install_script_args,
    is_app_running,
    launch_command,
    manual_install_command,
)
from installer_strings import tr
from ui.theme import (
    ACCENT,
    BG,
    BG_SOFT,
    BORDER,
    CARD,
    CARD_ALT,
    GREEN,
    GREEN_SOFT,
    MUTED,
    RED,
    RED_SOFT,
    TEXT,
    TEXT_DIM,
    YELLOW,
    YELLOW_SOFT,
    ellipsize,
    font,
    make_button,
    mono,
    setup_style,
)

CHECK_ORDER = (
    "python",
    "tkinter",
    "venv",
    "packages",
    "ffmpeg",
    "ffprobe",
    "js_runtime",
    "menu_entry",
    "desktop_shortcut",
)

STATUS_STYLE = {
    "ok": (GREEN, GREEN_SOFT),
    "warn": (YELLOW, YELLOW_SOFT),
    "missing": (RED, RED_SOFT),
    "off": (MUTED, CARD_ALT),
}


class InstallerApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(tr("title"))
        self.root.configure(bg=BG)
        self.root.minsize(900, 640)
        self._center(1000, 720)

        self._queue: queue.Queue = queue.Queue()
        self._busy = False
        self._detecting = False
        self._action = ""
        self._pending_install = (False, False, False)
        self._detect_data: dict = {}
        self._system_available = False
        self._proc: subprocess.Popen | None = None
        self._images: list[tk.PhotoImage] = []

        self._set_window_icon()
        setup_style(self.root)
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Escape>", lambda _event: self._on_close())
        self._poll_queue()
        self.root.after(120, self.refresh)

    # ------------------------------------------------------------------ layout
    def _center(self, width: int, height: int) -> None:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _set_window_icon(self) -> None:
        try:
            icon = tk.PhotoImage(file=str(PROJECT_DIR / "assets" / "icon-32.png"))
            self._images.append(icon)
            self.root.iconphoto(True, icon)
        except tk.TclError:
            pass

    def _build(self) -> None:
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True, padx=22, pady=18)

        header = tk.Frame(container, bg=BG)
        header.pack(fill="x")
        try:
            icon = tk.PhotoImage(file=str(PROJECT_DIR / "assets" / "icon-64.png"))
            self._images.append(icon)
            icon_label = tk.Label(header, image=icon, bg=BG)
        except tk.TclError:
            icon_label = tk.Label(header, text="▶", bg=BG, fg=ACCENT, font=font(30, "bold"))
        icon_label.pack(side="left", padx=(0, 14))

        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(
            titles,
            text=tr("title"),
            bg=BG,
            fg=TEXT,
            font=font(19, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            titles,
            text=tr("subtitle", version=VERSION),
            bg=BG,
            fg=TEXT_DIM,
            font=font(9),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))
        tk.Label(
            titles,
            text=tr("header_hint"),
            bg=BG,
            fg=MUTED,
            font=font(8),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        body = tk.Frame(container, bg=BG)
        body.pack(fill="both", expand=True, pady=(16, 0))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")

        self._build_status(left)
        self._build_options(left)
        self._build_log(right)
        self._build_actions(container)

    def _card(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

    def _build_status(self, parent: tk.Misc) -> None:
        card = self._card(parent)
        card.pack(fill="x")
        tk.Label(
            card,
            text=tr("section.status"),
            bg=CARD,
            fg=TEXT,
            font=font(10, "bold"),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 8))

        rows = tk.Frame(card, bg=CARD)
        rows.pack(fill="x", padx=14, pady=(0, 12))
        self.status_rows: dict[str, dict] = {}
        for key in CHECK_ORDER:
            row = tk.Frame(rows, bg=CARD)
            row.pack(fill="x", pady=2)
            row.grid_columnconfigure(2, weight=1)

            dot = tk.Canvas(row, width=10, height=10, bg=CARD, highlightthickness=0)
            dot.grid(row=0, column=0, padx=(0, 8))
            oval = dot.create_oval(1, 1, 9, 9, fill=MUTED, outline=MUTED)

            name = tk.Label(
                row,
                text=tr(f"check.{key}"),
                bg=CARD,
                fg=TEXT,
                font=font(9, "bold"),
                anchor="w",
                width=26,
            )
            name.grid(row=0, column=1, sticky="w")

            detail = tk.Label(
                row,
                text="",
                bg=CARD,
                fg=MUTED,
                font=font(8),
                anchor="w",
            )
            detail.grid(row=0, column=2, sticky="we", padx=(8, 8))

            badge = tk.Label(
                row,
                text=tr("status.checking"),
                bg=CARD_ALT,
                fg=MUTED,
                font=font(8, "bold"),
                padx=7,
                pady=1,
            )
            badge.grid(row=0, column=3, sticky="e")

            self.status_rows[key] = {
                "dot": dot,
                "oval": oval,
                "detail": detail,
                "badge": badge,
            }

    def _build_options(self, parent: tk.Misc) -> None:
        card = self._card(parent)
        card.pack(fill="x", pady=(12, 0))
        tk.Label(
            card,
            text=tr("section.options"),
            bg=CARD,
            fg=TEXT,
            font=font(10, "bold"),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 6))

        self.menu_var = tk.IntVar(value=1)
        self.desktop_var = tk.IntVar(value=1)
        self.prepare_var = tk.IntVar(value=1)
        self.system_var = tk.IntVar(value=0)

        self.menu_check = self._checkbutton(card, tr("option.menu"), self.menu_var)
        self.desktop_check = self._checkbutton(card, tr("option.desktop"), self.desktop_var)
        self.prepare_check = self._checkbutton(card, tr("option.prepare"), self.prepare_var)
        self.system_check = self._checkbutton(card, tr("option.system"), self.system_var)

        self.system_hint = tk.Label(
            card,
            text=tr("option.system_none"),
            bg=CARD,
            fg=MUTED,
            font=font(8),
            anchor="w",
            justify="left",
            wraplength=500,
        )
        self.system_hint.pack(fill="x", padx=32, pady=(0, 12))

    def _checkbutton(self, parent: tk.Misc, text: str, variable: tk.IntVar) -> tk.Checkbutton:
        widget = tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD,
            activeforeground=TEXT,
            selectcolor=CARD_ALT,
            font=font(9),
            highlightthickness=0,
            bd=0,
            anchor="w",
            padx=0,
            pady=2,
            cursor="hand2",
        )
        widget.pack(fill="x", padx=14)
        return widget

    def _build_log(self, parent: tk.Misc) -> None:
        card = self._card(parent)
        card.pack(fill="both", expand=True)
        tk.Label(
            card,
            text=tr("section.log"),
            bg=CARD,
            fg=TEXT,
            font=font(10, "bold"),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 8))

        frame = tk.Frame(card, bg=CARD)
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            frame,
            bg=BG_SOFT,
            fg=TEXT_DIM,
            insertbackground=TEXT,
            font=mono(9),
            wrap="word",
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=8,
            state="disabled",
        )
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        self.log_text.tag_configure("info", foreground=TEXT_DIM)
        self.log_text.tag_configure("cmd", foreground=ACCENT)
        self.log_text.tag_configure("ok", foreground=GREEN)
        self.log_text.tag_configure("warn", foreground=YELLOW)
        self.log_text.tag_configure("error", foreground=RED)

    def _build_actions(self, parent: tk.Misc) -> None:
        actions = tk.Frame(parent, bg=BG)
        actions.pack(fill="x", pady=(14, 0))

        self.footer = tk.Label(
            actions,
            text=tr("footer.checking"),
            bg=BG,
            fg=MUTED,
            font=font(9),
            anchor="w",
        )
        self.footer.pack(side="left", fill="x", expand=True)

        self.progress = ttk.Progressbar(
            actions,
            mode="indeterminate",
            length=130,
            style="Installer.Horizontal.TProgressbar",
        )
        self.progress.pack(side="left", padx=(0, 12))

        self.install_button = make_button(
            actions,
            tr("button.install"),
            self._start_install,
            kind="primary",
            size=9,
            padx=18,
            pady=7,
            bg=BG,
        )
        self.install_button.pack(side="right", padx=(6, 0))

        self.uninstall_button = make_button(
            actions,
            tr("button.uninstall"),
            self._uninstall,
            kind="danger",
            size=9,
            bg=BG,
        )
        self.uninstall_button.pack(side="right", padx=6)

        self.refresh_button = make_button(
            actions,
            tr("button.refresh"),
            self.refresh,
            kind="ghost",
            size=9,
            bg=BG,
        )
        self.refresh_button.pack(side="right", padx=6)

        self.launch_button = make_button(
            actions,
            tr("button.launch"),
            self._launch,
            kind="subtle",
            size=9,
            bg=BG,
        )
        self.launch_button.pack(side="right", padx=6)

        style = ttk.Style(self.root)
        style.configure(
            "Installer.Horizontal.TProgressbar",
            troughcolor=BG_SOFT,
            background=ACCENT,
            bordercolor=BORDER,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )

    # ------------------------------------------------------------------ state
    def _status_text(self, key: str, status: str) -> str:
        if status == "ok":
            if key in {"menu_entry", "desktop_shortcut"}:
                return tr("status.installed")
            return tr("status.ok")
        return tr(f"status.{status}")

    def _set_check(self, key: str, status: str, detail: str) -> None:
        row = self.status_rows.get(key)
        if not row:
            return
        color, tint = STATUS_STYLE.get(status, STATUS_STYLE["off"])
        row["dot"].itemconfigure(row["oval"], fill=color, outline=color)
        row["detail"].configure(text=ellipsize(detail, 52))
        row["badge"].configure(text=self._status_text(key, status), bg=tint, fg=color)

    def _apply_detection(self, data: dict) -> None:
        first = not self._detect_data
        self._detect_data = data
        checks = data.get("checks", {})
        for key in CHECK_ORDER:
            check = checks.get(key, {})
            self._set_check(key, str(check.get("status", "off")), str(check.get("detail", "")))

        menu_installed = checks.get("menu_entry", {}).get("status") == "ok"
        desktop_installed = checks.get("desktop_shortcut", {}).get("status") == "ok"
        packages_ok = checks.get("packages", {}).get("status") == "ok"
        self.menu_var.set(0 if menu_installed else 1)
        self.desktop_var.set(0 if desktop_installed else 1)
        self.prepare_var.set(0 if packages_ok else 1)

        missing = list(data.get("missing_system_packages") or [])
        command = list(data.get("system_install_command") or [])
        self._system_available = bool(missing and command)
        self.system_var.set(1 if self._system_available else 0)
        self.system_check.configure(state="normal" if self._system_available else "disabled")
        if missing:
            hint = tr("option.system_hint", packages=", ".join(missing))
            if not command:
                hint += "\n" + tr("option.system_manual", command=self._manual_command(missing))
        else:
            hint = tr("option.system_none")
        self.system_hint.configure(text=hint)

        self.install_button.configure(
            text=tr("button.reinstall") if (menu_installed or desktop_installed) else tr("button.install")
        )
        self._update_launch_button(bool(data.get("app_running")))
        self._update_footer()
        if not first:
            self._log(tr("log.detected"), "info")

    def _update_footer(self) -> None:
        data = self._detect_data
        if not data:
            self.footer.configure(text=tr("footer.checking"), fg=MUTED)
            return
        checks = data.get("checks", {})
        missing = [
            tr(f"check.{key}")
            for key, value in checks.items()
            if value.get("status") == "missing"
        ]
        warnings = [
            tr(f"check.{key}")
            for key, value in checks.items()
            if value.get("status") == "warn"
        ]
        if missing:
            self.footer.configure(text=tr("footer.missing", items=", ".join(missing)), fg=RED)
        elif warnings:
            self.footer.configure(text=tr("footer.warn", items=", ".join(warnings)), fg=YELLOW)
        elif checks.get("menu_entry", {}).get("status") == "ok" or checks.get(
            "desktop_shortcut", {}
        ).get("status") == "ok":
            self.footer.configure(text=tr("footer.ready"), fg=GREEN)
        else:
            self.footer.configure(text=tr("footer.select"), fg=MUTED)

    def _update_launch_button(self, running: bool | None = None) -> None:
        if running is None:
            running = is_app_running()
        self.launch_button.configure(
            text=tr("button.running") if running else tr("button.launch"),
            state="disabled" if (running or self._busy) else "normal",
        )

    def _set_busy(self, busy: bool, title: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for widget in (
            self.install_button,
            self.uninstall_button,
            self.refresh_button,
            self.menu_check,
            self.desktop_check,
            self.prepare_check,
        ):
            widget.configure(state=state)
        self.system_check.configure(
            state="normal" if (not busy and self._system_available) else "disabled"
        )
        if busy:
            self.progress.start(12)
            self.footer.configure(
                text=tr("footer.busy", title=title) if title else tr("footer.checking"),
                fg=ACCENT,
            )
        else:
            self.progress.stop()
            self._update_launch_button()
            self._update_footer()

    # ------------------------------------------------------------------ actions
    def refresh(self) -> None:
        if self._busy or self._detecting:
            return
        self._detecting = True
        self.footer.configure(text=tr("footer.checking"), fg=MUTED)
        self._log(tr("log.detecting"), "info")
        threading.Thread(target=self._detect_worker, daemon=True).start()

    def _detect_worker(self) -> None:
        try:
            self._queue.put(("detected", detect_all()))
        except Exception as exc:
            self._queue.put(("detect_error", f"{type(exc).__name__}: {exc}"))

    def _start_install(self) -> None:
        if self._busy:
            return
        menu = self.menu_var.get() == 1
        desktop = self.desktop_var.get() == 1
        prepare = self.prepare_var.get() == 1
        system = self.system_var.get() == 1 and self._system_available
        if not any((menu, desktop, prepare, system)):
            messagebox.showwarning(tr("msg.nothing_title"), tr("msg.nothing"))
            return
        self._pending_install = (menu, desktop, prepare)

        if system:
            command = list(self._detect_data.get("system_install_command") or [])
            if command:
                self._log(tr("log.system"), "cmd")
                self._run(command, "system", tr("option.system"))
                return
            missing = list(self._detect_data.get("missing_system_packages") or [])
            manual = self._manual_command(missing)
            self._log(tr("log.manual", command=manual), "warn")
            messagebox.showwarning(
                tr("msg.system_manual_title"),
                tr("msg.system_manual", command=manual),
            )

        self._run_install_script(menu, desktop, prepare)

    def _run_install_script(self, menu: bool, desktop: bool, prepare: bool) -> None:
        command = install_script_args(menu, desktop, prepare)
        if len(command) <= 2:
            self._log(tr("log.nothing"), "warn")
            self.refresh()
            return
        self._run(command, "install", tr("button.install"))

    def _uninstall(self) -> None:
        if self._busy:
            return
        if not messagebox.askyesno(tr("msg.uninstall_title"), tr("msg.uninstall")):
            return
        self._pending_install = (False, False, False)
        self._run(
            install_script_args(False, False, False, uninstall=True),
            "uninstall",
            tr("button.uninstall"),
        )

    def _launch(self) -> None:
        if is_app_running():
            self._log(tr("log.app_running"), "warn")
            messagebox.showinfo(tr("msg.app_running_title"), tr("msg.app_running"))
            self._update_launch_button(True)
            return
        try:
            subprocess.Popen(
                launch_command(),
                cwd=str(PROJECT_DIR),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as exc:
            self._log(tr("msg.launch_failed", error=exc), "error")
            messagebox.showerror(
                tr("msg.launch_failed_title"),
                tr("msg.launch_failed", error=exc),
            )
            return
        self._log(tr("log.app_started"), "ok")
        self.root.after(1500, lambda: self._update_launch_button())

    # ------------------------------------------------------------------ process
    def _run(self, command: list[str], action: str, title: str) -> None:
        if self._busy:
            return
        self._action = action
        self._set_busy(True, title)
        self._log(tr("log.command", command=shlex.join(command)), "cmd")
        threading.Thread(target=self._run_worker, args=(command,), daemon=True).start()

    def _run_worker(self, command: list[str]) -> None:
        code = 1
        try:
            process = subprocess.Popen(
                command,
                cwd=str(PROJECT_DIR),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            self._proc = process
            if process.stdout is not None:
                for line in process.stdout:
                    line = line.rstrip("\n").replace("\r", "")
                    if line:
                        self._queue.put(("log", line))
            code = process.wait()
        except Exception as exc:
            self._queue.put(("log", f"{type(exc).__name__}: {exc}"))
            code = 1
        finally:
            self._proc = None
        self._queue.put(("finished", code))

    def _on_finished(self, code: int) -> None:
        self._set_busy(False)
        action = self._action
        self._action = ""

        if action == "system":
            if code == 0:
                self._log(tr("log.system_done"), "ok")
                menu, desktop, prepare = self._pending_install
                if menu or desktop or prepare:
                    self._run_install_script(menu, desktop, prepare)
                else:
                    self.refresh()
                    messagebox.showinfo(tr("msg.install_done_title"), tr("log.system_done"))
            else:
                self._log(tr("log.system_failed"), "error")
                messagebox.showerror(
                    tr("msg.failed_title"),
                    tr("msg.failed", code=code),
                )
                self.refresh()
            return

        if code != 0:
            self._log(tr("msg.failed", code=code), "error")
            messagebox.showerror(tr("msg.failed_title"), tr("msg.failed", code=code))
            self.refresh()
            return

        if action == "install":
            self._log(tr("log.install_done"), "ok")
            self.refresh()
            if messagebox.askyesno(tr("msg.install_done_title"), tr("msg.install_done")):
                self._launch()
        elif action == "uninstall":
            self._log(tr("log.uninstall_done"), "ok")
            self.refresh()
            messagebox.showinfo(tr("msg.uninstall_done_title"), tr("msg.uninstall_done"))

    # ------------------------------------------------------------------ queue
    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                elif kind == "detected":
                    self._detecting = False
                    self._apply_detection(payload)
                elif kind == "detect_error":
                    self._detecting = False
                    self._log(tr("log.detect_error", error=payload), "error")
                    self.footer.configure(text=tr("log.detect_error", error=payload), fg=RED)
                elif kind == "finished":
                    self._on_finished(int(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _log(self, text: str, tag: str = "info") -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text.rstrip("\n") + "\n", tag)
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 1500:
            self.log_text.delete("1.0", f"{line_count - 1200}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------ misc
    def _manual_command(self, packages: list[str]) -> str:
        return manual_install_command(packages)

    def _on_close(self) -> None:
        if self._busy:
            if not messagebox.askyesno(tr("msg.close_busy_title"), tr("msg.close_busy")):
                return
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--detect" in args:
        print(detect_json())
        return 0
    if "--help" in args or "-h" in args:
        print("Kullanım: python3 install_gui.py [--detect]")
        print("  --detect   Ortam denetimini JSON olarak yazdır ve çık.")
        return 0
    app = InstallerApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
