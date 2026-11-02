#!/usr/bin/env bash
# Abrek Download — Firefox eklentisi kurulum yardımcısı.
#
# Kullanım:
#   ./firefox-eklenti.sh          # XPI oluştur, Firefox'ta about:debugging sayfasını aç
#   ./firefox-eklenti.sh --xpi    # yalnızca dist/Abrek-Download-firefox.xpi dosyasını oluştur
#   ./firefox-eklenti.sh --signed # AMO'dan indirilen imzalı XPI'yi kur
#   ./firefox-eklenti.sh --help   # bu yardımı göster
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$PROJECT_DIR/extension/firefox"
DIST_DIR="$PROJECT_DIR/dist"
XPI="$DIST_DIR/Abrek-Download-firefox.xpi"
SIGNED_XPI="$DIST_DIR/Abrek-Download-firefox-signed.xpi"
MANIFEST="$SRC_DIR/manifest.json"
PYTHON="${PYTHON:-python3}"

usage() {
    sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

mode="debug"
case "${1:-}" in
    --debug) mode="debug" ;;
    --xpi) mode="xpi" ;;
    --signed) mode="signed" ;;
    -h|--help) usage; exit 0 ;;
    "")
        ;;
    *)
        echo "Bilinmeyen seçenek: $1" >&2
        usage >&2
        exit 2
        ;;
esac

if [ ! -f "$MANIFEST" ]; then
    echo "Eklenti kaynağı bulunamadı: $MANIFEST" >&2
    exit 1
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python 3 bulunamadı. Lütfen python kurun." >&2
    exit 1
fi

mkdir -p "$DIST_DIR"
PACKAGE_REPORT="$("$PYTHON" - "$SRC_DIR" "$XPI" <<'PY'
import sys
import zipfile
from pathlib import Path

src = Path(sys.argv[1])
out = Path(sys.argv[2])
files = [
    path
    for path in sorted(src.rglob("*"))
    if path.is_file()
    and "__pycache__" not in path.parts
    and not path.name.startswith(".")
]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        archive.write(path, path.relative_to(src).as_posix())
    names = archive.namelist()
if "manifest.json" not in names:
    raise SystemExit("HATA: XPI kökünde manifest.json yok.")
signed = any(
    name.startswith("META-INF/")
    and (name.endswith(".rsa") or name.endswith(".sig"))
    for name in names
)
print(f"{len(files)} dosya paketlendi: {out}")
print("SIGNED" if signed else "UNSIGNED")
PY
)"
printf '%s\n' "$PACKAGE_REPORT" | head -n 1

is_signed=0
if printf '%s\n' "$PACKAGE_REPORT" | tail -n 1 | grep -qx "SIGNED"; then
    is_signed=1
fi

echo
echo "Firefox XPI hazır: $XPI"
if [ "$is_signed" -eq 1 ]; then
    echo "İmza durumu: imzalı (kalıcı kurulum yapılabilir)"
else
    echo "İmza durumu: imzasız (about:debugging ile geçici kurulum)"
fi
echo

if [ "$mode" = "signed" ]; then
    if [ ! -f "$SIGNED_XPI" ]; then
        cat >&2 <<EOF
İmzalı XPI bulunamadı: $SIGNED_XPI

AMO'dan indirdiğiniz imzalı dosyayı bu adla dist/ klasörüne koyun:
  https://addons.mozilla.org/developers/
Ardından betiği yeniden çalıştırın:
  ./firefox-eklenti.sh --signed
EOF
        exit 1
    fi
    echo "İmzalı XPI açılıyor: $SIGNED_XPI"
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$SIGNED_XPI" >/dev/null 2>&1 &
    else
        echo "Dosyayı Firefox'ta elle açın: $SIGNED_XPI" >&2
    fi
    exit 0
fi

if [ "$mode" = "xpi" ]; then
    cat <<EOF
Geçici kurulum için:
  1. Firefox'ta about:debugging#/runtime/this-firefox sayfasını açın.
  2. "Geçici eklenti yükle..." düğmesine basın.
  3. Şu dosyayı seçin:
     $MANIFEST
     (manifest.json seçildiğinde Firefox klasörün tamamını yükler.)
     Alternatif: $XPI

ÖNEMLİ: İmzasız XPI'yi about:addons → "Dosyadan eklenti yükle" ile
veya çift tıklayarak KURMAYIN. Firefox bunu "eklenti bozuk göründüğü
için yüklenemedi" diye reddeder. Bu bir paketleme hatası değil, Mozilla'nın
imza zorunluluğudur. Kalıcı kurulum için XPI'yi AMO'da imzalatın:
  https://addons.mozilla.org/developers/  →  "Submit a New Add-on"
  →  "On your own" (kendi dağıtımınız)  →  XPI dosyasını yükleyin.
  AMO'nun ürettiği imzalı XPI'yi dist/Abrek-Download-firefox-signed.xpi
  olarak kaydedip ./firefox-eklenti.sh --signed çalıştırın.
EOF
    exit 0
fi

if command -v firefox >/dev/null 2>&1; then
    echo "Firefox açılıyor: about:debugging#/runtime/this-firefox"
    firefox --new-tab "about:debugging#/runtime/this-firefox" >/dev/null 2>&1 &
else
    echo "Uyarı: firefox komutu bulunamadı. Sayfayı elle açın:" >&2
    echo "  about:debugging#/runtime/this-firefox" >&2
fi

# XPI'yi dosya yöneticisinde açmıyoruz: çift tıklama about:addons üzerinden
# imza denetimine girer ve yanıltıcı "bozuk" hatasına yol açar. Bunun yerine
# about:debugging dosya seçicisinde manifest.json'un bulunduğu klasörü açıyoruz.
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$SRC_DIR" >/dev/null 2>&1 &
fi

cat <<EOF
Geçici kurulum (yaklaşık 30 saniye):
  1. Açılan Firefox sekmesinde "Geçici eklenti yükle..." düğmesine basın.
  2. Açılan pencerede şu dosyayı seçin:
     $MANIFEST
     (manifest.json seçildiğinde Firefox klasörün tamamını yükler.)
     Alternatif: $XPI
     (Dosya yöneticisi eklenti klasöründe açıldı.)
  3. Eklenti araç çubuğunda görünecek. Abrek Download açıkken videoları yakalar.

ÖNEMLİ: İmzasız XPI'yi about:addons → "Dosyadan eklenti yükle" ile
veya çift tıklayarak kurmayın; Firefox "eklenti bozuk göründüğü için
yüklenemedi" hatası verir. Bu hata imza zorunluluğundan kaynaklanır,
XPI'nin kendisi sağlamdır.

Not: Firefox geçici eklentileri tarayıcı kapanınca kaldırır. Her oturumda
1-2. adımı tekrarlamanız gerekir. Bu betiği yeniden çalıştırmak yeterlidir.

Kalıcı kurulum (isteğe bağlı):
  İmzasız eklenti Firefox sürüm/beta sürümlerinde kalıcı kurulamaz.
  Ücretsiz AMO imzası için:
    1. https://addons.mozilla.org/developers/ adresine girin.
    2. "Submit a New Add-on" → "On your own" seçin.
    3. Şu XPI dosyasını yükleyin: $XPI
    4. AMO'nun verdiği imzalı XPI'yi indirip şu adla kaydedin:
       $SIGNED_XPI
    5. ./firefox-eklenti.sh --signed
  Alternatif: Firefox Developer Edition/Nightly/ESR kullanıp
  about:config → xpinstall.signatures.required = false ayarlayın.
EOF
