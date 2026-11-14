# AEON Model Card — `Spectral1DCNN` & `PatchAnomalyViT`

> **Training data / Eğitim verisi:** simulated SPHEREx-like 102-band spectra (0.75–5.0 µm) — **not real
> SPHEREx data**. Validation on real SPHEREx DR1 spectra has not been done yet.
> Simüle edilmiş SPHEREx benzeri tayflarla eğitildi; gerçek SPHEREx verisiyle doğrulama henüz yapılmadı.

## Served model / Servis edilen model

| `model_versions` value | Meaning |
|---|---|
| `1dcnn-spherex-v1.1-noise-aware` | Trained checkpoint `app/weights/aeon_models.pt` (loaded by default, or from `HF_MODEL_REPO`) |
| `template-fallback (untrained CNN + template projection)` | Checkpoint missing/unreadable: classification is a linear template discriminant only |
| `patch-vit-v1.0-noise-background` | ViT autoencoder trained only on pure-noise backgrounds |
| `untrained-vit + PSF S/N heuristics` | No checkpoint |

`anomaly_score` is **not a learned probability**: it combines the ViT reconstruction error with a PSF-
coherent peak S/N term, a ± dipole bonus and a class prior. Treat it as a ranking heuristic.

## Training (`training/train.py`, seed 2026)

- 5 classes × 2500 spectra from the physical templates in `app/models.py` (same model family as the core
  backend's `spectra.py`), magnitudes spanning bright to near-limit.
- Noise model matching the AEON core pipeline: additive per-band detector noise σ = 11.5 µJy × U(0.7, 1.6)
  (SPHEREx 5σ depth AB 19.5; negative fluxes kept), 4 % calibration jitter, and a blended neighbour star in
  half of the spectra (6.2″ pixels).
- 75 / 25 split, 40 epochs AdamW.

## Measured accuracy / Ölçülen doğruluk

**Held-out simulated test set (n = 3125): accuracy 0.977**

| Class | F1 |
|---|---|
| `cold_brown_dwarf` | 1.000 |
| `planet_x_candidate` | 0.955 |
| `young_variable_star` | 0.999 |
| `main_sequence_star` | 0.946 |
| `high_z_galaxy` | 0.986 |

Confusion matrix (rows true, columns predicted; class order as above):
`[[602,0,0,0,0],[0,594,0,50,0],[0,0,635,0,0],[0,6,0,631,0],[0,0,1,16,590]]`.
Main confusion: faint Planet X–like reflectors → main-sequence star (50 of 644).

**Core-pipeline spectra (AEON backend `/api/v1/spectrum`, 8 catalogue objects × 2 epochs): 16 / 16**,
including WISE 0855 (p ≥ 0.93) and PX-2026-09 (p = 1.00). These spectra come from the same physical model
family as the training templates, so this checks robustness to the pipeline's photometry and noise, not
generalisation to real data.

Previous embedded (untrained) model on the same 16 spectra: 10 / 16 (WISE 0855 and PX-2026-09 misclassified).

**250 K Y dwarf with SPHEREx-level noise (σ = 11.5 µJy per band), 50 noise draws per magnitude:** W2 AB 16, 17, 18, 19 → 50/50 each.

## Limits
- No real-sky training or validation; real SPHEREx spectra (bright-star saturation, LVF sampling, blends)
  may behave differently.
- Weights are < 0.5 MB and stored in the repository; `HF_MODEL_REPO` overrides them when set.
