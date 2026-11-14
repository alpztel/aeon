# AEON — 3-Minute Jury Demo Tour Script (TR | EN)

Bu doküman, NASA Space Apps Challenge jürisine yapılacak **3 dakikalık canlı AEON sunumu** için saniyesi saniyesine tıklama adımlarını ve Türkçe / İngilizce sunum metinlerini içerir.

> **Ön Hazırlık:**
> - Tarayıcıda `https://aeon.tech` (veya `http://localhost:3000`) açık.
> - Üst bardaki veri modu rozeti (`FITS Arşivi` veya `Fiziksel Gökyüzü Modeli`) görünür durumda.
> - Ses sistemi açık (Adım 1 veya Adım 2'de 102-bant spektral sonifikasyonu dinletmek için).

---

## [0:00 – 0:25] Giriş & Vizyon (25 sn)

### Tıklama / Eylem
1. Üst bardaki **`TR | EN`** dil düğmesine tıklayarak çift dilli arayüzü gösterin.
2. Altındaki **Canlı GCN Uyarı Bandı** (`GCN / VOEvent Canlı Uyarı Akışı`) üzerinde geçen geçici kaynak koordinatlarını işaret edin.
3. Üst bardaki kehribar renkli **`Jüri Demo Turu (3 dk)` / `Jury Demo Tour (3 min)`** düğmesine tıklayın.

### Konuşma Metni (TR)
> "Merhaba, biz AEON ekibiyiz. SPHEREx misyonu tüm gökyüzünü 0.75 ile 5.0 mikron arasında **102 ayrı kızılötesi spektral bantta**, 6 ayda bir tekrar tarayarak 4 boyutlu bir evren haritası üretiyor. AEON, bu çok dönemli kızılötesi küpleri gerçek zamanlı görüntü farkı, 102-bant spektroskopi, çoklu misyon çapraz eşleştirme ve kaydır-ve-yığ (shift-and-stack) analizleriyle birleştiren açık kaynaklı bir Astrofiziksel Keşif İşletim Sistemidir."

### Spoken Script (EN)
> "Hello, we are Team AEON. NASA's SPHEREx mission surveys the entire sky across **102 near-to-mid infrared spectral channels** from 0.75 to 5.0 microns every six months. AEON is an open Astrophysical Discovery OS that fuses these multi-epoch spectral cubes with real-time image differencing, 102-band spectroscopy, multi-mission cross-matching, and sub-threshold shift-and-stack recovery."

---

## [0:25 – 1:15] Adım 1 — Soğuk Kahverengi Cüce: `WISE J085510.83-071442.5` (50 sn)

### Tıklama / Eylem
1. **Demo Turu Çubuğu Adım 1 (`1. WISE 0855`)** seçili olduğunda sistem otomatik olarak `RA 133.7951°, Dec -7.2451°` koordinatlarına uçar ve **M2 — Görüntü Farkı Modu (`D`)** panelini açar.
2. **Görüntü Farkı Modu** panelinde `Dönem 1 (2026-Q1)`, `Dönem 2 (2026-Q3)` ve **`Fark (E2 - E1)`** kanvasındaki mavi-kırmızı **± dipol imzasını** gösterin (`Dipol Algılandı` rozeti).
3. Aşağıdaki **M3 — 102-Bant Kızılötesi Spektrum** paneline inin; `H₂O`, `CH₄`, `CO₂` ve `CO` soğurma şeritlerini ve **4–5 µm termal emisyon penceresini** işaret edin.
4. **`Spektrumu Dinle (Sonifikasyon)`** düğmesine tıklayarak 2.5 saniyelik Web Audio API seslendirmesini jüriye dinletin.
5. **M7 — Çoklu Misyon Çapraz Eşleştirme** panelinde **"Eşleşmeyen Soğuk KÖ Adayı (Gaia'da Yok)"** rozetini gösterin.

### Konuşma Metni (TR)
> "İlk durağımız Güneş'e 2.3 parsek uzaklıktaki bilinen en soğuk kahverengi cüce: **WISE 0855** (~250 Kelvin). Optik teleskoplarda ve Gaia DR3 kataloğunda tamamen görünmezdir. Ancak AEON'un **Görüntü Farkı Modu** (`D`), 2026-Q1 ve 2026-Q3 dönemlerini birbirinden çıkardığında, yılda 8.1 yay-saniyelik özdevinimini karakteristik bir pozitif-negatif dipol olarak anında yakalar. 102-bant SPHEREx spektrumunda derin metan (`CH₄`) ve su buharı (`H₂O`) soğurma çukurlarını ve 4.5 mikrondaki keskin termal tepeyi hem görsel hem de işitsel sonifikasyonla inceleyebiliyoruz."

### Spoken Script (EN)
> "Our first stop is **WISE 0855**, the coldest known brown dwarf at 250 Kelvin, just 2.3 parsecs away. It is completely invisible to optical surveys like Gaia DR3. In AEON's **Difference Mode** (`D`), subtracting 2026-Q1 from 2026-Q3 immediately reveals a sharp positive-negative dipole caused by its 8.1 arcseconds-per-year proper motion. In the 102-band SPHEREx spectrum below, deep methane and water-vapor absorption bands carve out the classic 4-to-5 micron thermal window, which we can also experience through real-time Web Audio sonification."

---

## [1:15 – 1:55] Adım 2 — Değişken Genç Yıldız: `RW Aurigae` (40 sn)

### Tıklama / Eylem
1. Demo Turu Çubuğunda **`İleri` (`2. RW Aurigae`)** düğmesine tıklayın.
2. **M3 — 102-Bant Spektrum** panelinde **`Mevcut Spektrumu Sabitle`** düğmesine tıklayarak `2026-Q3` spektrumunu referans olarak sabitleyin.
3. Üstteki **Dönem Zaman Çizelgesi**nden (`M1`) **`2026-Q1`** dönemine tıklayın: sabitlenen kesikli referans eğrisi ile yeni dönem arasındaki kısa dalga boyu (`< 2 µm`) toz sönümlemesi ve uzun dalga boyu (`> 3 µm`) sıcak iç disk parlamasını karşılaştırın.
4. **M9 — AI Spektral Sınıflandırma & Anomali** kartında `Genç Değişken Yıldız (T Tauri)` olasılık çubuğunu gösterin.

### Konuşma Metni (TR)
> "İkinci adımda genç T Tauri yıldızı **RW Aurigae**'ye geçiyoruz. Sabitlediğimiz 2026-Q3 spektrumunu 2026-Q1 ile karşılaştırdığımızda, bozulmuş ön-gezegen diskindeki toz bulutlarının 2 mikron altında yıldızı nasıl kararttığını, buna karşın 3 mikron üzerindeki sıcak iç disk emisyonunun nasıl parladığını doğrudan ölçüyoruz. 1D-CNN sınıflandırıcımız bu imzayı yüksek güvenle T Tauri değişkeni olarak etiketliyor."

### Spoken Script (EN)
> "Step two takes us to the young T Tauri star **RW Aurigae**. By pinning the 2026-Q3 spectrum and switching the epoch slider to 2026-Q1, we directly observe circumstellar dust occultation dimming the short wavelengths below 2 microns while thermal emission from the warm inner disk brightens beyond 3 microns—automatically classified by our 1D-CNN spectral engine."

---

## [1:55 – 2:45] Adım 3 — Sentetik Gürültü Altı Test Adayı: `PX-2026-09` (50 sn)

### Tıklama / Eylem
1. Demo Turu Çubuğunda **`İleri` (`3. PX-2026-09`)** düğmesine tıklayın.
2. Gökyüzü haritası ve spektrum panelindeki mor renkli **`SENTETİK TEST ADAYI — Gerçek bir gökcismi değildir`** uyarı şeridini jüriye özellikle gösterin.
3. **M4 — Kaydır-ve-Yığ (`S`)** panelinde:
   - `Statik Yığın` S/N değerinin (`~2.1σ`, gürültü altında) ve `Kaydırılmış Yığın (110 "/yıl, PA 62°, 520 AU)` S/N değerinin (`~10.6σ`, net nokta kaynak) yan yana farkını gösterin.
   - Sağ alttaki **Yerçekimsel Paralaks + Özdevinim İzi** grafiğini işaret edin.
4. **M5 — 3B Güneş Sistemi & REBOUND Yörünge Tahmini (`3`)** panelinde:
   - **`Kaydır-ve-Yığ Astrometrisinden Yörünge Oturt`** düğmesine tıklayın.
   - Three.js 3B sahnesinde Jüpiter–Neptün yörüngeleri, Kuiper Kuşağı ve `a = 520 AU, e = 0.22` elipsini döndürün; `1 Yıl / 5 Yıl / 10 Yıl` gelecek konum kartlarını gösterin.

### Konuşma Metni (TR)
> "Üçüncü adımda, sınır altı algılama hattımızı uçtan uca doğrulamak için açıkça **SENTETİK TEST ADAYI** olarak etiketlediğimiz **PX-2026-09**'u inceliyoruz. 520 AU uzaklıktaki bu sentetik metan buz devi, tekil karelerde ve statik yığında yalnızca **2.1 sigma** ile gürültü tabanında kaybolur. Ancak AEON'un **Kaydır-ve-Yığ** motoru, Dünya'nın yıllık paralaks döngüsünü ve yılda 110 yay-saniyelik hareket vektörünü 24 kare boyunca hizalayarak sinyali **10.6 sigmaya** çıkarır. Ardından çıkarılan astrometri noktalarını doğrudan **REBOUND N-cisim entegratörüne** aktararak cismin 1, 5 ve 10 yıllık gelecek gökyüzü konumlarını 3 boyutlu olarak tahmin ediyoruz."

### Spoken Script (EN)
> "In our final step, we validate our sub-threshold recovery pipeline on **PX-2026-09**—explicitly badged throughout the UI as an **injected synthetic test candidate**. At 520 AU, this synthetic ice giant sits at just **2.1 sigma** in a static stack, lost in the noise. When AEON's **Shift-and-Stack** engine aligns 24 frames along its 110 arcseconds-per-year trajectory and heliocentric parallax loop, the detection jumps to **10.6 sigma**. Feeding those astrometric detections into our **REBOUND N-body integrator** fits the 3D orbit and predicts exact sky coordinates 1, 5, and 10 years into the future."

---

## [2:45 – 3:00] Astro-LLM (`⌘K`) & Keşif Raporu (`P`) ile Kapanış (15 sn)

### Tıklama / Eylem
1. `Cmd/Ctrl + K` tuşuna basarak **M8 — Astro-LLM Komut Paleti**ni açın veya doğrudan Demo Turu çubuğundaki **`PDF Raporu İndir (P)`** düğmesine (veya `P` kısayoluna) basın.
2. İndirilen **`AEON_Discovery_Report.pdf`** dosyasını açarak koordinatlar, S/N kazanımı, 102-bant spektrum çizimi, REBOUND 1/5/10 yıl tahminleri ve sentetik aday uyarı kutusunun tek sayfada raporlandığını gösterin.

### Konuşma Metni (TR)
> "Son olarak tek bir **`P`** tuşuyla, tüm fotometrik, spektroskopik ve yörüngesel kanıtları içeren hakemli yayın formatındaki **`AEON_Discovery_Report.pdf`** dosyamızı indiriyoruz. AEON ile kızılötesi evrende hiçbir hareketli veya değişken kaynak gözden kaçmayacak. Teşekkür ederiz!"

### Spoken Script (EN)
> "Finally, pressing **`P`** generates a complete **`AEON_Discovery_Report.pdf`** containing the coordinates, shift-and-stack S/N gain, 102-band spectrum, multi-mission cross-match, and 10-year REBOUND ephemerides. Thank you!"
