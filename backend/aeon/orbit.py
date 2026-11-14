"""N-body orbit forecasts with REBOUND (Sun + Jupiter, Saturn, Uranus, Neptune + test particle).

Units: AU, yr, Msun (G = 4 pi^2). Frame: heliocentric ecliptic J2000. Planet initial conditions
come from the JPL approximate Keplerian elements (Standish, valid 1800-2050) propagated to the
start epoch with their mean-longitude rates. A pure-numpy leapfrog integrator is used only if the
REBOUND C library is unavailable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

try:  # pragma: no cover - availability depends on platform wheels
    import rebound

    REBOUND_VERSION: str | None = rebound.__version__
except Exception:  # pragma: no cover
    rebound = None
    REBOUND_VERSION = None

OBLIQUITY_RAD = math.radians(23.4392911)
KM_S_TO_AU_YR = 0.210945021
AU_KM = 149_597_870.7
G = 4 * math.pi**2


@dataclass(frozen=True)
class PlanetElements:
    name: str
    mass_msun: float
    a: float
    e: float
    inc: float          # deg
    L: float            # mean longitude at J2000, deg
    varpi: float        # longitude of perihelion, deg
    Omega: float        # deg
    L_rate: float       # deg / century


# JPL "Keplerian Elements for Approximate Positions of the Major Planets", Table 1.
PLANETS = (
    PlanetElements("Jupiter", 9.547919e-4, 5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909, 3034.74612775),
    PlanetElements("Saturn", 2.858860e-4, 9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448, 1222.49362201),
    PlanetElements("Uranus", 4.366244e-5, 19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.95427630, 74.01692503, 428.48202785),
    PlanetElements("Neptune", 5.151389e-5, 30.06992276, 0.00859048, 1.77004347, -55.12002969, 44.96476227, 131.78422574, 218.45945325),
)


# --------------------------------------------------------------------------------------------
# Coordinate helpers
# --------------------------------------------------------------------------------------------

def eq_to_ecl(v: np.ndarray) -> np.ndarray:
    c, s = math.cos(OBLIQUITY_RAD), math.sin(OBLIQUITY_RAD)
    x, y, z = v
    return np.array([x, c * y + s * z, -s * y + c * z])


def ecl_to_eq(v: np.ndarray) -> np.ndarray:
    c, s = math.cos(OBLIQUITY_RAD), math.sin(OBLIQUITY_RAD)
    x, y, z = v
    return np.array([x, c * y - s * z, s * y + c * z])


def radec_of(xyz_ecl: np.ndarray) -> tuple[float, float, float]:
    v = ecl_to_eq(np.asarray(xyz_ecl, dtype=float))
    r = float(np.linalg.norm(v))
    return math.degrees(math.atan2(v[1], v[0])) % 360.0, math.degrees(math.asin(v[2] / r)), r


def state_from_observation(ra: float, dec: float, distance_au: float, rate_arcsec_yr: float = 0.0,
                           pa_deg: float = 0.0, radial_velocity_km_s: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Heliocentric ecliptic position/velocity from a heliocentric direction, distance and
    heliocentric angular motion (Earth-reflex parallax already removed)."""
    a, d, pa = math.radians(ra), math.radians(dec), math.radians(pa_deg)
    r_hat = np.array([math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d)])
    e_hat = np.array([-math.sin(a), math.cos(a), 0.0])
    n_hat = np.array([-math.sin(d) * math.cos(a), -math.sin(d) * math.sin(a), math.cos(d)])
    mu = rate_arcsec_yr / 206264.806                          # rad / yr
    v = distance_au * mu * (math.sin(pa) * e_hat + math.cos(pa) * n_hat) + radial_velocity_km_s * KM_S_TO_AU_YR * r_hat
    return eq_to_ecl(distance_au * r_hat), eq_to_ecl(v)


def kepler_state(a: float, e: float, inc: float, Omega: float, omega: float, M: float,
                 mu: float = G) -> tuple[np.ndarray, np.ndarray]:
    """Elements (AU, rad) -> heliocentric ecliptic state. Elliptic orbits only."""
    E = M
    for _ in range(50):
        dE = (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
        E -= dE
        if abs(dE) < 1e-14:
            break
    nu = 2 * math.atan2(math.sqrt(1 + e) * math.sin(E / 2), math.sqrt(1 - e) * math.cos(E / 2))
    r = a * (1 - e * math.cos(E))
    p = a * (1 - e * e)
    h = math.sqrt(mu * p)
    pos_pf = np.array([r * math.cos(nu), r * math.sin(nu), 0.0])
    vel_pf = np.array([-mu / h * math.sin(nu), mu / h * (e + math.cos(nu)), 0.0])
    cO, sO, ci, si, cw, sw = math.cos(Omega), math.sin(Omega), math.cos(inc), math.sin(inc), math.cos(omega), math.sin(omega)
    R = np.array([
        [cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci, sO * si],
        [sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci, -cO * si],
        [sw * si, cw * si, ci],
    ])
    return R @ pos_pf, R @ vel_pf


def elements_from_state(r: np.ndarray, v: np.ndarray, mu: float = G) -> dict:
    r = np.asarray(r, float)
    v = np.asarray(v, float)
    rn, vn = np.linalg.norm(r), np.linalg.norm(v)
    h = np.cross(r, v)
    hn = np.linalg.norm(h)
    n = np.cross([0, 0, 1.0], h)
    nn = np.linalg.norm(n)
    evec = ((vn**2 - mu / rn) * r - np.dot(r, v) * v) / mu
    e = float(np.linalg.norm(evec))
    energy = vn**2 / 2 - mu / rn
    a = -mu / (2 * energy) if abs(energy) > 1e-15 else math.inf
    inc = math.acos(np.clip(h[2] / hn, -1, 1))
    Omega = math.atan2(n[1], n[0]) if nn > 1e-12 else 0.0
    if nn > 1e-12 and e > 1e-10:
        omega = math.acos(np.clip(np.dot(n, evec) / (nn * e), -1, 1))
        if evec[2] < 0:
            omega = 2 * math.pi - omega
    else:
        omega = 0.0
    if e > 1e-10:
        nu = math.acos(np.clip(np.dot(evec, r) / (e * rn), -1, 1))
        if np.dot(r, v) < 0:
            nu = 2 * math.pi - nu
    else:
        nu = 0.0
    out = {"a_au": a, "e": e, "inc_deg": math.degrees(inc), "Omega_deg": math.degrees(Omega) % 360,
           "omega_deg": math.degrees(omega) % 360, "true_anomaly_deg": math.degrees(nu) % 360}
    if e < 1:
        E = 2 * math.atan2(math.sqrt(1 - e) * math.sin(nu / 2), math.sqrt(1 + e) * math.cos(nu / 2))
        out["M_deg"] = math.degrees(E - e * math.sin(E)) % 360
        out["perihelion_au"] = a * (1 - e)
        out["aphelion_au"] = a * (1 + e)
    return out


def planet_states(t_year: float) -> list[tuple[PlanetElements, np.ndarray, np.ndarray]]:
    T = (t_year - 2000.0) / 100.0
    out = []
    for p in PLANETS:
        L = p.L + p.L_rate * T
        M = math.radians((L - p.varpi) % 360.0)
        omega = math.radians(p.varpi - p.Omega)
        r, v = kepler_state(p.a, p.e, math.radians(p.inc), math.radians(p.Omega), omega, M, G * (1 + p.mass_msun))
        out.append((p, r, v))
    return out


def ellipse_points(el: dict, n: int = 361) -> list[list[float]]:
    if not (el.get("e", 1) < 1 and math.isfinite(el.get("a_au", math.inf))):
        return []
    a, e = el["a_au"], el["e"]
    inc, Om, om = (math.radians(el[k]) for k in ("inc_deg", "Omega_deg", "omega_deg"))
    pts = []
    for E in np.linspace(0, 2 * math.pi, n):
        M = E - e * math.sin(E)
        r, _ = kepler_state(a, e, inc, Om, om, M)
        pts.append([round(float(c), 5) for c in r])
    return pts


# --------------------------------------------------------------------------------------------
# Integration
# --------------------------------------------------------------------------------------------

def _integrate_rebound(bodies: list[tuple[str, float, np.ndarray, np.ndarray]], times: np.ndarray):
    sim = rebound.Simulation()
    sim.G = G
    sim.integrator = "ias15"
    for name, m, r, v in bodies:
        sim.add(m=m, x=r[0], y=r[1], z=r[2], vx=v[0], vy=v[1], vz=v[2])
    sim.move_to_com()
    e0 = sim.energy()
    out = np.empty((len(times), len(bodies), 3))
    for i, t in enumerate(times):
        sim.integrate(float(t), exact_finish_time=1)
        sun = sim.particles[0]
        for j in range(len(bodies)):
            p = sim.particles[j]
            out[i, j] = (p.x - sun.x, p.y - sun.y, p.z - sun.z)
    err = abs((sim.energy() - e0) / e0) if e0 != 0 else 0.0
    return out, float(err), f"rebound-{REBOUND_VERSION}/ias15"


def _integrate_leapfrog(bodies, times, dt: float = 2e-4):  # pragma: no cover - fallback path
    m = np.array([b[1] for b in bodies])
    m[0] = 1.0
    x = np.array([b[2] for b in bodies], float)
    v = np.array([b[3] for b in bodies], float)
    com_v = (m[:, None] * v).sum(0) / m.sum()
    com_x = (m[:, None] * x).sum(0) / m.sum()
    x -= com_x
    v -= com_v

    def acc(x):
        d = x[None, :, :] - x[:, None, :]
        r3 = np.linalg.norm(d, axis=2) ** 3
        np.fill_diagonal(r3, np.inf)
        return G * (d * (m[None, :, None] / r3[:, :, None])).sum(1)

    def energy(x, v):
        ke = 0.5 * (m * (v**2).sum(1)).sum()
        pe = 0.0
        for i in range(len(m)):
            for j in range(i + 1, len(m)):
                pe -= G * m[i] * m[j] / np.linalg.norm(x[i] - x[j])
        return ke + pe

    e0 = energy(x, v)
    out = np.empty((len(times), len(bodies), 3))
    t = 0.0
    a = acc(x)
    for i, tt in enumerate(times):
        while t < tt - 1e-12:
            h = min(dt, tt - t)
            v += 0.5 * h * a
            x += h * v
            a = acc(x)
            v += 0.5 * h * a
            t += h
        out[i] = x - x[0]
    return out, float(abs((energy(x, v) - e0) / e0)), "numpy-leapfrog"


def integrate(bodies, times):
    if rebound is not None:
        return _integrate_rebound(bodies, times)
    return _integrate_leapfrog(bodies, times)  # pragma: no cover


def simulate(r0: np.ndarray, v0: np.ndarray, t_start: float, horizons: list[float], samples_per_year: int = 24) -> dict:
    t_max = max(horizons)
    n = int(math.ceil(t_max * samples_per_year))
    times = np.unique(np.concatenate([np.linspace(0.0, t_max, n + 1), np.asarray(horizons, float)]))
    planets = planet_states(t_start)
    bodies = [("Sun", 1.0, np.zeros(3), np.zeros(3))]
    bodies += [(p.name, p.mass_msun, r, v) for p, r, v in planets]
    bodies.append(("particle", 0.0, np.asarray(r0, float), np.asarray(v0, float)))
    traj, energy_err, engine = integrate(bodies, times)
    kep, _, _ = integrate([bodies[0], bodies[-1]], times)            # Sun-only reference orbit

    el = elements_from_state(r0, v0)
    period = el["a_au"] ** 1.5 if el["e"] < 1 and math.isfinite(el["a_au"]) else None

    def samples(j, arr):
        return [{"t": round(float(t), 5), "x": round(float(arr[i, j, 0]), 6), "y": round(float(arr[i, j, 1]), 6),
                 "z": round(float(arr[i, j, 2]), 6)} for i, t in enumerate(times)]

    horizon_out = []
    for hz in horizons:
        i = int(np.argmin(np.abs(times - hz)))
        xyz = traj[i, -1]
        ra, dec, dist = radec_of(xyz)
        dev = float(np.linalg.norm(xyz - kep[i, -1]) * AU_KM)
        horizon_out.append({"years": float(hz), "xyz_au": [round(float(c), 6) for c in xyz], "ra": round(ra, 6),
                            "dec": round(dec, 6), "distance_au": round(dist, 6), "kepler_only_deviation_km": round(dev, 1)})
    return {
        "engine": engine,
        "frame": "heliocentric_ecliptic_J2000_au",
        "epoch_start": t_start,
        "particle": {
            "elements": {k: (round(float(v), 6) if math.isfinite(v) else None) for k, v in el.items()},
            "period_years": round(period, 2) if period else None,
            "trajectory": samples(len(bodies) - 1, traj),
            "horizons": horizon_out,
            "orbit_ellipse": ellipse_points(el),
        },
        "planets": [{"name": bodies[j][0], "trajectory": samples(j, traj)} for j in range(1, len(bodies) - 1)],
        "energy_error": energy_err,
    }
