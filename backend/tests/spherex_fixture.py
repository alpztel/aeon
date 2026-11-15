"""Small synthetic files with the structure of SPHEREx Level 2 spectral images (IRSA DR1).

Header keywords, extension names/order, units, FLAGS bit definitions and the WCS-WAVE (-TAB)
layout are copied from a real DR1 cutout (see backend/docs/spherex-l2-notes.md). Pixel values
are synthetic: these files exist only for offline tests and are never shipped as data.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.time import Time

from aeon.archive import SPHEREX_FLAG_BITS

SCALE = 6.15                 # arcsec / pixel
OMEGA = 37.86                # arcsec^2, OMEGA_MEDIAN of the real file
MJYSR_PER_UJY_PX = 1.0 / (1e12 / (180 / math.pi * 3600) ** 2 * OMEGA)   # MJy/sr per uJy/pixel


def make_spherex_file(path: Path, ra: float, dec: float, *, n: int = 48, date: str = "2025-05-05T16:49:00",
                      detector: int = 3, wave_um: float = 2.3647, wave_slope_um_per_px: float = -0.0005,
                      bandwidth_um: float = 0.0586, rot_deg: float = 162.5, background_mjysr: float = 0.15,
                      source: tuple[float, float, float] | None = None, psf_fwhm_arcsec: float = 7.45,
                      extra_sources: list[tuple[float, float, float]] | None = None,
                      flags: dict[tuple[int, int], int] | None = None, noise_mjysr: float = 0.0,
                      seed: int = 0, extra_hdus: bool = True) -> Path:
    """Write a SPHEREx-like MEF.

    The image is a rotated TAN projection centred on (ra, dec). The wavelength at pixel (x, y)
    (0-based) is ``wave_um + wave_slope_um_per_px * (x - cx)`` in the WCS-WAVE table, mimicking the
    LVF gradient. ``source`` = (ra, dec, flux_uJy) adds a Gaussian point source.
    """
    rng = np.random.default_rng(seed)
    cx = cy = (n - 1) / 2.0
    th = math.radians(rot_deg)
    s = SCALE / 3600.0
    # Same handedness as the real file (det(PC) < 0: parity of the sky seen from inside).
    pc = np.array([[-s * math.cos(th), s * math.sin(th)], [s * math.sin(th), s * math.cos(th)]])

    img = np.full((n, n), background_mjysr, dtype=np.float64)
    for src in [s for s in [source, *(extra_sources or [])] if s is not None]:
        from astropy.wcs import WCS

        w = WCS(naxis=2)
        w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        w.wcs.crval = [ra, dec]
        w.wcs.crpix = [cx + 1, cy + 1]
        w.wcs.pc = pc
        w.wcs.cdelt = [1.0, 1.0]
        sx, sy = w.all_world2pix([[src[0], src[1]]], 0)[0]
        sig = psf_fwhm_arcsec / 2.3548 / SCALE
        yy, xx = np.mgrid[0:n, 0:n]
        g = np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * sig * sig)) / (2 * math.pi * sig * sig)
        img += src[2] * g * MJYSR_PER_UJY_PX
    if noise_mjysr:
        img += rng.normal(0.0, noise_mjysr, img.shape)

    t = Time(date)
    raw_x0, raw_y0 = 700, 900          # cutout origin in raw detector pixels (as IRSA cutouts do)
    h = fits.Header()
    h["BUNIT"] = ("MJy / sr", "Unit of pixel value")
    h["DETECTOR"] = (detector, "1-3: SWIR, 4-6: MWIR")
    h["OBSID"] = (f"2025W19_1B_{seed:04d}_1", "Observation ID")
    h["PSF_FWHM"] = (psf_fwhm_arcsec, "[arcsec] PSF FWHM Median")
    h["HIERARCH OMEGA_MEDIAN"] = (OMEGA, "[arcsec**2] solid angle pixel map median")
    h["RADESYS"] = "ICRS"
    h["WCSAXES"] = 2
    h["CRPIX1"], h["CRPIX2"] = cx + 1, cy + 1
    h["PC1_1"], h["PC1_2"], h["PC2_1"], h["PC2_2"] = pc[0, 0], pc[0, 1], pc[1, 0], pc[1, 1]
    h["CDELT1"], h["CDELT2"] = 1.0, 1.0
    h["CUNIT1"], h["CUNIT2"] = "deg", "deg"
    h["CTYPE1"], h["CTYPE2"] = "RA---TAN", "DEC--TAN"
    h["CRVAL1"], h["CRVAL2"] = ra, dec
    h["TIMESYS"] = "UTC"
    h["DATE-OBS"] = (t.isot, "ISO-8601 time of observation")
    h["MJD-OBS"] = (t.mjd, "[d] MJD of observation")
    h["DATE-AVG"] = (t.isot, "ISO-8601 time at midpoint of observation")
    h["MJD-AVG"] = (t.mjd, "[d] MJD at midpoint of observation")
    h["XPOSURE"] = (113.5826, "[s] Exposure (integration) time")
    h["WCSAXESW"] = 2
    h["WCSNAMEW"] = "Approximated per-pixel wavelength and bandwidth"
    h["CNAME1W"], h["CNAME2W"] = "Wavelength", "Bandwidth"
    h["CRPIX1W"], h["CRPIX2W"] = -float(raw_x0 - 1), -float(raw_y0 - 1)
    h["CDELT1W"], h["CDELT2W"] = 1, 1
    h["CUNIT1W"], h["CUNIT2W"] = "um", "um"
    h["CTYPE1W"], h["CTYPE2W"] = "WAVE-TAB", "WAVE-TAB"
    h["CRVAL1W"], h["CRVAL2W"] = 1, 1
    h["PV1_3W"], h["PV2_3W"] = 1, 2
    h["PS1_0W"], h["PS2_0W"] = "WCS-WAVE", "WCS-WAVE"
    h["PS1_1W"], h["PS2_1W"] = "VALUES", "VALUES"
    h["PS1_2W"], h["PS2_2W"] = "X", "Y"

    # Lookup table in raw detector coordinates: psi = p - CRPIX + CRVAL = p + raw_x0 (1-based p).
    xs = np.array([1, 256, 511, 766, 1021, 1275, 1530, 1785, 2040], dtype=np.int32)
    ys = np.array([1, 36, 71, 105, 140, 141, 379, 617, 855, 1091, 1326, 1564, 1802, 2040], dtype=np.int32)
    # pixel x0 (0-based) of this cutout <-> psi = x0 + 1 + raw_x0
    x0_of_psi = xs - 1 - raw_x0
    lam_x = wave_um + wave_slope_um_per_px * (x0_of_psi - cx)
    vals = np.zeros((ys.size, xs.size, 2), dtype=np.float32)
    vals[:, :, 0] = lam_x[None, :]
    vals[:, :, 1] = bandwidth_um
    cols = [fits.Column(name="X", format=f"{xs.size}J", dim=f"({xs.size})", array=xs[None]),
            fits.Column(name="Y", format=f"{ys.size}J", dim=f"({ys.size})", array=ys[None]),
            fits.Column(name="VALUES", format=f"{vals.size}E", dim=f"(2,{xs.size},{ys.size})", array=vals[None])]
    wave = fits.BinTableHDU.from_columns(cols, name="WCS-WAVE")

    fl = np.zeros((n, n), dtype=np.int32)
    for (yx, bits) in (flags or {}).items():
        fl[yx] = bits
    fh = fits.Header()
    fh["BUNIT"] = ""
    fh["EXTTYPE"] = "MASK"
    for name, bit in SPHEREX_FLAG_BITS.items():
        fh[f"MSKN{bit:04d}"] = name
        fh[f"MSKM{bit:04d}"] = 1 << bit
    var = np.full((n, n), (0.01 + noise_mjysr) ** 2, dtype=np.float32)
    vh = fits.Header()
    vh["BUNIT"] = "MJy2 / sr2"
    zh = fits.Header()
    zh["BUNIT"] = "MJy / sr"

    hdus = [fits.PrimaryHDU(header=fits.Header([("VERSION", "7.0.5", "SSDC Pipelines software version")])),
            fits.ImageHDU(img.astype(np.float32), h, name="IMAGE"),
            fits.ImageHDU(fl, fh, name="FLAGS"),
            fits.ImageHDU(var, vh, name="VARIANCE"),
            fits.ImageHDU(np.full((n, n), background_mjysr * 0.9, dtype=np.float32), zh, name="ZODI")]
    if extra_hdus:
        epsf = fits.BinTableHDU.from_columns([fits.Column(name="XCENTER", format="J", array=np.array([1020]))], name="EPSF")
        hdus.append(epsf)
    hdus.append(wave)
    fits.HDUList(hdus).writeto(path, overwrite=True)
    return path


def flag(name: str) -> int:
    return 1 << SPHEREX_FLAG_BITS[name]
