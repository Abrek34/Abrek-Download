#!/usr/bin/env bash
# Abrek Download'yı başlatır; sanal ortam yoksa kurar.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python 3 bulunamadı. Lütfen python kurun." >&2
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "Sanal ortam oluşturuluyor…"
    "$PYTHON" -m venv --system-site-packages .venv
fi

if ! .venv/bin/python -c "import tkinter" >/dev/null 2>&1; then
    echo "Tkinter bulunamadı. Arch/CachyOS için: sudo pacman -S tk" >&2
    exit 1
fi

if ! .venv/bin/python -c "import yt_dlp, requests" >/dev/null 2>&1; then
    echo "Bağımlılıklar kuruluyor…"
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
fi

exec .venv/bin/python app.py "$@"
