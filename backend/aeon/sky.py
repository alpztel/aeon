"""Physical sky model and SPHEREx-like image formation.

This is the scientific fallback used when no real FITS archive is mounted. It produces images
with a proper astropy WCS (TAN projection, north up, east left), a wavelength-dependent PSF
integrated over undersampled 6.2" pixels, a zodiacal background pedestal, and Gaussian noise
calibrated to the SPHEREx per-band 5-sigma depth. Sources:

* named catalog objects (demo targets, real reference stars) with proper motions and
  time-variable SEDs;
* a deterministic field population (stars + faint galaxies) whose surface density follows
  galactic latitude, generated per sky tile so every request for the same patch is identical.

The analysis pipeline (photutils photometry, differencing, shift-and-stack) treats these images
exactly like archive FITS data.
"""

from __future__ import annotations

import math
import os
import zlib
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
from scipy.special import erf

from . import bands, spectra
from .catalog import ENTRIES, CatalogEntry
from .ephem import apparent_position

NATIVE_PIXEL_SCALE = 6.2          # arcsec / pixel
TELESCOPE_DIAMETER_M = 0.20
EXPOSURES_PER_EPOCH = 6           # an epoch (quarter) image is a coadd of this many exposures
TILE_DEG = 0.5
FIELD_MAG_RANGE = (11.0, 23.5)    # AB at 4.6 um
FIELD_DENSITY_HIGH_LAT = 3000.0   # sources / deg^2 brighter than FIELD_MAG_RANGE[1]


def psf_fwhm_arcsec(wavelength_um: float | np.ndarray) -> float | np.ndarray:
    """Optics + pointing jitter in quadrature with the diffraction core (1.03 lambda/D)."""
    diffraction = 1.03 * np.asarray(wavelength_um) * 1e-6 / TELESCOPE_DIAMETER_M * 206264.806
    return np.sqrt(4.5**2 + diffraction**2)


BROADBAND_FWHM_ARCSEC = float(np.mean(psf_fwhm_arcsec(bands.WAVELENGTH_UM)))


def zodi_pedestal_ujy_per_arcsec2(wavelength_um: np.ndarray) -> np.ndarray:
    """Zodiacal light: scattered sunlight (5778 K) + thermal dust emission (~275 K).
    Scaled to ~0.3 MJy/sr at 1.25 um and ~0.2 MJy/sr at 4.6 um (ecliptic-averaged)."""
    lam = np.atleast_1d(np.asarray(wavelength_um, dtype=float))
    scat = spectra.planck_fnu(lam, 5778.0) / spectra.planck_fnu(np.array([1.25]), 5778.0)[0]
    therm = spectra.planck_fnu(lam, 275.0) / spectra.planck_fnu(np.array([4.6]), 275.0)[0]
    mjy_sr = 0.3 * scat + 0.15 * therm
    return mjy_sr * 1e12 / 4.25e10  # MJy/sr -> uJy/arcsec^2


# --------------------------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------------------------

@dataclass
class SourceSet:
    """Sources in a region at a set of times. Positions are (n_src, n_times)."""
    ra: np.ndarray
    dec: np.ndarray
    flux: np.ndarray        # (n_src, n_times, 102) uJy
    ids: list[str | None]


# ~0.3 MB per tile; AEON_TILE_CACHE tiles per process (default 256 ~ 80 MB)
@lru_cache(maxsize=int(os.environ.get("AEON_TILE_CACHE", "256")))
def _tile_sources(k: int, j: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Deterministic field population of one tile: ra, dec, mag_w2, teff, is_galaxy."""
    dec_lo = -90.0 + k * TILE_DEG
    dec_hi = min(dec_lo + TILE_DEG, 90.0)
    dec_c = 0.5 * (dec_lo + dec_hi)
    n_ra = max(1, int(360.0 * math.cos(math.radians(dec_c)) / TILE_DEG))
    width = 360.0 / n_ra
    ra_lo = j * width
    area = width * (math.sin(math.radians(dec_hi)) - math.sin(math.radians(dec_lo))) * 180.0 / math.pi
    b = SkyCoord(ra=(ra_lo + width / 2) * u.deg, dec=dec_c * u.deg).galactic.b.deg
    density = FIELD_DENSITY_HIGH_LAT * (1.0 + 9.0 * math.exp(-abs(b) / 10.0))
    rng = np.random.default_rng([k, j, 2026])
    n = rng.poisson(density * area)
    ra = ra_lo + rng.random(n) * width
    sin_dec = rng.uniform(math.sin(math.radians(dec_lo)), math.sin(math.radians(dec_hi)), n)
    dec = np.degrees(np.arcsin(sin_dec))
    # Euclidean-ish counts: dN/dm ~ 10^(0.3 m); inverse-CDF sampling.
    m0, m1 = FIELD_MAG_RANGE
    a = 0.3 * math.log(10)
    uu = rng.random(n)
    mag = np.log(np.exp(a * m0) + uu * (np.exp(a * m1) - np.exp(a * m0))) / a
    teff = np.clip(rng.lognormal(math.log(4300.0), 0.35, n), 2600.0, 15000.0)
    is_gal = (mag > 18.0) & (rng.random(n) < 0.12)
    return ra, dec, mag, teff, is_gal


def _tiles_for(ra: float, dec: float, radius_deg: float) -> list[tuple[int, int]]:
    out = []
    k_lo = max(0, int((dec - radius_deg + 90.0) // TILE_DEG))
    k_hi = min(int(180.0 / TILE_DEG) - 1, int((dec + radius_deg + 90.0) // TILE_DEG))
    for k in range(k_lo, k_hi + 1):
        dec_c = -90.0 + (k + 0.5) * TILE_DEG
        n_ra = max(1, int(360.0 * math.cos(math.radians(dec_c)) / TILE_DEG))
        width = 360.0 / n_ra
        cosd = max(math.cos(math.radians(min(abs(dec) + radius_deg, 89.9))), 1e-3)
        half = radius_deg / cosd
        if half >= 180.0:
            js = range(n_ra)
        else:
            j0 = int(math.floor((ra - half) / width))
            j1 = int(math.floor((ra + half) / width))
            js = sorted({jj % n_ra for jj in range(j0, j1 + 1)})
        out.extend((k, jj) for jj in js)
    return out


def _angsep_deg(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(np.radians, (ra1, dec1, ra2, dec2))
    h = np.sin((d2 - d1) / 2) ** 2 + np.cos(d1) * np.cos(d2) * np.sin((r2 - r1) / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(h, 0, 1))))


# ~3 MB per tile in float32 (was 6 MB float64 x 512 tiles = 3 GB per worker under random-sky load)
@lru_cache(maxsize=int(os.environ.get("AEON_TILE_SED_CACHE", "48")))   # ~3 MB each
def _tile_seds(k: int, j: int) -> np.ndarray:
    """Band fluxes (N, 102) uJy, float32, of a tile's field population (stars: Planck; galaxies: z-model)."""
    ra, _, mag, teff, is_gal = _tile_sources(k, j)
    flux = np.zeros((len(ra), 102), dtype=np.float32)
    stars = ~is_gal
    if stars.any():
        flux[stars] = spectra.blackbody_bands(mag[stars], teff[stars])
    gi = np.flatnonzero(is_gal)
    if len(gi):
        z = np.array([0.5 + (zlib.crc32(f"{ra[i]:.6f}".encode()) % 1000) / 1000 * 2.5 for i in gi])
        flux[gi] = spectra.high_z_galaxies(mag[gi], z)
    return flux


def field_sources(ra: float, dec: float, radius_deg: float, with_flux: bool = False) -> dict[str, np.ndarray]:
    tiles = _tiles_for(ra, dec, radius_deg)
    parts = [_tile_sources(k, j) for k, j in tiles]
    if not parts:
        empty = np.zeros(0)
        out = {"ra": empty, "dec": empty, "mag": empty, "teff": empty, "is_galaxy": empty.astype(bool)}
        if with_flux:
            out["flux"] = np.zeros((0, 102))
        return out
    cat = [np.concatenate([p[i] for p in parts]) for i in range(5)]
    sel = _angsep_deg(ra, dec, cat[0], cat[1]) <= radius_deg
    out = {"ra": cat[0][sel], "dec": cat[1][sel], "mag": cat[2][sel], "teff": cat[3][sel], "is_galaxy": cat[4][sel]}
    if with_flux:
        out["flux"] = np.concatenate([_tile_seds(k, j) for k, j in tiles])[sel]
    return out


def entry_flux(entry: CatalogEntry, t_year: float) -> np.ndarray:
    return spectra.model_flux(entry.object_class, entry.mag_ab_w2 or 20.0, t_year, entry.teff_k, entry.redshift)


def sources_in_region(ra: float, dec: float, radius_deg: float, times: list[float]) -> SourceSet:
    nt = len(times)
    f = field_sources(ra, dec, radius_deg, with_flux=True)
    n_field = len(f["ra"])
    flux_field = f["flux"]
    ras = [np.repeat(f["ra"][:, None], nt, axis=1)]
    decs = [np.repeat(f["dec"][:, None], nt, axis=1)]
    fluxes = [np.repeat(flux_field[:, None, :], nt, axis=1)]
    ids: list[str | None] = [None] * n_field

    margin = radius_deg + 0.05
    for e in ENTRIES:
        pos = [apparent_position(e, t) for t in times]
        if _angsep_deg(ra, dec, pos[0][0], pos[0][1]) > margin:
            continue
        ras.append(np.array([[p[0] for p in pos]]))
        decs.append(np.array([[p[1] for p in pos]]))
        fluxes.append(np.array([[entry_flux(e, t) for t in times]]))
        ids.append(e.id)
    return SourceSet(np.vstack(ras), np.vstack(decs), np.vstack(fluxes), ids)


# --------------------------------------------------------------------------------------------
# Image formation
# --------------------------------------------------------------------------------------------

def make_wcs(ra: float, dec: float, size_px: int, scale_arcsec: float) -> WCS:
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(size_px + 1) / 2.0, (size_px + 1) / 2.0]
    w.wcs.cdelt = [-scale_arcsec / 3600.0, scale_arcsec / 3600.0]
    w.wcs.cunit = ["deg", "deg"]
    w.wcs.radesys = "ICRS"
    return w


def _seed(*parts) -> int:
    return zlib.crc32(("|".join(f"{p:.6f}" if isinstance(p, float) else str(p) for p in parts)).encode())


def epoch_subtimes(t_center: float) -> list[float]:
    """Exposure mid-times within a quarter (0.25 yr) used to build an epoch coadd."""
    step = 0.25 / EXPOSURES_PER_EPOCH
    return [t_center - 0.125 + step * (i + 0.5) for i in range(EXPOSURES_PER_EPOCH)]


def point_source_sigma(band: int | None, n_exposures: int) -> float:
    """1-sigma point-source noise (uJy) for a band (or broadband mean) given the number of
    exposures combined, relative to a full-epoch coadd of EXPOSURES_PER_EPOCH exposures."""
    s = bands.POINT_SOURCE_SIGMA_UJY
    if band is None:
        s /= math.sqrt(bands.N_BANDS)
    return s * math.sqrt(EXPOSURES_PER_EPOCH / n_exposures)


def _gauss_pixel_weights(x0: np.ndarray, sigma_px: np.ndarray, n: int) -> np.ndarray:
    """Fraction of a 1-D Gaussian falling in each pixel. x0 (...,), sigma (...,) -> (..., n)."""
    edges = np.arange(n + 1) - 0.5
    z = (edges - np.asarray(x0)[..., None]) / (np.sqrt(2.0) * np.asarray(sigma_px)[..., None])
    return 0.5 * np.diff(erf(z), axis=-1)


def render(ra: float, dec: float, times: list[float], size_px: int = 64,
           scale_arcsec: float = NATIVE_PIXEL_SCALE, band: int | None = None,
           noise_sigma_ps: float | None = None, seed_tag: str = "img") -> tuple[np.ndarray, WCS, dict]:
    """Render an image averaged over `times` (exposure mid-times). Returns (image uJy/pix, wcs, meta).

    The returned image is background-subtracted only by the caller; here the zodiacal pedestal is
    included so the pipeline has a real background to estimate."""
    w = make_wcs(ra, dec, size_px, scale_arcsec)
    radius = (size_px * scale_arcsec / 3600.0) * 0.75 + 0.01
    src = sources_in_region(ra, dec, radius, times)
    if band is None:
        flux = src.flux.mean(axis=2)                       # (n_src, n_t)
        fwhm = BROADBAND_FWHM_ARCSEC
        lam = bands.WAVELENGTH_UM
        pedestal = float(np.mean(zodi_pedestal_ujy_per_arcsec2(lam))) * scale_arcsec**2
    else:
        flux = src.flux[:, :, band]
        fwhm = float(psf_fwhm_arcsec(bands.WAVELENGTH_UM[band]))
        pedestal = float(zodi_pedestal_ujy_per_arcsec2(bands.WAVELENGTH_UM)[band]) * scale_arcsec**2
    sigma_px = fwhm / 2.3548 / scale_arcsec
    img = np.zeros((size_px, size_px))
    nt = len(times)
    if len(src.ra):
        x, y = w.all_world2pix(src.ra.ravel(), src.dec.ravel(), 0)
        x = x.reshape(src.ra.shape)
        y = y.reshape(src.ra.shape)
        pad = 6 * sigma_px + 2
        inside = (x > -pad) & (x < size_px + pad) & (y > -pad) & (y < size_px + pad)
        half = int(math.ceil(6 * sigma_px)) + 2
        width = 2 * half + 1
        ii, tt = np.nonzero(inside)
        if len(ii):
            # Vectorised windowed stamps: each source deposits a (width x width) pixel-integrated
            # Gaussian around its position; out-of-frame pixels are dropped.
            xs, ys = x[ii, tt], y[ii, tt]
            x0 = np.floor(xs).astype(int) - half
            y0 = np.floor(ys).astype(int) - half
            wx = _gauss_pixel_weights(xs - x0, np.full(len(xs), sigma_px), width)      # (N, W)
            wy = _gauss_pixel_weights(ys - y0, np.full(len(ys), sigma_px), width)
            vals = (flux[ii, tt] / nt)[:, None, None] * wy[:, :, None] * wx[:, None, :]
            off = np.arange(width)
            rows = np.broadcast_to((y0[:, None] + off)[:, :, None], vals.shape)
            cols = np.broadcast_to((x0[:, None] + off)[:, None, :], vals.shape)
            ok = (rows >= 0) & (rows < size_px) & (cols >= 0) & (cols < size_px)
            np.add.at(img, (rows[ok], cols[ok]), vals[ok])
    n_exp = EXPOSURES_PER_EPOCH if nt > 1 else 1
    sigma_ps = noise_sigma_ps if noise_sigma_ps is not None else point_source_sigma(band, n_exp)
    nea = max(4 * math.pi * sigma_px**2, 1.0)                 # noise-equivalent area, pixels
    sigma_pix = sigma_ps / math.sqrt(nea)
    rng = np.random.default_rng(_seed(ra, dec, float(np.mean(times)), band, size_px, scale_arcsec, seed_tag))
    img = img + pedestal + rng.normal(0.0, sigma_pix, img.shape)
    meta = {
        "psf_fwhm_arcsec": fwhm, "psf_sigma_px": sigma_px, "sigma_pix": sigma_pix,
        "sigma_point_source_ujy": sigma_ps, "pedestal": pedestal, "n_sources": int(inside.sum()) if len(src.ra) else 0,
        "times": list(times),
    }
    return img, w, meta


def render_cube(ra: float, dec: float, times: list[float], size_px: int = 25,
                scale_arcsec: float = NATIVE_PIXEL_SCALE, seed_tag: str = "cube") -> tuple[np.ndarray, WCS, dict]:
    """102-band spectral cube (102, ny, nx) in uJy/pixel with per-band PSF, zodi and noise."""
    w = make_wcs(ra, dec, size_px, scale_arcsec)
    radius = (size_px * scale_arcsec / 3600.0) * 0.75 + 0.01
    src = sources_in_region(ra, dec, radius, times)
    lam = bands.WAVELENGTH_UM
    sigma_px = psf_fwhm_arcsec(lam) / 2.3548 / scale_arcsec        # (102,)
    cube = np.zeros((102, size_px, size_px))
    nt = len(times)
    if len(src.ra):
        x, y = w.all_world2pix(src.ra.ravel(), src.dec.ravel(), 0)
        x = x.reshape(src.ra.shape)
        y = y.reshape(src.ra.shape)
        ii, tt = np.nonzero((x > -10) & (x < size_px + 10) & (y > -10) & (y < size_px + 10))
        # Vectorised: per-band pixel-integrated Gaussians for all (source, time) pairs, in chunks to
        # bound memory, combined with einsum.
        for c0 in range(0, len(ii), 256):
            ci, ct = ii[c0:c0 + 256], tt[c0:c0 + 256]
            xs, ys = x[ci, ct], y[ci, ct]
            wx = _gauss_pixel_weights(np.repeat(xs[:, None], 102, axis=1), np.broadcast_to(sigma_px, (len(xs), 102)), size_px)
            wy = _gauss_pixel_weights(np.repeat(ys[:, None], 102, axis=1), np.broadcast_to(sigma_px, (len(ys), 102)), size_px)
            f = src.flux[ci, ct] / nt                                       # (n, 102)
            cube += np.einsum("nb,nby,nbx->byx", f, wy, wx, optimize=True)
    nea = np.maximum(4 * np.pi * sigma_px**2, 1.0)
    sigma_pix = bands.POINT_SOURCE_SIGMA_UJY / np.sqrt(nea)
    pedestal = zodi_pedestal_ujy_per_arcsec2(lam) * scale_arcsec**2
    rng = np.random.default_rng(_seed(ra, dec, float(np.mean(times)), size_px, scale_arcsec, seed_tag))
    cube = cube + pedestal[:, None, None] + rng.normal(0.0, 1.0, cube.shape) * sigma_pix[:, None, None]
    return cube, w, {"psf_sigma_px": sigma_px, "sigma_pix": sigma_pix, "pedestal": pedestal}


def to_fits(img: np.ndarray, w: WCS, header_extra: dict | None = None) -> fits.HDUList:
    hdr = w.to_header()
    hdr["BUNIT"] = "uJy/pixel"
    hdr["ORIGIN"] = "AEON"
    hdr["TELESCOP"] = "SPHEREx-like model"
    for k, v in (header_extra or {}).items():
        hdr[k[:8].upper()] = v
    return fits.HDUList([fits.PrimaryHDU(data=img.astype(np.float32), header=hdr)])
