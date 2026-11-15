"""Stage 3, regime A: the orbit of a star or brown dwarf in the Milky Way, and its closest approach
to the Sun.

Stars and brown dwarfs do not orbit the Sun: they orbit the Galactic centre. Their past and future
are integrated with galpy in MWPotential2014 (Bovy 2015, ApJS 216, 29), with R0 = 8 kpc,
V0 = 220 km/s and the solar motion of Schoenrich, Binney & Dehnen (2010), (11.1, 12.24, 7.25) km/s.

- Galactic orbit: +/- span_myr (default 250 Myr) from today; peri/apocentre, maximum height above
  the plane and eccentricity e = (r_apo - r_peri) / (r_apo + r_peri) over that span.
- Solar encounter: the Sun and the object are integrated together for +/- encounter_kyr (default
  50 kyr); the minimum of their separation is the closest approach (d_min, t_min). A straight-line
  estimate is reported next to it as a check.

A radial velocity that was not measured is not invented: the orbit is then integrated for
RV = -30, 0 and +30 km/s (rv_status "marginalized_envelope") and every solution is returned.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

try:  # pragma: no cover - availability depends on platform wheels
    import galpy

    GALPY_VERSION: str | None = galpy.__version__
except Exception:  # pragma: no cover
    galpy = None
    GALPY_VERSION = None

R0_KPC, V0_KM_S = 8.0, 220.0
SOLAR_MOTION_KM_S = (11.1, 12.24, 7.25)
RV_ENVELOPE_KM_S = (-30.0, 0.0, 30.0)
KM_S_PER_AU_YR = 4.740470464
PC_PER_KM_S_KYR = 1.0227121650537077e-3          # 1 km/s for 1 kyr, in pc
MAX_SPAN_MYR, MAX_ENCOUNTER_KYR = 1000.0, 500.0
N_ORBIT, N_ENCOUNTER = 400, 1000


class GalacticError(ValueError):
    pass


def _orbit(ra: float, dec: float, d_kpc: float, pmra: float, pmdec: float, rv: float):
    from galpy.orbit import Orbit

    return Orbit([ra, dec, d_kpc, pmra, pmdec, rv], radec=True, ro=R0_KPC, vo=V0_KM_S, solarmotion="schoenrich")


def _sun():
    from galpy.orbit import Orbit

    return Orbit(ro=R0_KPC, vo=V0_KM_S, solarmotion="schoenrich")


def _integrate(o, t_myr: np.ndarray):
    import astropy.units as u
    from galpy.potential import MWPotential2014

    o.integrate(t_myr * u.Myr, MWPotential2014)
    return o


def _xyz(o, t_myr: np.ndarray) -> np.ndarray:
    """Galactocentric Cartesian positions in kpc at the integration times."""
    import astropy.units as u

    t = t_myr * u.Myr
    return np.vstack([np.atleast_1d(o.x(t)), np.atleast_1d(o.y(t)), np.atleast_1d(o.z(t))]).astype(float)


def _galactic_orbit(ra, dec, d_kpc, pmra, pmdec, rv, span_myr: float, n_samples: int) -> dict[str, Any]:
    halves = []
    for sign in (-1.0, 1.0):
        t = sign * np.linspace(0.0, span_myr, N_ORBIT + 1)
        o = _integrate(_orbit(ra, dec, d_kpc, pmra, pmdec, rv), t)
        xyz = _xyz(o, t)
        halves.append((t, xyz))
    (tb, xb), (tf, xf) = halves
    t = np.concatenate([tb[::-1], tf[1:]])
    xyz = np.concatenate([xb[:, ::-1], xf[:, 1:]], axis=1)
    big_r = np.hypot(xyz[0], xyz[1])
    r = np.sqrt(big_r**2 + xyz[2] ** 2)
    r_peri, r_apo = float(r.min()), float(r.max())
    step = max(1, (len(t) - 1) // max(n_samples, 2))
    idx = np.arange(0, len(t), step)
    return {
        "rv_km_s": rv,
        "r_peri_kpc": round(r_peri, 4), "r_apo_kpc": round(r_apo, 4),
        "z_max_kpc": round(float(np.abs(xyz[2]).max()), 4),
        "eccentricity": round((r_apo - r_peri) / (r_apo + r_peri), 4),
        "trajectory": {
            "t_myr": [round(float(v), 3) for v in t[idx]],
            "x_kpc": [round(float(v), 4) for v in xyz[0][idx]],
            "y_kpc": [round(float(v), 4) for v in xyz[1][idx]],
            "z_kpc": [round(float(v), 4) for v in xyz[2][idx]],
            "r_kpc": [round(float(v), 4) for v in big_r[idx]],
        },
    }


def _helio_velocity_icrs(ra, dec, d_pc, pmra, pmdec, rv) -> tuple[np.ndarray, np.ndarray]:
    a, d = math.radians(ra), math.radians(dec)
    r_hat = np.array([math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d)])
    e_hat = np.array([-math.sin(a), math.cos(a), 0.0])
    n_hat = np.array([-math.sin(d) * math.cos(a), -math.sin(d) * math.sin(a), math.cos(d)])
    k = KM_S_PER_AU_YR * d_pc / 1000.0
    return r_hat * d_pc, rv * r_hat + k * pmra * e_hat + k * pmdec * n_hat


def _encounter(ra, dec, d_kpc, pmra, pmdec, rv, window_kyr: float, n_samples: int) -> dict[str, Any]:
    ts, sep = [], []
    for sign in (-1.0, 1.0):
        t = sign * np.linspace(0.0, window_kyr / 1000.0, N_ENCOUNTER + 1)
        star = _xyz(_integrate(_orbit(ra, dec, d_kpc, pmra, pmdec, rv), t), t)
        sun = _xyz(_integrate(_sun(), t), t)
        ts.append(t * 1000.0)
        sep.append(np.linalg.norm(star - sun, axis=0) * 1000.0)       # pc
    t = np.concatenate([ts[0][::-1], ts[1][1:]])
    d = np.concatenate([sep[0][::-1], sep[1][1:]])
    i = int(np.argmin(d))
    at_edge = i in (0, len(d) - 1)
    t_min, d_min = float(t[i]), float(d[i])
    if not at_edge:                                                   # parabola through the three lowest samples
        y0, y1, y2 = d[i - 1], d[i], d[i + 1]
        denom = y0 - 2 * y1 + y2
        if denom > 0:
            off = 0.5 * (y0 - y2) / denom
            t_min = float(t[i] + off * (t[1] - t[0]))
            d_min = float(y1 - 0.25 * (y0 - y2) * off)
    # straight-line check: constant heliocentric velocity
    r0, v = _helio_velocity_icrs(ra, dec, d_kpc * 1000.0, pmra, pmdec, rv)
    v2 = float(v @ v)
    t_lin = -float(r0 @ v) / v2 / PC_PER_KM_S_KYR if v2 > 0 else 0.0
    d_lin = float(np.linalg.norm(r0 + v * t_lin * PC_PER_KM_S_KYR))
    step = max(1, (len(t) - 1) // max(n_samples, 2))
    idx = np.arange(0, len(t), step)
    return {
        "rv_km_s": rv,
        "status": "beyond_window" if at_edge else "found",
        "t_min_kyr": round(t_min, 3), "d_min_pc": round(d_min, 4),
        "d_now_pc": round(float(d[len(d) // 2]), 4),
        "linear_check": {"t_min_kyr": round(t_lin, 3), "d_min_pc": round(d_lin, 4)},
        "curve": {"t_kyr": [round(float(x), 3) for x in t[idx]], "distance_pc": [round(float(x), 4) for x in d[idx]]},
    }


def simulate(ra: float, dec: float, distance_pc: float, pm_ra_cosdec_mas_yr: float, pm_dec_mas_yr: float,
             radial_velocity_km_s: float | None = None, span_myr: float = 250.0, encounter_kyr: float = 50.0,
             n_samples: int = 200) -> dict[str, Any]:
    """Galactic orbit and solar encounter; see the module docstring."""
    if galpy is None:  # pragma: no cover
        raise GalacticError("galpy is not installed in this deployment.")
    if not (distance_pc > 0 and math.isfinite(distance_pc)):
        raise GalacticError("distance_pc must be positive.")
    if not (0 < span_myr <= MAX_SPAN_MYR) or not (0 < encounter_kyr <= MAX_ENCOUNTER_KYR):
        raise GalacticError(f"span_myr must be in (0, {MAX_SPAN_MYR:g}] and encounter_kyr in (0, {MAX_ENCOUNTER_KYR:g}].")
    measured = radial_velocity_km_s is not None
    rvs = [float(radial_velocity_km_s)] if measured else list(RV_ENVELOPE_KM_S)
    d_kpc = distance_pc / 1000.0
    orbits = [_galactic_orbit(ra, dec, d_kpc, pm_ra_cosdec_mas_yr, pm_dec_mas_yr, rv, span_myr, n_samples) for rv in rvs]
    encounters = [_encounter(ra, dec, d_kpc, pm_ra_cosdec_mas_yr, pm_dec_mas_yr, rv, encounter_kyr, n_samples) for rv in rvs]
    sun = _galactic_orbit_sun(span_myr, n_samples)
    out: dict[str, Any] = {
        "engine": f"galpy-{GALPY_VERSION}/MWPotential2014",
        "potential": "MWPotential2014 (Bovy 2015, ApJS 216, 29)",
        "r0_kpc": R0_KPC, "v0_km_s": V0_KM_S, "solar_motion_km_s": list(SOLAR_MOTION_KM_S),
        "rv_status": "measured" if measured else "marginalized_envelope",
        "span_myr": span_myr, "encounter_window_kyr": encounter_kyr,
        "input": {"ra": ra, "dec": dec, "distance_pc": distance_pc, "pm_ra_cosdec_mas_yr": pm_ra_cosdec_mas_yr,
                  "pm_dec_mas_yr": pm_dec_mas_yr, "radial_velocity_km_s": radial_velocity_km_s},
        "orbits": orbits, "encounters": encounters, "sun": sun,
    }
    keys = ("r_peri_kpc", "r_apo_kpc", "z_max_kpc", "eccentricity")
    if measured:
        out["summary"] = {k: orbits[0][k] for k in keys}
        out["summary"].update(t_min_kyr=encounters[0]["t_min_kyr"], d_min_pc=encounters[0]["d_min_pc"],
                              encounter_status=encounters[0]["status"])
    else:
        out["summary"] = {k: [min(o[k] for o in orbits), max(o[k] for o in orbits)] for k in keys}
        out["summary"].update(
            t_min_kyr=[min(e["t_min_kyr"] for e in encounters), max(e["t_min_kyr"] for e in encounters)],
            d_min_pc=[min(e["d_min_pc"] for e in encounters), max(e["d_min_pc"] for e in encounters)],
            encounter_status="found" if all(e["status"] == "found" for e in encounters) else "beyond_window")
        out["rv_note"] = ("no measured radial velocity: orbits for RV = -30, 0 and +30 km/s; ranges are the "
                          "envelope of the three, not a 1-sigma interval")
    return out


def _galactic_orbit_sun(span_myr: float, n_samples: int) -> dict[str, Any]:
    halves = []
    for sign in (-1.0, 1.0):
        t = sign * np.linspace(0.0, span_myr, N_ORBIT + 1)
        halves.append((t, _xyz(_integrate(_sun(), t), t)))
    (tb, xb), (tf, xf) = halves
    t = np.concatenate([tb[::-1], tf[1:]])
    xyz = np.concatenate([xb[:, ::-1], xf[:, 1:]], axis=1)
    step = max(1, (len(t) - 1) // max(n_samples, 2))
    idx = np.arange(0, len(t), step)
    return {"t_myr": [round(float(v), 3) for v in t[idx]], "x_kpc": [round(float(v), 4) for v in xyz[0][idx]],
            "y_kpc": [round(float(v), 4) for v in xyz[1][idx]], "z_kpc": [round(float(v), 4) for v in xyz[2][idx]],
            "r_kpc": [round(float(v), 4) for v in np.hypot(xyz[0], xyz[1])[idx]]}
