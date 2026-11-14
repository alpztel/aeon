"""Orbit determination from geocentric astrometry (t, RA, Dec).

Model: a heliocentric state (position, velocity) at a reference epoch t0, propagated under the
Sun's gravity (velocity-Verlet, short arcs), observed from Earth's heliocentric position (ERFA
ephemeris). Earth's reflex parallax is what makes the distance observable from a single-year arc.

Parameters (6): tangent-plane offsets (xi, eta) of the t0 direction [arcsec], ln(distance/AU),
heliocentric angular rates (mu_E, mu_N) [arcsec/yr] and radial velocity [km/s]. The radial velocity
is weakly constrained by short arcs, so it carries a Gaussian prior (0 +/- vr_prior km/s); the other
parameters are free. A distance grid seeds the non-linear fit to avoid local minima.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import least_squares

from . import ephem
from .orbit import AU_KM, G, KM_S_TO_AU_YR, elements_from_state, eq_to_ecl

ARCSEC = math.pi / 180 / 3600


def propagate(r0: np.ndarray, v0: np.ndarray, dts: np.ndarray, steps_per_year: int = 64) -> np.ndarray:
    """Heliocentric positions at offsets `dts` (yr) from t0 under solar gravity. Shape (n, 3)."""
    out = np.empty((len(dts), 3))
    for sign in (1.0, -1.0):
        idx = np.flatnonzero(dts * sign >= 0) if sign > 0 else np.flatnonzero(dts < 0)
        if not len(idx):
            continue
        order = idx[np.argsort(np.abs(dts[idx]))]
        r, v, t = r0.astype(float).copy(), v0.astype(float).copy(), 0.0
        a = -G * r / np.linalg.norm(r) ** 3
        for k in order:
            target = abs(dts[k])
            while t < target - 1e-12:
                # ~500 steps per orbit near the Sun, at most 1/steps_per_year far away.
                h = min(1.0 / steps_per_year, 0.002 * float(np.linalg.norm(r)) ** 1.5, target - t)
                v = v + 0.5 * sign * h * a
                r = r + sign * h * v
                a = -G * r / np.linalg.norm(r) ** 3
                v = v + 0.5 * sign * h * a
                t += h
            out[k] = r
    return out


class _Model:
    def __init__(self, t: np.ndarray, ra: np.ndarray, dec: np.ndarray, sigma: np.ndarray, t0: float, vr_prior: float):
        self.t, self.sigma, self.t0, self.vr_prior = t, sigma, t0, vr_prior
        self.u_obs = ephem.unit(ra, dec)
        self.earth = ephem.earth_helio(t)
        self.earth0 = ephem.earth_helio([t0])[0]
        mean = self.u_obs.mean(axis=0)
        self.ra0, self.dec0 = (float(x) for x in ephem.radec(mean))
        self.u0 = ephem.unit(self.ra0, self.dec0)
        self.east, self.north = ephem.tangent_basis(self.ra0, self.dec0)
        # Per-observation tangent bases for residuals.
        self.e_obs = np.stack([ephem.tangent_basis(a, d)[0] for a, d in zip(ra, dec)])
        self.n_obs = np.stack([ephem.tangent_basis(a, d)[1] for a, d in zip(ra, dec)])

    def state(self, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        xi, eta, lnd, mu_e, mu_n, vr = p
        u = self.u0 + xi * ARCSEC * self.east + eta * ARCSEC * self.north
        u = u / np.linalg.norm(u)
        d = math.exp(lnd)                                          # geocentric distance at t0
        r0 = self.earth0 + d * u
        rh = np.linalg.norm(r0)
        rhat = r0 / rh
        e_h, n_h = ephem.tangent_basis(*(float(x) for x in ephem.radec(r0)))
        v0 = rh * ARCSEC * (mu_e * e_h + mu_n * n_h) + vr * KM_S_TO_AU_YR * rhat
        return r0, v0

    def predict(self, p: np.ndarray) -> np.ndarray:
        r0, v0 = self.state(p)
        r = propagate(r0, v0, self.t - self.t0)
        g = r - self.earth
        return g / np.linalg.norm(g, axis=1)[:, None]

    def residuals(self, p: np.ndarray) -> np.ndarray:
        u = self.predict(p)
        dx = np.einsum("ij,ij->i", u - self.u_obs, self.e_obs) / ARCSEC / self.sigma
        dy = np.einsum("ij,ij->i", u - self.u_obs, self.n_obs) / ARCSEC / self.sigma
        return np.concatenate([dx, dy, [p[5] / self.vr_prior]])


def fit(detections: list[dict], t0: float | None = None, vr_prior_km_s: float = 3.0,
        distance_grid_au: tuple[float, float] = (5.0, 3000.0)) -> dict:
    if len(detections) < 3:
        raise ValueError("At least 3 detections are needed for an orbit fit.")
    t = np.array([float(d["t"]) for d in detections])
    if np.ptp(t) < 1e-3:
        raise ValueError("Detections must span more than ~0.4 days.")
    ra = np.array([float(d["ra"]) for d in detections])
    dec = np.array([float(d["dec"]) for d in detections])
    sigma = np.array([float(d.get("sigma_arcsec") or 1.0) for d in detections])
    t0 = float(np.mean(t)) if t0 is None else float(t0)
    m = _Model(t, ra, dec, sigma, t0, vr_prior_km_s)

    # 1) distance grid: fit direction and rates with the distance held fixed.
    best = None
    for d in np.geomspace(distance_grid_au[0], distance_grid_au[1], 40):
        def res_fixed(q, lnd=math.log(d)):
            return m.residuals(np.array([q[0], q[1], lnd, q[2], q[3], 0.0]))
        sol = least_squares(res_fixed, np.zeros(4), method="lm", max_nfev=200)
        if best is None or sol.cost < best[0]:
            best = (sol.cost, d, sol.x)
    _, d0, q = best

    # 2) full non-linear fit.
    p0 = np.array([q[0], q[1], math.log(d0), q[2], q[3], 0.0])
    sol = least_squares(m.residuals, p0, method="lm", max_nfev=2000)
    p = sol.x
    n_obs = len(t)
    dof = max(2 * n_obs + 1 - 6, 1)
    chi2 = float(np.sum(sol.fun ** 2))
    try:
        cov = np.linalg.inv(sol.jac.T @ sol.jac) * max(chi2 / dof, 1.0)
        perr = np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        perr = np.full(6, np.nan)

    r0, v0 = m.state(p)
    u = m.predict(p)
    resid_arcsec = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", u, m.u_obs), -1, 1))) * 3600
    d = math.exp(p[2])
    rate = math.hypot(p[3], p[4])
    r_ecl, v_ecl = eq_to_ecl(r0), eq_to_ecl(v0)
    ra0, dec0 = (float(x) for x in ephem.radec(r0 - m.earth0))
    return {
        "t0": t0,
        "r0_ecl_au": r_ecl, "v0_ecl_au_yr": v_ecl,
        "summary": {
            "n_detections": n_obs,
            "arc_years": round(float(np.ptp(t)), 5),
            "ra": round(ra0 % 360, 7), "dec": round(dec0, 7),
            "distance_au": round(d, 4),
            "distance_err_au": round(d * float(perr[2]), 4) if math.isfinite(perr[2]) else None,
            "heliocentric_distance_au": round(float(np.linalg.norm(r0)), 4),
            "rate_arcsec_yr": round(rate, 4),
            "rate_err_arcsec_yr": round(float(math.hypot(perr[3], perr[4])), 4) if math.isfinite(perr[3]) else None,
            "pa_deg": round(math.degrees(math.atan2(p[3], p[4])) % 360, 3),
            "radial_velocity_km_s": round(float(p[5]), 4),
            "rms_residual_arcsec": round(float(np.sqrt(np.mean(resid_arcsec ** 2))), 4),
            "max_residual_arcsec": round(float(resid_arcsec.max()), 4),
            "reduced_chi2": round(chi2 / dof, 4),
            "converged": bool(sol.success),
            "elements": {k: (round(float(v), 6) if math.isfinite(v) else None)
                         for k, v in elements_from_state(r_ecl, v_ecl).items()},
            "speed_km_s": round(float(np.linalg.norm(v0)) / KM_S_TO_AU_YR, 4),
            "position_err_km": round(d * float(math.hypot(perr[0], perr[1])) * ARCSEC * AU_KM, 1) if math.isfinite(perr[0]) else None,
        },
    }
