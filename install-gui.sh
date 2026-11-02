#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Abrek Download — GUI installer launcher (source tree)
#
# Tkinter kurulum arayüzünü (install_gui.py) açar. Grafik oturum yoksa veya
# Tkinter eksikse terminal kurulumuna (install.sh) düşer.
#
# Kullanım:
#   bash install-gui.sh                 # GUI kurulum sihirbazını aç
#   bash install-gui.sh --detect        # ortam denetimini JSON olarak yazdır
#   bash install-gui.sh --help          # yardım
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

cli_only=0
for arg in "$@"; do
    case "$arg" in
        --detect|--help|-h|--version|-V) cli_only=1 ;;
    esac
done

# Grafik oturum yoksa terminal kurulumuna geç.
if [[ "$cli_only" -eq 0 && -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    echo "Grafik oturumu bulunamadı (DISPLAY / WAYLAND_DISPLAY boş)." >&2
    echo "Terminal kurulumuna geçiliyor…" >&2
    if command -v sudo >/dev/null 2>&1; then
        exec sudo bash "$ROOT/install.sh" --all --prepare
    fi
    echo "sudo bulunamadı; şu komutu çalıştırın: sudo bash \"$ROOT/install.sh\" --all --prepare" >&2
    exit 77
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Hata: python3 bulunamadı." >&2
    if command -v sudo >/dev/null 2>&1; then
        echo "Terminal kurulumuna geçiliyor…" >&2
        exec sudo bash "$ROOT/install.sh" --all --prepare
    fi
    exit 1
fi

# Tkinter yoksa önce kurmayı dene (pkexec), olmazsa terminal kurulumuna düş.
if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    if command -v pkexec >/dev/null 2>&1 && command -v pacman >/dev/null 2>&1; then
        echo "Tkinter eksik; tk paketi kuruluyor…"
        pkexec pacman -S --needed --noconfirm tk || true
    fi
    if ! python3 -c "import tkinter" >/dev/null 2>&1; then
        echo "Hata: Tkinter bulunamadı." >&2
        echo "Arch/CachyOS için: sudo pacman -S tk" >&2
        echo "Terminal kurulumuna geçiliyor…" >&2
        if command -v sudo >/dev/null 2>&1; then
            exec sudo bash "$ROOT/install.sh" --all --prepare
        fi
        exit 1
    fi
fi

PYTHON_BIN="python3"
if [ -x "$ROOT/.venv/bin/python" ] && "$ROOT/.venv/bin/python" -c "import tkinter" >/dev/null 2>&1; then
    PYTHON_BIN="$ROOT/.venv/bin/python"
fi

exec "$PYTHON_BIN" "$ROOT/install_gui.py" "$@"
