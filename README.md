# Abrek Download

Linux için, tarayıcı eklentisiyle çalışan bir video indirici. İnternette gezinirken
oynatılan videoları otomatik yakalar; YouTube gibi sitelerde `yt-dlp`, doğrudan
medya dosyalarında çok parçalı indirme motoru kullanır.

Masaüstünde `/home/bbbb/Masaüstü/VideoAvci` klasöründe çalışır.

## Özellikler

- **Tarayıcı eklentisi:** Brave/Chrome ve Firefox için video yakalama.
- **Otomatik algılama:** `<video>` etiketleri, ağ istekleri, HLS (`.m3u8`) ve
  DASH (`.mpd`) yayınları.
- **İki indirme motoru:** `yt-dlp` site videoları için, çok parçalı doğrudan
  indirici medya dosyaları için.
- **Duraklat / devam et / iptal / yeniden dene.**
- **Kuyruk:** aynı anda birden fazla indirme, hız ve ETA gösterimi.
- **Kalıcı kuyruk:** uygulama kapanıp açıldığında yarım indirmeler kaldığı
  yerden devam eder.
- **Kalite seçimi:** en iyi, 4K, 2K, 1080p, 720p, 480p veya sadece ses.
- **Koyu Türkçe arayüz**, masaüstü bildirimleri ve uygulama menüsü kısayolu.

## Hızlı başlatma

```bash
cd /home/bbbb/Masaüstü/VideoAvci
./baslat.sh
```

İlk çalıştırmada `.venv` sanal ortamı oluşturulur ve `yt-dlp` kurulur.
Uygulama açıldıktan sonra pencereyi kapatmak indirmeleri duraklatır; bir sonraki
açılışta kaldığı yerden devam eder.

### Uygulama menüsüne ekleme

```bash
cd /home/bbbb/Masaüstü/VideoAvci
./install.sh
```

Bu komut `Abrek Download` kısayolunu uygulama menüsüne ekler. Masaüstü kısayolu
isterseniz `VideoAvci.desktop` dosyasını masaüstüne kopyalayabilirsiniz.

## Tarayıcı eklentisi kurulumu

Uygulama açıkken **Eklenti** sekmesinde adımlar ve eklenti klasörünün yolu
görünür. Klasörü oradan açabilir veya aşağıdaki yolları kullanabilirsiniz:

- Brave / Chrome: `extension/chrome`
- Firefox: `extension/firefox`

### Brave / Chrome

1. Adres çubuğuna `brave://extensions` (Chrome'da `chrome://extensions`) yazın.
2. Sağ üstten **Geliştirici modu**nu açın.
3. **Paketlenmemiş öğe yükle** düğmesine tıklayın.
4. `extension/chrome` klasörünü seçin.
5. Eklenti simgesini araç çubuğuna sabitleyin.

Eklenti, `http://127.0.0.1:8765` adresindeki yerel köprü üzerinden uygulamaya
bağlanır. Uygulama kapalıysa yakalanan videolar eklentide bekletilir ve uygulama
açılınca gönderilir.

### Firefox

1. Adres çubuğuna `about:debugging#/runtime/this-firefox` yazın.
2. **Geçici Eklenti Yükle** düğmesine tıklayın.
3. `extension/firefox/manifest.json` dosyasını seçin.

Firefox geçici eklentileri tarayıcı yeniden başlatılınca kaldırır. Kalıcı
kurulum için eklentinin imzalanması gerekir; günlük kullanımda geçici yükleme
yeterlidir.

## Kullanım

1. Uygulamayı açın; sol alttaki **Yerel köprü** göstergesi yeşil olmalı.
2. Tarayıcıda bir video oynatın. Eklenti simgesindeki sayaç artar.
3. Abrek Download'daki **Yakalananlar** sekmesinde videoyu görüp **İndir**'e basın.
4. Alternatif olarak **İndirilenler** sekmesindeki bağlantı alanına bir video
   sayfası veya medya adresi yapıştırıp kalite seçerek indirebilirsiniz.

İndirilen dosyalar varsayılan olarak `~/İndirilenler/VideoAvci` klasörüne
kaydedilir. **Ayarlar** sekmesinden değiştirilebilir.

### Klavye kısayolları

- `Ctrl+N`: bağlantı alanına git
- `F5`: listeyi yenile
- `Ctrl+Q`: uygulamayı kapat

## Ayarlar

- İndirme klasörü
- Aynı anda indirme sayısı (1-5)
- Doğrudan indirmelerde bağlantı/parça sayısı (1-8)
- Varsayılan kalite
- Hız sınırı (KB/s, `0` = sınırsız)
- Giriş gerektiren siteler için çerez kaynağı (Brave, Firefox, Chrome, Chromium)
- Otomatik devam ve masaüstü bildirimleri
- yt-dlp güncelleme

Çerez kullanırken tarayıcının kapalı olması gerekir; aksi halde çerez veritabanı
kilitli olabilir.

## Veri yolları

| Amaç | Yol |
| --- | --- |
| Ayarlar | `~/.config/videoavci/config.json` |
| Kuyruk | `~/.local/share/videoavci/queue.json` |
| Yakalananlar | `~/.local/share/videoavci/captures.json` |
| Parça dosyaları | `~/.local/share/videoavci/parts/` |
| Günlükler | `~/.local/state/videoavci/logs/app.log` |
| Varsayılan indirmeler | `~/İndirilenler/VideoAvci` |

## Sorun giderme

### "Yerel köprü başlatılamadı" uyarısı

`8765` portu başka bir uygulama tarafından kullanılıyor olabilir. Şununla
kontrol edin:

```bash
ss -ltnp | grep 8765
```

Portu kullanan uygulamayı kapatıp Abrek Download'daki **Yeniden dene** düğmesine
basın. Uygulama ikinci kez açılmaya çalışılırsa mevcut pencereyi kullanmanız
gerektiğini belirten bir uyarı görürsünüz.

### Eklenti videoyu yakalamıyor

- Uygulamanın açık ve köprü göstergesinin yeşil olduğundan emin olun.
- Eklentinin **Geliştirici modu** ile yüklendiğini kontrol edin.
- Sayfayı yenileyip videoyu tekrar oynatın.
- **Eklenti** sekmesindeki **Bağlantıyı test et** düğmesini kullanın.
- Bazı siteler videoyu DRM (Widevine) ile korur; bu içerikler indirilemez.

### İndirme hatası

Görev kartındaki **Ayrıntı** düğmesi hata mesajını ve yt-dlp günlüğünü gösterir.
Site desteği için `yt-dlp`'yi güncelleyin:

```bash
./guncelle.sh
```

veya **Ayarlar → Bakım → Güncelle**.

### Tkinter bulunamadı

Arch/CachyOS:

```bash
sudo pacman -S tk
```

## Proje yapısı

```
VideoAvci/
├── app.py                 # Tkinter ana pencere ve sayfa yönetimi
├── baslat.sh              # Uygulamayı başlatır
├── guncelle.sh            # Bağımlılıkları günceller
├── install.sh             # Uygulama menüsüne kurar
├── VideoAvci.desktop      # Masaüstü kısayolu
├── core/
│   ├── config.py          # Yollar ve ayarlar
│   ├── manager.py         # Kuyruk, görevler, yakalananlar
│   ├── direct.py          # Çok parçalı indirme motoru
│   ├── ytdlp.py           # yt-dlp sarmalayıcısı
│   ├── server.py          # 127.0.0.1:8765 yerel API
│   ├── models.py          # DownloadTask / Capture
│   └── utils.py           # Yardımcılar
├── extension/
│   ├── chrome/            # Brave / Chrome MV3 eklentisi
│   └── firefox/           # Firefox MV3 eklentisi
├── ui/                    # Arayüz bileşenleri ve sayfalar
└── assets/                # Simgeler
```

## Yasal not

Abrek Download yalnızca indirme hakkınız olan içerikler için kullanılmalıdır.
Telif hakkıyla korunan içerikleri izinsiz indirmek yasal sorunlara yol
açabilir. DRM korumalı yayınlar (Netflix, Disney+, vb.) desteklenmez.
