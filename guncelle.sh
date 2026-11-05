#!/usr/bin/env bash
# Abrek Download bağımlılıklarını ve yt-dlp'yi günceller.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

PYTHON="${PYTHON:-python3}"

if [ ! -x ".venv/bin/python" ] || ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    if [ -d ".venv" ]; then
        echo "Sanal ortam bozuk; onarılıyor…"
        rm -rf .venv
    fi
    "$PYTHON" -m venv --system-site-packages .venv
fi

if ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    echo "Sanal ortam oluşturulamadı. Python kurulumunuzu denetleyin." >&2
    exit 1
fi

echo "Bağımlılıklar güncelleniyor…"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --upgrade -r requirements.txt
.venv/bin/python -m pip install --upgrade yt-dlp

VERSION="$(.venv/bin/python -c 'import yt_dlp; print(yt_dlp.version.__version__)')"
echo "Tamamlandı. yt-dlp sürümü: $VERSION"
