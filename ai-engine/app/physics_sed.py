"""Physical 102-band SPHEREx spectrophotometric diagnostics & spender-like autoencoder.

Inspired by:
- `fkiwy/spexpi` (SPExPI: SPHEREx spectrophotometric extraction & molecular band indices)
- `tHarvey303/BD-Finder` & `tbmstolker/species` (Sonora Bobcat/Cholla substellar SED fitting)
- `pmelchior/spender` (Redshift/scale-invariant spectral latent representation)

Computes from a 102-band SPHEREx spectrum (0.75-5.0 um, flux in uJy):
- Molecular absorption indices: CH4 (3.3 um), H2O (2.7 um), CO (4.67 um)
- Synthetic WISE W1 (3.35 um) and W2 (4.60 um) AB magnitudes & W1 - W2 color
- Effective temperature estimate T_eff (K) and surface gravity log(g) via template grid chi^2
- 8-dimensional scale-invariant latent vector z and reconstruction RMS
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .models import WAVELENGTH_UM, preprocess_flux, synthesize_spectrum

# Precompute a physical template grid spanning 70 K (ice giant) to 6500 K (solar/F-star)
_TEMPLATE_GRID_SPECS: list[tuple[str, float, float, np.ndarray]] = []
_TEMPLATE_RAW: list[tuple[str, float, float, np.ndarray]] = []      # same grid, un-normalised flux
MIN_FIT_BANDS = 12


def _init_template_grid() -> list[tuple[str, float, float, np.ndarray]]:
    if _TEMPLATE_GRID_SPECS:
        return _TEMPLATE_GRID_SPECS

    grid_defs = [
        # (class, teff_k, log_g)
        # Planet X: reflected sunlight x methane reflectance. Its shape does not depend on the body's
        # temperature, so the template carries none (NaN) and no temperature is reported for it.
        ("planet_x_candidate", float("nan"), float("nan")),
        ("cold_brown_dwarf", 220.0, 4.2),
        ("cold_brown_dwarf", 250.0, 4.3),
        ("cold_brown_dwarf", 350.0, 4.5),
        ("cold_brown_dwarf", 550.0, 4.7),
        ("cold_brown_dwarf", 900.0, 4.9),
        ("cold_brown_dwarf", 1300.0, 5.0),
        ("young_variable_star", 3600.0, 3.8),
        ("young_variable_star", 4100.0, 4.0),
        ("young_variable_star", 4500.0, 4.1),
        ("main_sequence_star", 3200.0, 4.8),
        ("main_sequence_star", 4800.0, 4.5),
        ("main_sequence_star", 5800.0, 4.44),
        ("main_sequence_star", 7200.0, 4.2),
        ("high_z_galaxy", 4200.0, 4.0),
    ]
    for cls_name, teff, log_g in grid_defs:
        raw = synthesize_spectrum(cls_name, mag_ab_w2=15.0, teff_k=teff, redshift=2.0 if cls_name == "high_z_galaxy" else None)
        norm_vec = preprocess_flux(raw)
        _TEMPLATE_GRID_SPECS.append((cls_name, teff, log_g, norm_vec))
        _TEMPLATE_RAW.append((cls_name, teff, log_g, np.asarray(raw, dtype=np.float64)))

    return _TEMPLATE_GRID_SPECS


# Deterministic orthogonal basis (102 -> 8 -> 102) for spender-like spectral autoencoding
_BASIS_8D: np.ndarray | None = None


def _get_basis_8d() -> np.ndarray:
    global _BASIS_8D
    if _BASIS_8D is None:
        n = len(WAVELENGTH_UM)
        x = np.linspace(0.0, math.pi, n, dtype=np.float64)
        basis = np.zeros((8, n), dtype=np.float64)
        for k in range(8):
            row = np.cos((k + 0.5) * x)
            norm = np.linalg.norm(row)
            basis[k] = row / max(norm, 1e-12)
        _BASIS_8D = basis
    return _BASIS_8D


def _band_median_positive(flux64: np.ndarray, mask: np.ndarray, floor: float) -> float:
    vals = flux64[mask]
    pos = vals[vals > 0.0]
    if pos.size == 0:
        return floor
    return float(max(np.median(pos), floor))


def masked_template_fit(flux: np.ndarray, mask: np.ndarray, upper_limits: np.ndarray | None = None) -> dict[str, Any] | None:
    """Nearest grid template using only the bands in mask (the target's own measured bands).

    Log-flux distance with a free scale: the template is fitted in shape, then scaled to the data.
    upper_limits (bools): bands whose flux is target + a blended neighbour, i.e. an upper limit on
    the target; a scaled template brighter than such a band is penalised (one-sided, in dex).
    Returns class, T_eff, log g and the scaled template flux (to fill the other bands), or None if
    fewer than MIN_FIT_BANDS usable positive bands."""
    arr = np.asarray(flux, dtype=np.float64)
    ul = (np.asarray(upper_limits, dtype=bool) & np.isfinite(arr) & (arr > 0.0)) if upper_limits is not None else None
    m = np.asarray(mask, dtype=bool) & np.isfinite(arr) & (arr > 0.0)
    if int(m.sum()) < MIN_FIT_BANDS:
        return None
    _init_template_grid()
    floor = 1e-4
    ref = float(np.percentile(arr[m], 90))
    lo = np.log10(np.maximum(arr[m] / ref, floor))
    best = None
    for cls_name, teff, log_g, raw in _TEMPLATE_RAW:
        rm = raw[m]
        pos = rm[rm > 0.0]
        if pos.size == 0:
            continue
        tref = float(np.percentile(pos, 90))
        lt = np.log10(np.maximum(rm / tref, floor))
        d = lo - lt
        off = float(np.mean(d))
        dist = float(np.mean((d - off) ** 2))
        scaled = raw * (ref / tref) * 10.0 ** off
        if ul is not None and ul.any():
            excess = np.log10(np.maximum(scaled[ul], 1e-30) / arr[ul])
            dist += float(np.mean(np.clip(excess, 0.0, None) ** 2))
        if best is None or dist < best[0]:
            best = (dist, cls_name, teff, log_g, scaled)
    if best is None:
        return None
    return {"class": best[1], "teff": best[2], "log_g": best[3], "template_flux": best[4],
            "rms_dex": round(math.sqrt(best[0]), 4), "n_bands": int(m.sum())}


def fill_unusable_bands(flux: list[float] | np.ndarray, mask: list[bool] | np.ndarray,
                        upper_limits: list[bool] | np.ndarray | None = None) -> tuple[np.ndarray, dict[str, Any] | None]:
    """Spectrum with the bands outside mask replaced by the best template fitted to the bands inside it
    (and kept below the upper-limit bands); unchanged if the fit is not possible."""
    arr = np.asarray(flux, dtype=np.float64).copy()
    m = np.asarray(mask, dtype=bool)
    fit = masked_template_fit(arr, m, upper_limits)
    if fit is not None:
        arr[~m] = fit["template_flux"][~m]
    return arr, fit


# Wavelength windows each diagnostic reads (um); it is reported only if most of its bands are usable.
_DIAG_WINDOWS = {
    "w1_ab_mag": [(3.10, 3.60)],
    "w2_ab_mag": [(4.25, 4.90)],
    "w1_minus_w2_ab": [(3.10, 3.60), (4.25, 4.90)],
    "ch4_3_3um_index": [(3.10, 3.60), (3.20, 3.48)],
    "h2o_2_7um_index": [(2.05, 2.30), (2.55, 2.85), (3.85, 4.25)],
    "co_4_67um_index": [(3.85, 4.25), (4.55, 4.80)],
}


REFLECTED_LIGHT_NOTE = (
    "0.75-5 um light of a distant planet is reflected sunlight: its shape carries the Sun's colour, not the "
    "body's temperature. Thermal emission peaks near 60-250 um, outside SPHEREx. For a body at d AU the "
    "equilibrium temperature is ~278.6 K x (1 - A)^(1/4) / sqrt(d), about 11 K at 520 AU (Bond albedo 0.3)."
)


def analyze_spectrum_physics(flux_ujy: list[float] | np.ndarray, mask: list[bool] | np.ndarray | None = None,
                             upper_limits: list[bool] | np.ndarray | None = None) -> dict[str, Any]:
    """Compute physical diagnostics, molecular absorption depths, and latent embedding.

    mask (102 bools): the target's own bands (measured by real frames, not blended with a
    neighbour). The template fit then uses only those bands, the others are filled from the fitted
    template, and diagnostics whose wavelength windows are mostly outside the mask are null."""
    if mask is not None:
        m = np.asarray(mask, dtype=bool)
        if m.shape != (102,):
            raise ValueError(f"mask must have 102 entries, got {m.shape}")
        if not m.all():
            filled, fit = fill_unusable_bands(flux_ujy, m, upper_limits)
            if fit is not None:
                out = analyze_spectrum_physics(filled)
                reflected = fit["class"] == "planet_x_candidate"
                out.update(
                    best_template_class=fit["class"],
                    teff_k=None if reflected else round(float(fit["teff"]), 1),
                    log_g_cgs=None if reflected else round(float(fit["log_g"]), 2),
                    teff_method="not_measurable_reflected_light" if reflected else "template_grid",
                    temperature_note=(REFLECTED_LIGHT_NOTE if reflected else
                                      f"nearest template fitted to the {fit['n_bands']} usable bands (measured, not blended); "
                                      f"rms {fit['rms_dex']} dex"),
                    bands_used=fit["n_bands"],
                )
                lam = WAVELENGTH_UM.astype(np.float64)
                for key, wins in _DIAG_WINDOWS.items():
                    # null when any window it reads is mostly outside the usable bands
                    for lo, hi in wins:
                        sel = (lam >= lo) & (lam <= hi)
                        if sel.any() and m[sel].mean() < 0.5:
                            out[key] = None
                            break
                return out
    arr64 = np.asarray(flux_ujy, dtype=np.float64)
    if arr64.shape != (102,):
        raise ValueError(f"Expected 102 spectral bands, got {arr64.shape}")
    if not np.all(np.isfinite(arr64)):
        raise ValueError("Spectrum contains non-finite values (NaN or Inf)")

    lam = WAVELENGTH_UM.astype(np.float64)
    pos = arr64[arr64 > 0.0]
    if pos.size == 0:
        # No positive flux: nothing can be measured. Report nulls, never placeholder physics.
        return {
            "teff_k": None,
            "log_g_cgs": None,
            "w1_ab_mag": None,
            "w2_ab_mag": None,
            "w1_minus_w2_ab": None,
            "ch4_3_3um_index": None,
            "h2o_2_7um_index": None,
            "co_4_67um_index": None,
            "latent_8d": [0.0] * 8,
            "spectral_recon_rms": None,
            "best_template_class": None,
            "teff_method": "none",
            "temperature_note": "no positive flux in the spectrum",
        }

    # Dimensionless pre-scaling by 90th percentile (with max*1e-100 guard against 400-decade split overflow)
    ref_scale = max(float(np.percentile(pos, 90)), float(np.max(pos)) * 1e-100)
    if not math.isfinite(ref_scale) or ref_scale <= 0.0:
        ref_scale = 1.0
    scaled = arr64 / ref_scale
    floor = 1e-4

    # Bandpass masks (in um)
    m_j = (lam >= 1.15) & (lam <= 1.35)
    m_k = (lam >= 2.05) & (lam <= 2.30)
    m_h2o = (lam >= 2.55) & (lam <= 2.85)
    m_w1 = (lam >= 3.10) & (lam <= 3.60)
    m_ch4_trough = (lam >= 3.20) & (lam <= 3.48)
    m_peak_4um = (lam >= 3.85) & (lam <= 4.25)
    m_w2 = (lam >= 4.25) & (lam <= 4.90)
    m_co_trough = (lam >= 4.55) & (lam <= 4.80)

    f_j = _band_median_positive(scaled, m_j, floor)
    f_k = _band_median_positive(scaled, m_k, floor)
    f_h2o = _band_median_positive(scaled, m_h2o, floor)
    f_w1 = _band_median_positive(scaled, m_w1, floor)
    f_ch4 = _band_median_positive(scaled, m_ch4_trough, floor)
    f_peak4 = _band_median_positive(scaled, m_peak_4um, floor)
    f_w2 = _band_median_positive(scaled, m_w2, floor)
    f_co = _band_median_positive(scaled, m_co_trough, floor)

    # True AB magnitudes in W1 and W2 (clamped to physical astronomical range [-30, +35])
    # m_AB = -2.5 * log10(F_uJy / 3631e6) = 23.90 - 2.5 * log10(F_uJy)
    log_ref = math.log10(ref_scale) if ref_scale > 0 else 0.0
    w1_ab = 23.90 - 2.5 * (math.log10(f_w1) + log_ref)
    w2_ab = 23.90 - 2.5 * (math.log10(f_w2) + log_ref)
    w1_ab = float(max(-30.0, min(35.0, w1_ab)))
    w2_ab = float(max(-30.0, min(35.0, w2_ab)))
    # Color W1 - W2 depends ONLY on flux ratio f_w2 / f_w1 (scale-invariant even at 1e300!)
    w1_minus_w2 = float(max(-10.0, min(15.0, 2.5 * math.log10(max(f_w2, floor) / max(f_w1, floor)))))

    # Molecular absorption indices (positive = absorption trough relative to pseudo-continuum)
    cont_ch4 = 0.5 * (f_k + f_peak4)
    ch4_index = float(max(-5.0, min(10.0, math.log10(max(cont_ch4, floor) / max(f_ch4, floor)))))

    cont_h2o = 0.5 * (f_k + f_peak4)
    h2o_index = float(max(-5.0, min(10.0, math.log10(max(cont_h2o, floor) / max(f_h2o, floor)))))

    cont_co = f_peak4
    co_index = float(max(-5.0, min(10.0, math.log10(max(cont_co, floor) / max(f_co, floor)))))

    # Template grid chi^2 inversion for T_eff and log(g)
    norm_obs = preprocess_flux(arr64).astype(np.float64)
    grid = _init_template_grid()
    best_cls = "main_sequence_star"
    best_teff = 5800.0
    best_logg = 4.44
    best_dist = float("inf")

    for cls_name, teff, log_g, tmpl_vec in grid:
        dist = float(np.mean((norm_obs - tmpl_vec.astype(np.float64)) ** 2))
        if dist < best_dist:
            best_dist = dist
            best_cls = cls_name
            best_teff = teff
            best_logg = log_g

    # Refine T_eff continuously using Wien/Rayleigh-Jeans color slope between 1.25 um and 4.6 um
    j_to_w2_dex = math.log10(max(f_w2, floor) / max(f_j, floor))
    if best_cls == "cold_brown_dwarf" and j_to_w2_dex > 1.5:
        # Ultracool Y/T sequence calibration
        refined_teff = max(180.0, min(1400.0, 950.0 / (1.0 + 0.85 * max(0.0, j_to_w2_dex))))
        best_teff = round(0.6 * best_teff + 0.4 * refined_teff, 1)

    # Spender-like 8D orthogonal latent projection & reconstruction residual
    basis = _get_basis_8d()
    latent = basis @ norm_obs
    recon = basis.T @ latent
    recon_rms = float(np.sqrt(np.mean((norm_obs - recon) ** 2)))

    reflected = best_cls == "planet_x_candidate"
    return {
        "teff_k": None if reflected else round(float(best_teff), 1),
        "log_g_cgs": None if reflected else round(float(best_logg), 2),
        "teff_method": "not_measurable_reflected_light" if reflected else "template_grid",
        "temperature_note": (REFLECTED_LIGHT_NOTE if reflected else
                             "nearest of the Sonora/SPHEREx-like template grid (coarse: a few hundred K steps)"),
        "w1_ab_mag": round(w1_ab, 3),
        "w2_ab_mag": round(w2_ab, 3),
        "w1_minus_w2_ab": round(w1_minus_w2, 3),
        "ch4_3_3um_index": round(ch4_index, 4),
        "h2o_2_7um_index": round(h2o_index, 4),
        "co_4_67um_index": round(co_index, 4),
        "latent_8d": [round(float(v), 4) for v in latent],
        "spectral_recon_rms": round(recon_rms, 4),
        "best_template_class": best_cls,
    }
