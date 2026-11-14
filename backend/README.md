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
| `POST /api/v1/analysis/shift-stack` | Static-sky removal, digital tracking along the predicted apparent track (rate, PA, optional distance for Earth parallax), S/N gain |
| `POST /api/v1/analysis/blind-search` | distance (uniform in parallax) × 5×5 (rate, PA) grid + local refinement, best stack |
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
- `ephem.py` – apparent geocentric positions: Earth ephemeris (astropy/ERFA), parallax, hypothesis tracks, SPHEREx-like visibility.
- `orbit_fit.py` – orbit determination from astrometry (least squares, covariance errors).
- `archive.py` – real FITS mode: drop WCS images into `AEON_DATA_DIR` (epoch from `AEONEPOC`,
  `MJD-OBS` or `DATE-OBS`) and cutouts/differencing use them instead of the model.
- `catalog.py` – DuckDB catalog (demo targets + real reference objects).

## Science notes and limits

- **PX-2026-09 is synthetic** (`is_synthetic: true`), injected to validate the detection chain.
- **Earth parallax is modelled and tracked.** Catalog and rendered positions are apparent geocentric
  positions (proper motion + parallax from Earth's ERFA ephemeris). At 520 AU the annual parallax
  ellipse has a ~397″ semi-major axis, so a straight-line stack misses PX-2026-09 (S/N ≈ 2). Digital
  tracking with `distance_au: 520` recovers it (single exposure S/N ≈ 2, 24-exposure stack S/N ≈ 10), and
  the blind search over distance × rate × PA (~1700 hypotheses, ~4 s) recovers 110″/yr, PA ≈ 60°,
  d ≈ 520 AU.
- Hypotheses assume linear heliocentric motion over the one-year baseline (orbital curvature at
  hundreds of AU is far below a pixel per year). Blind-search S/N is the maximum over all hypotheses,
  so its false-alarm level rises with `n_hypotheses` (reported in the response).
- **Cadence:** `cadence: "uniform"` (idealised, default) or `"spherex"` — frames only while the field's
  solar elongation is within 90° ± 10° (model assumption for SPHEREx's Sun-perpendicular scanning):
  two ~3-week windows a year on the ecliptic, all year near the ecliptic poles. The static-sky template
  of each frame uses only frames > 30 days away, so a mover parked inside one window is not erased.
  PX-2026-09 with SPHEREx cadence: tracked stack S/N ≈ 9; two windows constrain distance/rate more
  weakly (orbit fit ≈ 524 ± 12 AU) than an evenly sampled year (≈ 518 ± 0.6 AU).
- **Discovery → orbit:** shift-stack returns `astrometry` (independent centroids of 4 sub-stacks);
  `orbit/simulate` with `detections` fits a heliocentric state (parallax included) by least squares and
  forecasts it with REBOUND. Hypothesis positions refer to mid-survey 2026.5.
- **Performance:** gzip responses, `Server-Timing` header, cached frame stacks (slider moves reuse
  rendered frames) and spectra.
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
