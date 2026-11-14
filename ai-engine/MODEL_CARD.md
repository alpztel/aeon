# AEON Model Card — `Spectral1DCNN` & `PatchAnomalyViT`

> **Eğitim Verisi Bildirimi / Training Data Disclosure:**
> Bu modeller **simüle edilmiş SPHEREx-benzeri veriyle eğitildi** (*trained on simulated SPHEREx-like 102-band near-infrared data* spanning `0.75–5.0 µm` across 6 detector arrays × 17 channels).
> Eğitim verisi üretim ve doğrulama betiği `ai-engine/training/train.py` altındadır (`seed=2026` ile deterministik ve tekrar üretilebilir).

---

## 1. Mimari Özeti (Architecture)

1. **`Spectral1DCNN` (`app/models.py`):**
   - **Girdi:** 102 bantlık yakın-kızılötesi akı dizisi (`flux_ujy`, µJy), log-normalize (`log10`) ve sıfır ortalama / birim standart sapmaya ölçeklenmiş.
   - **Katmanlar:** 3× `Conv1d` (`kernel_size=7, 5, 3`, `BatchNorm1d`, `GELU`), `AdaptiveAvgPool1d`, tam bağlantılı sınıflandırma başlığı ve fiziksel şablon diskriminant izdüşümü.
   - **Çıktı:** 5 astrofiziksel sınıf için olasılık dağılımı (`probabilities`) ve `top_class`.
2. **`PatchAnomalyViT` (`app/models.py`):**
   - **Girdi:** 64×64 piksel gökyüzü kesiti (`Image`, `8×8` yamalara ayrılmış 64 yama).
   - **Katmanlar:** Doğrusal yama gömme (`patch_embed`), öğrenilebilir konumsal gömme (`pos_embed`), 2 katmanlı `TransformerEncoder` (`nhead=4`, `d_model=32`, `GELU`) ve yama yeniden-oluşturma başlığı.
   - **Çıktı:** Yeniden-oluşturma hatası, sağlam tepe S/N ve dipol imzasını birleştiren `0.00–1.00` aralığında `anomaly_score`.

---

## 2. Ayrılmış Test Kümesi Doğruluk Raporu (`seed=2026`)

`python ai-engine/training/train.py` ile üretilen 600 gürültülü ve sönümlenmiş örnek (`n_train = 450`, `n_test = 150`) üzerindeki ayrılmış test sonuçları:

- **Toplam Doğruluk (Overall Accuracy):** `0.9667` (%96,67)

### Sınıf Başına F1 Skorları (Per-Class F1)

| Sınıf (`ObjectClass`) | F1 Skoru | Fiziksel İmza |
|---|---|---|
| `cold_brown_dwarf` | **0.9286** | 220–480 K Planck zarfı + derin $\text{H}_2\text{O}$, $\text{CH}_4$, $\text{CO}_2$, $\text{CO}$ soğurma bantları (4–5 µm tepe) |
| `planet_x_candidate` | **1.0000** | Yansıyan Güneş ışığı (5778 K) × güçlü metan ($\text{CH}_4$) buzu soğurması |
| `young_variable_star` | **0.9831** | T Tauri fotosferi + değişken toz sönümlemesi ($A_V$) + sıcak/ılık iç disk fazlalığı |
| `main_sequence_star` | **1.0000** | 3200–7500 K yıldız fotosferi sürekliliği |
| `high_z_galaxy` | **0.9057** | Kırmızıya kaymış ($z \in [1.2, 3.2]$) 4000 Å kırılması, 1.6 µm $\text{H}^-$ tümseği ve 3.3 µm PAH |

### Karışıklık Matrisi (Confusion Matrix — Satırlar: Gerçek, Sütunlar: Tahmin)

| Gerçek \ Tahmin | `cold_brown_dwarf` | `planet_x_candidate` | `young_variable_star` | `main_sequence_star` | `high_z_galaxy` |
|---|---:|---:|---:|---:|---:|
| **`cold_brown_dwarf`** | **26** | 0 | 0 | 0 | 3 |
| **`planet_x_candidate`** | 0 | **37** | 0 | 0 | 0 |
| **`young_variable_star`** | 0 | 0 | **29** | 0 | 0 |
| **`main_sequence_star`** | 0 | 0 | 0 | **29** | 0 |
| **`high_z_galaxy`** | 1 | 0 | 1 | 0 | **24** |

---

## 3. Ağırlık Saklama ve Yedekleme

- Model ağırlıkları (< 1 MB) `HF_MODEL_REPO` tanımlı olduğunda açılışta Hugging Face Hub üzerinden indirilir; çevrimdışı veya anahtarsız test ortamlarında (`pytest`) fiziksel şablonlarla kalibre edilmiş gömülü ağırlıklara (`1dcnn-spherex-v1.0-embedded`, `patch-vit-v1.0-embedded`) kesintisiz düşer.
