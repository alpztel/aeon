"""Forced aperture photometry on 102-band spectral cubes (photutils) and absorption-band metrics."""

from __future__ import annotations

import math

import numpy as np
from astropy.stats import sigma_clipped_stats
from astropy.wcs import WCS
from photutils.aperture import CircularAnnulus, CircularAperture, aperture_photometry

from . import bands, spectra


def background_subtract(img: np.ndarray, sigma: float = 3.0) -> tuple[np.ndarray, float, float]:
    """Subtract a sigma-clipped median background. Returns (image, background, robust std).
    Large images are sampled on a 2x2 stride for the statistics (same estimate, ~4x faster)."""
    sample = img[::2, ::2] if img.size > 16384 else img
    _, median, std = sigma_clipped_stats(sample, sigma=sigma, maxiters=10)
    return img - median, float(median), float(std)


def extract_spectrum(cube: np.ndarray, w: WCS, ra: float, dec: float, aperture_arcsec: float,
                     psf_sigma_px: np.ndarray) -> dict:
    """Forced photometry at (ra, dec) in every band.

    * circular aperture of radius aperture_arcsec (photutils), local background from an annulus
      (sigma-clipped median);
    * analytic aperture correction for the Gaussian PSF of each band;
    * uncertainty from annulus pixel scatter including the background-estimate term.
    """
    scale = abs(w.wcs.cdelt[1]) * 3600.0
    x, y = w.all_world2pix([[ra, dec]], 0)[0]
    r = max(aperture_arcsec / scale, 0.75)
    r_in, r_out = max(3.0 * r, r + 2.0), max(5.0 * r, r + 5.0)
    aper = CircularAperture((x, y), r=r)
    ann = CircularAnnulus((x, y), r_in=r_in, r_out=r_out)
    area = aper.area
    ann_mask = ann.to_mask(method="center")
    flux = np.empty(cube.shape[0])
    err = np.empty(cube.shape[0])
    for b in range(cube.shape[0]):
        img = cube[b]
        ann_vals = ann_mask.get_values(img)
        _, bkg, bstd = sigma_clipped_stats(ann_vals, sigma=3.0)
        raw = float(aperture_photometry(img, aper)["aperture_sum"][0])
        n_ann = max(float(ann_vals.size), 1.0)
        s = psf_sigma_px[b]
        ee = 1.0 - math.exp(-r * r / (2 * s * s))          # encircled energy of a Gaussian PSF
        flux[b] = (raw - bkg * area) / ee
        err[b] = bstd * math.sqrt(area * (1.0 + area / n_ann)) / ee
    return {
        "flux": flux, "err": err,
        "pixel": (float(x), float(y)),
        "aperture_px": r, "annulus_px": (r_in, r_out),
    }


def forced_point(img: np.ndarray, x: float, y: float, aperture_px: float, psf_sigma_px: float) -> dict:
    """Forced photometry of one image at pixel (x, y): same estimator as extract_spectrum (aperture,
    sigma-clipped annulus background, Gaussian aperture correction), NaN-aware. Returns NaN flux if
    any pixel inside the aperture is NaN."""
    r = max(aperture_px, 0.75)
    r_in, r_out = max(3.0 * r, r + 2.0), max(5.0 * r, r + 5.0)
    aper = CircularAperture((x, y), r=r)
    ann = CircularAnnulus((x, y), r_in=r_in, r_out=r_out)
    ap_vals = aper.to_mask(method="center").get_values(img)
    ann_vals = ann.to_mask(method="center").get_values(img)
    ann_vals = ann_vals[np.isfinite(ann_vals)]
    if ap_vals.size == 0 or not np.isfinite(ap_vals).all() or ann_vals.size < 8:
        return {"flux": float("nan"), "err": float("nan"), "aperture_px": r, "annulus_px": (r_in, r_out)}
    _, bkg, bstd = sigma_clipped_stats(ann_vals, sigma=3.0)
    raw = float(aperture_photometry(img, aper)["aperture_sum"][0])
    area = aper.area
    ee = 1.0 - math.exp(-r * r / (2 * psf_sigma_px * psf_sigma_px))
    return {"flux": (raw - bkg * area) / ee, "err": float(bstd) * math.sqrt(area * (1.0 + area / ann_vals.size)) / ee,
            "aperture_px": r, "annulus_px": (r_in, r_out)}


def absorption_features(flux: np.ndarray, err: np.ndarray, lam: np.ndarray | None = None) -> list[dict]:
    """Band depth of each molecular feature relative to a log-linear continuum interpolated from
    flanking bands (2.5-4 sigma of the feature width away). Detected if depth > 3 sigma and > 5%.
    ``lam`` defaults to the 102 AEON band centres; real spectra pass their own (gappy) grid."""
    lam = bands.WAVELENGTH_UM if lam is None else np.asarray(lam, dtype=float)
    out = []
    pos = np.clip(flux, 1e-6, None)
    for f in spectra.FEATURES:
        core = np.abs(lam - f.center_um) <= f.sigma_um
        left = (lam < f.center_um - 2.5 * f.sigma_um) & (lam > f.center_um - 4.5 * f.sigma_um)
        right = (lam > f.center_um + 2.5 * f.sigma_um) & (lam < f.center_um + 4.5 * f.sigma_um)
        if not core.any() or not (left.any() or right.any()):
            continue
        anchors = np.flatnonzero(left | right)
        if left.any() and right.any():
            coef = np.polyfit(lam[anchors], np.log(pos[anchors]), 1)
            cont = np.exp(np.polyval(coef, lam[core]))
        else:
            cont = np.full(core.sum(), np.median(pos[anchors]))
        c = float(np.mean(cont))
        obs = float(np.mean(flux[core]))
        obs_err = float(np.sqrt(np.sum(err[core] ** 2)) / core.sum())
        cont_err = float(np.sqrt(np.sum(err[anchors] ** 2)) / len(anchors))
        depth = 1.0 - obs / c if c > 0 else 0.0
        depth_err = math.hypot(obs_err, cont_err) / c if c > 0 else 1.0
        out.append({
            "molecule": f.molecule, "center_um": f.center_um,
            "depth": round(float(np.clip(depth, -1.0, 1.0)), 4),
            "detected": bool(depth > 0.05 and depth > 3.0 * depth_err and c > 3.0 * cont_err),
        })
    return out
