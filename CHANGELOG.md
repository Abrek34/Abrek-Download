# Sürüm Notları

## 1.11.1 — 2026-11-04

### Kurulum

- **Otomatik JavaScript çalışma zamanı kurulumu:** deno/node eksikse kurulum
  arayüzü artık sistem paket yansısına (mirror) güvenmeden kullanıcı düzeyinde
  `deno` kurar (`~/.deno/bin`, `~/.local/bin` bağlantısı). Kurulum programı
  eksik bağımlılığı kendisi tamamlar.

## 1.11.0 — 2026-11-04

### Hata sınıflandırması

- **Tipli hatalar:** `core/errors.py` ile `DownloadError`, `TransientDownloadError`,
  `PermanentDownloadError`, `DrmProtectedError`, `DiskSpaceError` vb. eklendi.
  Otomatik yeniden deneme artık hata mesajındaki kelimeler yerine `ErrorKind`
  alanına göre karar verir; yalnızca yt-dlp alt süreci çıktısı deterministik
  metin eşlemesiyle sınıflandırılır. `retry_after` değeri yeniden deneme
  gecikmesine yansıtılır (üst sınır 300 sn).

### Yerleşik medya analizi

- **Harici araçlar yalnızca yedek:** `core/probe.py` HLS, DASH, ISO BMFF (MP4),
  MPEG-TS ve WebM/Matroska için saf Python ayrıştırıcıları içerir. ffprobe ve
  yt-dlp yalnızca yerel analiz eksik kaldığında kullanılır. HLS `SAMPLE-AES` ve
  DASH `ContentProtection`, MP4 `pssh` ve WebM `ContentEncryption` algılanır.

### Tarayıcı eklentisi

- **Sözleşme testleri:** Chrome/Firefox manifestleri, ikonlar, kalite seçenekleri,
  API uç noktaları ve ortak varlıklar için `tests/test_extension.py` eklendi.

### DRM

- **Algılama ve engelleme:** Yakalamalara `drm` alanı eklendi; DRM korumalı
  içerikler için indirme düğmesi devre dışı bırakılır ve açık bir mesaj gösterilir.
  DRM korumasını aşmak yasal ve teknik olarak mümkün değildir; bu nedenle
  bypass uygulanmaz.

### Diğer

- Sürüm `1.11.0` olarak güncellendi.

## 1.10.0 — 2026-11-04

### Dayanıklılık ve indirme motoru

- **Otomatik yeniden deneme:** Ağ, zaman aşımı, HTTP 408/425/429 ve 5xx gibi
  geçici hatalarda görev üstel geri çekilmeyle (15/30/60/120 sn) yeniden
  kuyruğa alınır. Varsayılan olarak 2 denemedir; Ayarlar'dan 0-5 arasında
  değiştirilebilir. DRM, 404, 403, özel video ve desteklenmeyen URL gibi kalıcı
  hatalar otomatik denenmez.
- **Doğrudan indiricide akıllı yeniden deneme:** Parça ve tek akış indirmeleri
  `Retry-After` başlığına ve üstel geri çekilmeye uyar; kalıcı HTTP hatalarında
  boşuna beklenmez. Duraklat/iptal sinyalleri bekleme sırasında da dikkate
  alınır.
- **Disk alanı güvenliği:** İndirme başlamadan ve parçalar birleştirilmeden önce
  boş alan denetlenir. Yer yetersizse yarım dosya bırakmak yerine anlaşılır bir
  hata verilir.
- **yt-dlp son dosya çözümlemesi:** `after_move` çıktısı ve video kimliği
  kullanılır; eşzamanlı indirmelerde başka görevin dosyası seçilmez. Parça
  eşzamanlılığı ayarlardaki bağlantı sayısına bağlandı.
- **Kuyruk temizleme yarışı:** Tümünü temizle işlemi aktif görevlerin
  sayaçlarını erken sıfırlamaz; çalışan iş parçacıkları kendi temizliğini
  yapana kadar eşzamanlılık sınırı korunur.

### Yakalama analizi

- Her yakalama için ayrı iş parçacığı açmak yerine 2 işçili sınırlı kuyruk
  kullanılır. Analiz zaman damgası kalıcıdır (`probed_at`) ve 24 saat içinde
  aynı yakalama yeniden incelenmez; başarısız analizler de tekrar tekrar
  denenmez.

### Arayüz ve API

- **Toplu bağlantı ekleme:** İndirilenler sayfasına çok satırlı bağlantı
  penceresi eklendi; eklenen, zaten kuyrukta olan ve geçersiz adresler
  özetlenir. Tek kayıtla toplu kuyruk ekleme yapılır.
- Ayarlar sayfasına otomatik yeniden deneme ve deneme sayısı denetimleri
  eklendi.
- Yerel API'ye `GET /api/tasks/<id>`, `GET /api/stats` ve
  `POST /api/captures/<id>/download` uçları; Chrome özel ağ erişimi için
  `Access-Control-Allow-Private-Network` desteği eklendi.
- Tarayıcı eklentisi kalite menüsüne 2160p/1440p/480p seçenekleri eklendi;
  eklenti sürümü 1.2.1 oldu.

### Testler

- `parse_retry_after`, `free_space`, `is_transient_error`,
  `capture_needs_probe`, otomatik yeniden deneme, toplu ekleme, kuyruk
  temizleme, yeni API uçları ve yt-dlp son dosya seçimi için birim testleri
  eklendi. Toplam test sayısı 91'e çıktı.

## 1.9.0 — 2026-11-03

### Kritik düzeltmeler

- **`_probe_av` çalışmıyordu:** `pathlib` içe aktarılmadan `pathlib.PurePath`
  kullanıldığı için her çağrı sessizce `(False, False)` dönüyordu; ses-only HLS
  akışları hiç bulunamıyordu. Artık `yt-dlp` modülü ve YouTube ek argümanlarıyla
  çalışır, çıktıyı güvenli biçimde ayrıştırır.
- **Ses akışı yanlış indiriliyordu:** `_find_matching_audio` rastgele bir aday
  döndürebiliyor, `_download_one` ses URL'sini normal kalite seçicisiyle
  indiriyordu. Artık yalnızca gerçekten ses-only akış seçilir ve `audio_only`
  modunda yeniden kodlama yapılmadan indirilir.
- **Başarısız birleştirme videoyu siliyordu:** ffmpeg hatasında kaynak video
  siliniyordu. Artık kaynaklar korunur, MP4 başarısızsa MKV denenir ve
  birleştirme yine başarısız olursa video tek başına teslim edilir.
- **Bellek koruması:** ffprobe için indirilen ilk HLS parçası 4 MB ile
  sınırlandırıldı; büyük/bozuk parçalar belleği şişiremez.

### Tarayıcı eklentisi

- Sayfa/video yakalamaları tanımsız `postJson` ve `pushPending` çağrıları
  yüzünden hiç gönderilmiyordu; `postCapture` ve `addPending` ile düzeltildi.
- `handleDetection` içindeki tanımsız `contentRange` değişkeni giderildi.
- Instagram filtre regex'i düzeltildi; artık `instagram.com` doğru eşleşiyor.
- Geçersiz `merge` kalite değeri kaldırıldı; 2160p/1440p seçenekleri eklendi.
- Eklenti sürümü 1.2.0'a yükseltildi (Chrome ve Firefox).

### Yerel köprü ve güvenlik

- `Origin: null` istekleri artık reddediliyor; sandbox iframe/file kaynaklı
  isteklere karşı koruma sağlandı.
- Güvenlik başlıkları eklendi (`X-Frame-Options`, `Referrer-Policy`, CSP).
- `allow_reuse_address` sunucu kurulmadan önce etkinleştirildi.
- Görev denetimi için `POST /api/tasks/<id>/pause|resume|cancel|retry` uçları
  eklendi.

### Arayüz ve kullanım

- Yakalananlar sayfasına yakalamayı duraklat/sürdür düğmesi ve bağlantı kopyalama
  eklendi.
- İndirilenler sayfasına "Klasörü aç" düğmesi eklendi.
- Tema/dil değişikliğinde yeniden başlatma uyarısı gösteriliyor.
- Ayarlardaki varsayılan kalite, indirme sayfasındaki seçimle eşitleniyor.
- `--help` ve `--version` komut satırı seçenekleri eklendi.
- Üst düzeydeki kullanılmayan/eski `config.py` ve `manager.py` kopyaları
  kaldırıldı; sürüm 1.9.0'a yükseltildi.

## 1.8.13 — 2026-11-02

### Yeni özellikler

- **Ses + görüntü birleştirme:** film sitelerinde (vidmixi vb.) video-only ve
  audio-only HLS akışları ayrı yakalanıyordu; indirme sırasında eşleşen ses
  akışı otomatik bulunur, her ikisi indirilir ve ffmpeg ile tek dosyada
  birleştirilir.

## 1.8.15 — 2026-11-02

### Bug fixes & performans iyileştirmeleri

- **`_find_matching_audio`**: Yakalamaların ses/video ayrımı `_probe_av` ile
  kontrol edilir; ses‑only döne kadar iter. Eski kod tek URL ile döndürdü; artık
  doğru eşleşme sağlar.
- **`_merge_av`**: `ffmpeg -c copy` hata verirse `RuntimeError` fırlatıp
  video‑only dosyayı geri döndürür; uygulama çökmez.
- **`_download_one`**: `task.url` her zaman `finally` bloğu ile orijinaline geri
  yüklenir; exception'lar URL'u bozar.
- **`_probe_av`**: `yt-dlp` binary yol bulma mekanizması birkaç seçenekçe denenir
  (.venv, proje kökü, PATH); daha sağlam bulunur.
- **`_schedule_probe`**: Aynı yakalama için 24 saat içinde tekrar probe yapmayı
  engeller; needless overhead önlenir.

### Minor

- `_probe_av` çıktısından son satır JSON parse'i yapılır (yt-dlp bazen birden
  fazla satır çıktı verir).
- `_find_matching_audio` hiçbiri sesli değilse None döner; calling code bunu
  normal indirme yolunaiter.

## 1.8.12 — 2026-11-02

### Düzeltmeler

- **Film sitelerinde indirme hatası:** ⬇ menüsü ilk yakalamayı (sayfa
  bağlantısı) hemen gösteriyordu; gerçek video bağlantısı (m3u8) birkaç saniye
  sonra yakalanıyordu. Menü artık birkaç saniye bekleyip medya bağlantısını
  önceliklendiriyor; medya bağlantısı varsa sayfa bağlantısı ikinci planda
  kalıyor.

## 1.8.11 — 2026-11-02

### Düzeltmeler

- **Film sitelerinde indirme hatası:** yakalanan medya URL'si yt-dlp tarafından
  desteklenmeyen bir sayfa bağlantısı olabiliyordu. Ağ yakalama daha esnek
  hale getirildi (octet-stream, uzantısız media URL'leri de yakalanır); böylece
  gerçek video bağlantısı (mp4/m3u8) yakalanıp doğrudan indirilebilir.

## 1.8.10 — 2026-11-02

### Düzeltmeler

- **Film sitelerinde ⬇ tıklayınca "yakalanamadı":** sayfa yakalaması yalnızca
  ilk yüklemede tetikleniyordu; video sonradan yüklendiğinde yakalama
  eklenmiyordu. Şimdi video elementi göründüğünde sayfa yakalaması yeniden
  tetiklenir; iframe içindeki oynatıcılar da üst sayfa URL'si ile yakalanır.

## 1.8.9 — 2026-11-02

### Yeni özellikler

- **Genel site desteği:** Ağırlıklı olarak `<video>` içeren sayfalarda (film
  siteleri vb.) sayfa bağlantısı da yakalama olarak eklenir; böylece film
  sitelerinde ⬇ düğmesi tıklandığında "Yakalanan medya yok" yerine sayfa
  yakalaması listelenir ve yt-dlp ile indirilebilir.

## 1.8.8 — 2026-11-02

### Düzeltmeler

- **İndir düğmesi kayboluyordu:** eklenti yeniden yüklendiğinde DOM'daki eski
  işaretleyici kalıyor ve buton enjekte edilmiyordu. Buton eksikse yeniden
  saracak şekilde düzeltildi.

## 1.8.7 — 2026-11-02

### Düzeltmeler

- **Yakalama yeniden çalışmıyor:** eklentinin `onBeforeRequest` dinleyicisi
  `requestHeaders` extraInfoSpec değeri Firefox'ta geçersiz olduğundan hiç
  kaydedilmiyordu (tüm yakalama sessizce bozuluyordu). Geçersiz parametre
  kaldırıldı; yakalama yeniden çalışıyor (test edildi).

## 1.8.6 — 2026-11-02

### Düzeltmeler

- **Yakalama çalışmıyordu:** `handleDetection` içinde `pageUrl` değişkeni
  tanımlanmadan önce kullanılıyordu (temporal dead zone) ve yakalama sessizce
  başarısız oluyordu. Değişken kullanımı doğru sıraya alındı; Instagram ve
  diğer sitelerde yakalama yeniden çalışıyor.

## 1.8.5 — 2026-11-02

### Düzeltmeler

- **Instagram yakalama:** aralık (range) istekleri ve varyantlar artık
  engellemiyor; Instagram Reels videoları yakalanabiliyor. Aynı video için
  yinelenen yakalama engelleniyor.
- **Yakalamayı duraklat:** Ayarlar sayfasına "Video yakalamayı duraklat"
  seçeneği eklendi. Etkinken tarayıcı eklentisi yeni yakalama göndermez;
  `/api/health` üzerinden durum yayınlanır ve eklenti bu duruma uyar.

## 1.8.4 — 2026-11-02

### Düzeltmeler

- **Arayüz iyileştirmeleri:** sol üstteki play üçgeni yerine program simgesi
  kullanılıyor; "Abrek Download" başlığının yarım görünmesi (sidebar genişliği
  ve metin sarma) düzeltildi; yüksek DPI ekranlarda yazı ölçeği otomatik
  ayarlanıyor; pencere varsayılan/min boyutları iyileştirildi.

## 1.8.3 — 2026-11-02

### Yeni özellikler

- **GUI kurulum sihirbazı çalıştırılabilir hale getirildi:** `install-gui.sh`
  betiği eklendi. Grafik oturum yoksa veya Tkinter eksikse terminal kurulumuna
  (`install.sh`) düşer; `install_gui.py` çalıştırılabilir yapıldı.

## 1.8.2 — 2026-11-02

### Yeni özellikler

- **Kuyruğu toplu temizleme:** İndirilenler sayfasına "Tümünü temizle" düğmesi
  eklendi. Onay sonrası tüm görevler (aktif olanlar dahil) listeden kaldırılır;
  indirilen dosyalar silinmez. Yanlışlıkla "tümünü indir" yapıldığında oluşan
  yüzlerce görevi tek tıkla temizlemeyi sağlar.

## 1.8.1 — 2026-11-02

### Düzeltmeler

- **Instagram Reels yakalama taşması:** tek bir Reels sayfasında onlarca
  varyant/prefetch medya isteği yakalanıp "Yakalananlar" listesini dolduruyordu.
  Arka plan artık aynı Instagram tekil medya sayfası için ikinci yakalamayı
  engelliyor; prefetch istekleri ve küçük yanıtlar eleniyor. İçerik betiği
  Instagram'da performance kayıtlarını taramıyor ve sayfa değişince yerel
  "görüldü" listesini sıfırlıyor. Uygulama tarafında da aynı sayfa için
  yinelenen yakalama engellendi.

## 1.8.0 — 2026-11-01

### Yeni özellikler

- **Firefox kurulum yardımcısı:** `./firefox-eklenti.sh` betiği
  `dist/Abrek-Download-firefox.xpi` dosyasını oluşturur, Firefox'ta
  `about:debugging` sayfasını ve eklenti klasörünü açar. Kalıcı kurulum için
  AMO imza adımlarını gösterir.
- Eklenti sayfasına **Firefox kurulum yardımcısını aç** düğmesi eklendi.
- **Hata bildirimleri:** başarısız indirmeler için (aynı görevde bir kez)
  masaüstü bildirimi gösterilir. Yeniden denemeden sonra tekrar bildirilir.
- **Oynatma listesi kontrolü arka planda:** uzun listelerde arayüz donmaz;
  düğme "Liste denetleniyor…" durumuna geçer.

### Düzeltmeler

- **Firefox "bozuk" hatası:** imzasız XPI `about:addons` ile kurulmaya
  çalışıldığında Firefox'un verdiği yanıltıcı "eklenti bozuk" hatası
  açıklandı. Yardımcı artık geçici kurulumda `manifest.json` öneriyor ve
  AMO'dan indirilen imzalı XPI için `--signed` seçeneği sunuyor.
- **Firefox video menüsü:** eklentinin "Yükleniyor…" durumunda takılmasına yol
  açan `sendMessage` geri çağırma kullanımı Promise tabanlı çağrıya çevrildi.
  Chrome ve Firefox eklentileri 1.1.0 sürümüne yükseltildi.
- **Güvenli yerel köprü:** API artık yalnızca `127.0.0.1` ve `localhost` Host
  başlıklarını kabul ediyor; kontrol paneli değerleri HTML olarak kaçırılıyor.
- **Devam eden indirmeler:** `Accept-Encoding: identity` kullanılıyor; sunucu
  ETag/Last-Modified değerleri saklanıp değiştiğinde eski yarım parçalar
  birleştirilmiyor, indirme sıfırdan başlatılıyor.
- **Yetim parçalar:** kuyrukta karşılığı olmayan `parts/` klasörleri açılışta
  temizleniyor; görev kaldırıldığında parçaları da siliniyor.
- **Bitiş eylemi:** kapandıktan sonra kapanış/suspend eylemi yalnızca bir kez
  uygulanıyor; duraklatılmış görevler de eylem öncesi bekleniyor.
- **Bozuk sanal ortam onarımı:** `baslat.sh`, `guncelle.sh` ve
  `install.sh --prepare` çalışmayan `.venv` ortamını yeniden oluşturuyor.
- Görev kartları yalnızca değişen alanları yeniden çiziyor; gereksiz Tk
  güncellemeleri azaltıldı.

### Testler

- Host doğrulama, parça planlama, yetim parça temizliği ve bitiş eylemi için
  15 yeni test eklendi (toplam 53 test).

## 1.7.0 — 2026-11-01

### Yeni özellikler

- **Kurulum arayüzü:** `./kurulum.sh` ile ortam denetimi, eksik bileşen
  listesi ve uygulama menüsü/masaüstü kısayolu oluşturma işlemleri tek
  pencereden yönetiliyor.
- `install.sh` artık `--menu`, `--desktop`, `--all`, `--prepare`,
  `--uninstall` seçeneklerini destekliyor. Masaüstü kısayolu ve kaldırma
  işlemleri betik üzerinden de yapılabiliyor.
- `core/installer.py` ile ortam denetimi ve komut üretimi test edilebilir
  hale getirildi; 11 yeni birim/entegrasyon testi eklendi.

## 1.6.1 — 2026-11-01

### Düzeltmeler

- **YouTube indirmeleri:** yt-dlp'nin JS challenge desteği için `deno`
  çalışma zamanı ve `--remote-components ejs:github` bileşeni kullanılıyor.
  Bu sayede varsayılan istemcilerde "This video is not available" hatası
  alınan videolar indirilebiliyor.
- YouTube bağlantıları artık önce doğrudan indirme denenmeden yt-dlp ile
  işleniyor; gereksiz hata ve gecikme önleniyor.
- Başlatma betiği eksik JavaScript çalışma zamanı için uyarı veriyor.

## 1.6.0 — 2026-11-01

### Yeni özellikler

- **Hatalıları yeniden dene:** İndirilenler sayfasından başarısız görevlerin
  tümünü tek düğmeyle kuyruğa geri alın.
- **Tümünü indir:** Yakalananlar sayfasındaki videoların tümünü tek tıkla
  indirme kuyruğuna ekleyin.
- **Bağlantıyı kopyala:** Görev ayrıntıları penceresinden kaynak adresini
  panoya kopyalayın; pencereyi `Esc` ile kapatın.
- **Komut satırından indirme:** `./baslat.sh "URL"` ile uygulamayı açıp
  bağlantıyı kuyruğa ekleyin; uygulama zaten açıksa bağlantı çalışan pencereye
  gönderilir.

### Düzeltmeler

- Arama kutusu ile durum filtresi birlikte kullanıldığında liste artık doğru
  sonuç veriyor.
- Uygulama açılışında tamamlanan görevler için yinelenen bildirim
  gösterilmiyor.
- Pano izleyici aynı video bağlantısını tekrar yakalayabiliyor.
- `.php` gibi medya olmayan uzantılar yerine sunucunun bildirdiği MIME türüne
  göre `.mp4`/`.mp3` uzantısı seçiliyor.
- Kurulum betiği `Exec` ve `Icon` yollarını projenin taşındığı konuma göre
  yeniden yazıyor.
- Başlatma betiği eksik `ffmpeg`/`ffprobe` için uyarı veriyor.

### İyileştirmeler

- Kalite, durum ve yakalama etiketleri Türkçe/İngilizce olarak yerelleştirildi.
- yt-dlp sürümü paket metadatasından hızlıca okunuyor.
- İndirme durumu geri çağrıları kararlı anahtarlar ve yerelleştirilmiş ayrıntı
  metni kullanıyor.
- 25 birim testi eklendi.

## 1.5.1

- Tarayıcı eklentisiyle video yakalama, çok parçalı indirme motoru, kalıcı
  kuyruk, tema ve dil desteği.
