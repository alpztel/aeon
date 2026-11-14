"""Image analysis: difference imaging, shift-and-stack, and blind velocity-grid search.

Conventions: images are (ny, nx) with x increasing to the WEST (CDELT1 < 0, east left) and y
increasing to the NORTH. Position angle is measured from north through east.
"""

from __future__ import annotations

import math

import numpy as np
from astropy.convolution import Gaussian2DKernel, convolve_fft
from astropy.stats import sigma_clipped_stats
from astropy.wcs import WCS
from photutils.segmentation import SourceCatalog, detect_sources
from scipy import ndimage

from .photometry import background_subtract


# --------------------------------------------------------------------------------------------
# Matched filtering / S/N maps
# --------------------------------------------------------------------------------------------

def snr_map(img: np.ndarray, psf_sigma_px: float, weight: np.ndarray | None = None) -> np.ndarray:
    """PSF-matched-filter S/N map. The filtered image is normalised by its own robust scatter,
    so the value at a point source equals its optimal-photometry S/N for white noise."""
    kernel = Gaussian2DKernel(x_stddev=max(psf_sigma_px, 0.5))
    k = kernel.array / kernel.array.sum()
    filt = convolve_fft(img, k, normalize_kernel=False, boundary="fill", fill_value=0.0)
    if weight is not None:
        filt = np.where(weight > 0.5, filt, 0.0)
        vals = filt[weight > 0.5]
    else:
        vals = filt
    _, med, std = sigma_clipped_stats(vals, sigma=3.0, maxiters=10)
    return (filt - med) / max(std, 1e-12)


def _offset_px(rate_arcsec_yr: float, pa_deg: float, dt_yr: np.ndarray, scale_arcsec: float):
    """Pixel displacement (dx, dy) of an object moving at rate/PA after dt years."""
    pa = math.radians(pa_deg)
    d_east = rate_arcsec_yr * math.sin(pa) * dt_yr
    d_north = rate_arcsec_yr * math.cos(pa) * dt_yr
    return -d_east / scale_arcsec, d_north / scale_arcsec


def to_detection(x: float, y: float, w: WCS, flux: float, snr: float, sign: str = "positive") -> dict:
    ra, dec = w.all_pix2world([[x, y]], 0)[0]
    return {"x": round(float(x), 3), "y": round(float(y), 3), "ra": round(float(ra) % 360, 7),
            "dec": round(float(dec), 7), "flux_ujy": round(float(flux), 4), "snr": round(float(snr), 3),
            "sign": sign}


# --------------------------------------------------------------------------------------------
# Difference imaging
# --------------------------------------------------------------------------------------------

def difference(img1: np.ndarray, img2: np.ndarray, w: WCS, psf_sigma_px: float,
               threshold_sigma: float = 5.0) -> dict:
    """I(t2) - I(t1) after independent background subtraction (same PSF, same WCS grid).
    Detections: segmentation of the matched-filter S/N map of the difference, both signs."""
    a, _, _ = background_subtract(img1)
    b, _, _ = background_subtract(img2)
    diff = b - a
    _, _, noise = sigma_clipped_stats(diff, sigma=3.0, maxiters=10)
    snr = snr_map(diff, psf_sigma_px)
    detections = []
    for sign, s in (("positive", snr), ("negative", -snr)):
        seg = detect_sources(s, threshold_sigma, n_pixels=2)
        if seg is None:
            continue
        cat = SourceCatalog(diff if sign == "positive" else -diff, seg)
        for src in cat:
            ys, xs = np.nonzero(seg.data == src.label)
            peak = float(s[ys, xs].max())
            detections.append(to_detection(src.x_centroid, src.y_centroid, w,
                                           float(src.segment_flux) * (1 if sign == "positive" else -1), peak, sign))
    detections.sort(key=lambda d: -d["snr"])
    return {"difference": diff, "background_subtracted": (a, b), "noise_sigma": float(noise), "detections": detections}


# --------------------------------------------------------------------------------------------
# Shift-and-stack
# --------------------------------------------------------------------------------------------

def remove_static_sky(frames: np.ndarray) -> np.ndarray:
    """Subtract each frame's background and the per-pixel median over all frames (static template).
    A source moving more than a few PSF widths across the sequence survives; fixed stars cancel."""
    bs = np.stack([background_subtract(f)[0] for f in frames])
    template = np.median(bs, axis=0)
    return bs - template


def shift_stack(residuals: np.ndarray, times: np.ndarray, rate_arcsec_yr: float, pa_deg: float,
                scale_arcsec: float, combine: str = "mean", t_ref: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Shift each frame back along the trial motion (sub-pixel, bilinear) and combine.
    Returns (stack, coverage) where coverage is the fraction of frames contributing per pixel."""
    t_ref = float(np.mean(times)) if t_ref is None else t_ref
    dx, dy = _offset_px(rate_arcsec_yr, pa_deg, times - t_ref, scale_arcsec)
    shifted = np.empty_like(residuals)
    cover = np.empty_like(residuals)
    ones = np.ones(residuals.shape[1:])
    for i in range(len(residuals)):
        shifted[i] = ndimage.shift(residuals[i], (-dy[i], -dx[i]), order=1, mode="constant", cval=0.0)
        cover[i] = ndimage.shift(ones, (-dy[i], -dx[i]), order=1, mode="constant", cval=0.0)
    coverage = cover.sum(axis=0)
    if combine == "median":
        masked = np.where(cover > 0.5, shifted, np.nan)
        with np.errstate(all="ignore"):
            stack = np.nan_to_num(np.nanmedian(masked, axis=0))
    else:
        stack = np.where(coverage > 0, shifted.sum(axis=0) / np.maximum(coverage, 1e-9), 0.0)
    return stack, coverage / len(residuals)


def stack_peak(stack: np.ndarray, coverage: np.ndarray, psf_sigma_px: float,
               search_radius_px: float | None = None) -> tuple[float, tuple[int, int], np.ndarray]:
    """Peak matched-filter S/N within well-covered pixels (optionally near the image centre)."""
    good = coverage >= 0.75
    snr = snr_map(stack, psf_sigma_px, weight=good.astype(float))
    mask = good.copy()
    if search_radius_px is not None:
        ny, nx = stack.shape
        yy, xx = np.mgrid[:ny, :nx]
        mask &= np.hypot(xx - (nx - 1) / 2, yy - (ny - 1) / 2) <= search_radius_px
    masked = np.where(mask, snr, -np.inf)
    iy, ix = np.unravel_index(int(np.argmax(masked)), masked.shape)
    return float(masked[iy, ix]), (int(iy), int(ix)), snr


def refine_centroid(img: np.ndarray, iy: int, ix: int, half: int = 2) -> tuple[float, float, float]:
    """Flux-weighted centroid and summed flux in a (2*half+1)^2 box around the peak."""
    ny, nx = img.shape
    y0, y1 = max(iy - half, 0), min(iy + half + 1, ny)
    x0, x1 = max(ix - half, 0), min(ix + half + 1, nx)
    box = np.clip(img[y0:y1, x0:x1], 0, None)
    tot = box.sum()
    if tot <= 0:
        return float(ix), float(iy), float(img[y0:y1, x0:x1].sum())
    yy, xx = np.mgrid[y0:y1, x0:x1]
    return float((xx * box).sum() / tot), float((yy * box).sum() / tot), float(img[y0:y1, x0:x1].sum())


def run_shift_stack(frames: np.ndarray, times: np.ndarray, w: WCS, psf_sigma_px: float, scale_arcsec: float,
                    rate: float, pa: float, combine: str = "mean", residuals: np.ndarray | None = None) -> dict:
    res = remove_static_sky(frames) if residuals is None else residuals
    t_ref = float(np.mean(times))
    stack, cov = shift_stack(res, times, rate, pa, scale_arcsec, combine, t_ref)
    peak_snr, (iy, ix), _ = stack_peak(stack, cov, psf_sigma_px)
    x, y, flux = refine_centroid(stack, iy, ix)
    # Single-frame S/N at the motion-corrected sub-pixel location in the frame nearest t_ref
    # (bilinear interpolation of the S/N map: unbiased, no peak-picking).
    i_ref = int(np.argmin(np.abs(times - t_ref)))
    dx, dy = _offset_px(rate, pa, np.array([times[i_ref] - t_ref]), scale_arcsec)
    single_snr_map = snr_map(res[i_ref], psf_sigma_px)
    ny, nx = stack.shape
    sx, sy = x + dx[0], y + dy[0]
    if 0 <= sx <= nx - 1 and 0 <= sy <= ny - 1:
        single = float(ndimage.map_coordinates(single_snr_map, [[sy], [sx]], order=1)[0])
    else:
        single = float("nan")
    return {
        "stacked": stack, "single_frame": res[i_ref], "coverage": cov,
        "snr_stacked": peak_snr, "snr_single_frame": single,
        "snr_gain": peak_snr / single if single and single > 0 and math.isfinite(single) else None,
        "peak": to_detection(x, y, w, flux, peak_snr), "t_ref": t_ref,
        "rate_arcsec_yr": rate, "pa_deg": pa,
    }


def blind_search(frames: np.ndarray, times: np.ndarray, w: WCS, psf_sigma_px: float, scale_arcsec: float,
                 rate_range: tuple[float, float], pa_range: tuple[float, float], grid: int = 5,
                 combine: str = "mean", refine: bool = True) -> dict:
    """Coarse grid x grid search over (rate, PA) maximising stacked S/N, followed by a finer
    grid x grid search centred on the coarse optimum (half the coarse spacing)."""
    res = remove_static_sky(frames)
    rates = np.linspace(rate_range[0], rate_range[1], grid)
    pas = np.linspace(pa_range[0], pa_range[1], grid)
    t_ref = float(np.mean(times))

    def score(r: float, p: float) -> float:
        st, cv = shift_stack(res, times, r, p, scale_arcsec, combine, t_ref)
        return stack_peak(st, cv, psf_sigma_px)[0]

    coarse = np.array([[score(r, p) for p in pas] for r in rates])
    ir, ip = np.unravel_index(int(np.argmax(coarse)), coarse.shape)
    best_r, best_p = float(rates[ir]), float(pas[ip])
    fine_grid = None
    if refine and grid > 1:
        dr = (rates[1] - rates[0]) / 2 if grid > 1 else 0
        dp = (pas[1] - pas[0]) / 2 if grid > 1 else 0
        f_rates = np.linspace(best_r - dr, best_r + dr, grid)
        f_pas = np.linspace(best_p - dp, best_p + dp, grid)
        fine = np.array([[score(r, p) for p in f_pas] for r in f_rates])
        jr, jp = np.unravel_index(int(np.argmax(fine)), fine.shape)
        if fine[jr, jp] > coarse[ir, ip]:
            best_r, best_p = float(f_rates[jr]), float(f_pas[jp])
        fine_grid = {"rates_arcsec_yr": f_rates.tolist(), "pas_deg": f_pas.tolist(), "grid": fine.round(3).tolist()}
    best = run_shift_stack(frames, times, w, psf_sigma_px, scale_arcsec, best_r, best_p, combine, residuals=res)
    return {"rates": rates.tolist(), "pas": pas.tolist(), "grid": coarse.round(3).tolist(),
            "refined": fine_grid, "best": best}
