"""Galactic regime of /api/v1/orbit/simulate: galpy in MWPotential2014, and the solar encounter.

Barnard's Star is the reference case: Gaia DR3 astrometry (source 4472832130942575872) and its
radial velocity of -110.5 km/s give the well-known closest approach to the Sun, about 3.75 ly
(1.15 pc) roughly 10 000 years from now.
"""

from __future__ import annotations

import math

import pytest

from aeon import galactic
from conftest import assert_schema

BARNARD = dict(ra=269.4485025, dec=4.7398396, distance_pc=1000.0 / 546.975939730948,
               pm_ra_cosdec_mas_yr=-801.551, pm_dec_mas_yr=10362.394, radial_velocity_km_s=-110.5)


@pytest.fixture(scope="module")
def barnard():
    return galactic.simulate(**BARNARD)


def test_barnard_closest_approach(barnard):
    enc = barnard["encounters"][0]
    assert barnard["rv_status"] == "measured" and enc["status"] == "found"
    assert 9.0 < enc["t_min_kyr"] < 10.5
    assert 1.10 < enc["d_min_pc"] < 1.20
    # over 10 kyr the Galactic potential bends the path by far less than the straight-line estimate's precision
    assert abs(enc["t_min_kyr"] - enc["linear_check"]["t_min_kyr"]) < 0.05
    assert abs(enc["d_min_pc"] - enc["linear_check"]["d_min_pc"]) < 0.005
    assert abs(enc["d_now_pc"] - BARNARD["distance_pc"]) < 1e-3


def test_barnard_galactic_orbit(barnard):
    o = barnard["orbits"][0]
    assert o["r_peri_kpc"] < 8.0 < o["r_apo_kpc"]
    assert 0.0 < o["eccentricity"] < 1.0
    assert math.isclose(o["eccentricity"], (o["r_apo_kpc"] - o["r_peri_kpc"]) / (o["r_apo_kpc"] + o["r_peri_kpc"]), abs_tol=1e-3)
    t = o["trajectory"]["t_myr"]
    assert t[0] == -250.0 and t[-1] == 250.0 and len(t) == len(o["trajectory"]["r_kpc"])
    assert barnard["summary"]["z_max_kpc"] == o["z_max_kpc"]


def test_sun_orbit_is_nearly_circular(barnard):
    r = barnard["sun"]["r_kpc"]
    assert 7.5 < min(r) < 8.1 and max(r) < 10.0
    assert max(abs(z) for z in barnard["sun"]["z_kpc"]) < 0.2


def test_missing_radial_velocity_is_an_envelope_not_a_guess():
    r = galactic.simulate(133.79513, -7.24514, 2.28, -8118.0, 680.0, None, span_myr=50.0, encounter_kyr=20.0)
    assert r["rv_status"] == "marginalized_envelope"
    assert [o["rv_km_s"] for o in r["orbits"]] == [-30.0, 0.0, 30.0]
    lo, hi = r["summary"]["d_min_pc"]
    assert lo < hi <= 2.28 + 1e-6
    assert r["summary"]["t_min_kyr"][0] < 0 < r["summary"]["t_min_kyr"][1]      # approaching or receding: unknown
    assert "rv_note" in r


def test_rejects_bad_input():
    with pytest.raises(galactic.GalacticError):
        galactic.simulate(10.0, 10.0, -1.0, 1.0, 1.0)
    with pytest.raises(galactic.GalacticError):
        galactic.simulate(10.0, 10.0, 10.0, 1.0, 1.0, span_myr=5000.0)


def test_api_star_target_gets_a_galactic_orbit(client):
    body = client.post("/api/v1/orbit/simulate", json={"target_id": "barnard", "span_myr": 20, "encounter_kyr": 20}).json()
    assert_schema(body, "OrbitResult")
    assert body["regime"] == "galactic" and body["frame"] == "galactocentric_cartesian_kpc"
    assert body["engine"].startswith("galpy") and body["planets"] == []
    assert body["galactic"]["rv_status"] == "marginalized_envelope"          # the catalog stores no radial velocity
    assert body["input"]["galactic"]["target_id"] == "barnard"


def test_api_explicit_astrometry_and_planet_x_regime(client):
    r = client.post("/api/v1/orbit/simulate", json={"galactic": BARNARD, "span_myr": 20, "encounter_kyr": 20})
    assert r.status_code == 200 and r.json()["galactic"]["rv_status"] == "measured"
    assert 9.0 < r.json()["galactic"]["summary"]["t_min_kyr"] < 10.5
    px = client.post("/api/v1/orbit/simulate", json={"target_id": "px-2026-09"}).json()
    assert px["regime"] == "solar_system" and px["engine"].startswith("rebound") and "galactic" not in px
    bad = client.post("/api/v1/orbit/simulate", json={"galactic": {**BARNARD, "distance_pc": 0}})
    assert bad.status_code == 422
