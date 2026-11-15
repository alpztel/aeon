# AEON `ai-engine` (port 8100)

FastAPI service for the `/api/v1/ai/*` paths of [`openapi.json`](../openapi.json): a natural-language
command parser and a 102-band spectral classifier with physics diagnostics.

| Path | What it does |
|---|---|
| `POST /api/v1/ai/command` | Turns an English or Turkish request into interface actions (13 `UiAction` types, such as `FLY_TO`, `SET_EPOCH` and `OPEN_SPECTRUM`). With `ANTHROPIC_API_KEY` set it uses Claude through the official `anthropic` SDK (model from `AEON_LLM_MODEL`, default `claude-opus-5-5`); without a key, or on any error, a deterministic English/Turkish rule-based parser answers. Requests about PX-2026-09 come back marked as a synthetic object |
| `POST /api/v1/ai/classify` | Classifies a 102-band spectrum, given in the request or fetched from the core backend for `ra`/`dec`, into five classes and adds physics diagnostics |
| `GET /healthz` | Container health check |

## Classification

- **Network.** A 1D-CNN (`1dcnn-spherex-v1.1-noise-aware`) separates `cold_brown_dwarf`,
  `planet_x_candidate`, `young_variable_star`, `main_sequence_star` and `high_z_galaxy`. The weights
  (`app/weights/aeon_models.pt`, under 0.5 MB) were trained on simulated SPHEREx-like spectra; see the
  [model card](MODEL_CARD.md) for training data and measured accuracy.
- **Only the target’s own light.** Bands the backend interpolated, or flagged as blended with a neighbour,
  are replaced by the best template fitted to the usable bands before the network sees them. The response
  reports `spectrum_data_mode`, `spectrum_bands_measured`, `spectrum_bands_blended` and
  `spectrum_bands_used`.
- **Physics diagnostics.** `physics_diagnostics` holds a template-grid temperature and log g, synthetic
  W1, W2 and W1−W2, and the CH₄ 3.3 µm, H₂O 2.7 µm and CO 4.67 µm band indices. A diagnostic whose
  wavelength windows are mostly unusable is null. Reflected-light spectra (Planet X–like) get no
  temperature (`teff_method: "not_measurable_reflected_light"`).
- **Agreement.** `physics_agrees` says whether the network and the physics template agree; the interface
  warns when they do not.
- **Anomaly score.** `anomaly_score` is a ranking heuristic (ViT reconstruction error, PSF-coherent S/N and
  a dipole term), not a probability. It is meaningful only when an image cutout is sent; the web interface
  sends none and does not show it.

## Limits

The network has not been trained or validated on real SPHEREx spectra. On real data it still mislabels
WISE 0855, because the synthetic Y-dwarf templates have a deeper 3.3 µm methane trough than the real
W1−W2 colour implies; the physics diagnostics flag the disagreement.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Enables Claude for `/ai/command` |
| `AEON_LLM_MODEL` | `claude-opus-5-5` | Model used for commands |
| `AEON_CORE_URL` | `http://localhost:8000` | Core backend for spectra and the catalog |
| `AEON_MISSIONS_URL` | `http://localhost:8200` | multi-mission-api |
| `HF_MODEL_REPO`, `HF_TOKEN` | — | Load the weights from Hugging Face instead of the repository |
| `AEON_CORS_ORIGINS` | see `.env.example` | Allowed browser origins |

## Run and test

```bash
cd ai-engine
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8100
pytest -q
```

[`training/train.py`](training/train.py) retrains the network (seed 2026), and [`hf-space/`](hf-space/)
holds a Gradio demo of the classifier for Hugging Face Spaces.
