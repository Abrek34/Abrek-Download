# Sürüm Notları

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
