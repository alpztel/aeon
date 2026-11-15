"""Multi-mission SED physical integration (0.4-22 um) & Wien/Planck color temperature fitter.

Inspired by:
- `tHarvey303/BD-Finder` & `tbmstolker/species` (Substellar & disk SED integration across Gaia + SPHEREx + WISE)
- `Caltech-IPAC/kete` & `dirac-institute/kbmod` (Ecliptic coordinates, annual reflex parallax amplitude & shift-stack gain)
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# J2000 obliquity of the ecliptic (deg)
OBLIQUITY_J2000_DEG = 23.4392911


def icrs_to_ecliptic_deg(ra_deg: float, dec_deg: float) -> tuple[float, float]:
    """Convert ICRS (RA, Dec) in degrees to heliocentric J2000 ecliptic (lambda, beta) in degrees."""
    ra_rad = math.radians(float(ra_deg) % 360.0)
    dec_rad = math.radians(max(-90.0, min(90.0, float(dec_deg))))
    eps = math.radians(OBLIQUITY_J2000_DEG)

    sin_beta = math.sin(dec_rad) * math.cos(eps) - math.cos(dec_rad) * math.sin(eps) * math.sin(ra_rad)
    sin_beta = max(-1.0, min(1.0, sin_beta))
    beta_rad = math.asin(sin_beta)

    y = math.sin(ra_rad) * math.cos(eps) + math.tan(dec_rad) * math.sin(eps) if abs(math.cos(dec_rad)) > 1e-12 else 0.0
    x = math.cos(ra_rad)
    if abs(math.cos(dec_rad)) <= 1e-12:
        # Exactly at celestial poles
        y_num = math.sin(dec_rad) * math.sin(eps)
        x_num = 0.0
        lam_rad = math.atan2(y_num, x_num)
    else:
        lam_rad = math.atan2(
            math.sin(ra_rad) * math.cos(eps) + math.sin(dec_rad) * math.sin(eps) / math.cos(dec_rad),
            math.cos(ra_rad),
        )
    lam_deg = math.degrees(lam_rad) % 360.0
    beta_deg = math.degrees(beta_rad)
    return round(lam_deg, 5), round(beta_deg, 5)


def compute_kete_kbmod_kinematics(
    ra_deg: float,
    dec_deg: float,
    parallax_mas: float | None = None,
    distance_au: float | None = None,
    n_frames: int = 24,
) -> dict[str, Any]:
    """Compute ecliptic coordinates, annual reflex parallax factor, and KBMOD shift-stack SNR gain."""
    lam_ecl, beta_ecl = icrs_to_ecliptic_deg(ra_deg, dec_deg)
    # Ecliptic latitude geometric parallax factor: semi-minor over semi-major of parallactic ellipse = |sin(beta)|
    parallax_ellipse_aspect = round(abs(math.sin(math.radians(beta_ecl))), 4)

    if distance_au is not None and distance_au > 0:
        # Solar system body at distance_au AU: annual parallax amplitude = 1 AU / d_AU in radians -> arcsec
        annual_parallax_arcsec = round(math.degrees(math.atan2(1.0, float(distance_au))) * 3600.0, 3)
    elif parallax_mas is not None and parallax_mas > 0:
        annual_parallax_arcsec = round(float(parallax_mas) / 1000.0, 4)
    else:
        annual_parallax_arcsec = 0.0

    n_clean = max(1, min(1000, int(n_frames)))
    kbmod_snr_gain = round(math.sqrt(float(n_clean)), 3)

    return {
        "ecliptic_lon_deg": lam_ecl,
        "ecliptic_lat_deg": beta_ecl,
        "parallax_ellipse_aspect": parallax_ellipse_aspect,
        "annual_parallax_arcsec": annual_parallax_arcsec,
        "kbmod_expected_snr_gain": kbmod_snr_gain,
    }


BOND_ALBEDO_DEFAULT = 0.3       # ice giants: Neptune 0.29, Uranus 0.30


def equilibrium_temperature_k(distance_au: float, bond_albedo: float = BOND_ALBEDO_DEFAULT) -> float:
    """Radiative equilibrium temperature of a fast rotator at distance_au from the Sun:
    T = 278.6 K x (1 - A)^(1/4) / sqrt(d_AU) (no internal heat)."""
    return 278.6 * (1.0 - bond_albedo) ** 0.25 / math.sqrt(distance_au)


def fit_multi_mission_sed(sed_points: list[dict[str, Any]], distance_au: float | None = None) -> dict[str, Any]:
    """Integrate broadband + SPHEREx SED (0.4-22 um) and estimate color temperature & IR excess.

    distance_au (a solar-system body): its 0.4-22 um light is reflected sunlight, whose colour is the
    Sun's (~5000 K), not the body's. The reported temperature is then the equilibrium temperature
    (teff_method "equilibrium"); the colour temperature of the points is kept apart as
    reflected_color_temperature_k."""
    out = _fit_points(sed_points)
    out["n_points"] = sum(1 for p in sed_points if _usable(p))
    if distance_au is not None and math.isfinite(float(distance_au)) and float(distance_au) > 0:
        d = float(distance_au)
        out["reflected_color_temperature_k"] = out["teff_sed_k"]
        out.update(
            teff_sed_k=round(equilibrium_temperature_k(d), 1),
            teff_method="equilibrium",
            bond_albedo_assumed=BOND_ALBEDO_DEFAULT,
            distance_au=d,
            spectral_regime="reflected_sunlight",
            temperature_note=("solar-system body: 0.4-22 um light is reflected sunlight; temperature = radiative "
                              "equilibrium at this distance (Bond albedo 0.3, no internal heat)"),
        )
    else:
        out["teff_method"] = "wien_color_temperature" if out["teff_sed_k"] is not None else "none"
    return out


def _usable(pt: dict[str, Any]) -> bool:
    w, f = pt.get("wavelength_um"), pt.get("flux_ujy")
    return w is not None and f is not None and math.isfinite(w) and math.isfinite(f) and w > 0 and f > 0


def _fit_points(sed_points: list[dict[str, Any]]) -> dict[str, Any]:
    valid = []
    for pt in sed_points:
        w = pt.get("wavelength_um")
        f = pt.get("flux_ujy")
        if w is not None and f is not None and math.isfinite(w) and math.isfinite(f) and w > 0 and f > 0:
            valid.append((float(w), float(f)))

    if not valid:
        return {
            "teff_sed_k": None,
            "bolometric_flux_wm2": 0.0,
            "ir_to_optical_ratio": None,
            "spectral_regime": "unmeasured",
        }

    valid.sort(key=lambda x: x[0])
    # Merge duplicate/near-identical wavelengths (e.g. AllWISE + CatWISE at 3.35 um)
    merged: list[tuple[float, float]] = []
    for w, f in valid:
        if merged and abs(w - merged[-1][0]) / max(w, 1e-9) < 1e-3:
            prev_w, prev_f = merged[-1]
            merged[-1] = (0.5 * (prev_w + w), 0.5 * (prev_f + f))
        else:
            merged.append((w, f))

    lam_um = np.array([v[0] for v in merged], dtype=np.float64)
    flux_ujy = np.array([v[1] for v in merged], dtype=np.float64)

    # Convert F_nu [uJy] to nu * F_nu [W / m^2]:
    # 1 uJy = 1e-32 W m^-2 Hz^-1, nu = c / lambda = 2.99792458e14 / lambda_um [Hz]
    # => nu * F_nu = 2.99792458e-18 * (flux_ujy / lambda_um) [W / m^2]
    max_f = float(np.max(flux_ujy))
    scaled_f = flux_ujy / max_f
    nu_fnu_scaled = 2.99792458e-18 * (scaled_f / lam_um)

    if len(merged) >= 2:
        log_lam = np.log(lam_um)
        span = float(log_lam[-1] - log_lam[0])
        if span > 0.05:
            # Explicit trapezoidal rule compatible with both NumPy 1.x and NumPy 2.x
            f_bol_scaled = float(np.sum(0.5 * (nu_fnu_scaled[1:] + nu_fnu_scaled[:-1]) * (log_lam[1:] - log_lam[:-1])))
        else:
            f_bol_scaled = float(np.mean(nu_fnu_scaled)) * 0.25
        f_bol = max(0.0, f_bol_scaled) * max_f
        if not math.isfinite(f_bol):
            f_bol = 1e300
    else:
        # Single-band effective logarithmic bandpass width d(ln lam) ~ 0.25
        f_bol = float(nu_fnu_scaled[0]) * 0.25 * max_f

    # Peak wavelength of nu * F_nu -> Wien displacement estimate T_color ~ 3670 K / lambda_peak_um
    peak_idx = int(np.argmax(nu_fnu_scaled))
    lam_peak = float(lam_um[peak_idx])
    teff_est = float(max(60.0, min(15000.0, 3670.0 / max(lam_peak, 0.24))))

    # Rayleigh-Jeans tail correction: if peak is at the shortest observed wavelength (peak_idx == 0)
    # and F_nu drops steeply with wavelength (d ln F_nu / d ln lam <= -1.4), the true Wien peak is
    # blueward of lam_um[0]. Infer T_eff from the near-IR Planck slope alpha = d ln F_nu / d ln lam.
    if len(merged) >= 3 and peak_idx == 0 and lam_um[0] >= 0.70:
        d_ln_lam = math.log(lam_um[-1] / lam_um[0])
        if d_ln_lam > 0.3:
            alpha = math.log(max(scaled_f[-1], 1e-12) / max(scaled_f[0], 1e-12)) / d_ln_lam
            if alpha <= -1.45:
                # Near-IR Rayleigh-Jeans asymptotic slope: alpha -> -2 as T -> infinity
                excess_slope = max(0.04, min(2.0, 2.05 + alpha))
                rj_teff = 14388.0 / (float(lam_um[0]) * (2.6 * excess_slope))
                teff_est = float(max(teff_est, min(12000.0, rj_teff)))

    # Infrared-to-optical energy ratio (lambda >= 2.5 um vs lambda < 2.5 um)
    ir_mask = lam_um >= 2.5
    opt_mask = lam_um < 2.5
    if np.any(ir_mask) and np.any(opt_mask):
        ir_med = float(np.median(nu_fnu_scaled[ir_mask]))
        opt_med = float(np.median(nu_fnu_scaled[opt_mask]))
        ir_ratio = round(float(min(1e6, ir_med / max(opt_med, 1e-12))), 3)
    elif np.any(ir_mask):
        ir_ratio = 999.0
        teff_est = min(teff_est, 450.0)
    else:
        ir_ratio = 0.0

    if ir_ratio is not None and ir_ratio >= 25.0:
        regime = "ultracool_or_substellar"
    elif ir_ratio is not None and ir_ratio >= 1.2:
        regime = "infrared_excess_disk"
    else:
        regime = "photospheric"

    return {
        "teff_sed_k": round(teff_est, 1),
        "bolometric_flux_wm2": float(f"{f_bol:.4e}"),
        "ir_to_optical_ratio": ir_ratio,
        "spectral_regime": regime,
    }
