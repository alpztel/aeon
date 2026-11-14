# AEON core backend (`/backend`)

Owner: Node 1 · branch `agent/claude-leader-backend`. Implements the `core` paths of
[`../openapi.json`](../openapi.json).

| Path | What it does |
|------|--------------|
| `GET /api/v1/health` | Version, engines, `data_mode` (`fits_archive` or `physical_model`) |
| `GET /api/v1/catalog/search` | Name resolution or cone search in DuckDB (+ optional field sources) |
| `GET /api/v1/sky/cutout` | Background-subtracted cutout as JSON or FITS (astropy WCS header) |
| `GET /api/v1/spectrum` | 102-band spectrum: photutils forced photometry on a spectral cube, molecular band depths |
| `POST /api/v1/analysis/difference` | I(t2) − I(t1), matched-filter S/N map, ± detections (photutils segmentation) |
| `POST /api/v1/analysis/shift-stack` | Static-sky removal, sub-pixel shift along (rate, PA), stack, S/N gain |
| `POST /api/v1/analysis/blind-search` | 5×5 (rate, PA) grid + 5×5 refinement, best stack |
| `POST /api/v1/orbit/simulate` | REBOUND IAS15: Sun + Jupiter…Neptune + particle, 1/5/10-yr horizons |

## Modules (`aeon/`)

- `bands.py` – 102 SPHEREx-like bands (6 arrays × 17 channels, 0.75–5.0 µm), depth AB 19.5 (5σ).
- `spectra.py` – SED models: Y/T dwarf (colour-temperature envelope + H2O/CH4/CO2/CO bands),
  methane ice giant in reflected sunlight, T Tauri star with variable extinction + disk,
  main-sequence Planck, redshifted galaxy.
- `sky.py` – model sky: deterministic tiled field population (density vs galactic latitude), named
  objects with proper motion, wavelength-dependent PSF integrated over 6.2″ pixels, zodiacal
  pedestal, depth-calibrated noise, FITS output.
- `photometry.py`, `analysis.py` – Astropy/Photutils pipeline shared by model and archive data.
- `orbit.py` – REBOUND integration, JPL planetary elements, state ↔ elements conversion.
- `archive.py` – real FITS mode: drop WCS images into `AEON_DATA_DIR` (epoch from `AEONEPOC`,
  `MJD-OBS` or `DATE-OBS`) and cutouts/differencing use them instead of the model.
- `catalog.py` – DuckDB catalog (demo targets + real reference objects).

## Science notes and limits

- **PX-2026-09 is synthetic** (`is_synthetic: true`), injected to validate the detection chain.
  In the model, single-exposure S/N ≈ 1.5–3; a 24-exposure stack along 110″/yr, PA 62° gives S/N ≈ 6–9.
- Shift-and-stack rates are **heliocentric**: a real search must first remove Earth's reflex
  (parallax) motion for each trial distance; the model sky renders PX with heliocentric motion only.
- WISE 0855 positions use linear proper motion from epoch 2010.5 (parallax 0.44″ ignored).
- Orbit forecasts start at 2026.5 from heliocentric direction + distance + angular rate; the
  "Kepler-only deviation" compares against a Sun-only integration (includes the Sun's reflex wobble).
- Spectrum and cube products are model-only until 102-band SPHEREx cubes are mounted.

## Develop

```bash
pip install -r requirements.txt
uvicorn aeon.main:app --reload --port 8000
pytest -q
```

On Windows keep the virtualenv on a short path (e.g. `C:\venvs\aeon`): astropy's compiled
modules fail to load when the full path exceeds 260 characters.
