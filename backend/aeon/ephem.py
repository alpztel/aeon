"""Apparent (geocentric) positions: proper motion + Earth's reflex parallax.

Earth's heliocentric position comes from astropy's built-in ERFA ephemeris (epv00, no download).
All vectors are ICRS equatorial, in AU. For an object at heliocentric position r_obj(t) the
apparent direction seen from Earth is r_obj(t) - r_earth(t).

For a distant solar-system body (hundreds of AU) the parallax term dominates its apparent motion:
the annual ellipse has a semi-major axis of 206265"/d (~397" at 520 AU), far larger than its
heliocentric orbital motion (~110"/yr). Searches that stack frames along straight lines therefore
miss such objects; `track` below supplies the curved apparent path for a trial distance.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from astropy.coordinates import get_body_barycentric
from astropy.time import Time

AU_PER_PC = 206264.806


@lru_cache(maxsize=4096)
def _earth_helio(t_rounded: float) -> tuple[float, float, float]:
    tt = Time(t_rounded, format="decimalyear", scale="tdb")
    e = get_body_barycentric("earth", tt).xyz.to_value("AU")
    s = get_body_barycentric("sun", tt).xyz.to_value("AU")
    return float(e[0] - s[0]), float(e[1] - s[1]), float(e[2] - s[2])


def earth_helio(times) -> np.ndarray:
    """Heliocentric ICRS position of the Earth (AU) at decimal years; shape (n, 3)."""
    ts = np.atleast_1d(np.asarray(times, dtype=float))
    # 1e-6 yr = 32 s: Earth moves ~1e-6 AU, negligible against any parallax considered here.
    return np.array([_earth_helio(round(float(t), 6)) for t in ts])


def unit(ra_deg, dec_deg) -> np.ndarray:
    a, d = np.radians(ra_deg), np.radians(dec_deg)
    return np.stack([np.cos(d) * np.cos(a), np.cos(d) * np.sin(a), np.sin(d)], axis=-1)


def radec(v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    v = np.asarray(v, dtype=float)
    r = np.linalg.norm(v, axis=-1)
    ra = np.degrees(np.arctan2(v[..., 1], v[..., 0])) % 360.0
    dec = np.degrees(np.arcsin(np.clip(v[..., 2] / r, -1, 1)))
    return ra, dec


def tangent_basis(ra_deg: float, dec_deg: float) -> tuple[np.ndarray, np.ndarray]:
    a, d = math.radians(ra_deg), math.radians(dec_deg)
    east = np.array([-math.sin(a), math.cos(a), 0.0])
    north = np.array([-math.sin(d) * math.cos(a), -math.sin(d) * math.sin(a), math.cos(d)])
    return east, north


def distance_au_of(entry) -> float | None:
    if getattr(entry, "distance_au", None):
        return float(entry.distance_au)
    if getattr(entry, "distance_pc", None):
        return float(entry.distance_pc) * AU_PER_PC
    return None


def apparent_position(entry, t_year: float) -> tuple[float, float]:
    """Apparent geocentric RA/Dec of a catalog entry at t (proper motion + parallax)."""
    from .catalog import position_at

    ra, dec = position_at(entry, t_year)
    d = distance_au_of(entry)
    if not d:
        return ra, dec
    v = d * unit(ra, dec) - earth_helio([t_year])[0]
    a, b = radec(v)
    return float(a), float(b)


def track(ra_ref: float, dec_ref: float, t_ref: float, times, rate_arcsec_yr: float, pa_deg: float,
          distance_au: float | None) -> tuple[np.ndarray, np.ndarray]:
    """Apparent positions at `times` for a hypothesis that is seen at (ra_ref, dec_ref) at t_ref.

    * distance_au None: linear motion on the sky (rate, PA), no parallax.
    * otherwise: the body is placed at geocentric distance `distance_au` along the reference
      direction, given a heliocentric tangential velocity rate*d at PA, moved linearly in
      heliocentric space, and re-projected from Earth's position at each time.
    """
    ts = np.atleast_1d(np.asarray(times, dtype=float))
    east, north = tangent_basis(ra_ref, dec_ref)
    pa = math.radians(pa_deg)
    direction = math.sin(pa) * east + math.cos(pa) * north
    if distance_au is None:
        mu = rate_arcsec_yr / AU_PER_PC                                   # rad / yr
        u0 = unit(ra_ref, dec_ref)
        ang = mu * (ts - t_ref)
        v = np.cos(ang)[:, None] * u0[None, :] + np.sin(ang)[:, None] * direction[None, :]
        return radec(v)
    e_ref = earth_helio([t_ref])[0]
    r_ref = e_ref + distance_au * unit(ra_ref, dec_ref)
    vel = distance_au * (rate_arcsec_yr / AU_PER_PC) * direction           # AU / yr
    r_t = r_ref[None, :] + vel[None, :] * (ts - t_ref)[:, None]
    return radec(r_t - earth_helio(ts))


def parallax_amplitude_arcsec(distance_au: float) -> float:
    return AU_PER_PC / distance_au


def solar_elongation_deg(ra: float, dec: float, times) -> np.ndarray:
    """Angle between a sky position and the Sun as seen from Earth, at each time."""
    sun_dir = -earth_helio(times)
    sun_dir /= np.linalg.norm(sun_dir, axis=1)[:, None]
    return np.degrees(np.arccos(np.clip(sun_dir @ unit(ra, dec), -1, 1)))


def spherex_visible_times(ra: float, dec: float, t_start: float, t_end: float,
                          half_width_deg: float = 10.0, step_days: float = 0.5) -> np.ndarray:
    """Times when a field is inside a SPHEREx-like observing band.

    SPHEREx scans great circles roughly perpendicular to the Sun-Earth line, so a field is
    observed when its solar elongation is near 90 deg. Model assumption: |elongation - 90| <=
    half_width_deg. Ecliptic fields get two windows per year; fields near the ecliptic poles are
    visible all year (as for the real survey's deep fields).
    """
    grid = np.arange(t_start, t_end, step_days / 365.25)
    elong = solar_elongation_deg(ra, dec, grid)
    return grid[np.abs(elong - 90.0) <= half_width_deg]
