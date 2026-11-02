"""Kurulum arayüzü için ortam algılama yardımcıları.

Kurulum mantığının tek kaynağı ``install.sh`` dosyasıdır. Bu modül yalnızca
ortamı denetler, eksikleri listeler ve arayüzün çalıştıracağı komutları üretir.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shlex
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import API_HOST, API_PORT, PROJECT_DIR, VERSION

DESKTOP_FILE_NAME = "Abrek Download.desktop"
MENU_FILE_NAME = "videoavci.desktop"
ICON_FILE_NAME = "videoavci.png"
JS_RUNTIMES = ("deno", "node", "bun", "qjs", "quickjs")


@dataclass(frozen=True)
class Check:
    """Tek bir ortam denetiminin sonucu."""

    key: str
    status: str  # ok | warn | missing | off
    detail: str = ""
    optional: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def desktop_dir() -> Path:
    configured = os.environ.get("XDG_DESKTOP_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if shutil.which("xdg-user-dir"):
        try:
            result = subprocess.run(
                ["xdg-user-dir", "DESKTOP"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            value = (result.stdout or "").strip()
            if value:
                return Path(value).expanduser()
        except Exception:
            pass
    return Path.home() / "Desktop"


def menu_entry_path() -> Path:
    return data_home() / "applications" / MENU_FILE_NAME


def desktop_shortcut_path() -> Path:
    return desktop_dir() / DESKTOP_FILE_NAME


def _run(command: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _command_version(name: str, args: tuple[str, ...] = ("--version",)) -> str:
    path = shutil.which(name)
    if not path:
        return ""
    try:
        result = _run([path, *args], timeout=8)
    except Exception:
        return ""
    return _first_line(result.stdout or result.stderr)


def entry_points_to_project(path: Path, project_dir: Path = PROJECT_DIR) -> bool:
    """Masaüstü dosyasındaki Exec satırı bu projeye mi işaret ediyor?"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        if not line.startswith("Exec="):
            continue
        value = line[5:].strip()
        try:
            parts = shlex.split(value)
        except ValueError:
            parts = [value.strip('"')]
        if not parts:
            return False
        try:
            target = Path(parts[0]).expanduser().resolve()
            expected = (project_dir / "baslat.sh").resolve()
        except OSError:
            return False
        return target == expected
    return False


def package_manager() -> str:
    for name in ("pacman", "apt-get", "dnf", "zypper"):
        if shutil.which(name):
            return name
    return ""


def _package_names(missing_ffmpeg: bool, missing_tk: bool, missing_js: bool) -> list[str]:
    manager = package_manager()
    names: list[str] = []
    if manager == "pacman":
        if missing_ffmpeg:
            names.append("ffmpeg")
        if missing_tk:
            names.append("tk")
        if missing_js:
            names.append("deno")
    elif manager == "apt-get":
        if missing_ffmpeg:
            names.append("ffmpeg")
        if missing_tk:
            names.append("python3-tk")
        if missing_js:
            names.append("nodejs")
    elif manager == "dnf":
        if missing_ffmpeg:
            names.append("ffmpeg")
        if missing_tk:
            names.append("python3-tkinter")
        if missing_js:
            names.append("nodejs")
    elif manager == "zypper":
        if missing_ffmpeg:
            names.append("ffmpeg")
        if missing_tk:
            names.append("python3-tk")
        if missing_js:
            names.append("nodejs")
    return names


def system_install_command(packages: list[str]) -> list[str]:
    """Yetki yükseltmeli paket kurulum komutu; kullanılamıyorsa boş liste."""
    if not packages:
        return []
    manager = package_manager()
    if not manager or not shutil.which("pkexec"):
        return []
    if manager == "pacman":
        return ["pkexec", "pacman", "-S", "--needed", "--noconfirm", *packages]
    if manager == "apt-get":
        return ["pkexec", "apt-get", "install", "-y", *packages]
    if manager == "dnf":
        return ["pkexec", "dnf", "install", "-y", *packages]
    if manager == "zypper":
        return ["pkexec", "zypper", "--non-interactive", "install", *packages]
    return []


def install_script_args(
    menu: bool,
    desktop: bool,
    prepare: bool,
    uninstall: bool = False,
    project_dir: Path = PROJECT_DIR,
) -> list[str]:
    command = ["bash", str(project_dir / "install.sh")]
    if uninstall:
        return command + ["--uninstall"]
    if menu:
        command.append("--menu")
    if desktop:
        command.append("--desktop")
    if prepare:
        command.append("--prepare")
    return command


def manual_install_command(packages: list[str]) -> str:
    """Kullanıcıya gösterilecek yetki yükseltmeli kurulum komutu."""
    if not packages:
        return ""
    manager = package_manager()
    joined = " ".join(packages)
    if manager == "pacman":
        return f"sudo pacman -S --needed {joined}"
    if manager == "apt-get":
        return f"sudo apt-get install -y {joined}"
    if manager == "dnf":
        return f"sudo dnf install -y {joined}"
    if manager == "zypper":
        return f"sudo zypper install {joined}"
    return joined


def launch_command(project_dir: Path = PROJECT_DIR) -> list[str]:
    return ["bash", str(project_dir / "baslat.sh")]


def is_app_running(host: str = API_HOST, port: int = API_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _venv_details(project_dir: Path) -> tuple[Check, Check]:
    venv_python = project_dir / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return (
            Check("venv", "missing", "Sanal ortam yok"),
            Check("packages", "missing", "yt-dlp ve requests kurulu değil"),
        )
    code = (
        "import json, sys\n"
        "import requests, yt_dlp\n"
        "print(json.dumps({'python': sys.version.split()[0], "
        "'yt_dlp': yt_dlp.version.__version__, 'requests': requests.__version__}))\n"
    )
    try:
        result = _run([str(venv_python), "-c", code], timeout=20)
    except Exception as exc:
        return (
            Check("venv", "missing", f"Çalıştırılamadı: {exc}"),
            Check("packages", "missing", "Bağımlılıklar denetlenemedi"),
        )
    if result.returncode != 0:
        return (
            Check("venv", "ok", "Python ortamı hazır"),
            Check("packages", "missing", "yt-dlp veya requests eksik"),
        )
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return (
            Check("venv", "ok", "Python ortamı hazır"),
            Check("packages", "missing", "Bağımlılık sürümleri okunamadı"),
        )
    return (
        Check("venv", "ok", f"Python {data.get('python', '?')}"),
        Check(
            "packages",
            "ok",
            f"yt-dlp {data.get('yt_dlp', '?')} • requests {data.get('requests', '?')}",
        ),
    )


def detect_all(project_dir: Path = PROJECT_DIR) -> dict:
    """Arayüzün gösterdiği tüm denetimleri ve kurulum önerilerini döndürür."""
    checks: dict[str, Check] = {}

    python_ok = sys.version_info >= (3, 10)
    checks["python"] = Check(
        "python",
        "ok" if python_ok else "missing",
        f"Python {platform.python_version()}",
    )

    try:
        import tkinter  # noqa: F401

        checks["tkinter"] = Check("tkinter", "ok", f"Tk {tkinter.TkVersion}")
        tk_ok = True
    except Exception:
        checks["tkinter"] = Check("tkinter", "missing", "Tkinter bulunamadı")
        tk_ok = False

    venv_check, packages_check = _venv_details(project_dir)
    checks["venv"] = venv_check
    checks["packages"] = packages_check

    ffmpeg_version = _command_version("ffmpeg", ("-version",))
    checks["ffmpeg"] = Check(
        "ffmpeg",
        "ok" if ffmpeg_version else "warn",
        ffmpeg_version or "ffmpeg bulunamadı",
        optional=True,
    )
    ffprobe_version = _command_version("ffprobe", ("-version",))
    checks["ffprobe"] = Check(
        "ffprobe",
        "ok" if ffprobe_version else "warn",
        ffprobe_version or "ffprobe bulunamadı",
        optional=True,
    )

    js_name = ""
    js_version = ""
    for name in JS_RUNTIMES:
        version = _command_version(name)
        if version:
            js_name, js_version = name, version
            break
    checks["js_runtime"] = Check(
        "js_runtime",
        "ok" if js_name else "warn",
        js_version or "deno veya node bulunamadı",
        optional=True,
    )

    menu_path = menu_entry_path()
    menu_ok = entry_points_to_project(menu_path, project_dir)
    checks["menu_entry"] = Check(
        "menu_entry",
        "ok" if menu_ok else "off",
        str(menu_path) if menu_ok else "Kurulu değil",
        optional=True,
    )
    shortcut_path = desktop_shortcut_path()
    shortcut_ok = entry_points_to_project(shortcut_path, project_dir)
    checks["desktop_shortcut"] = Check(
        "desktop_shortcut",
        "ok" if shortcut_ok else "off",
        str(shortcut_path) if shortcut_ok else "Kurulu değil",
        optional=True,
    )

    missing_packages = _package_names(
        missing_ffmpeg=not ffmpeg_version or not ffprobe_version,
        missing_tk=not tk_ok,
        missing_js=not js_name,
    )
    command = system_install_command(missing_packages)

    return {
        "version": VERSION,
        "project_dir": str(project_dir),
        "package_manager": package_manager(),
        "missing_system_packages": missing_packages,
        "system_install_command": command,
        "app_running": is_app_running(),
        "checks": {key: check.as_dict() for key, check in checks.items()},
    }


def detect_json() -> str:
    return json.dumps(detect_all(), ensure_ascii=False, indent=2)
