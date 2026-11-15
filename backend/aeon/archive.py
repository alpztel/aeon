"""Real FITS archive access (AEON_DATA_DIR).

Two kinds of files are indexed:

* **SPHEREx Level 2 spectral images** (IRSA ``spherex_dr1`` / ``spherex_qr*``): multi-extension
  files with ``IMAGE`` (MJy/sr), ``FLAGS`` (int32 bitmap), ``VARIANCE`` ((MJy/sr)^2), ``ZODI``,
  ``EPSF``/``PSF`` and ``WCS-WAVE``. Every pixel sees a different wavelength (linear variable
  filter); the per-pixel wavelength and bandwidth come from the alternate WCS ``W``
  (``CTYPE1W = 'WAVE-TAB'``, lookup table in the ``WCS-WAVE`` extension). See
  ``backend/docs/spherex-l2-notes.md``.
* **Generic 2-D images** with a celestial WCS (the original archive mode). Units are uJy/pixel
  unless ``BUNIT`` says MJy/sr.

The epoch is read from ``AEONEPOC`` or from the observation time (``MJD-AVG``, ``MJD-OBS``,
``DATE-AVG``, ``DATE-OBS``) and mapped to the **calendar quarter** of the observation
(Jan-Mar -> 2026-Q1, ...). For 2026 observations this equals the nearest AEON epoch (except within
~1 day of a quarter boundary); real
SPHEREx data from 2025 is folded onto the quarter of the year in which it was taken, and the real
observation date is always reported in the provenance.

All images are resampled onto a north-up / east-left TAN grid (the contract's image orientation)
at the requested pixel scale, conserving surface brightness, and converted to uJy per output pixel.
Flagged pixels become NaN.
"""

from __future__ import annotations

import math
import os
import threading
import warnings
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.utils.exceptions import AstropyWarning
from astropy.wcs import WCS, FITSFixedWarning
from astropy.wcs.utils import proj_plane_pixel_scales
from scipy import ndimage

from . import bands
from .epochs import EPOCHS

ARCSEC2_PER_SR = (180.0 / math.pi * 3600.0) ** 2          # 4.25452e10
MJY_SR_TO_UJY_ARCSEC2 = 1e12 / ARCSEC2_PER_SR              # 1 MJy/sr = 23.5045 uJy/arcsec^2

# SPHEREx FLAGS bits (names from the MSKNnnnn/MSKMnnnn keywords of the FLAGS header).
SPHEREX_FLAG_BITS = {
    "TRANSIENT": 0, "OVERFLOW": 1, "SUR_ERROR": 2, "NONFUNC": 6, "DICHROIC": 7, "MISSING_DATA": 9,
    "HOT": 10, "COLD": 11, "FULLSAMPLE": 12, "PHANMISS": 14, "NONLINEAR": 15, "PERSIST": 17,
    "OUTLIER": 19, "CROSSTALK": 20, "SOURCE": 21, "GHOST": 22, "GHOST_FPA": 23, "GHOST_EXT": 24,
    "STREAK": 25, "BLOOM": 26, "SNOWBALL": 27, "HALO": 28,
}
# Pixels rejected by AEON. This is AEON's own choice (IRSA does not publish a recommended mask):
# hardware/readout failures and transient artefacts. SOURCE (>50% of pixels: "mapped to a known
# source"), DICHROIC (low but calibrated efficiency) and FULLSAMPLE (informational) are kept.
SPHEREX_REJECT = ("TRANSIENT", "OVERFLOW", "SUR_ERROR", "NONFUNC", "MISSING_DATA", "HOT", "COLD",
                  "NONLINEAR", "PERSIST", "OUTLIER", "CROSSTALK", "GHOST", "GHOST_FPA", "GHOST_EXT",
                  "STREAK", "BLOOM", "SNOWBALL", "HALO")
SPHEREX_REJECT_MASK = sum(1 << SPHEREX_FLAG_BITS[n] for n in SPHEREX_REJECT)

QUARTER_EPOCHS = ("2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4")

# Pixel arrays of small files (IRSA cutouts, the bulk of the archive) are kept in memory after the
# first read, up to AEON_PIXEL_CACHE_MB per process (LRU). Larger files (complete 2040x2040 L2
# images) are never cached whole: only the window a request needs is read from disk.
PIXEL_CACHE_BYTES = int(float(os.environ.get("AEON_PIXEL_CACHE_MB", "96")) * 1024 * 1024)
CACHE_MAX_PIXELS = 512 * 512
SURVEY_GROUP_DAYS = 60.0     # frames within this many days of the best frame form one visit


@contextmanager
def _quiet():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        warnings.simplefilter("ignore", AstropyWarning)
        yield


@dataclass
class ArchiveImage:
    path: Path
    epoch: str
    wcs: WCS
    shape: tuple[int, int]
    scale_arcsec: float
    kind: str = "generic"                 # "spherex" | "generic"
    hdu: int = 0
    mjd: float | None = None
    detector: int | None = None
    obs_id: str | None = None
    unit: str = "uJy/pixel"
    psf_fwhm_arcsec: float | None = None
    omega_arcsec2: float | None = None    # median pixel solid angle (SPHEREx OMEGA_MEDIAN)
    hdu_flags: int | None = None          # SPHEREx FLAGS / VARIANCE extension indices (no name lookups per read)
    hdu_var: int | None = None
    wave: tuple | None = field(default=None, repr=False)   # WCS-WAVE model read once at indexing (wave_model)

    # Read on every request for every frame; astropy Time is too slow to rebuild each time.
    @cached_property
    def date_obs(self) -> str | None:
        return None if self.mjd is None else Time(self.mjd, format="mjd").isot[:19]

    @cached_property
    def decimal_year(self) -> float | None:
        return None if self.mjd is None else float(Time(self.mjd, format="mjd").decimalyear)


@dataclass
class Frame:
    """One archive image that covers a sky position, with the wavelength seen there."""
    image: ArchiveImage
    wavelength_um: float | None
    bandwidth_um: float | None
    band: int | None


# --------------------------------------------------------------------------------------------
# Header helpers
# --------------------------------------------------------------------------------------------

def _obs_time(header: fits.Header) -> Time | None:
    for key in ("MJD-AVG", "MJD-OBS", "MJD-BEG"):
        if key in header:
            try:
                return Time(float(header[key]), format="mjd")
            except (TypeError, ValueError):
                pass
    for key in ("DATE-AVG", "DATE-OBS", "DATE-BEG"):
        if key in header:
            try:
                return Time(header[key])
            except ValueError:
                pass
    return None


def epoch_for_time(t: Time) -> str:
    """Calendar quarter of the observation date -> AEON epoch label."""
    month = int(t.datetime.month) if hasattr(t.datetime, "month") else int(t.isot[5:7])
    return QUARTER_EPOCHS[(month - 1) // 3]


def _epoch_of(header: fits.Header) -> str | None:
    if "AEONEPOC" in header and header["AEONEPOC"] in EPOCHS:
        return header["AEONEPOC"]
    t = _obs_time(header)
    return None if t is None else epoch_for_time(t)


def is_spherex(hdul: fits.HDUList) -> bool:
    names = {h.name for h in hdul}
    if not {"IMAGE", "FLAGS"} <= names:
        return False
    h = hdul["IMAGE"].header
    return str(h.get("CTYPE1W", "")).startswith("WAVE") or "WCS-WAVE" in names


def flux_unit_factor(bunit: str) -> str:
    b = str(bunit).replace(" ", "").lower()
    return "MJy/sr" if b in ("mjy/sr", "mjysr-1", "mjy/steradian") else "uJy/pixel"


def bad_pixel_mask(flags: np.ndarray, reject_mask: int = SPHEREX_REJECT_MASK) -> np.ndarray:
    return (np.asarray(flags).astype(np.int64) & int(reject_mask)) != 0


def band_of_wavelength(lam_um: float) -> int | None:
    """AEON band (bands.py) whose [centre - bw/2, centre + bw/2] contains lam, else nearest band
    if within one bandwidth, else None."""
    lo = bands.WAVELENGTH_UM - bands.BANDWIDTH_UM / 2
    hi = bands.WAVELENGTH_UM + bands.BANDWIDTH_UM / 2
    inside = np.flatnonzero((lam_um >= lo) & (lam_um < hi))
    if inside.size:
        return int(inside[0])
    k = int(np.argmin(np.abs(bands.WAVELENGTH_UM - lam_um)))
    return k if abs(bands.WAVELENGTH_UM[k] - lam_um) <= bands.BANDWIDTH_UM[k] else None


# --------------------------------------------------------------------------------------------
# SPHEREx per-pixel wavelength (WCS-WAVE lookup table, alternate WCS 'W')
# --------------------------------------------------------------------------------------------

def wave_table_lookup(header: fits.Header, table: fits.FITS_rec, x0: float, y0: float) -> tuple[float, float]:
    """Bilinear interpolation of the WCS-WAVE table at 0-based pixel (x0, y0) of this image.

    Implements the -TAB algorithm of FITS Paper III for this table: intermediate coordinate
    q = CDELTiW * (p - CRPIXiW) with p the 1-based pixel, psi = q + CRVALiW, then psi is located in
    the index vector (columns X, Y = raw-detector control points) and VALUES (2, nx, ny) — or
    (2, nx, ny) per the TDIM — is bilinearly interpolated. Independent of astropy's -TAB support.
    """
    return wave_model_eval(wave_model(header, table), x0, y0)


def wave_model(header: fits.Header, table: fits.FITS_rec) -> tuple:
    """The few numbers wave_table_lookup needs, copied out of the file (a few kB per image), so the
    wavelength at any pixel is evaluated later without opening the file again."""
    xs = np.asarray(table["X"][0], dtype=float).copy()
    ys = np.asarray(table["Y"][0], dtype=float).copy()
    vals = np.asarray(table["VALUES"][0], dtype=float)        # numpy shape (ny, nx, 2) for TDIM (2,nx,ny)
    if vals.shape[:2] != (ys.size, xs.size):
        vals = vals.reshape(ys.size, xs.size, 2)
    vals = np.ascontiguousarray(vals)
    return (float(header.get("CDELT1W", 1.0)), float(header["CRPIX1W"]), float(header.get("CRVAL1W", 1.0)),
            float(header.get("CDELT2W", 1.0)), float(header["CRPIX2W"]), float(header.get("CRVAL2W", 1.0)),
            xs, ys, vals)


def wave_model_eval(model: tuple, x0: float, y0: float) -> tuple[float, float]:
    cd1, cp1, cv1, cd2, cp2, cv2, xs, ys, vals = model
    px, py = x0 + 1.0, y0 + 1.0
    psi_x = cd1 * (px - cp1) + cv1
    psi_y = cd2 * (py - cp2) + cv2
    # Fractional index (0-based) of psi within the control-point vectors.
    fx = float(np.interp(psi_x, xs, np.arange(xs.size)))
    fy = float(np.interp(psi_y, ys, np.arange(ys.size)))
    out = []
    for k in range(2):
        out.append(float(ndimage.map_coordinates(vals[:, :, k], [[fy], [fx]], order=1, mode="nearest")[0]))
    return out[0], out[1]


def spherex_wavelength(hdul: fits.HDUList, x0: float, y0: float) -> tuple[float, float]:
    """(central wavelength, bandwidth) in um at 0-based pixel (x0, y0) of the IMAGE extension.

    Uses astropy's -TAB implementation exactly as in the IRSA tutorials
    (``WCS(header, fobj=hdul, key='W')`` with SIP disabled) and falls back to AEON's own bilinear
    implementation if the reader does not support -TAB.
    """
    header = hdul["IMAGE"].header
    try:
        h = header.copy()
        for k in list(h.keys()):           # spectral WCS has no SIP; drop it to avoid astropy INFO noise
            if k.split("_")[0] in ("A", "B", "AP", "BP") and k[:2] in ("A_", "B_", "AP", "BP"):
                del h[k]
        with _quiet():
            sw = WCS(h, fobj=hdul, key="W")
            sw.sip = None
            lam, bw = sw.pixel_to_world_values(x0, y0)
        lam, bw = float(lam), float(bw)
        if np.isfinite(lam) and np.isfinite(bw) and lam > 0:
            return lam, bw
    except Exception:  # noqa: BLE001 - any -TAB reader failure -> independent implementation
        pass
    return wave_table_lookup(header, hdul["WCS-WAVE"].data, x0, y0)


# --------------------------------------------------------------------------------------------
# Resampling onto the contract's north-up grid
# --------------------------------------------------------------------------------------------

def target_wcs(ra: float, dec: float, size_px: int, scale_arcsec: float) -> WCS:
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(size_px + 1) / 2.0, (size_px + 1) / 2.0]
    w.wcs.cdelt = [-scale_arcsec / 3600.0, scale_arcsec / 3600.0]
    w.wcs.cunit = ["deg", "deg"]
    w.wcs.radesys = "ICRS"
    return w


def resample(data: np.ndarray, src_wcs: WCS, dst_wcs: WCS, shape: tuple[int, int]) -> np.ndarray:
    """Bilinear resampling of a surface-brightness map; NaN where the source is NaN or absent."""
    sx, sy = source_coords(src_wcs, dst_wcs, shape)
    return resample_at(data, sx, sy, shape, data.shape)


def grid_world(dst_wcs: WCS, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """(ra, dec) of every destination pixel, flattened. The same for every frame of a stack."""
    ny, nx = shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    return dst_wcs.all_pix2world(xx.ravel(), yy.ravel(), 0)


def source_coords(src_wcs: WCS, dst_wcs: WCS, shape: tuple[int, int],
                  world: tuple[np.ndarray, np.ndarray] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """0-based source pixel (x, y) of every destination pixel (``world`` = grid_world, if known)."""
    ra, dec = world if world is not None else grid_world(dst_wcs, shape)
    with _quiet():
        sx, sy = src_wcs.all_world2pix(ra, dec, 0, quiet=True)
    return sx, sy


def source_window(sx: np.ndarray, sy: np.ndarray, full_shape: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """(y0, y1, x0, x1) of the source pixels bilinear interpolation at (sx, sy) can touch, clipped to
    the image, with one pixel to spare so that interpolation inside the window equals interpolation
    on the whole image. None when no destination pixel falls on the image."""
    ny, nx = full_shape
    ok = np.isfinite(sx) & np.isfinite(sy) & (sx > -1.0) & (sx < nx) & (sy > -1.0) & (sy < ny)
    if not ok.any():
        return None
    x0 = max(int(math.floor(sx[ok].min())) - 1, 0)
    x1 = min(int(math.floor(sx[ok].max())) + 3, nx)
    y0 = max(int(math.floor(sy[ok].min())) - 1, 0)
    y1 = min(int(math.floor(sy[ok].max())) + 3, ny)
    return y0, y1, x0, x1


def resample_at(data: np.ndarray, sx: np.ndarray, sy: np.ndarray, shape: tuple[int, int],
                full_shape: tuple[int, int], x0: int = 0, y0: int = 0) -> np.ndarray:
    """Bilinear samples of data at source pixels (sx, sy). ``data`` may be the window of the full
    image starting at (y0, x0) given by source_window; the result is the same as on the full image."""
    good = np.isfinite(data)
    filled = np.where(good, data, 0.0)
    coords = np.vstack([sy - y0, sx - x0]) if (x0 or y0) else np.vstack([sy, sx])
    val = ndimage.map_coordinates(filled, coords, order=1, mode="constant", cval=0.0)
    wgt = ndimage.map_coordinates(good.astype(float), coords, order=1, mode="constant", cval=0.0)
    inside = (sx >= -0.5) & (sx <= full_shape[1] - 0.5) & (sy >= -0.5) & (sy <= full_shape[0] - 0.5)
    out = np.where((wgt > 0.75) & inside, val / np.maximum(wgt, 1e-12), np.nan)
    return out.reshape(shape)


# --------------------------------------------------------------------------------------------
# Archive
# --------------------------------------------------------------------------------------------

class FitsArchive:
    def __init__(self, root: str | os.PathLike | None) -> None:
        self.root = Path(root) if root else None
        self.images: list[ArchiveImage] = []
        self._footprints: tuple | None = None
        self._pix_cache: OrderedDict = OrderedDict()
        self._pix_bytes = 0
        self._pix_lock = threading.Lock()
        self.wave_check: str | None = None     # result of the one-off WCS-WAVE cross-check (scan)
        if self.root and self.root.is_dir():
            self.scan()

    # ---------------------------------------------------------------- indexing
    def scan(self) -> None:
        self.images.clear()
        self._footprints = None
        with self._pix_lock:
            self._pix_cache.clear()
            self._pix_bytes = 0
        paths = sorted(self.root.glob("**/*.fits")) + sorted(self.root.glob("**/*.fits.gz"))
        for p in paths:
            try:
                img = self._index(p)
            except (OSError, StopIteration, ValueError, KeyError, TypeError):
                img = None
            if img is not None:
                self.images.append(img)
        self._check_wave_model()

    def _check_wave_model(self) -> None:
        """Requests evaluate the SPHEREx wavelength with AEON's own -TAB implementation on the table
        copied at indexing (no file access). Cross-check it once per scan against astropy's reader
        on the first SPHEREx file; if they disagree, drop the copied tables so every lookup goes
        through astropy (slower, but never wrong)."""
        img = next((i for i in self.images if i.wave is not None), None)
        if img is None:
            return
        x, y = (img.shape[1] - 1) / 2.0, (img.shape[0] - 1) / 2.0
        try:
            with _quiet(), fits.open(img.path, memmap=False) as hdul:
                ref = spherex_wavelength(hdul, x, y)
        except (OSError, KeyError, ValueError):
            return
        own = wave_model_eval(img.wave, x, y)
        if abs(own[0] - ref[0]) <= 1e-4 and abs(own[1] - ref[1]) <= 1e-4:
            self.wave_check = "ok"
            return
        self.wave_check = f"mismatch on {img.path.name}: own {own} vs astropy {ref}; using astropy"
        warnings.warn(f"AEON WCS-WAVE {self.wave_check}", RuntimeWarning, stacklevel=2)
        for i in self.images:
            i.wave = None

    def _index(self, p: Path) -> ArchiveImage | None:
        with _quiet(), fits.open(p, memmap=False) as hdul:
            if is_spherex(hdul):
                h = hdul["IMAGE"].header
                w = WCS(h, relax=True).celestial
                t = _obs_time(h)
                epoch = h.get("AEONEPOC") if h.get("AEONEPOC") in EPOCHS else (epoch_for_time(t) if t else None)
                if not w.has_celestial or epoch is None:
                    return None
                scale = float(np.mean(proj_plane_pixel_scales(w)) * 3600.0)
                omega = h.get("OMEGA_MEDIAN")
                names = [x.name for x in hdul]
                wave = None
                if "WCS-WAVE" in names and "CRPIX1W" in h and "CRPIX2W" in h:
                    try:
                        wave = wave_model(h, hdul["WCS-WAVE"].data)
                    except (KeyError, ValueError, IndexError, TypeError):
                        wave = None
                return ArchiveImage(
                    path=p, epoch=epoch, wcs=w, shape=(int(h["NAXIS2"]), int(h["NAXIS1"])), scale_arcsec=scale,
                    kind="spherex", hdu=names.index("IMAGE"), mjd=None if t is None else float(t.mjd),
                    detector=h.get("DETECTOR"), obs_id=h.get("OBSID"), unit=flux_unit_factor(h.get("BUNIT", "")),
                    psf_fwhm_arcsec=float(h["PSF_FWHM"]) if "PSF_FWHM" in h else None,
                    omega_arcsec2=float(omega) if omega else None,
                    hdu_flags=names.index("FLAGS"),
                    hdu_var=names.index("VARIANCE") if "VARIANCE" in names else None,
                    wave=wave,
                )
            idx, hdu = next((i, x) for i, x in enumerate(hdul) if getattr(x, "data", None) is not None and x.data.ndim == 2)
            w = WCS(hdu.header)
            epoch = _epoch_of(hdu.header) or _epoch_of(hdul[0].header)
            if not w.has_celestial or epoch is None:
                return None
            t = _obs_time(hdu.header) or _obs_time(hdul[0].header)
            scale = float(np.mean(proj_plane_pixel_scales(w.celestial)) * 3600.0)
            return ArchiveImage(p, epoch, w.celestial, hdu.data.shape, scale, kind="generic", hdu=idx,
                                mjd=None if t is None else float(t.mjd), unit=flux_unit_factor(hdu.header.get("BUNIT", "")))

    @property
    def available(self) -> bool:
        return bool(self.images)

    @property
    def n_spherex(self) -> int:
        return sum(1 for i in self.images if i.kind == "spherex")

    # ---------------------------------------------------------------- coverage
    @staticmethod
    def _contains(img: ArchiveImage, ra: float, dec: float, margin_px: float = 0.0) -> tuple[bool, float, float]:
        with _quiet():
            # Cheap linear test first: SIP inversion can diverge far outside the frame.
            lx, ly = img.wcs.wcs_world2pix([[ra, dec]], 0)[0]
            if not (np.isfinite(lx) and np.isfinite(ly)) or max(abs(lx - img.shape[1] / 2), abs(ly - img.shape[0] / 2)) > 2 * max(img.shape):
                return False, float(lx), float(ly)
            x, y = img.wcs.all_world2pix([[ra, dec]], 0, quiet=True)[0]
        ok = bool(np.isfinite(x) and np.isfinite(y) and -0.5 + margin_px <= x <= img.shape[1] - 0.5 - margin_px
                  and -0.5 + margin_px <= y <= img.shape[0] - 0.5 - margin_px)
        return ok, float(x), float(y)

    def wavelength_at(self, img: ArchiveImage, ra: float, dec: float) -> tuple[float, float] | None:
        if img.kind != "spherex":
            return None
        _, x, y = self._contains(img, ra, dec)
        if img.wave is not None:
            return wave_model_eval(img.wave, x, y)
        with _quiet(), fits.open(img.path, memmap=False) as hdul:
            return spherex_wavelength(hdul, x, y)

    def _candidates(self, ra: float, dec: float) -> list[ArchiveImage]:
        """Images whose footprint may contain (ra, dec): a vectorised angular-distance cut on each
        image's centre and half-diagonal (x1.5 + 1 arcmin for distortion), so the exact WCS test
        runs on a handful of images instead of the whole archive."""
        fp = self._footprints
        if fp is None or fp[0] != len(self.images):
            n = len(self.images)
            cra, cdec, rad = np.empty(n), np.empty(n), np.empty(n)
            for k, img in enumerate(self.images):
                with _quiet():
                    c = img.wcs.wcs_pix2world([[(img.shape[1] - 1) / 2.0, (img.shape[0] - 1) / 2.0]], 0)[0]
                cra[k], cdec[k] = c
                rad[k] = 1.5 * 0.5 * math.hypot(*img.shape) * img.scale_arcsec / 3600.0 + 1.0 / 60.0
            fp = self._footprints = (n, np.radians(cra), np.radians(cdec), rad)
        n, cra, cdec, rad = fp
        if not n:
            return []
        r0, d0 = math.radians(ra), math.radians(dec)
        cosd = np.sin(d0) * np.sin(cdec) + np.cos(d0) * np.cos(cdec) * np.cos(cra - r0)
        sep = np.degrees(np.arccos(np.clip(cosd, -1.0, 1.0)))
        bad = ~np.isfinite(sep)        # undefined centre: keep, the exact test decides
        return [self.images[k] for k in np.flatnonzero((sep <= rad) | bad)]

    def frames(self, ra: float, dec: float, epoch: str, band: int | None = None,
               allowed_bands: set[int] | None = None) -> list[Frame]:
        """Archive frames covering (ra, dec) in an epoch.

        If the epoch holds frames from more than one visit (e.g. 2025 and 2026 data folded onto the
        same quarter), only the visit closest to the nominal AEON epoch is kept. ``band`` keeps
        SPHEREx frames whose wavelength at (ra, dec) falls in that AEON band; ``allowed_bands``
        restricts to a set of bands (used to match two epochs for differencing).
        """
        hits: list[Frame] = []
        for img in self._candidates(ra, dec):
            if img.epoch != epoch:
                continue
            ok, _, _ = self._contains(img, ra, dec, margin_px=1.0)
            if not ok:
                continue
            if img.kind == "spherex":
                lam, bw = self.wavelength_at(img, ra, dec)
                b = band_of_wavelength(lam)
                if band is not None and b != band:
                    continue
                if allowed_bands is not None and b not in allowed_bands:
                    continue
                hits.append(Frame(img, lam, bw, b))
            elif band is None and allowed_bands is None:
                hits.append(Frame(img, None, None, None))
        timed = [f for f in hits if f.image.decimal_year is not None]
        if timed:
            nominal = EPOCHS[epoch]
            best = min(timed, key=lambda f: abs(f.image.decimal_year - nominal))
            hits = [f for f in hits if f.image.mjd is None or abs(f.image.mjd - best.image.mjd) <= SURVEY_GROUP_DAYS]
        return hits

    def find(self, ra: float, dec: float, epoch: str) -> ArchiveImage | None:
        fr = self.frames(ra, dec, epoch)
        return fr[0].image if fr else None

    # ---------------------------------------------------------------- pixels
    def _read_file(self, img: ArchiveImage, win: tuple[int, int, int, int] | None):
        """(image, bad-pixel mask, variance or None) as stored in the file, whole or one window."""
        sl = (slice(None), slice(None)) if win is None else (slice(win[0], win[1]), slice(win[2], win[3]))

        def get(h):
            if win is None:
                return np.asarray(h.data)
            try:
                return np.asarray(h.section[sl])
            except Exception:  # noqa: BLE001 - section unsupported (e.g. some compressed files)
                return np.asarray(h.data[sl])

        with _quiet(), fits.open(img.path, memmap=False) as hdul:
            if img.kind == "spherex":
                i_img = img.hdu
                i_flags = img.hdu_flags if img.hdu_flags is not None else hdul.index_of("FLAGS")
                i_var = img.hdu_var if img.hdu_flags is not None else (hdul.index_of("VARIANCE") if "VARIANCE" in hdul else None)
                data = get(hdul[i_img])
                bad = bad_pixel_mask(get(hdul[i_flags])) | ~np.isfinite(data)
                var = get(hdul[i_var]) if i_var is not None else None
            else:
                data = get(hdul[img.hdu])
                bad = ~np.isfinite(data)
                var = None
        return data, bad, var

    def _raw(self, img: ArchiveImage, win: tuple[int, int, int, int] | None = None):
        if img.shape[0] * img.shape[1] > CACHE_MAX_PIXELS or PIXEL_CACHE_BYTES <= 0:
            return self._read_file(img, win)
        key = img.path
        with self._pix_lock:
            hit = self._pix_cache.get(key)
            if hit is not None:
                self._pix_cache.move_to_end(key)
        if hit is None:
            data, bad, var = self._read_file(img, None)
            for a in (data, bad, var):
                if a is not None:
                    a.setflags(write=False)     # shared between requests
            hit = (data, bad, var)
            nbytes = sum(a.nbytes for a in hit if a is not None)
            with self._pix_lock:
                if key not in self._pix_cache:
                    self._pix_cache[key] = hit
                    self._pix_bytes += nbytes
                    while self._pix_bytes > PIXEL_CACHE_BYTES and len(self._pix_cache) > 1:
                        _, old = self._pix_cache.popitem(last=False)
                        self._pix_bytes -= sum(a.nbytes for a in old if a is not None)
        if win is None:
            return hit
        y0, y1, x0, x1 = win
        return tuple(None if a is None else a[y0:y1, x0:x1] for a in hit)

    def read(self, img: ArchiveImage, win: tuple[int, int, int, int] | None = None
             ) -> tuple[np.ndarray, np.ndarray | None, np.ndarray]:
        """(surface brightness in uJy/arcsec^2, variance in (uJy/arcsec^2)^2 or None, bad-pixel mask).

        SPHEREx: IMAGE [MJy/sr] with FLAGS-rejected pixels set to NaN. Generic uJy/pixel images are
        divided by the pixel solid angle so that every image is resampled as surface brightness.
        ``win`` = (y0, y1, x0, x1) returns only that window (read from disk alone for large files).
        """
        data, bad, var = self._raw(img, win)
        data = np.asarray(data, dtype=float)
        var = None if var is None else np.asarray(var, dtype=float)
        if img.unit == "MJy/sr":
            sb = data * MJY_SR_TO_UJY_ARCSEC2
            var = None if var is None else var * MJY_SR_TO_UJY_ARCSEC2 ** 2
        else:
            area = img.omega_arcsec2 or img.scale_arcsec ** 2
            sb = data / area
        sb = np.where(bad, np.nan, sb)
        if var is not None:
            var = np.where(bad | ~np.isfinite(var) | (var <= 0), np.nan, var)
        return sb, var, bad

    def resampled(self, img: ArchiveImage, ra: float, dec: float, size_px: int,
                  scale_arcsec: float | None = None, *, with_var: bool = True,
                  grid: tuple[WCS, tuple[np.ndarray, np.ndarray]] | None = None
                  ) -> tuple[np.ndarray, np.ndarray | None, WCS]:
        """Image (uJy per output pixel) and variance on a north-up TAN grid centred on (ra, dec).
        Unmeasured pixels are NaN. ``with_var=False`` skips the variance (returned as None);
        ``grid`` = (target_wcs, grid_world) shared by all frames of one stack."""
        scale = scale_arcsec or img.scale_arcsec
        shape = (size_px, size_px)
        if grid is None:
            w = target_wcs(ra, dec, size_px, scale)
            world = None
        else:
            w, world = grid
        area = scale * scale
        sx, sy = source_coords(img.wcs, w, shape, world)
        win = source_window(sx, sy, img.shape)
        if win is None:                       # the grid misses the image entirely
            nan = np.full(shape, np.nan)
            return nan, (nan.copy() if with_var and img.kind == "spherex" and img.hdu_var is not None else None), w
        if img.shape[0] * img.shape[1] <= CACHE_MAX_PIXELS:
            win = (0, img.shape[0], 0, img.shape[1])     # small (cached) file: whole image, bit-identical
        sb, var, _ = self.read(img, win)
        y0, x0 = win[0], win[2]
        out = resample_at(sb, sx, sy, shape, img.shape, x0, y0) * area
        # Variance: resample the per-pixel variance and rescale for the change of pixel area
        # (white noise, nearest-neighbour approximation: var per output px ~ var_sb * area_in * area_out).
        v = None
        if with_var and var is not None:
            area_in = img.omega_arcsec2 or img.scale_arcsec ** 2
            v = resample_at(var, sx, sy, shape, img.shape, x0, y0) * area_in * area
        return out, v, w

    def native_stamp(self, img: ArchiveImage, ra: float, dec: float, half: int) -> tuple[np.ndarray, float, float]:
        """Unresampled (2*half+1)^2 stamp in uJy per native pixel around (ra, dec), NaN where flagged
        or off the frame, and the target position (x, y) inside the stamp. Used for photometry, so
        that the PSF is not broadened by interpolation."""
        area = img.omega_arcsec2 or img.scale_arcsec ** 2
        _, x, y = self._contains(img, ra, dec)
        ix, iy = int(round(x)), int(round(y))
        stamp = np.full((2 * half + 1, 2 * half + 1), np.nan)
        y0, y1 = max(iy - half, 0), min(iy + half + 1, img.shape[0])
        x0, x1 = max(ix - half, 0), min(ix + half + 1, img.shape[1])
        if y1 > y0 and x1 > x0:
            sb, _, _ = self.read(img, (y0, y1, x0, x1))      # only the stamp's pixels
            stamp[y0 - (iy - half):y1 - (iy - half), x0 - (ix - half):x1 - (ix - half)] = sb * area
        return stamp, x - (ix - half), y - (iy - half)

    def cutout(self, img: ArchiveImage, ra: float, dec: float, size_px: int,
               scale_arcsec: float | None = None) -> tuple[np.ndarray, WCS]:
        """Backward-compatible single-image cutout; NaNs filled with the median."""
        out, _, w = self.resampled(img, ra, dec, size_px, scale_arcsec)
        if np.isnan(out).all():
            raise ValueError(f"{img.path.name} does not cover ({ra}, {dec})")
        return np.where(np.isnan(out), np.nanmedian(out), out), w


def coverage_fraction(img: np.ndarray) -> float:
    return float(np.isfinite(img).mean()) if img.size else 0.0


def sky_of(ra: float, dec: float) -> SkyCoord:
    return SkyCoord(ra * u.deg, dec * u.deg)
