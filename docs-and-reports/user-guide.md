# AEON — Kullanıcı Kılavuzu · User Guide

[Türkçe](#türkçe) · [English](#english)

---

## Türkçe

### 1. Genel bakış

AEON, NASA’nın SPHEREx taramasından gelen gerçek Level-2 görüntülerden bir hedefin 102 bantlık
yakın-kızılötesi tayfını (0,75–5,0 µm) çıkarır; bu tayfı Galaktik hızla birleştirerek yaş ve kütle tahmin
eder, cismin geçmiş ve gelecek yörüngesini hesaplar ve her sonucu SIMBAD ile literatürle karşılaştırır.

Sistemi yerelde çalıştırmak için kök dizindeki [README](../README.md#quick-start) adımlarını izleyin
(Docker Compose + `npm run dev`, ardından <http://localhost:3000>).

### 2. Ekran düzeni

| Bölge | İçerik |
|---|---|
| Üst çubuk | Hedef arama (ad, tanımlayıcı ya da “RA Dec”), veri modu göstergesi, rehberli tur, PDF raporu, kısayollar, komut paleti, TR/EN dil seçimi |
| Orta | Seçili hedefin SPHEREx görüntüsü (renk haritası seçilebilir) |
| Alt | Dört tarama dönemi (`2026-Q1` … `2026-Q4`); gerçek SPHEREx verisi olan dönemler işaretlidir |
| Sol alt | Hedef kartı: sınıf, konum, özdevinim, W2 parlaklığı |
| Sağ | Dört adımlı araç rayı; seçilen araç sağdaki panelde açılır |

### 3. Dört adım

| Adım | Araç | Ne gösterir |
|---|---|---|
| **1 · Hedef ve hareket** | Örnek hedefler (`G`) | Sınıflara göre gerçek hedefler ve gerçek SPHEREx verisi olan dönemleri |
| | Hareket tespiti (`D`) | İki dönem arasındaki fark; hareket eden kaynak ± dipol olarak görünür |
| | Kaydır ve Yığ (`S`) | Tek pozda görünmeyen sönük gezginler; yalnızca Güneş Sistemi adayları ve boş alan konumları için |
| **2 · Tayf ve kimlik** | 102-Bant Tayf | Ölçülen, aradeğerlenen ve komşu kaynakla karışan bantlar ayrı işaretlenir; H₂O, CH₄, CO₂, CO bantları |
| | Fiziksel kimlik | Sınıf olasılıkları, sıcaklık, log g, molekül indeksleri; ağ ile fizik uyuşmazsa uyarı |
| **3 · Yaş ve yörünge** | Yaş ve Yörünge (`3`) | Tayfsal, kinematik ve birleşik yaş; kütle; yıldız ve kahverengi cüceler için Samanyolu yörüngesi ve Güneş’e en yakın geçiş, Güneş Sistemi adayları için REBOUND yörüngesi |
| **4 · Doğrulama** | Doğrulama Karnesi | AEON sonuçları ile SIMBAD ve literatür yan yana; her satırda karar (tutarlı / kısmen / tutarsız) ve nedeni |

### 4. Veri modu

- **Gerçek SPHEREx (`fits_archive`):** görüntü ve tayf gerçek SPHEREx karelerinden gelir.
- **Fiziksel model (`physical_model`):** o konum ve dönem için gerçek veri yoktur (ya da parlak bir yıldız
  dedektörü doyurmuştur); aynı hat fiziksel bir gökyüzü modelinde çalışır ve bu açıkça yazılır.
- **Çevrimdışı önbellek (`offline_cache`):** API’ye ulaşılamadığında üç demo hedefi için kaydedilmiş
  yanıtlar gösterilir.

### 5. Ölçülemeyen değerler ve sentetik nesneler

- Radyal hızı ölçülmemiş bir cisim için hız ve yörünge −30, 0 ve +30 km/s için ayrı ayrı hesaplanır ve
  aralık (zarf) olarak gösterilir; uydurma bir değer kullanılmaz.
- Ölçülemeyen bir değer “ölçülemedi” olarak ve nedeniyle birlikte gösterilir.
- **PX-2026-09 gerçek bir gök cismi değildir.** Algılama hattını uçtan uca sınamak için eklenmiş sentetik
  bir test nesnesidir ve her ekranda böyle etiketlenir.

### 6. Klavye kısayolları

| Tuş | İşlev |
|---|---|
| `G` | Örnek hedefler |
| `D` | Hareket tespiti |
| `S` | Kaydır ve Yığ |
| `3` | Yaş ve Yörünge |
| `P` | PDF raporu |
| `Ctrl/⌘ K` | Komut paleti (ör. “WISE 0855’e git”, “tayfı aç”) |
| `?` | Kısayolları göster |
| `←` `→` | Önceki / sonraki dönem |

---

## English

### 1. Overview

AEON extracts a 102-band near-infrared spectrum (0.75–5.0 µm) of a target from real SPHEREx Level-2
images, combines it with the object’s Galactic velocity to estimate its age and mass, computes its past
and future orbit, and checks every result against SIMBAD and the literature.

To run it locally, follow the root [README](../README.md#quick-start) (Docker Compose and `npm run dev`,
then open <http://localhost:3000>).

### 2. Screen layout

| Area | Content |
|---|---|
| Top bar | Target search (name, identifier or “RA Dec”), data-mode indicator, guided tour, PDF report, shortcuts, command palette, EN/TR switch |
| Centre | SPHEREx image of the selected target (with a choice of colour maps) |
| Bottom | The four survey epochs (`2026-Q1` … `2026-Q4`); epochs with real SPHEREx data are marked |
| Bottom left | Target card: class, position, proper motion, W2 brightness |
| Right | The four-step tool rail; the chosen tool opens in the panel |

### 3. The four steps

| Step | Tool | What it shows |
|---|---|---|
| **1 · Target and motion** | Example gallery (`G`) | Real targets by class, with the epochs that hold real SPHEREx data |
| | Motion detection (`D`) | The difference between two epochs; a moving source appears as a ± dipole |
| | Shift and Stack (`S`) | Faint movers that no single exposure shows; offered for solar-system candidates and bare field positions |
| **2 · Spectrum and identity** | 102-band spectrum | Measured, interpolated and blended bands marked separately; H₂O, CH₄, CO₂ and CO bands |
| | Physical identity | Class probabilities, temperature, log g and band indices; a warning when the network and the physics disagree |
| **3 · Age and orbit** | Age and Orbit (`3`) | Spectral, kinematic and joint age; mass; the Milky Way orbit and closest approach to the Sun for stars and brown dwarfs, a REBOUND orbit for solar-system candidates |
| **4 · Validation** | Validation scorecard | AEON next to SIMBAD and the literature, with a verdict (consistent, partly consistent, discrepant) and its cause on every row |

### 4. Data mode

- **Real SPHEREx (`fits_archive`):** the image and spectrum come from real SPHEREx frames.
- **Physical model (`physical_model`):** there is no real data at this position and epoch (or a bright star
  saturated the detector); the same pipeline runs on a physical sky model and says so.
- **Offline cache (`offline_cache`):** when the API cannot be reached, recorded responses for the three
  demo targets are shown.

### 5. Unmeasured values and synthetic objects

- For an object without a measured radial velocity, velocity and orbit are computed for −30, 0 and
  +30 km/s and shown as a range (an envelope); no value is invented.
- A value that cannot be measured is shown as “not measured”, with the reason.
- **PX-2026-09 is not a real object.** It is a synthetic test object injected to test the detection chain
  end to end, and it is labelled as such on every screen.

### 6. Keyboard shortcuts

| Key | Action |
|---|---|
| `G` | Example gallery |
| `D` | Motion detection |
| `S` | Shift and Stack |
| `3` | Age and Orbit |
| `P` | PDF report |
| `Ctrl/⌘ K` | Command palette (for example “fly to WISE 0855”, “open the spectrum”) |
| `?` | Show shortcuts |
| `←` `→` | Previous / next epoch |
