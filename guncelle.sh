#!/usr/bin/env bash
# Abrek Download bağımlılıklarını ve yt-dlp'yi günceller.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

PYTHON="${PYTHON:-python3}"

if [ ! -x ".venv/bin/python" ]; then
    "$PYTHON" -m venv --system-site-packages .venv
fi

echo "Bağımlılıklar güncelleniyor…"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --upgrade -r requirements.txt
.venv/bin/python -m pip install --upgrade yt-dlp

VERSION="$(.venv/bin/python -c 'import yt_dlp; print(yt_dlp.version.__version__)')"
echo "Tamamlandı. yt-dlp sürümü: $VERSION"
