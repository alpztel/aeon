"""Cross-modal spectrum-image alignment (AstroCLIP-like) & ZOGY optimal PSF/dipole significance.

Inspired by:
- `PolymathicAI/AstroCLIP` (Cross-modal joint embedding of astronomical spectra & sky cutouts)
- Zackay, Ofek & Gal-Yam 2016 (ZOGY Fourier/spatial matched-filter proper-motion dipole & S_corr statistics)
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .models import preprocess_flux

# Separable 5x5 Gaussian PSF kernel (sigma = 1.15 px, normalized to sum=1, L2 norm precomputed)
_PSF_1D = np.array([0.06136, 0.24477, 0.38774, 0.24477, 0.06136], dtype=np.float64)
_PSF_2D = np.outer(_PSF_1D, _PSF_1D)
_PSF_L2 = float(np.sqrt(np.sum(_PSF_2D**2)))


def _convolve2d_psf5(img: np.ndarray) -> np.ndarray:
    """Fast vectorized separable 5x5 Gaussian PSF convolution with reflection padding."""
    pad = np.pad(img, 2, mode="edge")
    # Horizontal pass
    h = (
        _PSF_1D[0] * pad[:, 0:-4]
        + _PSF_1D[1] * pad[:, 1:-3]
        + _PSF_1D[2] * pad[:, 2:-2]
        + _PSF_1D[3] * pad[:, 3:-1]
        + _PSF_1D[4] * pad[:, 4:]
    )
    # Vertical pass
    out = (
        _PSF_1D[0] * h[0:-4, :]
        + _PSF_1D[1] * h[1:-3, :]
        + _PSF_1D[2] * h[2:-2, :]
        + _PSF_1D[3] * h[3:-1, :]
        + _PSF_1D[4] * h[4:, :]
    )
    return out


def compute_zogy_metrics(image_dict: dict[str, Any] | None) -> dict[str, Any]:
    """Compute ZOGY S_corr matched-filter point-source significance & proper-motion dipole score."""
    if not image_dict or "data" not in image_dict:
        return {
            "zogy_peak_snr": 0.0,
            "dipole_polarity_score": 0.0,
            "cosmic_ray_veto": False,
            "is_moving_dipole": False,
        }

    w = int(image_dict.get("width", 64))
    h = int(image_dict.get("height", 64))
    raw = np.asarray(image_dict["data"], dtype=np.float64)
    if raw.size != w * h or w < 5 or h < 5:
        raise ValueError(f"Invalid image shape ({w}x{h}) for data length {raw.size}")
    if not np.all(np.isfinite(raw)):
        raise ValueError("Image data contains non-finite values (NaN or Inf)")

    # Pre-scale by max absolute value to prevent overflow at 1e300 or underflow at 1e-300
    max_abs = float(np.max(np.abs(raw)))
    if max_abs <= 0.0 or not math.isfinite(max_abs):
        return {
            "zogy_peak_snr": 0.0,
            "dipole_polarity_score": 0.0,
            "cosmic_ray_veto": False,
            "is_moving_dipole": False,
        }

    img = (raw / max_abs).reshape(h, w)
    med = float(np.median(img))
    centered = img - med
    mad = float(np.median(np.abs(centered)))
    sigma_sky = 1.4826 * mad
    std_sky = float(np.std(centered))

    if max(sigma_sky, std_sky) < 1e-12:
        return {
            "zogy_peak_snr": 0.0,
            "dipole_polarity_score": 0.0,
            "cosmic_ray_veto": False,
            "is_moving_dipole": False,
        }

    noise_unit = sigma_sky if sigma_sky > 1e-9 else std_sky
    norm_img = centered / noise_unit

    # Check single-pixel cosmic ray OR 1D row/column readout bleed veto at peak position:
    # A real 2D optical/IR PSF spreads energy along BOTH X and Y axes around the peak.
    peak_idx = int(np.argmax(norm_img))
    py, px = divmod(peak_idx, w)
    peak_raw_snr = float(norm_img[py, px])
    y0, y1 = max(0, py - 1), min(h, py + 2)
    x0, x1 = max(0, px - 1), min(w, px + 2)
    patch = np.maximum(0.0, norm_img[y0:y1, x0:x1])
    neighbor_energy = float(np.sum(patch) - max(0.0, peak_raw_snr))

    orth_y = 0.0
    if py > 0:
        orth_y += max(0.0, float(norm_img[py - 1, px]))
    if py + 1 < h:
        orth_y += max(0.0, float(norm_img[py + 1, px]))
    orth_x = 0.0
    if px > 0:
        orth_x += max(0.0, float(norm_img[py, px - 1]))
    if px + 1 < w:
        orth_x += max(0.0, float(norm_img[py, px + 1]))

    cosmic_ray_veto = bool(
        peak_raw_snr > 6.0
        and (neighbor_energy < 0.15 * peak_raw_snr or min(orth_x, orth_y) < 0.08 * peak_raw_snr)
    )

    # ZOGY matched-filter significance map: S_corr = (I * P) / (sigma_sky * ||P||_2)
    s_corr = _convolve2d_psf5(norm_img) / _PSF_L2
    zogy_peak_snr = float(np.max(s_corr))
    if cosmic_ray_veto:
        zogy_peak_snr *= 0.25

    # Proper-motion dipole detector: looks for a positive PSF lobe paired with a negative PSF lobe
    # within 1.5 to 12 pixels (characteristic of difference images of moving brown dwarfs / Planet X)
    zogy_min_snr = float(np.min(s_corr))
    min_idx = int(np.argmin(s_corr))
    ny, nx = divmod(min_idx, w)
    sep_px = math.hypot(py - ny, px - nx)

    if zogy_peak_snr > 2.5 and zogy_min_snr < -2.5 and 1.2 <= sep_px <= 16.0 and not cosmic_ray_veto:
        symmetry = min(abs(zogy_peak_snr), abs(zogy_min_snr)) / max(abs(zogy_peak_snr), abs(zogy_min_snr), 1e-6)
        dipole_strength = math.tanh(0.08 * math.sqrt(abs(zogy_peak_snr * zogy_min_snr)))
        dipole_score = float(min(1.0, symmetry * dipole_strength * 1.35))
    else:
        dipole_score = 0.0

    return {
        "zogy_peak_snr": round(float(max(0.0, min(999.0, zogy_peak_snr))), 2),
        "dipole_polarity_score": round(dipole_score, 4),
        "cosmic_ray_veto": cosmic_ray_veto,
        "is_moving_dipole": bool(dipole_score >= 0.35),
    }


def embed_spectrum_16d(flux_ujy: list[float] | np.ndarray | None) -> np.ndarray | None:
    """Project 102-band spectrum into L2-normalized 16D AstroCLIP spectral embedding."""
    if flux_ujy is None:
        return None
    norm = preprocess_flux(flux_ujy).astype(np.float64)
    # Pool 102 channels into 16 spectral bands + global slope/curvature descriptors
    splits = np.array_split(norm, 16)
    vec = np.array([float(np.mean(s)) for s in splits], dtype=np.float64)
    l2 = float(np.linalg.norm(vec))
    if l2 < 1e-12:
        return np.zeros(16, dtype=np.float64)
    return vec / l2


def embed_image_16d(image_dict: dict[str, Any] | None) -> np.ndarray | None:
    """Project 64x64 cutout into L2-normalized 16D AstroCLIP visual morphology embedding."""
    if not image_dict or "data" not in image_dict:
        return None
    zogy = compute_zogy_metrics(image_dict)
    w = int(image_dict.get("width", 64))
    h = int(image_dict.get("height", 64))
    raw = np.asarray(image_dict["data"], dtype=np.float64)
    max_abs = float(np.max(np.abs(raw)))
    if max_abs <= 0.0 or not math.isfinite(max_abs):
        return np.zeros(16, dtype=np.float64)

    img = (raw / max_abs).reshape(h, w)
    med = float(np.median(img))
    centered = img - med
    # Radial concentric ring profile around image center + peak
    cy, cx = h / 2.0, w / 2.0
    yy, xx = np.ogrid[:h, :w]
    rr = np.hypot(yy - cy, xx - cx)
    rings = [
        float(np.mean(centered[rr <= 3.0])),
        float(np.mean(centered[(rr > 3.0) & (rr <= 7.0)])),
        float(np.mean(centered[(rr > 7.0) & (rr <= 14.0)])),
        float(np.mean(centered[rr > 14.0])),
    ]
    q1 = float(np.mean(centered[: h // 2, : w // 2]))
    q2 = float(np.mean(centered[: h // 2, w // 2 :]))
    q3 = float(np.mean(centered[h // 2 :, : w // 2]))
    q4 = float(np.mean(centered[h // 2 :, w // 2 :]))
    percentiles = [float(np.percentile(centered, p)) for p in (5, 25, 75, 95, 99)]

    vec = np.array(
        rings
        + [q1, q2, q3, q4]
        + percentiles
        + [
            math.tanh(zogy["zogy_peak_snr"] / 15.0),
            zogy["dipole_polarity_score"],
            -1.0 if zogy["cosmic_ray_veto"] else 0.5,
        ],
        dtype=np.float64,
    )
    l2 = float(np.linalg.norm(vec))
    if l2 < 1e-12:
        return np.zeros(16, dtype=np.float64)
    return vec / l2


def compute_astroclip_alignment(
    flux_ujy: list[float] | np.ndarray | None,
    image_dict: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute cross-modal spectrum-image alignment and ZOGY significance metrics."""
    zogy = compute_zogy_metrics(image_dict)
    e_spec = embed_spectrum_16d(flux_ujy)
    e_img = embed_image_16d(image_dict)

    if e_spec is not None and e_img is not None:
        # Cross-modal alignment between red/IR slope and spatial PSF/dipole concentration
        raw_cos = float(np.dot(e_spec, e_img))
        if zogy["cosmic_ray_veto"]:
            similarity = -0.65
        else:
            similarity = float(max(-1.0, min(1.0, raw_cos)))
        tension = round(float(max(0.0, min(1.0, 0.5 * (1.0 - similarity)))), 4)
    else:
        similarity = 0.0
        tension = 0.0

    return {
        "astroclip_similarity": round(similarity, 4),
        "cross_modal_tension": tension,
        **zogy,
    }
