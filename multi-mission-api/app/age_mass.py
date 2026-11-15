"""Stage 2: break the mass-age degeneracy with a spectral channel and a kinematic channel.

Spectral channel. A cooling brown dwarf of a given brightness can be light and young or heavy and
old: one observable fixes a curve in the (mass, age) plane, not a point. The observable is compared
with published evolution models on a (mass, age) grid:

- substellar ("substellar_w2"): absolute W2 magnitude against the Sonora Bobcat evolution tracks
  and Sonora Bobcat atmosphere magnitudes (Marley et al. 2021), solar metallicity, cloud-free;
- stellar ("stellar_hr"): bolometric luminosity and effective temperature against the BHAC15 tracks
  (Baraffe et al. 2015), which cover the pre-main sequence and the main sequence.

Kinematic channel. p(age | U, V, W) from the age-velocity dispersion relation (kinematics.py).

Joint. The product of the two on the same age grid, for a flat prior in age and in log mass. A star
whose SED shows a warm disk also gets the disk-survival factor exp(-age / 2.5 Myr) (Mamajek 2009).

Nothing is assumed silently: every model table, prior and uncertainty floor used is in the output
("assumptions"), and a channel without the data it needs returns status "unmeasured" with the reason.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

DATA_DIR = Path(__file__).resolve().parent / "data"

MJUP_PER_MSUN = 1.3271244e20 / 1.2668653e17      # IAU 2015 nominal GM_sun / GM_jup = 1047.57
RJUP_PER_RSUN = 6.957e8 / 7.1492e7               # IAU 2015 nominal radii
LSUN_W = 3.828e26                                # IAU 2015 nominal solar luminosity
PC_M = 3.0856775814913673e16

AGE_MIN_GYR, AGE_MAX_GYR = 0.001, 12.0           # prior range (flat in age)
SEAM_MSUN = 0.075                                # Sonora Bobcat below, BHAC15 from here up
N_AGE, N_MASS = 180, 280

MODEL_SYSTEMATIC_MAG = 0.3                       # assumed floor: cloud-free models vs real W2
LOG_L_FLOOR_DEX = 0.10                           # assumed floor: SED sampling / unobserved flux
LOG_L_FLOOR_SPARSE_DEX = 0.20                    # ... when nothing samples the SED between 0.9 and 2.5 um
CHI2_MAX = 9.0                                   # best model further than this from the data: no solution
DISK_EXCESS_FACTOR = 3.0                         # W3 / W4 this far above the photosphere: circumstellar dust
PHOTOSPHERE_MAX_UM = 2.5
TEFF_FLOOR_FRAC = 0.05                           # assumed floor on a colour temperature
DISK_TIMESCALE_GYR = 0.0025                      # Mamajek 2009: primordial disk fraction ~ exp(-t / 2.5 Myr)

REFERENCES = {
    "sonora_bobcat": "Marley et al. 2021, ApJ 920, 85 (Zenodo doi:10.5281/zenodo.5063476)",
    "bhac15": "Baraffe, Homeier, Allard & Chabrier 2015, A&A 577, A42",
    "disk_lifetime": "Mamajek 2009, AIP Conf. Proc. 1158, 3 (arXiv:0906.5011)",
}


# --------------------------------------------------------------------------------------------
# Model tables
# --------------------------------------------------------------------------------------------

def _tracks_sonora() -> dict[float, np.ndarray]:
    """mass [Msun] -> rows (age_gyr, log L, Teff, log g, R/Rsun), sorted by age."""
    tracks: dict[float, list[list[float]]] = {}
    for ln in (DATA_DIR / "sonora_bobcat_evolution_solar.txt").read_text(encoding="utf-8").splitlines():
        p = ln.split()
        if len(p) != 7:
            continue
        try:
            m, age, logl, teff, logg, rad, _ = (float(x) for x in p)
        except ValueError:
            continue
        tracks.setdefault(m, []).append([age, logl, teff, logg, rad])
    return {m: np.array(sorted(r)) for m, r in tracks.items()}


def _tracks_bhac() -> dict[float, np.ndarray]:
    tracks: dict[float, list[list[float]]] = {}
    for ln in (DATA_DIR / "bhac15_tracks.txt").read_text(encoding="utf-8").splitlines():
        if ln.startswith("#"):
            continue
        p = ln.split()
        if len(p) != 6:
            continue
        m, logt, teff, logl, logg, rad = (float(x) for x in p)
        tracks.setdefault(m, []).append([10.0 ** (logt - 9.0), logl, teff, logg, rad])
    return {m: np.array(sorted(r)) for m, r in tracks.items()}


@lru_cache(maxsize=1)
def _mag_table() -> dict[str, np.ndarray]:
    """Sonora Bobcat absolute magnitudes (Vega, 10 pc) on the regular (Teff, log g) grid."""
    rows = []
    for ln in (DATA_DIR / "sonora_bobcat_mags_solar.txt").read_text(encoding="utf-8").splitlines():
        p = ln.split()
        if len(p) != 31:
            continue
        try:
            v = [float(x) for x in p]
        except ValueError:
            continue
        rows.append([v[0], v[1], v[3], v[-4], v[-3]])            # Teff, log g, R/Rsun, W1, W2
    a = np.array(rows)
    teffs, loggs = np.unique(a[:, 0]), np.unique(a[:, 1])
    shape = (len(teffs), len(loggs))
    cube = {k: np.full(shape, np.nan) for k in ("radius", "w1", "w2")}
    for teff, logg, rad, w1, w2 in a:
        i, j = int(np.searchsorted(teffs, teff)), int(np.searchsorted(loggs, logg))
        cube["radius"][i, j], cube["w1"][i, j], cube["w2"][i, j] = rad, w1, w2
    return {"teff": teffs, "logg": loggs, **cube}


def _bilinear(table: np.ndarray, xs: np.ndarray, ys: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """table[i, j] on (xs, ys) -> values at (x, y); NaN outside the table."""
    ok = (x >= xs[0]) & (x <= xs[-1]) & (y >= ys[0]) & (y <= ys[-1])
    xc, yc = np.clip(x, xs[0], xs[-1]), np.clip(y, ys[0], ys[-1])
    i = np.clip(np.searchsorted(xs, xc, side="right") - 1, 0, len(xs) - 2)
    j = np.clip(np.searchsorted(ys, yc, side="right") - 1, 0, len(ys) - 2)
    tx = (xc - xs[i]) / (xs[i + 1] - xs[i])
    ty = (yc - ys[j]) / (ys[j + 1] - ys[j])
    val = (table[i, j] * (1 - tx) * (1 - ty) + table[i + 1, j] * tx * (1 - ty)
           + table[i, j + 1] * (1 - tx) * ty + table[i + 1, j + 1] * tx * ty)
    return np.where(ok, val, np.nan)


@lru_cache(maxsize=1)
def model_grid() -> dict[str, np.ndarray]:
    """Evolution models on a regular (log mass, log age) grid: Teff, log L, log g, radius and the
    absolute W1 / W2 magnitudes of the Sonora Bobcat atmospheres where they exist (200-2400 K)."""
    log_age = np.linspace(math.log10(AGE_MIN_GYR), math.log10(AGE_MAX_GYR), N_AGE)
    tracks: list[tuple[float, np.ndarray]] = sorted(
        [(m, t) for m, t in _tracks_sonora().items() if m < SEAM_MSUN]
        + [(m, t) for m, t in _tracks_bhac().items() if m >= SEAM_MSUN])
    masses = np.array([m for m, _ in tracks])
    cols = np.full((len(tracks), 4, N_AGE), np.nan)             # log L, log Teff, log g, log R
    for k, (_, t) in enumerate(tracks):
        la = np.log10(t[:, 0])
        inside = (log_age >= la[0]) & (log_age <= la[-1])
        for c, src in enumerate((t[:, 1], np.log10(t[:, 2]), t[:, 3], np.log10(t[:, 4]))):
            cols[k, c, inside] = np.interp(log_age[inside], la, src)
    log_mass = np.linspace(math.log10(masses[0]), math.log10(masses[-1]), N_MASS)
    lm_tracks = np.log10(masses)
    lo = np.clip(np.searchsorted(lm_tracks, log_mass, side="right") - 1, 0, len(masses) - 2)
    w = ((log_mass - lm_tracks[lo]) / (lm_tracks[lo + 1] - lm_tracks[lo]))[:, None, None]
    fine = cols[lo] * (1 - w) + cols[lo + 1] * w                # NaN where either track ends
    logl, teff, logg, radius = fine[:, 0], 10.0 ** fine[:, 1], fine[:, 2], 10.0 ** fine[:, 3]
    mt = _mag_table()
    r_tab = _bilinear(mt["radius"], mt["teff"], mt["logg"], teff, logg)
    dm = -5.0 * np.log10(radius / r_tab)                        # same atmosphere, the track's radius
    return {
        "log_mass": log_mass, "log_age": log_age, "log_l": logl, "teff": teff, "log_g": logg, "radius": radius,
        "m_w1": _bilinear(mt["w1"], mt["teff"], mt["logg"], teff, logg) + dm,
        "m_w2": _bilinear(mt["w2"], mt["teff"], mt["logg"], teff, logg) + dm,
    }


# --------------------------------------------------------------------------------------------
# Posterior summaries
# --------------------------------------------------------------------------------------------

def _quantiles(x: np.ndarray, weight: np.ndarray, qs=(0.16, 0.5, 0.84)) -> list[float] | None:
    """Quantiles of a density sampled on x (weights are per-sample probabilities)."""
    w = np.where(np.isfinite(weight), weight, 0.0)
    if w.sum() <= 0.0:
        return None
    cdf = np.cumsum(w) / w.sum()
    return [float(np.interp(q, cdf, x)) for q in qs]


def _weighted_quantiles(values: np.ndarray, weight: np.ndarray, qs=(0.16, 0.5, 0.84)) -> list[float] | None:
    wmax = np.nanmax(weight) if weight.size else 0.0
    if not (wmax > 0):
        return None
    ok = np.isfinite(values) & (weight > wmax * 1e-6)           # the negligible tail is not worth sorting
    if not ok.any():
        return None
    v, w = values[ok], weight[ok]
    order = np.argsort(v)
    cdf = np.cumsum(w[order]) / w.sum()
    return [float(np.interp(q, cdf, v[order])) for q in qs]


_PRIOR_WIDTH = 0.68 * (AGE_MAX_GYR - AGE_MIN_GYR)


def _age_summary(log_age: np.ndarray, p_age: np.ndarray) -> dict[str, Any] | None:
    q = _quantiles(log_age, p_age)
    if q is None:
        return None
    lo, med, hi = (10.0 ** v for v in q)
    frac = (hi - lo) / _PRIOR_WIDTH
    return {"median_gyr": _sig(med), "lo_gyr": _sig(lo), "hi_gyr": _sig(hi), "interval": "16-84 %",
            "constraint": "unconstrained" if frac > 0.75 else "weak" if frac > 0.4 else "constrained",
            "interval_over_prior": round(frac, 3)}


def _sig(x: float, n: int = 3) -> float:
    if x == 0 or not math.isfinite(x):
        return x
    return float(f"{x:.{n}g}")


def _curve(log_age: np.ndarray, p: np.ndarray | None, n: int = 56) -> list[float] | None:
    """Density per unit age, resampled and scaled to a peak of 1 (for plotting)."""
    if p is None or not np.isfinite(p).any() or np.nanmax(p) <= 0:
        return None
    dens = p / 10.0 ** log_age                                  # per-sample weight -> per unit age
    idx = np.linspace(0, len(log_age) - 1, n).round().astype(int)
    out = dens[idx] / np.nanmax(dens)
    return [round(float(v), 4) for v in out]


# --------------------------------------------------------------------------------------------
# Solver
# --------------------------------------------------------------------------------------------

def solve(observables: dict[str, tuple[float, float]], *, mode: str, kinematic_pdf: np.ndarray | None = None,
          disk: bool = False, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Posterior over (mass, age) for the given observables.

    observables: name -> (value, sigma) among "m_w2" (absolute, Vega), "log_l" (log10 L/Lsun), "teff" (K).
    kinematic_pdf: p(age | U, V, W) on model_grid()["log_age"] (flat prior in age), or None.
    """
    g = model_grid()
    log_age, log_mass = g["log_age"], g["log_mass"]
    age = 10.0 ** log_age
    chi2 = np.zeros((N_MASS, N_AGE))
    for name, (val, sig) in observables.items():
        model = {"m_w2": g["m_w2"], "log_l": g["log_l"], "teff": g["teff"]}[name]
        chi2 = chi2 + ((model - val) / sig) ** 2                # NaN where the models do not reach
    like = np.where(np.isfinite(chi2), np.exp(-0.5 * (chi2 - np.nanmin(chi2))), 0.0) if observables else None

    out: dict[str, Any] = {
        "mode": mode,
        "inputs": inputs or {},
        "assumptions": {
            "age_prior": f"flat in age, {AGE_MIN_GYR:g}-{AGE_MAX_GYR:g} Gyr",
            "mass_prior": "flat in log mass over the model grid",
            "metallicity": "solar ([M/H] = 0)",
            "models": (REFERENCES["sonora_bobcat"] + f" below {SEAM_MSUN} Msun; " + REFERENCES["bhac15"] + " above"),
        },
        "age_grid_gyr": [round(float(10.0 ** v), 5) for v in log_age[np.linspace(0, N_AGE - 1, 56).round().astype(int)]],
    }

    prior_age = age                                              # flat in age on a log grid
    kin = None
    if kinematic_pdf is not None and np.isfinite(kinematic_pdf).all() and kinematic_pdf.max() > 0:
        kin = kinematic_pdf / kinematic_pdf.max()
        out["kinematic"] = {**(_age_summary(log_age, kin * prior_age) or {}), "status": "ok",
                            "method": "p(U, V, W | age) from the age-velocity dispersion relation, flat age prior",
                            "pdf": _curve(log_age, kin * prior_age)}
    else:
        out["kinematic"] = {"status": "unmeasured", "reason": "no space velocity (distance and proper motion needed)"}

    disk_factor = np.exp(-age / DISK_TIMESCALE_GYR) if disk else None
    if disk:
        out["assumptions"]["disk_prior"] = (f"warm disk in the SED: age prior x exp(-age / {DISK_TIMESCALE_GYR * 1000:g} Myr), "
                                            + REFERENCES["disk_lifetime"])

    chi2_min = float(np.nanmin(chi2)) if observables and np.isfinite(chi2).any() else None
    if chi2_min is not None and chi2_min > CHI2_MAX:
        like = None
    if like is None or like.sum() <= 0.0:
        if chi2_min is not None and chi2_min > CHI2_MAX:
            out["spectral"] = {"status": "no_model_match", "chi2_min": round(chi2_min, 2),
                               "reason": (f"the measured values lie outside what the evolution models reach (best chi2 = "
                                          f"{chi2_min:.1f} > {CHI2_MAX:g}); no age or mass is reported from them")}
        else:
            out["spectral"] = {"status": "unmeasured",
                               "reason": (inputs or {}).get("reason") or "no observable the evolution models can be compared with"}
        out["mass"] = None
        if kin is not None:
            out["joint"] = {**out["kinematic"], "method": "kinematic channel only (no spectral constraint)"}
        else:
            out["joint"] = {"status": "unmeasured", "reason": "neither channel has data"}
        return out

    def summarise(post: np.ndarray, label: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        p_age, p_mass = post.sum(axis=0), post.sum(axis=1)
        a = _age_summary(log_age, p_age) or {}
        a.update(status="ok", pdf=_curve(log_age, p_age))
        mq = _quantiles(log_mass, p_mass)
        mass = None
        if mq is not None:
            lo, med, hi = (10.0 ** v for v in mq)
            mass = {"median_msun": _sig(med), "lo_msun": _sig(lo), "hi_msun": _sig(hi),
                    "median_mjup": _sig(med * MJUP_PER_MSUN), "lo_mjup": _sig(lo * MJUP_PER_MSUN),
                    "hi_mjup": _sig(hi * MJUP_PER_MSUN), "interval": "16-84 %", "from": label}
            for key, arr, nd in (("teff_k", g["teff"], 0), ("log_g_cgs", g["log_g"], 2),
                                 ("radius_rjup", g["radius"] * RJUP_PER_RSUN, 3), ("log_l_lsun", g["log_l"], 2)):
                q = _weighted_quantiles(arr.ravel(), post.ravel())
                if q is not None:
                    mass[f"model_{key}"] = {"median": round(q[1], nd), "lo": round(q[0], nd), "hi": round(q[2], nd)}
        return a, mass

    spec_post = like * prior_age[None, :]
    spectral, spec_mass = summarise(spec_post, "spectral")
    spectral["method"] = {"substellar_w2": "absolute W2 vs Sonora Bobcat evolution + atmosphere models",
                          "stellar_hr": "bolometric luminosity and temperature vs BHAC15 tracks"}.get(mode, mode)
    spectral["chi2_min"] = round(float(np.nanmin(chi2)), 3)
    out["spectral"] = spectral
    out["mass_spectral_only"] = spec_mass

    joint_post = spec_post.copy()
    used = ["spectral"]
    if kin is not None:
        joint_post = joint_post * kin[None, :]
        used.append("kinematic")
    if disk_factor is not None:
        joint_post = joint_post * disk_factor[None, :]
        used.append("disk")
    if joint_post.sum() <= 0.0:
        out["joint"] = {"status": "inconsistent", "reason": "the channels do not overlap on the model grid"}
        out["mass"] = spec_mass
    else:
        joint, mass = summarise(joint_post, "joint")
        joint["channels"] = used
        out["joint"], out["mass"] = joint, mass

    # The degeneracy itself: the best-fitting mass at each age (what one observable alone allows).
    track = []
    for j in np.linspace(0, N_AGE - 1, 28).round().astype(int):
        col = like[:, j]
        if col.max() < math.exp(-2.0):
            continue
        i = int(np.argmax(col))
        track.append({"age_gyr": _sig(float(age[j])), "mass_mjup": _sig(float(10.0 ** log_mass[i] * MJUP_PER_MSUN)),
                      "teff_k": round(float(g["teff"][i, j]), 0), "log_g_cgs": round(float(g["log_g"][i, j]), 2)})
    out["degeneracy_track"] = track
    return out


# --------------------------------------------------------------------------------------------
# Observables from the cross-match
# --------------------------------------------------------------------------------------------

W2_WINDOW_UM = (4.2, 5.0)
W2_AB_MINUS_VEGA = 3.339                                        # Jarrett et al. 2011


def spherex_w2_vega(spherex_points: list[dict[str, Any]], n_expected: int | None = None) -> dict[str, Any] | None:
    """W2-like Vega magnitude from the target's own SPHEREx bands in 4.2-5.0 um: the mean F_nu of the
    measured, unblended, S/N >= 3 bands (no W2 response weighting). None with fewer than 6 bands."""
    pts = [p for p in spherex_points if W2_WINDOW_UM[0] <= p["wavelength_um"] <= W2_WINDOW_UM[1]
           and p.get("survey") == "SPHEREx" and p["flux_ujy"] > 0]
    if len(pts) < 6:
        return None
    f = np.array([p["flux_ujy"] for p in pts])
    e = np.array([p.get("flux_err_ujy") or 0.0 for p in pts])
    mean = float(f.mean())
    err = float(math.sqrt(np.sum(e**2)) / len(f))
    return {"mag_vega": round(23.9 - 2.5 * math.log10(mean) - W2_AB_MINUS_VEGA, 3),
            "sigma_mag": round(2.5 / math.log(10.0) * err / mean, 3), "n_bands": len(pts),
            "source": f"SPHEREx, mean F_nu of {len(pts)} measured unblended bands in 4.2-5.0 um"}


def teff_bracket(sed: list[dict[str, Any]]) -> tuple[float, float] | None:
    """Colour temperatures 3670 K um / lambda of the SED points next to the nu F_nu peak: how well the
    sampling pins the Wien peak down."""
    pts = sorted((p["wavelength_um"], p["flux_ujy"] / p["wavelength_um"]) for p in sed
                 if p.get("flux_ujy") and p["flux_ujy"] > 0 and p.get("wavelength_um"))
    if len(pts) < 3:
        return None
    k = max(range(len(pts)), key=lambda i: pts[i][1])
    lo_lam = pts[max(k - 1, 0)][0]
    hi_lam = pts[min(k + 1, len(pts) - 1)][0]
    return 3670.0 / hi_lam, 3670.0 / lo_lam


def blackbody_fraction_beyond(lambda_um: float, teff_k: float) -> float:
    """Fraction of a blackbody's bolometric flux emitted at wavelengths longer than lambda_um."""
    x0 = 14387.77 / (lambda_um * teff_k)
    x = np.linspace(1e-6, x0, 4000)
    y = x**3 / np.expm1(x)
    below = float(np.sum(0.5 * (y[1:] + y[:-1]) * np.diff(x))) * 15.0 / math.pi**4
    return max(0.0, min(1.0, below))


def _planck_ratio(lam1_um: float, lam2_um: float, teff_k: float) -> float:
    """B_nu(lam2) / B_nu(lam1) of a blackbody."""
    x1, x2 = 14387.77 / (lam1_um * teff_k), 14387.77 / (lam2_um * teff_k)
    return (lam1_um / lam2_um) ** 3 * math.expm1(x1) / math.expm1(x2)


SIGMA_SB = 5.670374419e-8
BB_MAX_UM = 5.0


def blackbody_fit(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Blackbody through SED points (least squares in log flux; free temperature and solid angle).

    Used when nothing samples the SED peak (no point between 0.9 and 2.5 um): the trapezoid across
    that gap would lose most of a cool star's light, while a blackbody interpolates the peak.
    Returns T, the T range within 1.5 x the best rms, and F_bol = Omega sigma T^4 / pi."""
    pts = [(p["wavelength_um"], p["flux_ujy"]) for p in points
           if p.get("wavelength_um") and p.get("flux_ujy") and p["flux_ujy"] > 0 and p["wavelength_um"] <= BB_MAX_UM]
    if len(pts) < 3:
        return None
    lam = np.array([p[0] for p in pts])
    logf = np.log10(np.array([p[1] for p in pts]) * 1e-32)            # W m^-2 Hz^-1
    nu = 2.99792458e14 / lam
    temps = np.geomspace(1200.0, 12000.0, 400)
    x = 14387.77 / (lam[None, :] * temps[:, None])
    logb = np.log10(2.0 * 6.62607015e-34 * nu[None, :] ** 3 / 2.99792458e8**2 / np.expm1(x))
    off = (logf[None, :] - logb).mean(axis=1)
    rms = np.sqrt(((logf[None, :] - logb - off[:, None]) ** 2).mean(axis=1))
    k = int(np.argmin(rms))
    ok = temps[rms <= max(1.5 * rms[k], rms[k] + 0.01)]
    t = float(temps[k])
    return {"teff_k": t, "teff_lo_k": float(ok.min()), "teff_hi_k": float(ok.max()), "rms_dex": float(rms[k]),
            "f_bol_wm2": float(10.0 ** off[k] * SIGMA_SB * t**4 / math.pi), "n_points": len(pts),
            "at_grid_edge": k in (0, len(temps) - 1)}


def disk_excess(sed: list[dict[str, Any]], teff_k: float) -> dict[str, Any] | None:
    """Mid-infrared excess over the photosphere: WISE W3 (11.6 um) or W4 (22 um) brighter than
    DISK_EXCESS_FACTOR x the blackbody extrapolation of W1 (3.35 um) at teff_k. None: not testable."""
    w = {round(p["wavelength_um"], 2): p["flux_ujy"] for p in sed if p.get("survey") == "WISE" and p.get("flux_ujy")}
    if 3.35 not in w:
        return None
    ratios = {}
    for lam, name in ((11.56, "W3"), (22.09, "W4")):
        if lam in w:
            ratios[name] = round(w[lam] / (w[3.35] * _planck_ratio(3.35, lam, teff_k)), 2)
    if not ratios:
        return None
    return {"detected": max(ratios.values()) > DISK_EXCESS_FACTOR, "observed_over_photosphere": ratios,
            "photosphere_teff_k": round(teff_k, 0), "threshold": DISK_EXCESS_FACTOR}


def estimate(*, sed: list[dict[str, Any]], sed_physics: dict[str, Any], gaia_rows: list[dict[str, Any]],
             wise_rows: list[dict[str, Any]], spherex_points: list[dict[str, Any]], astrometry: dict[str, Any],
             galactic: dict[str, Any], object_class: str | None, distance_au: float | None) -> dict[str, Any]:
    """Age and mass of the cross-matched source, or the reason they cannot be measured."""
    if distance_au is not None:
        return {"status": "not_applicable", "reason": "solar-system body: no stellar or substellar evolution track applies"}
    if object_class == "high_z_galaxy":
        return {"status": "not_applicable", "reason": "extragalactic source: stellar evolution tracks do not apply"}
    d_pc = astrometry.get("distance_pc") if astrometry else None
    g = model_grid()
    kin_pdf = None
    if galactic.get("status") == "ok":
        from .kinematics import kinematic_age_pdf

        kin_pdf = kinematic_age_pdf(galactic, 10.0 ** g["log_age"])
    inputs: dict[str, Any] = {"distance_pc": d_pc, "distance_source": (astrometry or {}).get("distance_source")}
    if not isinstance(d_pc, (int, float)) or d_pc <= 0:
        out = solve({}, mode="none", kinematic_pdf=kin_pdf,
                    inputs={**inputs, "reason": "no parallax or distance: luminosity and absolute magnitude unknown"})
        out["status"] = "partial" if kin_pdf is not None else "unmeasured"
        return _with_references(out, kin_pdf)
    dist_mod = 5.0 * math.log10(d_pc / 10.0)
    sigma_d_mag = 0.0
    if isinstance(astrometry.get("distance_err_pc"), (int, float)):
        sigma_d_mag = 5.0 / math.log(10.0) * float(astrometry["distance_err_pc"]) / d_pc
    # A source Gaia sees with a parallax is a star (or a bright late-M / L dwarf): the stellar tracks
    # apply. Anything Gaia does not measure is fitted as a substellar object through its W2 brightness.
    has_gaia_parallax = bool(gaia_rows) and isinstance(gaia_rows[0].get("parallax_mas"), (int, float))

    obs: dict[str, tuple[float, float]] = {}
    disk = False
    if not has_gaia_parallax:
        mode = "substellar_w2"
        w2 = spherex_w2_vega(spherex_points)
        if w2 is None and wise_rows and wise_rows[0].get("w2mpro") is not None:
            w2 = {"mag_vega": float(wise_rows[0]["w2mpro"]), "sigma_mag": float(wise_rows[0].get("w2sigmpro") or 0.05),
                  "source": "AllWISE w2mpro"}
        if w2 is not None:
            m_abs = w2["mag_vega"] - dist_mod
            sigma = math.sqrt(w2["sigma_mag"] ** 2 + sigma_d_mag**2 + MODEL_SYSTEMATIC_MAG**2)
            obs["m_w2"] = (m_abs, sigma)
            inputs.update(w2_vega=w2["mag_vega"], w2_source=w2["source"], m_w2_abs=round(m_abs, 3),
                          m_w2_sigma=round(sigma, 3), model_systematic_mag_assumed=MODEL_SYSTEMATIC_MAG)
            if wise_rows and wise_rows[0].get("w2mpro") is not None:
                inputs["allwise_w2_vega"] = float(wise_rows[0]["w2mpro"])
        else:
            inputs["reason"] = "no W2 measurement (neither SPHEREx 4.2-5.0 um bands nor AllWISE)"
    else:
        from .sed_fitter import _fit_points

        mode = "stellar_hr"
        phot = [p for p in sed if p.get("wavelength_um") and p["wavelength_um"] <= PHOTOSPHERE_MAX_UM]
        has_nir = any(0.9 <= p["wavelength_um"] <= PHOTOSPHERE_MAX_UM for p in phot)
        teff = sigma_t = f_bol = None
        inputs["sed_sampled_0p9_2p5um"] = has_nir
        if has_nir:
            # SPHEREx samples the SED peak: model-free numbers (Wien peak, trapezoid integral).
            phot_fit = _fit_points(phot) if len(phot) >= 3 else None
            br = teff_bracket(phot) if phot_fit else None
            if phot_fit and br:
                teff = float(phot_fit["teff_sed_k"])
                sigma_t = max(0.5 * (br[1] - br[0]), TEFF_FLOOR_FRAC * teff)
                excess = disk_excess(sed, max(br[0], 2000.0))
                disk = bool(excess and excess["detected"])
                if excess:
                    inputs["mid_ir_excess"] = excess
                if disk:
                    tail = blackbody_fraction_beyond(PHOTOSPHERE_MAX_UM, teff)
                    f_bol = phot_fit["bolometric_flux_wm2"] / (1.0 - tail) if tail < 0.9 else None
                    note = (f"photosphere only: 4 pi d^2 x the SED integral below {PHOTOSPHERE_MAX_UM} um plus the blackbody "
                            f"tail beyond it ({tail:.0%}); the disk excess is left out; no extinction correction")
                else:
                    f_bol = sed_physics.get("bolometric_flux_wm2")
                    note = "4 pi d^2 x the 0.4-22 um SED integral; no extinction correction"
                inputs["teff_note"] = "colour temperature of the nu F_nu peak below 2.5 um; sigma from the neighbouring SED points"
            floor = LOG_L_FLOOR_DEX
        else:
            # Nothing between 0.9 and 2.5 um (no usable SPHEREx bands): a blackbody through Gaia + W1 / W2.
            bb = blackbody_fit(sed)
            if bb is not None:
                excess = disk_excess(sed, max(bb["teff_lo_k"], 2000.0))
                disk = bool(excess and excess["detected"])
                if excess:
                    inputs["mid_ir_excess"] = excess
                if disk:                                             # W1 / W2 carry disk light: optical points only
                    bb = blackbody_fit(phot)
            if bb is not None and not bb["at_grid_edge"]:
                teff = bb["teff_k"]
                sigma_t = max(0.5 * (bb["teff_hi_k"] - bb["teff_lo_k"]), TEFF_FLOOR_FRAC * teff)
                f_bol = bb["f_bol_wm2"]
                note = (f"4 pi d^2 x the bolometric flux of a blackbody fitted to {bb['n_points']} "
                        f"{'optical (Gaia)' if disk else 'Gaia + WISE W1/W2'} points (rms {bb['rms_dex']:.2f} dex): the SED peak "
                        "is not sampled; no extinction correction")
                inputs["teff_note"] = "temperature of the fitted blackbody; sigma: the range within 1.5 x the best rms"
            floor = LOG_L_FLOOR_SPARSE_DEX
        if disk:
            inputs["disk"] = "mid-infrared excess over the photosphere (warm circumstellar dust)"
        if isinstance(f_bol, (int, float)) and f_bol > 0:
            log_l = math.log10(4.0 * math.pi * (d_pc * PC_M) ** 2 * f_bol / LSUN_W)
            sigma = math.sqrt(floor**2 + (0.4 * sigma_d_mag) ** 2)
            obs["log_l"] = (log_l, sigma)
            inputs.update(log_l_lsun=round(log_l, 3), log_l_sigma=round(sigma, 3), log_l_note=note,
                          log_l_floor_dex_assumed=floor)
        if teff is not None and sigma_t is not None:
            obs["teff"] = (teff, sigma_t)
            inputs.update(teff_k=round(teff, 0), teff_sigma_k=round(sigma_t, 0))
        if not obs:
            inputs["reason"] = "no usable SED (bolometric flux or colour temperature)"
    out = solve(obs, mode=mode, kinematic_pdf=kin_pdf, disk=disk, inputs=inputs)
    out["status"] = "ok" if out["spectral"].get("status") == "ok" else ("partial" if kin_pdf is not None else "unmeasured")
    return _with_references(out, kin_pdf)


def _with_references(out: dict[str, Any], kin_pdf: np.ndarray | None) -> dict[str, Any]:
    out["references"] = dict(REFERENCES)
    if kin_pdf is not None:
        from .kinematics import AVR_REFERENCE

        out["references"]["age_velocity_relation"] = AVR_REFERENCE
    return out
