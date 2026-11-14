# AEON Discovery Report (`AEON_Discovery_Report.pdf`) — Şablon & Mimari Dokümantasyonu

Bu dizin, **M11 — Tek Tıkla Keşif Raporu Üretici** (`frontend/src/lib/pdf-report.ts`) tarafından istemci tarafında (tarayıcıda) dinamik olarak oluşturulan **`AEON_Discovery_Report.pdf`** dosyasının sayfa yapısını ve içerik alanlarını belgeler.

---

## 1. Nasıl Tetiklenir?

`AEON_Discovery_Report.pdf` raporu üç farklı yolla üretilip indirilebilir:
1. **Klavye Kısayolu:** Arayüzde herhangi bir anda **`P`** tuşuna basarak.
2. **Üst Çubuk / Araç Çubuğu Düğmesi:** **`PDF Raporu`** (`PDF Report (P)`) düğmesine tıklayarak.
3. **Jüri Demo Turu / Astro-LLM (`⌘K`):** Demo turunun 3. adımındaki **`PDF Raporu İndir (P)`** düğmesiyle veya `Cmd/Ctrl+K` paletine *"PDF keşif raporu indir"* / *"Generate PDF report"* yazarak (`GENERATE_PDF` eylemi).

---

## 2. PDF Sayfa Düzeni (A4 Portrait — `595 × 842 pt`)

Rapor, harici bir sunucu bağımlılığı olmaksızın doğrudan tarayıcıda standart **PDF-1.4** vektör grafikleri ve tipografisiyle üretilir; seçili arayüz diline göre (**`TR`** veya **`EN`**) tüm başlıklar otomatik çevrilir:

1. **Üst Başlık Bandı (`Header Banner`):**
   - `AEON — Astrophysical Discovery OS` başlığı
   - Üretim zaman damgası (`UTC ISO-8601`) ve aktif veri kaynağı (`fits_archive` / `physical_model` / `offline_cache`).
2. **Sentetik Test Adayı Uyarı Kutusu (`Synthetic Warning Banner` — Yalnızca `is_synthetic: true` ise):**
   - `PX-2026-09` gibi sentetik test hedefleri için kırmızı/kehribar çerçeveli uyarı kutusu:
     - **TR:** `UYARI: SENTETİK TEST ADAYI (is_synthetic = true) — Gerçek gökyüzünde var olmayan, algılama hattını doğrulamak için enjekte edilmiş sentetik test nesnesidir.`
     - **EN:** `WARNING: SYNTHETIC TEST CANDIDATE (is_synthetic = true) — Injected test object to validate the sub-threshold recovery pipeline.`
3. **Bölüm 1 — Hedef & Gökyüzü Koordinatları (`Target & Sky Coordinates`):**
   - Hedef kimliği (`id`, `name`), nesne sınıfı (`object_class`), ICRS koordinatları (`RA`, `Dec`), aktif dönem (`epoch`), özdevinim (`pm_ra_cosdec`, `pm_dec`), W2 AB parlaklığı ve uzaklık (`pc` veya `AU`).
4. **Bölüm 2 — Görüntü Farkı & Kaydır-ve-Yığ S/N Özeti (`Difference & Shift-Stack S/N Summary`):**
   - `2026-Q3 - 2026-Q1` tepe fark S/N (`σ`), dipol tespiti (`EVET/HAYIR`), statik yığın S/N, kaydırılmış yığın S/N ve S/N kazanım çarpanı (`×`).
5. **Bölüm 3 — 102-Bant Kızılötesi Spektrum (`0.75 – 5.0 µm Vector Plot`):**
   - Ölçekli vektör grafik kutusu içinde 102 SPHEREx kanalının akı eğrisi (`µJy`) ve işaretlenen moleküler soğurma bantları (`H₂O`, `CH₄`, `CO₂`, `CO`).
6. **Bölüm 4 — Çoklu Misyon Çapraz Eşleştirme & AI Sınıflandırma (`Multi-Mission Cross-Match & AI Classification`):**
   - Gaia DR3 (optik), AllWISE (orta-KÖ) ve MAST (JWST/HST) eşleşme sayıları, `Eşleşmeyen Soğuk KÖ Adayı` durumu, `SpectralCNN1D` birincil sınıf olasılığı ve `PatchAnomalyViT` anomali skoru.
7. **Bölüm 5 — REBOUND 3B Yörünge Elemanları & 1 / 5 / 10 Yıl Konum Tahmini (`REBOUND 3D Orbit Forecast`):**
   - Yarı-büyük eksen (`a`), dışmerkezlik (`e`), eğiklik (`i`), periyot (`P`) ve `+1 Yıl`, `+5 Yıl`, `+10 Yıl` için tahmin edilen `(RA, Dec, r_AU, Δ")` tablosu.
