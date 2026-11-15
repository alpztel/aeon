"""Stage 2, kinematic channel: Galactic space velocity (U, V, W), population membership and the
age that the age-velocity dispersion relation allows.

Every coefficient is a published one:
- Solar motion w.r.t. the LSR (U, V, W) = (11.1, 12.24, 7.25) km/s: Schoenrich, Binney & Dehnen 2010,
  MNRAS 403, 1829.
- Age-velocity dispersion relation sigma_i(tau) = v10 ((tau + tau1) / (10 Gyr + tau1))^beta for the
  U, V, W components: Aumer & Binney 2009, MNRAS 397, 1286, eq. 16 and Table 6. This is the modern
  fit of the disc-heating law of Wielen (1977, beta = 1/2); the exponents of Holmberg et al. (2009),
  0.39 / 0.40 / 0.53, are discussed against it in the same paper.
- Thin disk / thick disk / halo / Hercules velocity ellipsoids and local fractions: Bensby, Feltzing &
  Oey 2014, A&A 562, A71, Table A.1.

A radial velocity that nobody measured is never invented: the velocity is then computed for
RV = -30, 0 and +30 km/s and reported as an envelope (rv_status "marginalized_envelope").
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

SOLAR_MOTION_KM_S = (11.1, 12.24, 7.25)
RV_ENVELOPE_KM_S = (-30.0, 0.0, 30.0)

# component: (beta, tau1 [Gyr], v10 [km/s])   Aumer & Binney 2009, Table 6
AVR_COMPONENTS = {"U": (0.307, 0.001, 41.899), "V": (0.430, 0.715, 28.823), "W": (0.445, 0.001, 23.831)}
AVR_REFERENCE = "Aumer & Binney 2009, MNRAS 397, 1286 (eq. 16, Table 6)"

# population: (sigma_U, sigma_V, sigma_W, U_asym, V_asym, local fraction X)   Bensby et al. 2014, Table A.1
POPULATIONS = {
    "thin_disk": (35.0, 20.0, 16.0, 0.0, -15.0, 0.85),
    "thick_disk": (67.0, 38.0, 35.0, 0.0, -46.0, 0.09),
    "halo": (160.0, 90.0, 90.0, 0.0, -220.0, 0.0015),
    "hercules": (26.0, 9.0, 17.0, -40.0, -50.0, 0.06),
}
POPULATION_REFERENCE = "Bensby, Feltzing & Oey 2014, A&A 562, A71 (Table A.1)"

KM_S_PER_AU_YR = 4.740470464          # 1 AU/yr in km/s


def _galactic_basis() -> np.ndarray:
    """Rows: unit vectors of Galactic x (to the centre), y (rotation), z (north pole) in ICRS."""
    from astropy.coordinates import Galactic, SkyCoord
    import astropy.units as u

    rows = []
    for lon, lat in ((0.0, 0.0), (90.0, 0.0), (0.0, 90.0)):
        c = SkyCoord(l=lon * u.deg, b=lat * u.deg, frame=Galactic()).icrs
        ra, dec = math.radians(c.ra.deg), math.radians(c.dec.deg)
        rows.append([math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)])
    return np.array(rows)


_BASIS: np.ndarray | None = None


def heliocentric_uvw(ra_deg: float, dec_deg: float, distance_pc: float, pm_ra_cosdec_mas_yr: float,
                     pm_dec_mas_yr: float, rv_km_s: float) -> tuple[float, float, float]:
    """Heliocentric (U, V, W) in km/s; U towards the Galactic centre, V along rotation, W to the
    north Galactic pole (right-handed)."""
    global _BASIS
    if _BASIS is None:
        _BASIS = _galactic_basis()
    a, d = math.radians(ra_deg), math.radians(dec_deg)
    r_hat = np.array([math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d)])
    e_hat = np.array([-math.sin(a), math.cos(a), 0.0])
    n_hat = np.array([-math.sin(d) * math.cos(a), -math.sin(d) * math.sin(a), math.cos(d)])
    k = KM_S_PER_AU_YR * distance_pc / 1000.0            # mas/yr x pc -> km/s
    v_icrs = rv_km_s * r_hat + k * pm_ra_cosdec_mas_yr * e_hat + k * pm_dec_mas_yr * n_hat
    u, v, w = _BASIS @ v_icrs
    return float(u), float(v), float(w)


def avr_sigma(component: str, age_gyr: np.ndarray | float) -> np.ndarray:
    beta, tau1, v10 = AVR_COMPONENTS[component]
    return v10 * ((np.asarray(age_gyr, dtype=float) + tau1) / (10.0 + tau1)) ** beta


def age_likelihood(u_lsr: float, v_lsr: float, w_lsr: float, ages_gyr: np.ndarray) -> np.ndarray:
    """p(U, V, W | age): one star drawn from the velocity ellipsoid of its age group (zero mean in the
    LSR; the asymmetric drift of old groups is neglected, which makes old ages slightly less likely)."""
    out = np.ones_like(ages_gyr, dtype=float)
    for comp, val in (("U", u_lsr), ("V", v_lsr), ("W", w_lsr)):
        s = avr_sigma(comp, ages_gyr)
        out *= np.exp(-0.5 * (val / s) ** 2) / (s * math.sqrt(2.0 * math.pi))
    return out


def membership(u_lsr: float, v_lsr: float, w_lsr: float) -> dict[str, Any]:
    """Relative probabilities of the Bensby et al. (2014) populations (their eq. A.1 x local fraction)."""
    f: dict[str, float] = {}
    for name, (su, sv, sw, ua, va, x) in POPULATIONS.items():
        k = 1.0 / ((2.0 * math.pi) ** 1.5 * su * sv * sw)
        f[name] = x * k * math.exp(-((u_lsr - ua) ** 2) / (2 * su**2) - ((v_lsr - va) ** 2) / (2 * sv**2)
                                   - (w_lsr**2) / (2 * sw**2))
    total = sum(f.values())
    if total <= 0.0:
        return {"probabilities": None, "most_likely": None, "td_over_d": None}
    probs = {k: round(v / total, 4) for k, v in f.items()}
    return {"probabilities": probs, "most_likely": max(probs, key=probs.get),
            "td_over_d": round(f["thick_disk"] / f["thin_disk"], 4) if f["thin_disk"] > 0 else None}


def space_velocity(astrometry: dict[str, Any] | None) -> dict[str, Any]:
    """U, V, W w.r.t. the LSR from an astrometry record (see crossmatch._aeon_astrometry).

    Needs a position, a distance and a proper motion. With a measured RV there is one solution; with
    none there are three (RV_ENVELOPE_KM_S) and the envelope of each component is reported."""
    a = astrometry or {}
    need = ("ra", "dec", "distance_pc", "pm_ra_cosdec_mas_yr", "pm_dec_mas_yr")
    missing = [k for k in need if not isinstance(a.get(k), (int, float)) or not math.isfinite(float(a[k]))]
    if missing or float(a.get("distance_pc") or 0.0) <= 0.0:
        return {"status": "unmeasured", "reason": "no " + ", ".join(missing or ["distance_pc"]),
                "inputs": a or None}
    rv = a.get("radial_velocity_km_s")
    measured = isinstance(rv, (int, float)) and math.isfinite(float(rv))
    rvs = [float(rv)] if measured else list(RV_ENVELOPE_KM_S)
    solutions = []
    for r in rvs:
        uh, vh, wh = heliocentric_uvw(float(a["ra"]), float(a["dec"]), float(a["distance_pc"]),
                                      float(a["pm_ra_cosdec_mas_yr"]), float(a["pm_dec_mas_yr"]), r)
        u, v, w = uh + SOLAR_MOTION_KM_S[0], vh + SOLAR_MOTION_KM_S[1], wh + SOLAR_MOTION_KM_S[2]
        solutions.append({
            "rv_km_s": r, "u_lsr_km_s": round(u, 2), "v_lsr_km_s": round(v, 2), "w_lsr_km_s": round(w, 2),
            "v_tot_km_s": round(math.sqrt(u * u + v * v + w * w), 2),
            "u_helio_km_s": round(uh, 2), "v_helio_km_s": round(vh, 2), "w_helio_km_s": round(wh, 2),
            "membership": membership(u, v, w),
        })
    out: dict[str, Any] = {
        "status": "ok", "inputs": a,
        "rv_status": "measured" if measured else "marginalized_envelope",
        "solar_motion_km_s": list(SOLAR_MOTION_KM_S),
        "frame": "LSR, right-handed: U to the Galactic centre, V along rotation, W to the north Galactic pole",
        "solutions": solutions,
        "references": {"solar_motion": "Schoenrich, Binney & Dehnen 2010, MNRAS 403, 1829",
                       "membership": POPULATION_REFERENCE},
    }
    if not measured:
        out["envelope"] = {k: [min(s[k] for s in solutions), max(s[k] for s in solutions)]
                           for k in ("u_lsr_km_s", "v_lsr_km_s", "w_lsr_km_s", "v_tot_km_s")}
        out["rv_note"] = ("no measured radial velocity: U, V, W are given for RV = -30, 0 and +30 km/s; "
                          "the tangential part (proper motion x distance) is measured")
    return out


def kinematic_age_pdf(galactic: dict[str, Any], ages_gyr: np.ndarray) -> np.ndarray | None:
    """p(age | U, V, W) on ages_gyr for a flat age prior (not normalised). With an RV envelope the
    three solutions are averaged with equal weight."""
    if galactic.get("status") != "ok":
        return None
    acc = np.zeros_like(ages_gyr, dtype=float)
    for s in galactic["solutions"]:
        acc += age_likelihood(s["u_lsr_km_s"], s["v_lsr_km_s"], s["w_lsr_km_s"], ages_gyr)
    return acc / len(galactic["solutions"])
