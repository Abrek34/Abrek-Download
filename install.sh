#!/usr/bin/env bash
# Abrek Download'yı uygulama menüsüne ve simge temasına kurar.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/256x256/apps"

mkdir -p "$APPS_DIR" "$ICON_DIR"

cp "$PROJECT_DIR/assets/icon-256.png" "$ICON_DIR/videoavci.png"
sed "s|/home/bbbb/Masaüstü/VideoAvci|$PROJECT_DIR|g" \
    "$PROJECT_DIR/VideoAvci.desktop" > "$APPS_DIR/videoavci.desktop"

chmod +x "$PROJECT_DIR/baslat.sh" "$PROJECT_DIR/guncelle.sh" "$PROJECT_DIR/install.sh"
chmod +x "$APPS_DIR/videoavci.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Abrek Download uygulama menüsüne eklendi."
echo "Başlatmak için uygulama menüsünden Abrek Download'yı seçin veya:"
echo "  $PROJECT_DIR/baslat.sh"
echo
echo "Tarayıcı eklentisi klasörü:"
echo "  Brave / Chrome : $PROJECT_DIR/extension/chrome"
echo "  Firefox        : $PROJECT_DIR/extension/firefox"
