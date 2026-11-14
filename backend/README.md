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
- `archive.py` – real FITS mode: reads **SPHEREx Level 2 spectral images** (IMAGE/FLAGS/VARIANCE/WCS-WAVE,
  MJy/sr, flagged pixels → NaN, per-pixel LVF wavelength) and generic 2-D WCS images from `AEON_DATA_DIR`,
  resampled north-up/east-left in µJy/pixel. Details: [`docs/spherex-l2-notes.md`](docs/spherex-l2-notes.md).
- `irsa.py` – downloader for real SPHEREx DR1 data from NASA/IPAC IRSA (SIA2 search + IBE cutouts).
- `catalog.py` – DuckDB catalog (demo targets + real reference objects).

## Science notes and limits

- **PX-2026-09 is synthetic** (`is_synthetic: true`), injected to validate the detection chain.
  In the model, single-exposure S/N ≈ 1.5–3; a 24-exposure stack along 110″/yr, PA 62° gives S/N ≈ 6–9.
- Shift-and-stack rates are **heliocentric**: a real search must first remove Earth's reflex
  (parallax) motion for each trial distance; the model sky renders PX with heliocentric motion only.
- WISE 0855 positions use linear proper motion from epoch 2010.5 (parallax 0.44″ ignored).
- Orbit forecasts start at 2026.5 from heliocentric direction + distance + angular rate; the
  "Kepler-only deviation" compares against a Sun-only integration (includes the Sun's reflex wobble).
- Spectra come from real SPHEREx frames when the archive covers ≥ 34 of the 102 bands at the target in that
  epoch; otherwise the model is used and `pipeline.archive_fallback_reason` says why.

## Real SPHEREx data (IRSA)

`data_mode` is `fits_archive` whenever `AEON_DATA_DIR` holds archive files covering the request, and
`physical_model` otherwise (per request, per epoch). Download real SPHEREx DR1 spectral images:

```bash
export AEON_DATA_DIR=/srv/aeon-data          # Windows: set AEON_DATA_DIR=C:eon-data
python -m aeon.irsa list --ra 133.75990 --dec -7.24221             # what IRSA has (no download)
python -m aeon.irsa fetch-demo                                       # wise-0855, rw-aur, px-2026-09 field
python -m aeon.irsa fetch --ra 76.95642 --dec 30.40142 --size-px 96  # any position
```

Options: `--collection` (default `spherex_dr1`), `--size-px` (cutout side, native 6.15″ px, default 96),
`--max-files`, `--detectors 5 6`, `--workers` (default 4), `--timeout`, `--retries`, `--max-file-mb`,
`--max-total-mb`, `--keep-psf`. Re-running skips cached files and retries failed ones (IRSA answers HTTP 503
now and then). Each target directory gets a `manifest.json` with the source URLs. Restart the API after a
download (the archive is indexed once at start-up).

**Disk and bandwidth.** Every IRSA cutout is ~4 MB (the unmodified EPSF table dominates); AEON drops EPSF and
stores ~0.2 MB per 96-px frame. WISE 0855 (258 frames in DR1) = ~1.0 GB downloaded, ~55 MB on disk, ~10 min with
4–6 workers. RW Aur has 226 frames. Full 2040² files (65 MB each) are never downloaded.

**How real data enters the endpoints.**

| Endpoint | Real-data behaviour |
|---|---|
| `/sky/cutout` | mean of the frames covering the target in the epoch (`band` omitted = all-band mean; `band=k` = frames whose LVF wavelength at the target falls in AEON band k), resampled to the requested scale; `provenance` lists frames, dates and wavelengths |
| `/analysis/difference` | archive only if both epochs are covered, restricted to the bands seen in both; never mixes archive and model; adds `dt_years_observed` |
| `/spectrum` | forced photometry on every LVF frame, binned into the 102 bands; `pipeline.measured` marks real bands, the rest are log-λ interpolations (flagged, inflated errors) because the contract requires 102 values |
| shift-stack / blind-search | still model (SPHEREx revisits a field ~2× per year; there is no 24-frame time series) |

**Epochs.** Real observation date → calendar quarter (`2026-Q1` = Jan–Mar …). DR1 contains 2025 data, which is
folded onto its quarter (WISE 0855: Q2 = Apr–May 2026, Q4 = Oct–Dec 2025, Q1/Q3 = model). The true dates are in
`provenance.obs_date_range`; `dt_years_observed` can be negative (WISE 0855 Q2→Q4 = −0.47 yr).

**Limits.** Bright stars saturate (RW Aur: most frames flagged in the aperture → model spectrum); 6.15″ pixels
blend neighbours; the Gaussian aperture correction ignores the real undersampled PSF; PX-2026-09 remains
synthetic — for its field only the real background is downloaded.

## Develop

```bash
pip install -r requirements.txt
uvicorn aeon.main:app --reload --port 8000
pytest -q                    # offline; IRSA round trip: pytest -q --run-network
```

On Windows keep the virtualenv on a short path (e.g. `C:\venvs\aeon`): astropy's compiled
modules fail to load when the full path exceeds 260 characters.
