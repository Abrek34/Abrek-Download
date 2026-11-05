#!/usr/bin/env bash
# Abrek Download kurulum arayüzünü başlatır.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

pick_python() {
    if [ -n "${PYTHON:-}" ]; then
        printf '%s\n' "$PYTHON"
        return
    fi
    if [ -x "$PROJECT_DIR/.venv/bin/python" ] &&
        "$PROJECT_DIR/.venv/bin/python" -c "import tkinter" >/dev/null 2>&1; then
        printf '%s\n' "$PROJECT_DIR/.venv/bin/python"
        return
    fi
    printf '%s\n' "python3"
}

PYTHON_BIN="$(pick_python)"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Python 3 bulunamadı. Lütfen python kurun." >&2
    exit 1
fi
if ! "$PYTHON_BIN" -c "import tkinter" >/dev/null 2>&1; then
    echo "Tkinter bulunamadı; kurulum arayüzü açılamıyor." >&2
    echo "Arch/CachyOS için: sudo pacman -S tk" >&2
    echo "Debian/Ubuntu için: sudo apt install python3-tk" >&2
    exit 1
fi

exec "$PYTHON_BIN" "$PROJECT_DIR/install_gui.py" "$@"
