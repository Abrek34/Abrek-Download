#!/usr/bin/env bash
# Abrek Download'yu uygulama menüsüne ve/veya masaüstüne kurar.
#
# Kullanım:
#   ./install.sh                 # uygulama menüsü kısayolu (eski davranış)
#   ./install.sh --menu          # yalnızca uygulama menüsü
#   ./install.sh --desktop       # yalnızca masaüstü kısayolu
#   ./install.sh --all           # ikisi birlikte
#   ./install.sh --prepare       # .venv ve Python bağımlılıklarını hazırla
#   ./install.sh --uninstall     # kısayolları kaldır (ayarlar/indirmeler korunur)
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/256x256/apps"
PYTHON="${PYTHON:-python3}"

install_menu=0
install_desktop=0
prepare=0
uninstall=0

usage() {
    sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

if [ "$#" -eq 0 ]; then
    install_menu=1
fi

while [ "$#" -gt 0 ]; do
    case "$1" in
        --menu) install_menu=1 ;;
        --desktop) install_desktop=1 ;;
        --all) install_menu=1; install_desktop=1 ;;
        --prepare) prepare=1 ;;
        --uninstall) uninstall=1 ;;
        -h|--help) usage; exit 0 ;;
        *)
            echo "Bilinmeyen seçenek: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

desktop_directory() {
    if [ -n "${XDG_DESKTOP_DIR:-}" ]; then
        printf '%s\n' "$XDG_DESKTOP_DIR"
        return
    fi
    if command -v xdg-user-dir >/dev/null 2>&1; then
        local value
        value="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
        if [ -n "$value" ]; then
            printf '%s\n' "$value"
            return
        fi
    fi
    printf '%s\n' "$HOME/Desktop"
}

write_entry() {
    local target="$1"
    mkdir -p "$(dirname -- "$target")"
    PROJECT_DIR="$PROJECT_DIR" awk '
        /^Exec=/ { print "Exec=\"" ENVIRON["PROJECT_DIR"] "/baslat.sh\""; next }
        /^Icon=/ { print "Icon=" ENVIRON["PROJECT_DIR"] "/assets/icon.png"; next }
        { print }
    ' "$PROJECT_DIR/VideoAvci.desktop" > "$target"
    chmod +x "$target"
    if command -v gio >/dev/null 2>&1; then
        gio set "$target" metadata::trusted true >/dev/null 2>&1 || true
    fi
}

refresh_caches() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
    fi
}

prepare_environment() {
    if ! command -v "$PYTHON" >/dev/null 2>&1; then
        echo "Python 3 bulunamadı. Lütfen python kurun." >&2
        return 1
    fi
    if [ ! -x "$PROJECT_DIR/.venv/bin/python" ] ||
        ! "$PROJECT_DIR/.venv/bin/python" -c "import sys" >/dev/null 2>&1; then
        if [ -d "$PROJECT_DIR/.venv" ]; then
            echo "Sanal ortam bozuk; onarılıyor…"
            rm -rf "$PROJECT_DIR/.venv"
        else
            echo "Sanal ortam oluşturuluyor…"
        fi
        "$PYTHON" -m venv --system-site-packages "$PROJECT_DIR/.venv"
    fi
    if ! "$PROJECT_DIR/.venv/bin/python" -c "import sys" >/dev/null 2>&1; then
        echo "Sanal ortam oluşturulamadı. Python kurulumunuzu denetleyin." >&2
        return 1
    fi
    if ! "$PROJECT_DIR/.venv/bin/python" -c "import tkinter" >/dev/null 2>&1; then
        echo "Uyarı: Tkinter bulunamadı. Arch/CachyOS için: sudo pacman -S tk" >&2
    fi
    if ! "$PROJECT_DIR/.venv/bin/python" -c "import yt_dlp, requests" >/dev/null 2>&1; then
        echo "Python bağımlılıkları kuruluyor…"
        "$PROJECT_DIR/.venv/bin/python" -m pip install --upgrade pip
        "$PROJECT_DIR/.venv/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"
    else
        echo "Python bağımlılıkları zaten kurulu."
    fi
}

if [ "$uninstall" -eq 1 ]; then
    rm -f "$APPS_DIR/videoavci.desktop" "$ICON_DIR/videoavci.png"
    rm -f "$(desktop_directory)/Abrek Download.desktop"
    DESKTOP_DIR="$(desktop_directory)"
    if [ -f "$DESKTOP_DIR/VideoAvci.desktop" ] && grep -q "$PROJECT_DIR/baslat.sh" "$DESKTOP_DIR/VideoAvci.desktop"; then
        rm -f "$DESKTOP_DIR/VideoAvci.desktop"
    fi
    refresh_caches
    echo "Abrek Download kısayolları kaldırıldı."
    echo "Ayarlar, indirme geçmişi ve indirilen dosyalar korundu."
    exit 0
fi

if [ "$prepare" -eq 1 ]; then
    prepare_environment
fi

if [ "$install_menu" -eq 1 ] || [ "$install_desktop" -eq 1 ]; then
    chmod +x "$PROJECT_DIR/baslat.sh" "$PROJECT_DIR/guncelle.sh" "$PROJECT_DIR/install.sh"
    if [ -f "$PROJECT_DIR/firefox-eklenti.sh" ]; then
        chmod +x "$PROJECT_DIR/firefox-eklenti.sh"
    fi
    if [ -f "$PROJECT_DIR/kurulum.sh" ]; then
        chmod +x "$PROJECT_DIR/kurulum.sh"
    fi
fi

if [ "$install_menu" -eq 1 ]; then
    mkdir -p "$APPS_DIR" "$ICON_DIR"
    cp "$PROJECT_DIR/assets/icon-256.png" "$ICON_DIR/videoavci.png"
    write_entry "$APPS_DIR/videoavci.desktop"
    echo "Abrek Download uygulama menüsüne eklendi."
fi

if [ "$install_desktop" -eq 1 ]; then
    DESKTOP_DIR="$(desktop_directory)"
    write_entry "$DESKTOP_DIR/Abrek Download.desktop"
    echo "Masaüstü kısayolu oluşturuldu: $DESKTOP_DIR/Abrek Download.desktop"
fi

if [ "$install_menu" -eq 1 ] || [ "$install_desktop" -eq 1 ]; then
    refresh_caches
    echo
    echo "Başlatmak için uygulama menüsünden Abrek Download'ı seçin veya:"
    echo "  $PROJECT_DIR/baslat.sh"
    echo
    echo "Tarayıcı eklentisi klasörü:"
    echo "  Brave / Chrome : $PROJECT_DIR/extension/chrome"
    echo "  Firefox        : $PROJECT_DIR/extension/firefox"
fi

if [ "$prepare" -eq 1 ] && [ "$install_menu" -eq 0 ] && [ "$install_desktop" -eq 0 ]; then
    echo "Python ortamı hazır."
fi
