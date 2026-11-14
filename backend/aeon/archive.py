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
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
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
    _wave_cache: dict = field(default_factory=dict, repr=False)

    @property
    def date_obs(self) -> str | None:
        return None if self.mjd is None else Time(self.mjd, format="mjd").isot[:19]

    @property
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
    px, py = x0 + 1.0, y0 + 1.0
    psi_x = float(header.get("CDELT1W", 1.0)) * (px - float(header["CRPIX1W"])) + float(header.get("CRVAL1W", 1.0))
    psi_y = float(header.get("CDELT2W", 1.0)) * (py - float(header["CRPIX2W"])) + float(header.get("CRVAL2W", 1.0))
    xs = np.asarray(table["X"][0], dtype=float)
    ys = np.asarray(table["Y"][0], dtype=float)
    vals = np.asarray(table["VALUES"][0], dtype=float)        # numpy shape (ny, nx, 2) for TDIM (2,nx,ny)
    if vals.shape[:2] != (ys.size, xs.size):
        vals = vals.reshape(ys.size, xs.size, 2)
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
    ny, nx = shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    ra, dec = dst_wcs.all_pix2world(xx.ravel(), yy.ravel(), 0)
    with _quiet():
        sx, sy = src_wcs.all_world2pix(ra, dec, 0, quiet=True)
    good = np.isfinite(data)
    filled = np.where(good, data, 0.0)
    coords = np.vstack([sy, sx])
    val = ndimage.map_coordinates(filled, coords, order=1, mode="constant", cval=0.0)
    wgt = ndimage.map_coordinates(good.astype(float), coords, order=1, mode="constant", cval=0.0)
    inside = (sx >= -0.5) & (sx <= data.shape[1] - 0.5) & (sy >= -0.5) & (sy <= data.shape[0] - 0.5)
    out = np.where((wgt > 0.75) & inside, val / np.maximum(wgt, 1e-12), np.nan)
    return out.reshape(ny, nx)


# --------------------------------------------------------------------------------------------
# Archive
# --------------------------------------------------------------------------------------------

class FitsArchive:
    def __init__(self, root: str | os.PathLike | None) -> None:
        self.root = Path(root) if root else None
        self.images: list[ArchiveImage] = []
        if self.root and self.root.is_dir():
            self.scan()

    # ---------------------------------------------------------------- indexing
    def scan(self) -> None:
        self.images.clear()
        paths = sorted(self.root.glob("**/*.fits")) + sorted(self.root.glob("**/*.fits.gz"))
        for p in paths:
            try:
                img = self._index(p)
            except (OSError, StopIteration, ValueError, KeyError, TypeError):
                img = None
            if img is not None:
                self.images.append(img)

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
                return ArchiveImage(
                    path=p, epoch=epoch, wcs=w, shape=tuple(hdul["IMAGE"].data.shape), scale_arcsec=scale,
                    kind="spherex", hdu=hdul.index_of("IMAGE"), mjd=None if t is None else float(t.mjd),
                    detector=h.get("DETECTOR"), obs_id=h.get("OBSID"), unit=flux_unit_factor(h.get("BUNIT", "")),
                    psf_fwhm_arcsec=float(h["PSF_FWHM"]) if "PSF_FWHM" in h else None,
                    omega_arcsec2=float(omega) if omega else None,
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
        key = (round(ra, 5), round(dec, 5))
        if key not in img._wave_cache:
            _, x, y = self._contains(img, ra, dec)
            with _quiet(), fits.open(img.path, memmap=False) as hdul:
                img._wave_cache[key] = spherex_wavelength(hdul, x, y)
        return img._wave_cache[key]

    def frames(self, ra: float, dec: float, epoch: str, band: int | None = None,
               allowed_bands: set[int] | None = None) -> list[Frame]:
        """Archive frames covering (ra, dec) in an epoch.

        If the epoch holds frames from more than one visit (e.g. 2025 and 2026 data folded onto the
        same quarter), only the visit closest to the nominal AEON epoch is kept. ``band`` keeps
        SPHEREx frames whose wavelength at (ra, dec) falls in that AEON band; ``allowed_bands``
        restricts to a set of bands (used to match two epochs for differencing).
        """
        hits: list[Frame] = []
        for img in self.images:
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
    def read(self, img: ArchiveImage) -> tuple[np.ndarray, np.ndarray | None, np.ndarray]:
        """(surface brightness in uJy/arcsec^2, variance in (uJy/arcsec^2)^2 or None, bad-pixel mask).

        SPHEREx: IMAGE [MJy/sr] with FLAGS-rejected pixels set to NaN. Generic uJy/pixel images are
        divided by the pixel solid angle so that every image is resampled as surface brightness.
        """
        with _quiet(), fits.open(img.path, memmap=False) as hdul:
            if img.kind == "spherex":
                data = np.asarray(hdul["IMAGE"].data, dtype=float)
                bad = bad_pixel_mask(hdul["FLAGS"].data) | ~np.isfinite(data)
                var = np.asarray(hdul["VARIANCE"].data, dtype=float) if "VARIANCE" in hdul else None
            else:
                data = np.asarray(hdul[img.hdu].data, dtype=float)
                bad = ~np.isfinite(data)
                var = None
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
                  scale_arcsec: float | None = None) -> tuple[np.ndarray, np.ndarray | None, WCS]:
        """Image (uJy per output pixel) and variance on a north-up TAN grid centred on (ra, dec).
        Unmeasured pixels are NaN."""
        scale = scale_arcsec or img.scale_arcsec
        w = target_wcs(ra, dec, size_px, scale)
        sb, var, _ = self.read(img)
        area = scale * scale
        out = resample(sb, img.wcs, w, (size_px, size_px)) * area
        # Variance: resample the per-pixel variance and rescale for the change of pixel area
        # (white noise, nearest-neighbour approximation: var per output px ~ var_sb * area_in * area_out).
        v = None
        if var is not None:
            area_in = img.omega_arcsec2 or img.scale_arcsec ** 2
            v = resample(var, img.wcs, w, (size_px, size_px)) * area_in * area
        return out, v, w

    def native_stamp(self, img: ArchiveImage, ra: float, dec: float, half: int) -> tuple[np.ndarray, float, float]:
        """Unresampled (2*half+1)^2 stamp in uJy per native pixel around (ra, dec), NaN where flagged
        or off the frame, and the target position (x, y) inside the stamp. Used for photometry, so
        that the PSF is not broadened by interpolation."""
        sb, _, _ = self.read(img)
        area = img.omega_arcsec2 or img.scale_arcsec ** 2
        _, x, y = self._contains(img, ra, dec)
        ix, iy = int(round(x)), int(round(y))
        stamp = np.full((2 * half + 1, 2 * half + 1), np.nan)
        y0, y1 = max(iy - half, 0), min(iy + half + 1, sb.shape[0])
        x0, x1 = max(ix - half, 0), min(ix + half + 1, sb.shape[1])
        if y1 > y0 and x1 > x0:
            stamp[y0 - (iy - half):y1 - (iy - half), x0 - (ix - half):x1 - (ix - half)] = sb[y0:y1, x0:x1] * area
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
