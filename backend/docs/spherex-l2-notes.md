# SPHEREx Level 2 spectral images — notes for the AEON archive mode

Verified on 2026-11-14 against IRSA documentation **and** a real DR1 file
(`level2_2025W19_1B_0116_1D3_spx_l2b-v27-2026-197.fits`, IBE cutout around WISE 0855).
Where a statement comes only from the real header it is marked *(header)*.

## Sources

- IRSA SPHEREx mission page — <https://irsa.ipac.caltech.edu/Missions/spherex.html>
- Data products — <https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-products>
- Data access (SIA2, TAP, cutouts) — <https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access>
- Releases (QR1–QR3, DR1) — <https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-releases>,
  <https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html>
- Cutout tool — <https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html>
- IRSA tutorials: <https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/>,
  <https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/>
- Explanatory Supplement (flag table 16, MEF layout §2.2) —
  <https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf> (not read: >10 MB for our fetcher;
  the flag definitions below were taken from the FITS header instead)

## Releases and collections

| Collection (SIA2 `COLLECTION=`) | Content |
|---|---|
| `spherex_dr1` | DR1 wide survey spectral images (Surveys 1 + 2 reprocessed), released Nov 2026, DOI 10.26131/IRSA678 |
| `spherex_dr1_deep` | DR1 deep fields |
| `spherex_dr1_cube` | All-Sky Cube: 102 channels, HEALPix order 5 tiles, 12.9″/px, DOI 10.26131/IRSA679 |
| `spherex_qr3`, `spherex_qr3_deep` | Quick Release 3 (same pipeline as DR1) |

QR2 is no longer searchable through SIA2; QR1 was retired in February 2026. Counts on 2026-11-14
(TAP `ivoa.obscore`): `spherex_dr1` 945 725, `spherex_qr3` 362 124 images. AEON uses `spherex_dr1`.

## Search and download

- SIA2: `https://irsa.ipac.caltech.edu/SIA?COLLECTION=spherex_dr1&POS=CIRCLE <ra> <dec> <r_deg>`
  (VOTable by default; `RESPONSEFORMAT=CSV` is unusable because the `cloud_access` JSON column contains
  unquoted commas). Relevant columns: `access_url`, `obs_id`, `energy_bandpassname` (`SPHEREx-D1`…`D6`),
  `em_min`/`em_max` (metres, detector range), `t_min`/`t_max` (MJD), `access_estsize` (kB, ~65 000 for a full file),
  `dataproduct_subtype` (`science`).
- Full file: `access_url` (2040×2040, ~65 MB). Also mirrored on AWS `s3://nasa-irsa-spherex/` (`cloud_access` column).
- Cutout: `access_url?center=<ra>,<dec>&size=<N>pix` (or `size=<deg>`). Returns the **same HDUs** cropped,
  WCS-WAVE remapped, EPSF unmodified (~4 MB, so a cutout is ~4 MB regardless of its size). Verified: `size=64pix`
  returns 64×64 IMAGE/FLAGS/VARIANCE/ZODI. The service occasionally answers HTTP 503 → retry.
- Coverage of the demo targets in DR1 (radius 0.01°): WISE 0855 — 258 frames (2025-05, 2025-10…12, 2026-04…05);
  RW Aur — 226 frames (2025-09, 2026-02…03).

## File structure (Level 2 spectral image, MEF)

| HDU | EXTNAME | Content |
|---|---|---|
| 0 | PRIMARY | no data; `VERSION` (pipeline) |
| 1 | `IMAGE` | float32 2040×2040, `BUNIT = 'MJy / sr'`, calibrated surface brightness, **zodi not subtracted** |
| 2 | `FLAGS` | int32 bitmap (compressed in full files), `EXTTYPE='MASK'`, bit names in `MSKNnnnn`, values in `MSKMnnnn` |
| 3 | `VARIANCE` | float32, `BUNIT = 'MJy2 / sr2'` |
| 4 | `ZODI` | float32 zodiacal-light model, MJy/sr |
| 5 | `EPSF` (`PSF` in QR2) | binary table of oversampled ePSFs per detector zone |
| 6 | `WCS-WAVE` | binary table, 1 row: `X` (9 control points), `Y` (9 or 14), `VALUES` (`TDIM = (2, nX, nY)`) |

Useful `IMAGE` keywords *(header)*: `DETECTOR` (1–6), `OBSID`, `DATE-OBS`/`MJD-OBS` (start),
`DATE-AVG`/`MJD-AVG` (mid-exposure), `DATE-END`/`MJD-END`, `XPOSURE` (113.6 s), `TIMESYS='UTC'`,
`PSF_FWHM` (arcsec, median), `OMEGA_MEDIAN` (arcsec², median pixel solid angle ≈ 37.86), `L2DQAFLG`,
`RADESYS='ICRS'`, celestial WCS `RA---TAN-SIP`/`DEC--TAN-SIP` with PC matrix (rotated frame, ~6.15″/px).

Detector wavelength ranges (mission page): D1 0.75–1.09 µm (R 39), D2 1.10–1.62 (R 41), D3 1.63–2.41 (R 41),
D4 2.42–3.82 (R 35), D5 3.83–4.41 (R 112), D6 4.42–5.00 µm (R 128). D1–D3 SWIR, D4–D6 MWIR (`DETECTOR` comment).

## Per-pixel wavelength (linear variable filter)

The `IMAGE` header carries an alternate WCS `W` *(header)*:

```
WCSNAMEW= 'Approximated per-pixel wavelength and bandwidth'
CTYPE1W = 'WAVE-TAB'  CTYPE2W = 'WAVE-TAB'      CUNIT1W = 'um'
CRPIX1W, CRPIX2W  (cutout offset into raw detector coords)   CRVAL1W = CRVAL2W = 1
PS1_0W  = 'WCS-WAVE'  PS1_1W = 'VALUES'  PS1_2W = 'X'  PS2_2W = 'Y'   PV1_3W = 1 (wavelength)  PV2_3W = 2 (bandwidth)
```

IRSA tutorial recipe (used by AEON first):

```python
spectral_wcs = WCS(hdul["IMAGE"].header, fobj=hdul, key="W")
spectral_wcs.sip = None
wl, bw = spectral_wcs.pixel_to_world(x, y)
```

AEON also implements the -TAB bilinear lookup itself (`archive.wave_table_lookup`) as a fallback for readers
without -TAB support; on the real file both agree to all printed digits (e.g. 2.364776 µm, 0.058646 µm at the
cutout centre). IRSA notes this table is approximate (~1 nm) and recommends the Spectral WCS calibration product for
precision science.

## Flags

Bits *(FLAGS header)*: 0 TRANSIENT, 1 OVERFLOW, 2 SUR_ERROR, 6 NONFUNC, 7 DICHROIC, 9 MISSING_DATA, 10 HOT,
11 COLD, 12 FULLSAMPLE, 14 PHANMISS, 15 NONLINEAR, 17 PERSIST, 19 OUTLIER, 20 CROSSTALK, 21 SOURCE, 22 GHOST,
23 GHOST_FPA, 24 GHOST_EXT, 25 STREAK, 26 BLOOM, 27 SNOWBALL, 28 HALO.

IRSA publishes no recommended mask in the pages read. **AEON's choice** (`archive.SPHEREX_REJECT`): reject all
of the above except SOURCE (>50 % of pixels — `PXSRCMSK = 51.16` in the sample — it only means "mapped to a known
source"), DICHROIC (low but calibrated efficiency) and FULLSAMPLE/PHANMISS (informational).

## How AEON uses it

- `aeon/irsa.py` searches SIA2 and downloads cutouts (default 96 px), drops EPSF, keeps
  IMAGE/FLAGS/VARIANCE/ZODI/WCS-WAVE: ~4 MB transferred, ~0.2 MB stored per frame.
- Units: MJy/sr × 23.5045 = µJy/arcsec² (1 sr = 4.25452×10¹⁰ arcsec²), times the output pixel area.
- Epoch: calendar quarter of `MJD-AVG` → `2026-Qn`. DR1 data from 2025 folds onto its quarter; when one quarter
  holds two visits (e.g. May 2025 and May 2026), the visit closest to the nominal AEON epoch is used (frames within
  60 days of the best frame). The true observation dates are reported in `provenance` and `dt_years_observed`.
- Images are resampled to the contract orientation (north up, east left) at the requested pixel scale.
- Spectrum: one forced-photometry point per LVF frame at the target (native pixels), binned into the 102 AEON bands.

## Limitations found with real data

- Bright stars (RW Aur, W1 ≈ 7) saturate: most frames have OVERFLOW/NONLINEAR/BLOOM flags in the aperture.
- 6.15″ pixels blend neighbours: the "WISE 0855" short-wavelength flux (~0.9 mJy at 0.75 µm) cannot be the Y dwarf
  (J ≈ 25) — it is blended field light; the 4.2–4.7 µm points (~0.6 mJy) agree with WISE W2 (AB 17.23 ≈ 0.47 mJy).
- The All-Sky Cube (`spherex_dr1_cube`) would give 102-channel spectra directly but at 12.9″/px; not used yet.
