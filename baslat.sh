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

if [ ! -x ".venv/bin/python" ] || ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    if [ -d ".venv" ]; then
        echo "Sanal ortam bozuk; onarılıyor…"
        rm -rf .venv
    else
        echo "Sanal ortam oluşturuluyor…"
    fi
    "$PYTHON" -m venv --system-site-packages .venv
fi

if ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    echo "Sanal ortam oluşturulamadı. Python kurulumunuzu denetleyin." >&2
    exit 1
fi

if ! .venv/bin/python -c "import tkinter" >/dev/null 2>&1; then
    echo "Tkinter bulunamadı. Arch/CachyOS için: sudo pacman -S tk" >&2
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    echo "Uyarı: ffmpeg/ffprobe bulunamadı." >&2
    echo "Video birleştirme ve ses çıkarma özellikleri çalışmayabilir." >&2
    echo "Arch/CachyOS için: sudo pacman -S ffmpeg" >&2
fi

JS_RUNTIME=""
for runtime in deno node bun qjs quickjs; do
    if command -v "$runtime" >/dev/null 2>&1; then
        JS_RUNTIME="$runtime"
        break
    fi
done
if [ -z "$JS_RUNTIME" ]; then
    echo "Uyarı: YouTube için JavaScript çalışma zamanı bulunamadı." >&2
    echo "YouTube indirmeleri için deno önerilir: sudo pacman -S deno" >&2
fi

if ! .venv/bin/python -c "import yt_dlp, requests" >/dev/null 2>&1; then
    echo "Bağımlılıklar kuruluyor…"
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
fi

exec .venv/bin/python app.py "$@"
