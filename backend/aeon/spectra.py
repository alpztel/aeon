"""Physical spectral energy distribution models evaluated on the 102 SPHEREx-like bands.

Every model returns F_nu in microjansky at bands.WAVELENGTH_UM. Models are phenomenological
but physically motivated: Planck continua, Gaussian optical-depth molecular bands, a
NIR power-law extinction law, reflected sunlight with methane-ice absorption, and a redshifted
stellar population with a 4000 A break and 1.6 um H- bump.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import bands

HC_OVER_K_UM_K = 14387.769  # hc/k in um*K
W2_UM = 4.6


@dataclass(frozen=True)
class Feature:
    molecule: str
    center_um: float
    sigma_um: float


# Molecular absorption bands that dominate 0.75-5 um in cold atmospheres and ices.
FEATURES: tuple[Feature, ...] = (
    Feature("H2O", 1.40, 0.060),
    Feature("H2O", 1.88, 0.070),
    Feature("H2O", 2.70, 0.140),
    Feature("CH4", 1.66, 0.045),
    Feature("CH4", 2.20, 0.060),
    Feature("CH4", 3.32, 0.120),
    Feature("CO2", 4.26, 0.035),
    Feature("CO", 4.67, 0.060),
)


def planck_fnu(wavelength_um: np.ndarray, temperature_k: float | np.ndarray) -> np.ndarray:
    """Planck F_nu shape (arbitrary units) ~ nu^3 / (exp(h nu / kT) - 1)."""
    lam = np.asarray(wavelength_um, dtype=float)
    t = np.asarray(temperature_k, dtype=float)
    x = HC_OVER_K_UM_K / (lam * t[..., None] if t.ndim else lam * t)
    x = np.clip(x, 1e-6, 700.0)
    return (1.0 / lam**3) / np.expm1(x)


def optical_depth(wavelength_um: np.ndarray, depths: dict[str, float]) -> np.ndarray:
    tau = np.zeros_like(wavelength_um, dtype=float)
    for f in FEATURES:
        amp = depths.get(f.molecule, 0.0)
        if amp:
            tau += amp * np.exp(-0.5 * ((wavelength_um - f.center_um) / f.sigma_um) ** 2)
    return tau


def extinction_mag(wavelength_um: np.ndarray, a_v: float) -> np.ndarray:
    """NIR power-law extinction A_lambda = A_V (lambda / 0.55 um)^-1.75."""
    return a_v * (wavelength_um / 0.55) ** -1.75


def _normalise(shape: np.ndarray, mag_ab_w2: float) -> np.ndarray:
    lam = bands.WAVELENGTH_UM
    ref = np.interp(W2_UM, lam, shape)
    return shape / max(ref, 1e-300) * float(bands.ab_to_ujy(mag_ab_w2))


# --- Object models -----------------------------------------------------------------------

def cold_brown_dwarf(mag_ab_w2: float, teff_k: float = 250.0) -> np.ndarray:
    """Y/T dwarf: colour-temperature envelope (emission from deeper, hotter layers in the
    opacity windows) carved by H2O, CH4, CO2 and CO bands. Peaks in the 4-5 um window."""
    lam = bands.WAVELENGTH_UM
    t_colour = 3.2 * teff_k
    cold = np.clip((500.0 - teff_k) / 250.0, 0.0, 1.0)  # 1 for Y dwarfs, 0 for warm T dwarfs
    tau = optical_depth(lam, {
        "H2O": 2.2,
        "CH4": 1.5 + 2.0 * cold,
        "CO2": 0.6 + 0.4 * cold,
        "CO": 0.5,
    })
    return _normalise(planck_fnu(lam, t_colour) * np.exp(-tau), mag_ab_w2)


def planet_x(mag_ab_w2: float) -> np.ndarray:
    """Distant ice giant: reflected sunlight (5778 K) x methane-dominated reflectance.
    Thermal emission of a ~40 K body is negligible shortward of 5 um."""
    lam = bands.WAVELENGTH_UM
    reflectance = 0.6 * np.exp(-optical_depth(lam, {"CH4": 2.6, "H2O": 0.4}))
    return _normalise(planck_fnu(lam, 5778.0) * reflectance, mag_ab_w2)


def young_variable_star(mag_ab_w2: float, t_year: float, teff_k: float = 4100.0) -> np.ndarray:
    """T Tauri star: photosphere + warm inner disk (1000 K) + cooler disk (350 K), with
    time-variable circumstellar extinction and disk luminosity (RW Aur-like dimming events).
    Normalisation is fixed for the quiescent state so that variability is preserved."""
    lam = bands.WAVELENGTH_UM
    phase = 2 * np.pi * (t_year - 2026.0) / 0.75
    a_v = 2.2 + 1.6 * np.sin(phase)                      # mag; dimming at short wavelengths
    disk = 1.0 + 0.45 * np.sin(phase + 1.3)              # inner-disk brightening at long wavelengths
    star = planck_fnu(lam, teff_k)
    hot = planck_fnu(lam, 1000.0)
    warm = planck_fnu(lam, 350.0)
    star_n = star / np.interp(2.2, lam, star)
    hot_n = hot / np.interp(2.2, lam, hot)
    warm_n = warm / np.interp(4.6, lam, warm)
    co = np.exp(-optical_depth(lam, {"CO": 0.15, "H2O": 0.1}))
    quiescent = star_n * 10 ** (-0.4 * extinction_mag(lam, 2.2)) + 0.8 * hot_n + 0.6 * warm_n
    current = star_n * 10 ** (-0.4 * extinction_mag(lam, a_v)) + 0.8 * disk * hot_n + 0.6 * disk * warm_n
    q_ref = np.interp(W2_UM, lam, quiescent)
    return current * co / q_ref * float(bands.ab_to_ujy(mag_ab_w2))


def main_sequence_star(mag_ab_w2: float, teff_k: float = 5800.0) -> np.ndarray:
    lam = bands.WAVELENGTH_UM
    co_depth = 0.12 if teff_k < 4500 else 0.0
    return _normalise(planck_fnu(lam, teff_k) * np.exp(-optical_depth(lam, {"CO": co_depth})), mag_ab_w2)


def high_z_galaxy(mag_ab_w2: float, z: float = 2.0) -> np.ndarray:
    """Evolved stellar population redshifted to z: 4000 A break, 1.6 um H- bump, 3.3 um PAH."""
    lam = bands.WAVELENGTH_UM
    rest = lam / (1 + z)
    cont = planck_fnu(rest, 3800.0)
    cont *= np.where(rest < 0.40, 0.35, 1.0)
    cont *= 1.0 + 0.25 * np.exp(-0.5 * ((rest - 1.6) / 0.25) ** 2)
    cont *= 1.0 + 0.6 * np.exp(-0.5 * ((rest - 3.3) / 0.02) ** 2)
    return _normalise(cont, mag_ab_w2)


def model_flux(object_class: str, mag_ab_w2: float, t_year: float, teff_k: float | None = None,
               redshift: float | None = None) -> np.ndarray:
    if object_class == "cold_brown_dwarf":
        return cold_brown_dwarf(mag_ab_w2, teff_k or 250.0)
    if object_class == "planet_x_candidate":
        return planet_x(mag_ab_w2)
    if object_class == "young_variable_star":
        return young_variable_star(mag_ab_w2, t_year, teff_k or 4100.0)
    if object_class == "high_z_galaxy":
        return high_z_galaxy(mag_ab_w2, redshift or 2.0)
    return main_sequence_star(mag_ab_w2, teff_k or 5800.0)


def blackbody_bands(mag_ab_w2: np.ndarray, teff_k: np.ndarray) -> np.ndarray:
    """Vectorised Planck SEDs for many field stars: returns (N, 102) uJy."""
    lam = bands.WAVELENGTH_UM
    shape = planck_fnu(lam, np.asarray(teff_k, dtype=float))  # (N, 102)
    ref = planck_fnu(np.array([W2_UM]), np.asarray(teff_k, dtype=float))[:, 0]
    return shape / ref[:, None] * bands.ab_to_ujy(np.asarray(mag_ab_w2))[:, None]
