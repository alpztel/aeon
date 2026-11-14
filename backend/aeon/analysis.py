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


# --------------------------------------------------------------------------------------------
# Digital tracking (shift-and-stack along an arbitrary predicted track)
# --------------------------------------------------------------------------------------------

class Tracker:
    """Stacks static-sky-subtracted frames along predicted tracks.

    For a hypothesis the caller supplies, per frame, the pixel offset (dx, dy) of the object from
    its reference-epoch position (cx, cy). Each frame is resampled (bilinear) on a co-moving grid
    centred on the predicted position, and the frames are averaged. Straight lines (linear motion)
    and Earth-parallax ellipses are handled identically.

    Noise is calibrated once per frame set from a null stack (random sub-pixel offsets), so S/N
    values of all hypotheses share one scale and small stamps can be scored quickly.
    """

    def __init__(self, residuals: np.ndarray, psf_sigma_px: float, cx: float, cy: float, seed: int = 7):
        self.res = residuals
        self.n = len(residuals)
        self.cx, self.cy = cx, cy
        sig = max(psf_sigma_px, 0.5)
        k = Gaussian2DKernel(x_stddev=sig).array
        self.kernel = k / k.sum()
        self.psf_sigma_px = psf_sigma_px
        rng = np.random.default_rng(seed)
        ny, nx = residuals.shape[1:]
        half = max(min(nx, ny) // 2 - 6, 8)
        null, cov = self.stack(rng.uniform(-3, 3, self.n), rng.uniform(-3, 3, self.n), 2 * half)
        filt = self._filter(null, cov)
        _, _, self.sigma_filt = sigma_clipped_stats(filt[cov >= 0.75], sigma=3.0, maxiters=10)
        self.sigma_filt = max(float(self.sigma_filt), 1e-12)
        single = ndimage.convolve(residuals[0], self.kernel, mode="nearest")
        _, _, self.sigma_single = sigma_clipped_stats(single, sigma=3.0, maxiters=10)

    def stack(self, dx: np.ndarray, dy: np.ndarray, size: int, combine: str = "mean"):
        g = np.arange(size) - (size - 1) / 2.0
        gy, gx = np.meshgrid(g, g, indexing="ij")
        # The offset of a hypothesis is constant over the stamp in each frame, so bilinear
        # resampling reduces to four weighted slices per frame (exact, and far faster than a
        # general interpolator). Stamps that touch the frame edge fall back to map_coordinates.
        ny, nx = self.res.shape[1:]
        g0 = -(size - 1) / 2.0
        fy0 = self.cy + np.asarray(dy, float) + g0
        fx0 = self.cx + np.asarray(dx, float) + g0
        iy = np.floor(fy0).astype(int)
        ix = np.floor(fx0).astype(int)
        ty = (fy0 - iy)[:, None, None]
        tx = (fx0 - ix)[:, None, None]
        inside = (iy >= 0) & (iy + size + 1 <= ny) & (ix >= 0) & (ix + size + 1 <= nx)
        if inside.all():
            off = np.arange(size)
            f = np.arange(self.n)[:, None, None]
            r0 = (iy[:, None] + off)[:, :, None]
            c0 = (ix[:, None] + off)[:, None, :]
            R = self.res
            samples = ((1 - ty) * (1 - tx) * R[f, r0, c0] + (1 - ty) * tx * R[f, r0, c0 + 1]
                       + ty * (1 - tx) * R[f, r0 + 1, c0] + ty * tx * R[f, r0 + 1, c0 + 1])
        else:
            samples = np.empty((self.n, size, size))
            for i in range(self.n):
                coords = [self.cy + dy[i] + gy, self.cx + dx[i] + gx]
                samples[i] = ndimage.map_coordinates(self.res[i], coords, order=1, mode="constant", cval=np.nan)
        valid = np.isfinite(samples)
        coverage = valid.mean(axis=0)
        with np.errstate(all="ignore"):
            if combine == "median":
                st = np.nanmedian(samples, axis=0)
            else:
                st = np.nanmean(samples, axis=0)
        return np.nan_to_num(st), coverage

    def _filter(self, stack: np.ndarray, coverage: np.ndarray) -> np.ndarray:
        return ndimage.convolve(np.where(coverage >= 0.75, stack, 0.0), self.kernel, mode="constant")

    def score(self, dx, dy, size: int, search_radius_px: float, combine: str = "mean"):
        """Peak S/N within `search_radius_px` of the reference position. Returns (snr, iy, ix, stack, cov)."""
        st, cov = self.stack(dx, dy, size, combine)
        snr = self._filter(st, cov) / self.sigma_filt
        c = (size - 1) / 2.0
        yy, xx = np.mgrid[:size, :size]
        mask = (np.hypot(xx - c, yy - c) <= search_radius_px) & (cov >= 0.75)
        masked = np.where(mask, snr, -np.inf)
        iy, ix = np.unravel_index(int(np.argmax(masked)), masked.shape)
        return float(masked[iy, ix]), int(iy), int(ix), st, cov

    def single_frame_snr(self, i: int, x: float, y: float) -> float:
        filt = ndimage.convolve(self.res[i], self.kernel, mode="nearest")
        ny, nx = filt.shape
        if not (0 <= x <= nx - 1 and 0 <= y <= ny - 1):
            return float("nan")
        return float(ndimage.map_coordinates(filt, [[y], [x]], order=1)[0] / max(self.sigma_single, 1e-12))

    def single_frame_stamp(self, i: int, dx: float, dy: float, size: int) -> np.ndarray:
        g = np.arange(size) - (size - 1) / 2.0
        gy, gx = np.meshgrid(g, g, indexing="ij")
        out = ndimage.map_coordinates(self.res[i], [self.cy + dy + gy, self.cx + dx + gx], order=1, mode="constant", cval=0.0)
        return out


def stamp_wcs(w: WCS, cx: float, cy: float, size: int) -> WCS:
    """WCS of a co-moving stamp whose centre is frame pixel (cx, cy) at the reference epoch."""
    sw = w.deepcopy()
    c = (size - 1) / 2.0
    sw.wcs.crpix = [w.wcs.crpix[0] - (cx - c), w.wcs.crpix[1] - (cy - c)]
    return sw


def run_tracked(tracker: Tracker, w: WCS, times: np.ndarray, t_ref: float, dx: np.ndarray, dy: np.ndarray,
                size: int, search_radius_px: float = 6.0, combine: str = "mean") -> dict:
    """Full-size stack for one hypothesis plus single-frame comparison."""
    snr, iy, ix, st, cov = tracker.score(dx, dy, size, search_radius_px, combine)
    x, y, flux = refine_centroid(st, iy, ix)
    sw = stamp_wcs(w, tracker.cx, tracker.cy, size)
    i_ref = int(np.argmin(np.abs(times - t_ref)))
    c = (size - 1) / 2.0
    # Peak offset from the stamp centre maps to the same offset in every frame along the track.
    fx = tracker.cx + dx[i_ref] + (x - c)
    fy = tracker.cy + dy[i_ref] + (y - c)
    single = tracker.single_frame_snr(i_ref, fx, fy)
    return {
        "stacked": st, "coverage": cov, "single_frame": tracker.single_frame_stamp(i_ref, dx[i_ref], dy[i_ref], size),
        "snr_stacked": snr, "snr_single_frame": single,
        "snr_gain": snr / single if single and single > 0 and math.isfinite(single) else None,
        "peak": to_detection(x, y, sw, flux, snr), "t_ref": t_ref, "wcs": sw,
    }
