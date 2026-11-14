# AEON — Astrophysical Discovery OS | Kullanıcı Kılavuzu / User Guide (TR | EN)

---

## Bölüm 1 — Türkçe Kullanıcı Kılavuzu (TR)

### 1. Genel Bakış
**AEON (Astrophysical Discovery OS)**, NASA'nın **SPHEREx** misyonunun 0.75–5.0 µm aralığındaki 102 spektral bantlı ve çok dönemli (`2026-Q1` … `2026-Q4`) kızılötesi gökyüzü taramalarını; görüntü farkı, 102-bant spektroskopi, çoklu misyon çapraz eşleştirme (Gaia DR3 + AllWISE + MAST JWST/HST), gürültü altı kaydır-ve-yığ (shift-and-stack) ve REBOUND 3B yörünge entegrasyonu ile birleştiren web tabanlı keşif platformudur.

### 2. Veri Modu Rozetleri (`data_mode`)
Üst bilgi çubuğundaki durum rozeti sistemin hangi veri kaynağını kullandığını şeffaf biçimde gösterir:
- **`FITS Arşivi` (`fits_archive`):** Yerel/sunucu FITS arşivindeki gerçek SPHEREx / WISE görüntü kareleri kullanılmaktadır.
- **`Fiziksel Gökyüzü Modeli` (`physical_model`):** Astropy WCS (`TAN` projeksiyonu), dalga boyuna bağlı PSF, zodyak ışığı arka planı ve 102-bant Planck + moleküler soğurma (`H₂O`, `CH₄`, `CO₂`, `CO`) fiziğiyle çalışan deterministik analiz hattı aktiftir.
- **`Çevrimdışı Demo Önbelleği` (`offline_cache`):** Sunucu bağlantısı olmadığında `/public/demo-cache/` altındaki önceden hesaplanmış gerçek yanıtlar kesintisiz olarak sunulmaktadır.

### 3. Sentetik Test Adayı Etiketleme Politikası (`is_synthetic: true`)
`PX-2026-09` gibi algılama hattını uçtan uca doğrulamak amacıyla enjekte edilen sentetik adaylar:
- Katalog aramasında, Gökyüzü Haritasında (M1), Spektrum Panelinde (M3), Kaydır-ve-Yığ Panelinde (M4) ve indirilen `AEON_Discovery_Report.pdf` (M11) raporunda açıkça **"SENTETİK TEST ADAYI — Gerçek bir gökcismi değildir"** rozetiyle işaretlenir.
- Hiçbir koşulda gerçek astronomik keşif olarak sunulmaz.

### 4. Modüller (M1 – M11)
| Modül | Adı | Temel İşlevler |
|---|---|---|
| **M1** | **2B Gökyüzü Haritası & Dönem Zaman Çizelgesi** | Aladin Lite (WISE AllSky / 2MASS / DSS2) + 64×64 WCS FITS kesiti, 5 renk haritası (`Inferno`, `Viridis`, `Magma`, `Coolwarm`, `Gri`), `Linear / Log / Asinh` ölçekleme ve `2026-Q1..Q4` dönem seçici. |
| **M2** | **Görüntü Farkı Modu (`D`)** | İki dönem arasındaki piksel farkı (`E2 - E1`), S/N (`σ`) haritası, perde kaydırıcı (curtain slider), zaman kırpma (blink) ve özdevinim `±` dipol tespiti. |
| **M3** | **102-Bant Kızılötesi Spektrum & Sonifikasyon** | 0.75–5.0 µm 102 kanal akı (`µJy`) ve `±1σ` hata çubukları, `H₂O / CH₄ / CO₂ / CO` moleküler soğurma şeritleri, dönem sabitleme ve Web Audio API spektral sonifikasyon. |
| **M4** | **Kaydır-ve-Yığ & Kör Arama (`S`)** | Gürültü altı (`< 3σ`) hareketli cisimleri hız (`"/yıl`), konum açısı (`PA °`) ve heliosentrik uzaklık (`AU`) boyunca hizalayarak `> 10σ` seviyesinde kurtarma; `5×5` hız-açı S/N ısı haritası ve paralaks izi. |
| **M5** | **3B Güneş Sistemi & REBOUND Yörünge (`3`)** | Three.js sahnesinde Güneş, Jüpiter–Neptün, Kuiper Kuşağı, SPHEREx tarama konisi, `1 / 5 / 10 yıl` gelecek konum tahminleri ve kaydır-ve-yığ astrometrisinden Gauss/en-küçük-kareler yörünge oturtma. |
| **M6** | **JWST / HST Çoklu Misyon PiP Penceresi** | MAST arşivinde JWST veya HST örtüşmesi bulunduğunda sürüklenebilir pencere-içinde-pencere (PiP) önizlemesi ve doğrudan MAST portal bağlantısı. |
| **M7** | **Çoklu Misyon Çapraz Eşleştirme & SED** | VizieR Gaia DR3 + AllWISE + MAST eşleştirmesi, `0.4–22 µm` birleşik SED grafiği ve **"Eşleşmeyen Soğuk KÖ Adayı (Gaia'da Yok)"** rozeti. |
| **M8** | **Astro-LLM Komut Paleti (`Cmd/Ctrl+K`)** | Türkçe ve İngilizce doğal dil komutlarını (`"WISE 0855'e git ve fark modunu aç"`) ayrıştırıp arayüz eylemlerini (`FLY_TO`, `TOGGLE_DIFF`, `RUN_BLIND_SEARCH`, `OPEN_3D_ORBIT`) yürüten yardımcı. |
| **M9** | **AI Spektral Sınıflandırma & Anomali** | `SpectralCNN1D` 5-sınıf olasılık dağılımı ve `PatchAnomalyViT` yeniden yapılandırma anomali skoru (`[0, 1]`). |
| **M10** | **GCN Uyarı Bandı & Vatandaş Bilimi Aday Havuzu** | Üstte canlı GCN/VOEvent uyarı şeridi; altta topluluk oylaması (`+1`) ve yeni aday gönderimi (`POST /api/v1/Community/candidates`). |
| **M11** | **Keşif Raporu PDF Üretici (`P`)** | Tek tuşla koordinat, S/N, 102-bant spektrum, çapraz eşleştirme, AI sınıflandırma ve REBOUND tahminlerini içeren `AEON_Discovery_Report.pdf` indirme. |

### 5. Klavye Kısayolları
| Tuş | İşlev |
|---|---|
| `D` | Görüntü Farkı Modu panelini aç / kapat |
| `S` | Kaydır-ve-Yığ (Shift-and-Stack) panelini aç / kapat |
| `3` | 3B Güneş Sistemi & REBOUND Yörünge panelini aç / kapat |
| `P` | `AEON_Discovery_Report.pdf` keşif raporunu oluştur ve indir |
| `Cmd/Ctrl + K` | Astro-LLM doğal dil komut paletini aç |
| `?` | Klavye kısayolları yardım penceresini aç |

---

## Part 2 — English User Guide (EN)

### 1. Overview
**AEON (Astrophysical Discovery OS)** is an interactive scientific workbench for exploring NASA **SPHEREx** multi-epoch (`2026-Q1` … `2026-Q4`), 102-band (`0.75–5.0 µm`) infrared sky cubes alongside Gaia DR3, AllWISE, and MAST (JWST/HST) archives.

### 2. Data Mode Badges (`data_mode`)
The header badge always indicates the active data provenance:
- **`FITS Archive` (`fits_archive`):** Pixel cutouts and spectra are extracted directly from real SPHEREx / WISE FITS files on disk.
- **`Physical Sky Model` (`physical_model`):** Deterministic Astropy WCS (`TAN` projection), wavelength-dependent PSF, zodiacal background, and 102-band Planck + molecular absorption (`H₂O`, `CH₄`, `CO₂`, `CO`) synthesis.
- **`Offline Demo Cache` (`offline_cache`):** Pre-computed responses from `/public/demo-cache/` used seamlessly when the backend API is unreachable.

### 3. Synthetic Candidate Policy (`is_synthetic: true`)
Any synthetic validation object (such as `PX-2026-09`) carries a prominent violet warning badge across the Sky Map, Spectrum Panel, Shift-and-Stack Panel, and exported `AEON_Discovery_Report.pdf`:
> **"SYNTHETIC TEST CANDIDATE — Not a real astronomical object"**

### 4. Keyboard Shortcuts
- **`D`** — Toggle Difference Mode (`M2`)
- **`S`** — Toggle Shift-and-Stack (`M4`)
- **`3`** — Toggle 3D Solar System & REBOUND Orbit (`M5`)
- **`P`** — Generate and download `AEON_Discovery_Report.pdf` (`M11`)
- **`Cmd/Ctrl + K`** — Open Astro-LLM Command Palette (`M8`)
- **`?`** — Open Keyboard Shortcuts Modal
