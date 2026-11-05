# Abrek Download

Linux için, tarayıcı eklentisiyle çalışan bir video indirici. İnternette gezinirken
oynatılan videoları otomatik yakalar; YouTube gibi sitelerde `yt-dlp`, doğrudan
medya dosyalarında çok parçalı indirme motoru kullanır.

Masaüstünde `Abrek-Download-main` klasöründe çalışır. Sürüm: **1.12.0**.

## Özellikler

- **Tarayıcı eklentisi:** Brave/Chrome ve Firefox için video yakalama.
- **Otomatik algılama:** `<video>` etiketleri, ağ istekleri, HLS (`.m3u8`) ve
  DASH (`.mpd`) yayınları.
- **İki indirme motoru:** `yt-dlp` site videoları için, çok parçalı doğrudan
  indirici medya dosyaları için.
- **Duraklat / devam et / iptal / yeniden dene.** Hatalı indirmeleri tek
  düğmeyle topluca yeniden deneyin.
- **Otomatik yeniden deneme:** ağ, zaman aşımı ve HTTP 429/5xx gibi geçici
  hatalarda görev artan bekleme süresiyle kendiliğinden yeniden denenir.
  DRM, 404 ve özel video gibi kalıcı hatalar boşuna tekrarlanmaz.
- **Kuyruk:** aynı anda birden fazla indirme, hız ve ETA gösterimi.
- **Kalıcı kuyruk:** uygulama kapanıp açıldığında yarım indirmeler kaldığı
  yerden devam eder.
- **Kalite seçimi:** en iyi, 4K, 2K, 1080p, 720p, 480p veya sadece ses.
- **Toplu işlem:** yakalanan videoların tümünü veya yapıştırdığınız birden çok
  bağlantıyı tek seferde kuyruğa ekleyin.
- **Disk güvenliği:** indirme ve birleştirme öncesinde boş alan denetlenir;
  yer yetersizse yarım dosya bırakmak yerine anlaşılır hata verilir.
- **Yakalama denetimi:** tarayıcı yakalamasını uygulamadan duraklatın/sürdürün,
  yakalanan bağlantıyı kopyalayın ve indirme klasörünü tek tıkla açın.
- **Ayrıntılar:** hata günlüğünü görüntüleyin, bağlantıyı kopyalayın.
- **Koyu/açık tema ve Türkçe/İngilizce arayüz**, masaüstü bildirimleri ve
  uygulama menüsü kısayolu.
- **Firefox kurulum yardımcısı:** tek betikle XPI oluşturma ve `about:debugging`
  sayfasını açma.
- **Dayanıklı indirme:** sunucu ETag/Last-Modified değişimini algılayarak eski
  yarım parçaları birleştirmez; yetim parça klasörlerini temizler.
- **Güvenli yerel köprü:** yalnızca `127.0.0.1`/`localhost` Host başlığını kabul
  eder, `Origin: null` isteklerini reddeder ve kontrol paneli HTML'ini kaçırır.

## Hızlı başlatma

```bash
cd ~/Desktop/Abrek-Download-main   # projenin bulunduğu yolu yazın
./baslat.sh
```

Komut satırından doğrudan indirme başlatabilirsiniz:

```bash
./baslat.sh "https://www.youtube.com/watch?v=..."
```

Uygulama kapalıysa açılır ve bağlantı kuyruğa eklenir; açıksa bağlantı çalışan
pencereye gönderilir. Kalite olarak ayarlardaki varsayılan değer kullanılır.

Kullanım ve sürüm bilgisi:

```bash
./baslat.sh --help
./baslat.sh --version
```

Yerel köprü üzerinden çalışan görevler `POST /api/tasks/<id>/pause`,
`resume`, `cancel` ve `retry` uçlarıyla denetlenebilir. `GET /api/tasks/<id>`,
`GET /api/stats` ve `POST /api/captures/<id>/download` uçları görev ayrıntısı,
özet sayaçlar ve yakalanan videoyu doğrudan kuyruğa ekleme sağlar.

İlk çalıştırmada `.venv` sanal ortamı oluşturulur ve `yt-dlp` kurulur.
Video birleştirme ve ses çıkarma için `ffmpeg`/`ffprobe`, YouTube'un JS
doğrulaması için `deno` (veya node) gerekir. Arch/CachyOS için:

```bash
sudo pacman -S ffmpeg deno
```
Uygulama açıldıktan sonra pencereyi kapatmak indirmeleri duraklatır; bir sonraki
açılışta kaldığı yerden devam eder.

### Uygulama menüsüne ekleme

```bash
cd ~/Desktop/Abrek-Download-main
./install.sh
```

Bu komut `Abrek Download` kısayolunu uygulama menüsüne ekler. Daha kolay bir
kurulum için grafik arayüzü de vardır:

```bash
cd ~/Desktop/Abrek-Download-main
./install-gui.sh
```

(`./kurulum.sh` de aynı arayüzü açar.)

Kurulum arayüzü ortamı denetler (Python, Tkinter, ffmpeg, deno, yt-dlp),
eksik bileşenleri listeler ve uygulama menüsü/masaüstü kısayollarını tek
tıklamayla oluşturur. Masaüstü kısayolu isterseniz `--desktop` seçeneğini
veya arayüzdeki kutuyu kullanın:

```bash
./install.sh --all
```

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

En kolay yol, proje klasöründe şu betiği çalıştırmaktır:

```bash
./firefox-eklenti.sh
```

Betik `dist/Abrek-Download-firefox.xpi` dosyasını oluşturur, Firefox'ta
`about:debugging#/runtime/this-firefox` sayfasını ve eklenti klasörünü açar.
Ardından:

1. **Geçici Eklenti Yükle** düğmesine tıklayın.
2. `extension/firefox/manifest.json` dosyasını seçin. (manifest.json seçildiğinde
   Firefox klasörün tamamını yükler.) Alternatif olarak
   `dist/Abrek-Download-firefox.xpi` dosyasını seçebilirsiniz.
3. Eklenti simgesini araç çubuğuna sabitleyin.

> **Önemli:** İmzasız XPI dosyasını `about:addons` → **Dosyadan eklenti yükle**
> ile veya çift tıklayarak kurmayın. Firefox bunu *"eklenti bozuk göründüğü
> için yüklenemedi"* diye reddeder. Bu bir paketleme hatası değil, Mozilla'nın
> imza zorunluluğudur. Geçici kurulum için yukarıdaki `about:debugging` yolunu
> kullanın.

Aynı işlemi uygulamadaki **Eklenti → Firefox kurulum yardımcısını aç**
düğmesiyle de yapabilirsiniz. Yalnızca XPI dosyasını üretmek için:

```bash
./firefox-eklenti.sh --xpi
```

Firefox geçici eklentileri tarayıcı yeniden başlatılınca kaldırır; her oturumda
yukarıdaki 1-2. adımı tekrarlamak gerekir. İmzasız bir eklenti Firefox'un
sürüm/beta kanallarında kalıcı olarak kurulamaz. Kalıcı kurulum için ücretsiz
AMO imzası kullanın:

1. <https://addons.mozilla.org/developers/> adresine girin.
2. **Submit a New Add-on → On your own** seçin.
3. `dist/Abrek-Download-firefox.xpi` dosyasını yükleyin.
4. AMO'nun ürettiği imzalı XPI dosyasını indirip
   `dist/Abrek-Download-firefox-signed.xpi` olarak kaydedin.
5. Şu komutla kurun:

```bash
./firefox-eklenti.sh --signed
```

Alternatif olarak Firefox Developer Edition, Nightly veya ESR kullanıp
`about:config` içinde `xpinstall.signatures.required` ayarını `false` yapabilirsiniz.

## Kullanım

1. Uygulamayı açın; sol alttaki **Yerel köprü** göstergesi yeşil olmalı.
2. Tarayıcıda bir video oynatın. Eklenti simgesindeki sayaç artar.
3. Abrek Download'daki **Yakalananlar** sekmesinde videoyu görüp **İndir**'e basın.
4. Alternatif olarak **İndirilenler** sekmesindeki bağlantı alanına bir video
   sayfası veya medya adresi yapıştırıp kalite seçerek indirebilirsiniz.
   **Toplu bağlantı** düğmesiyle her satıra bir adres yazarak birçok indirmeyi
   tek seferde kuyruğa ekleyebilirsiniz.

İndirilen dosyalar varsayılan olarak sistemin İndirilenler klasörü altındaki
`VideoAvci` dizinine kaydedilir. Yol, `user-dirs.dirs` içindeki
`XDG_DOWNLOAD_DIR` ayarından algılanır; genellikle `~/İndirilenler/VideoAvci`
veya `~/Downloads/VideoAvci` olur. **Ayarlar** sekmesinden değiştirilebilir.

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
- Proxy (HTTP/HTTPS/SOCKS; boş = doğrudan bağlantı)
- Giriş gerektiren siteler için çerez kaynağı (Brave, Firefox, Chrome, Chromium)
- `cookies.txt` dosyası (tarayıcı çerezleri okunamadığında; dosya seçiliyse
  tarayıcı seçeneği yok sayılır)
- Otomatik devam, geçici hatalarda otomatik yeniden deneme ve deneme sayısı
- Kuyruk geçmişi sınırı (tamamlanmış/hatalı görev sayısı; `0` = sınırsız)
- Masaüstü bildirimleri
- yt-dlp güncelleme

Çerez kullanırken tarayıcının kapalı olması gerekir; aksi halde çerez veritabanı
kilitli olabilir. Chrome'un yeni sürümlerinde tarayıcı çerezleri okunamazsa
tarayıcı eklentisiyle dışa aktardığınız Netscape biçimli `cookies.txt` dosyasını
seçebilirsiniz.

## Veri yolları

Ayarlar, veri ve durum yolları XDG ortam değişkenlerine uyar; indirme klasörü
`user-dirs.dirs` içindeki `XDG_DOWNLOAD_DIR` ayarından alınır. Parantez içinde
varsayılan değerler gösterilmiştir.

| Amaç | Yol |
| --- | --- |
| Ayarlar | `$XDG_CONFIG_HOME/videoavci/config.json` (`~/.config/...`) |
| Kuyruk | `$XDG_DATA_HOME/videoavci/queue.json` (`~/.local/share/...`) |
| Yakalananlar | `$XDG_DATA_HOME/videoavci/captures.json` (`~/.local/share/...`) |
| Parça dosyaları | `$XDG_DATA_HOME/videoavci/parts/` (`~/.local/share/...`) |
| Günlükler | `$XDG_STATE_HOME/videoavci/logs/app.log` (`~/.local/state/...`) |
| Varsayılan indirmeler | `XDG_DOWNLOAD_DIR/VideoAvci` (`~/İndirilenler/...` veya `~/Downloads/...`) |

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

### Firefox "eklenti bozuk göründüğü için yüklenemedi" hatası

Bu hata, imzasız XPI dosyasının `about:addons` → **Dosyadan eklenti yükle**
ile kurulmaya çalışılmasından kaynaklanır. Firefox sürüm/beta kanalları
imzasız eklentileri kalıcı olarak kabul etmez; XPI'nin kendisi bozuk değildir.
Geçici kurulum için:

1. `about:debugging#/runtime/this-firefox` sayfasını açın.
2. **Geçici eklenti yükle** düğmesine basın.
3. `extension/firefox/manifest.json` dosyasını seçin.

Kalıcı kurulum için AMO imzası gerekir; ayrıntılar için
[Firefox](#firefox) bölümüne bakın.

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

### YouTube "This video is not available" hatası

- `yt-dlp`'nin güncel olduğundan emin olun: `./guncelle.sh`
- YouTube'un JS doğrulaması için `deno` kurun:

  ```bash
  sudo pacman -S deno
  ```

- Uygulama YouTube bağlantılarında `--remote-components ejs:github` kullanır;
  ilk denemede GitHub'dan küçük bir çözücü bileşen indirilir. İnternet
  bağlantınızın açık olduğundan emin olun.
- Bazı videolar bölge, yaş veya telif kısıtlaması nedeniyle gerçekten
  kullanılamıyor olabilir. Bu durumda tarayıcıda videoyu açıp erişilebildiğini
  kontrol edin.

### "Permission denied" hatası

Zip dosyası bazı araçlarla çıkarıldığında betiklerin çalıştırma izni
kaybolabilir. Proje klasöründe şunu çalıştırın:

```bash
chmod +x baslat.sh guncelle.sh install.sh firefox-eklenti.sh
```

### Tkinter bulunamadı

Arch/CachyOS:

```bash
sudo pacman -S tk
```

## Proje yapısı

```
Abrek-Download-main/
├── app.py                 # Tkinter ana pencere ve sayfa yönetimi
├── baslat.sh              # Uygulamayı başlatır
├── guncelle.sh            # Bağımlılıkları günceller
├── install.sh             # Uygulama menüsüne kurar
├── firefox-eklenti.sh     # Firefox XPI + kurulum yardımcısı
├── install-gui.sh         # GUI kurulum sihirbazını başlatır (install_gui.py)
├── kurulum.sh             # Kurulum arayüzünü başlatır
├── install_gui.py         # Tkinter kurulum arayüzü
├── installer_strings.py   # Kurulum arayüzü metinleri
├── CHANGELOG.md           # Sürüm notları
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
├── tests/                 # Birim testleri
└── assets/                # Simgeler
```

## Geliştirme ve testler

Sanal ortam hazır olduktan sonra testleri çalıştırın:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Kod değişikliklerinden sonra ayrıca sözdizimi kontrolü yapılabilir:

```bash
python3 -m compileall -q app.py core ui tests
```

## Yasal not

Abrek Download yalnızca indirme hakkınız olan içerikler için kullanılmalıdır.
Telif hakkıyla korunan içerikleri izinsiz indirmek yasal sorunlara yol
açabilir. DRM korumalı yayınlar (Netflix, Disney+, vb.) desteklenmez.
