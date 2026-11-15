"""Stage 2-4: space velocity, the mass-age solver, SIMBAD and the validation scorecard.

Archive values in these tests are real (Gaia DR3 / AllWISE rows of the cross-match snapshot);
expected physics comes from the literature fixture (fixtures/validation_reference.json).
"""

from __future__ import annotations

import math
import os

import numpy as np
import pytest
import respx
from httpx import Response

from app import age_mass, kinematics, simbad, validation
from tests.conftest import assert_path_response_schema

BARNARD = dict(ra=269.4485025, dec=4.7398396, distance_pc=1000.0 / 546.975939730948, pm_ra_cosdec_mas_yr=-801.551,
               pm_dec_mas_yr=10362.394, radial_velocity_km_s=-110.46822)
W0855 = dict(ra=133.79513, dec=-7.24514, distance_pc=2.28, pm_ra_cosdec_mas_yr=-8118.0, pm_dec_mas_yr=680.0)
CORE = "http://localhost:8000"


# ---- kinematics -------------------------------------------------------------------------------

def test_space_velocity_matches_astropy():
    import astropy.units as u
    from astropy.coordinates import SkyCoord

    c = SkyCoord(ra=BARNARD["ra"] * u.deg, dec=BARNARD["dec"] * u.deg, distance=BARNARD["distance_pc"] * u.pc,
                 pm_ra_cosdec=BARNARD["pm_ra_cosdec_mas_yr"] * u.mas / u.yr, pm_dec=BARNARD["pm_dec_mas_yr"] * u.mas / u.yr,
                 radial_velocity=BARNARD["radial_velocity_km_s"] * u.km / u.s)
    ref = c.galactic.velocity.d_xyz.to_value(u.km / u.s)
    mine = kinematics.heliocentric_uvw(*[BARNARD[k] for k in ("ra", "dec", "distance_pc", "pm_ra_cosdec_mas_yr",
                                                             "pm_dec_mas_yr", "radial_velocity_km_s")])
    assert np.allclose(mine, ref, atol=1e-6)


def test_measured_rv_gives_one_solution_and_lsr_offsets():
    g = kinematics.space_velocity(BARNARD)
    assert g["status"] == "ok" and g["rv_status"] == "measured" and len(g["solutions"]) == 1 and "envelope" not in g
    s = g["solutions"][0]
    for comp, sun in zip("uvw", kinematics.SOLAR_MOTION_KM_S):
        assert math.isclose(s[f"{comp}_lsr_km_s"] - s[f"{comp}_helio_km_s"], sun, abs_tol=0.011)
    probs = s["membership"]["probabilities"]
    assert math.isclose(sum(probs.values()), 1.0, abs_tol=1e-3)
    assert s["v_tot_km_s"] > 100 and s["membership"]["most_likely"] == "thick_disk"      # a fast, old-disk star


def test_missing_rv_is_an_envelope_never_a_value():
    g = kinematics.space_velocity(W0855)
    assert g["rv_status"] == "marginalized_envelope"
    assert [s["rv_km_s"] for s in g["solutions"]] == [-30.0, 0.0, 30.0]
    lo, hi = g["envelope"]["v_tot_km_s"]
    assert lo < hi and "rv_note" in g
    assert g["inputs"].get("radial_velocity_km_s") is None


def test_no_distance_means_unmeasured():
    g = kinematics.space_velocity({"ra": 10.0, "dec": 5.0, "pm_ra_cosdec_mas_yr": 1.0, "pm_dec_mas_yr": 1.0})
    assert g["status"] == "unmeasured" and "distance_pc" in g["reason"]
    assert kinematics.space_velocity(None)["status"] == "unmeasured"


def test_avr_coefficients_are_the_published_ones():
    # Aumer & Binney 2009, Table 6: sigma(10 Gyr) = v10 by construction
    for comp, v10 in (("U", 41.899), ("V", 28.823), ("W", 23.831)):
        assert math.isclose(float(kinematics.avr_sigma(comp, 10.0)), v10, rel_tol=1e-9)
    assert float(kinematics.avr_sigma("W", 1.0)) < float(kinematics.avr_sigma("W", 8.0))
    ages = np.array([0.5, 2.0, 5.0, 10.0])
    fast = kinematics.age_likelihood(-130.0, 17.0, 26.0, ages)
    slow = kinematics.age_likelihood(5.0, 3.0, 2.0, ages)
    assert np.argmax(fast) == 3 and np.argmax(slow) == 0


# ---- model tables -----------------------------------------------------------------------------

def test_model_grid_reproduces_table_rows():
    g = age_mass.model_grid()
    # Sonora Bobcat, 0.0005 Msun at 1 Gyr: Teff 126 K, log L -8.617 (first track of the table)
    j = int(np.argmin(np.abs(g["log_age"] - 0.0)))
    assert math.isclose(g["teff"][0, j], 126.0, rel_tol=0.02) and math.isclose(g["log_l"][0, j], -8.617, abs_tol=0.03)
    # BHAC15, 1.0 Msun near the solar age: close to the Sun
    i = int(np.argmin(np.abs(g["log_mass"] - 0.0)))
    k = int(np.argmin(np.abs(g["log_age"] - math.log10(4.6))))
    assert abs(g["teff"][i, k] - 5772) < 150 and abs(g["log_l"][i, k]) < 0.08
    # Sonora magnitudes: 250 K, log g 4.25 -> W2 = 16.944 at the table radius
    mt = age_mass._mag_table()
    assert math.isclose(float(mt["w2"][list(mt["teff"]).index(250.0), list(mt["logg"]).index(4.25)]), 16.944, abs_tol=1e-9)


def test_blackbody_helpers():
    # points on a 3000 K blackbody are recovered
    lam = [0.511, 0.622, 0.777, 3.35, 4.6]
    x = [14387.77 / (w * 3000.0) for w in lam]
    pts = [{"wavelength_um": w, "flux_ujy": 1e6 * (1 / w) ** 3 / math.expm1(xi)} for w, xi in zip(lam, x)]
    bb = age_mass.blackbody_fit(pts)
    assert abs(bb["teff_k"] - 3000.0) < 30 and bb["rms_dex"] < 0.01
    assert age_mass.blackbody_fit(pts[:2]) is None
    assert 0.0 < age_mass.blackbody_fraction_beyond(2.5, 4000.0) < 0.2 < age_mass.blackbody_fraction_beyond(2.5, 2000.0)


# ---- the degeneracy and how kinematics breaks it ---------------------------------------------------

def _w0855_solution():
    g = age_mass.model_grid()
    gal = kinematics.space_velocity(W0855)
    kin = kinematics.kinematic_age_pdf(gal, 10.0 ** g["log_age"])
    m_abs = 13.704 - 5.0 * math.log10(2.28 / 10.0)                 # AllWISE w2mpro, catalog distance
    return age_mass.solve({"m_w2": (m_abs, 0.3)}, mode="substellar_w2", kinematic_pdf=kin)


def test_w0855_brightness_alone_leaves_the_age_open():
    r = _w0855_solution()
    assert r["spectral"]["status"] == "ok" and r["spectral"]["constraint"] == "unconstrained"
    m = r["mass_spectral_only"]
    # Luhman 2014: 3-10 M_Jup for ages of 1-10 Gyr
    assert m["lo_mjup"] < 5 and m["hi_mjup"] > 8 and 3 <= m["median_mjup"] <= 10
    track = r["degeneracy_track"]
    assert len(track) > 10 and track[0]["mass_mjup"] < track[-1]["mass_mjup"]        # older -> heavier
    assert all(200 < t["teff_k"] < 300 for t in track)                               # same brightness, same Teff


def test_w0855_kinematics_narrow_the_mass():
    r = _w0855_solution()
    spec, joint = r["mass_spectral_only"], r["mass"]
    assert r["joint"]["channels"] == ["spectral", "kinematic"]
    assert (joint["hi_mjup"] - joint["lo_mjup"]) < 0.7 * (spec["hi_mjup"] - spec["lo_mjup"])
    assert 225 - 15 <= joint["model_teff_k"]["median"] <= 260 + 15                    # Luhman 2014: 225-260 K
    assert r["joint"]["hi_gyr"] <= 12.0 and r["joint"]["lo_gyr"] > 1.0
    assert len(r["joint"]["pdf"]) == len(r["age_grid_gyr"]) == 56


def test_values_outside_the_models_give_no_solution():
    r = age_mass.solve({"m_w2": (-1.0, 0.3)}, mode="substellar_w2")
    assert r["spectral"]["status"] == "no_model_match" and r["mass"] is None
    assert r["joint"]["status"] == "unmeasured"
    empty = age_mass.solve({}, mode="none")
    assert empty["spectral"]["status"] == "unmeasured" and empty["mass"] is None


def test_estimate_refuses_what_it_cannot_measure():
    kw = dict(sed=[], sed_physics={}, gaia_rows=[], wise_rows=[], spherex_points=[], galactic={"status": "unmeasured"})
    assert age_mass.estimate(**kw, astrometry={}, object_class="planet_x_candidate", distance_au=520.0)["status"] == "not_applicable"
    assert age_mass.estimate(**kw, astrometry={}, object_class="high_z_galaxy", distance_au=None)["status"] == "not_applicable"
    out = age_mass.estimate(**kw, astrometry={}, object_class="cold_brown_dwarf", distance_au=None)
    assert out["status"] == "unmeasured" and "distance" in out["spectral"]["reason"]


# ---- validation rule --------------------------------------------------------------------------

def test_compare_rule():
    assert validation.compare({"lo": 7.6, "hi": 10.6}, {"lo": 3, "hi": 10}) == "consistent"
    assert validation.compare({"lo": 3038, "hi": 3226}, {"value": 3278, "err": 51}) == "partial"      # misses by 1 K
    assert validation.compare({"lo": 100, "hi": 110}, {"value": 300, "err": 10}) == "discrepant"
    assert validation.compare([-10.0, 20.0], 5.0) == "consistent"
    assert validation.compare({"lo": 3.1, "hi": 8.4}, {"lo": 5, "hi": None}) == "consistent"            # "older than 5 Gyr"
    assert validation.compare(None, 5.0) == "not_comparable" and validation.compare(5.0, None) == "not_comparable"


def test_literature_fixture_is_sourced():
    targets = validation.reference_data()["targets"]
    assert {"wise-0855", "barnard", "trappist-1", "tw-hya", "luhman-16"} <= set(targets)
    for tid, t in targets.items():
        assert t["simbad_id"]
        if t["literature"]:
            assert t["literature"]["sources"], tid
            for s in t["literature"]["sources"]:
                assert s["bibcode"] and s["arxiv"], tid


SIMBAD_CSV = ('main_id,otype,sp_type,ra,dec,plx_value,plx_err,plx_bibcode,pmra,pmdec,pm_bibcode,rvz_radvel,rvz_err,rvz_type,rvz_bibcode\n'
              '"NAME Barnard\'s star",PM*,M4V,269.4520825,4.6933649,546.9759,0.0401,2020yCat.1350....0G,-801.551,10362.394,'
              '2020yCat.1350....0G,-110.47,0.13,v,2018A&A...616A...1G\n')


@respx.mock
def test_simbad_live_row_and_outage(monkeypatch):
    monkeypatch.setenv("AEON_ENABLE_LIVE_SIMBAD", "1")
    route = respx.post(simbad.SIMBAD_TAP).mock(return_value=Response(200, text=SIMBAD_CSV))
    got = simbad.lookup("NAME Barnard's star", 269.45, 4.69)
    assert got["status"] == "live" and got["row"]["rvz_radvel"] == -110.47 and got["row"]["plx_bibcode"] == "2020yCat.1350....0G"
    from urllib.parse import parse_qs

    sent = parse_qs(route.calls[0].request.content.decode())["query"][0]
    assert "i.id = 'NAME Barnard''s star'" in sent                                  # the quote is escaped
    astro = simbad.astrometry(got["row"])
    assert math.isclose(astro["distance_pc"], 1000 / 546.9759, rel_tol=1e-9) and astro["radial_velocity_km_s"] == -110.47
    route.mock(return_value=Response(404, text="<!doctype html><title>Page unavailable</title>"))
    down = simbad.lookup("NAME Barnard's star", 269.45, 4.69)
    assert down["status"] == "unavailable" and down["row"] is None and "SIMBAD did not answer" in down["reason"]
    snap = simbad.lookup("NAME Barnard's star", 269.45, 4.69, snapshot={"row": got["row"], "retrieved_utc": "2026-01-01T00:00:00Z"})
    assert snap["status"] == "snapshot" and snap["row"]["main_id"].startswith("NAME Barnard")
    assert simbad.astrometry({"plx_value": None}) is None


# ---- end to end through the endpoint ----------------------------------------------------------------

def _orbit_answer(request):
    import json

    g = json.loads(request.content)["galactic"]
    measured = g.get("radial_velocity_km_s") is not None
    rng = (lambda a, b: a) if measured else (lambda a, b: [a, b])
    return Response(200, json={"engine": "galpy-1.12.1/MWPotential2014", "regime": "galactic", "galactic": {
        "engine": "galpy-1.12.1/MWPotential2014", "rv_status": "measured" if measured else "marginalized_envelope",
        "summary": {"r_peri_kpc": rng(5.9, 7.8), "r_apo_kpc": rng(15.3, 14.0), "z_max_kpc": rng(0.63, 2.0),
                    "eccentricity": rng(0.44, 0.28), "t_min_kyr": rng(9.72, 7.7), "d_min_pc": rng(1.155, 2.28),
                    "encounter_status": "found"},
        "orbits": [{"rv_km_s": 0.0, "r_peri_kpc": 5.9, "trajectory": {"t_myr": [0.0]}}],
        "encounters": [{"rv_km_s": 0.0, "status": "found", "t_min_kyr": 9.72, "d_min_pc": 1.155, "curve": {"t_kyr": [0.0]}}]}})


@respx.mock
def test_crossmatch_barnard_full_chain(client, monkeypatch):
    monkeypatch.setenv("AEON_ENABLE_LIVE_SIMBAD", "1")
    respx.get(f"{CORE}/api/v1/spectrum").mock(return_value=Response(200, json={
        "wavelength_um": [], "flux_ujy": [], "flux_err_ujy": [], "pipeline": {"data_mode": "physical_model"},
        "matched_object": {"id": "barnard", "name": "Barnard's Star", "object_class": "main_sequence_star", "distance_pc": 1.83,
                           "pm_ra_cosdec_arcsec_yr": -0.8, "pm_dec_arcsec_yr": 10.36}}))
    respx.post(f"{CORE}/api/v1/orbit/simulate").mock(side_effect=_orbit_answer)
    respx.post(simbad.SIMBAD_TAP).mock(return_value=Response(200, text=SIMBAD_CSV))
    body = client.get("/api/v1/missions/crossmatch", params={"ra": 269.4485025, "dec": 4.7398396}).json()
    assert_path_response_schema(body, "/api/v1/missions/crossmatch")

    gal = body["kinematics"]["galactic"]
    assert gal["rv_status"] == "measured" and gal["inputs"]["rv_source"] == "Gaia DR3 radial_velocity"
    am = body["age_mass"]
    assert am["status"] == "ok" and am["mode"] == "stellar_hr"
    assert abs(am["inputs"]["log_l_lsun"] - math.log10(0.00329)) < 0.2            # Ribas et al. 2018: 0.00329 Lsun
    assert 0.163 - 2 * 0.022 < am["mass"]["median_msun"] < 0.163 + 2 * 0.022      # Ribas et al. 2018
    assert am["spectral"]["constraint"] == "unconstrained"                          # a main-sequence star: age open
    assert am["joint"]["lo_gyr"] > 4.0                                              # kinematics: an old star
    assert body["galactic_orbit"]["status"] == "ok" and body["galactic_orbit"]["summary"]["d_min_pc"] == 1.155
    assert "trajectory" not in str(body["galactic_orbit"])

    val = body["validation"]
    rows = {r["key"]: r for r in val["rows"]}
    assert val["simbad"]["status"] == "live" and val["simbad"]["object"]["main_id"].startswith("NAME Barnard")
    assert rows["mass"]["agreement"] == "consistent" and rows["mass"]["unit"] == "M_sun"
    assert rows["age_gyr"]["agreement"] == "consistent"                               # literature: 7-10 Gyr
    assert rows["u_lsr_km_s"]["agreement"] == "consistent" and "2018A&A...616A...1G" in rows["u_lsr_km_s"]["reference_source"]
    assert rows["d_min_pc"]["agreement"] == "consistent"
    assert "2018arXiv181105955R" in rows["teff_k"]["reference_source"]
    # the summary only repeats numbers that are in the table
    text = val["synthesis"]["en"]
    assert rows["mass"]["aeon_text"] in text and rows["mass"]["reference_text"] in text
    assert val["counts"]["consistent"] >= 8 and val["counts"]["not_comparable"] == 0


@respx.mock
def test_crossmatch_w0855_envelope_and_simbad_outage(client, monkeypatch):
    monkeypatch.setenv("AEON_ENABLE_LIVE_SIMBAD", "1")
    lam = [0.75 + i * 0.0422 for i in range(102)]
    respx.get(f"{CORE}/api/v1/spectrum").mock(return_value=Response(200, json={
        "wavelength_um": lam, "flux_ujy": [0.0] * 102, "flux_err_ujy": [1.0] * 102, "pipeline": {"data_mode": "physical_model"},
        "matched_object": {"id": "wise-0855", "name": "WISE J085510.83-071442.5", "object_class": "cold_brown_dwarf",
                           "distance_pc": 2.28, "pm_ra_cosdec_arcsec_yr": -8.118, "pm_dec_arcsec_yr": 0.680}}))
    respx.post(f"{CORE}/api/v1/orbit/simulate").mock(side_effect=_orbit_answer)
    respx.post(simbad.SIMBAD_TAP).mock(return_value=Response(404, text="<!doctype html>"))
    body = client.get("/api/v1/missions/crossmatch", params={"ra": 133.79513, "dec": -7.24514}).json()
    assert_path_response_schema(body, "/api/v1/missions/crossmatch")
    gal = body["kinematics"]["galactic"]
    assert gal["rv_status"] == "marginalized_envelope" and gal["inputs"]["distance_source"] == "AEON catalog entry wise-0855"
    am = body["age_mass"]
    assert am["mode"] == "substellar_w2" and am["inputs"]["w2_source"] == "AllWISE w2mpro"
    assert am["spectral"]["constraint"] == "unconstrained" and am["joint"]["channels"] == ["spectral", "kinematic"]
    val = body["validation"]
    rows = {r["key"]: r for r in val["rows"]}
    assert val["simbad"]["status"] == "unavailable"
    assert rows["u_lsr_km_s"]["agreement"] == "not_comparable" and "SIMBAD" in rows["u_lsr_km_s"]["not_comparable_reason"]
    assert rows["mass"]["agreement"] == "consistent" and rows["mass"]["unit"] == "M_Jup"       # Luhman 2014: 3-10 M_Jup
    assert rows["teff_k"]["agreement"] == "consistent"                                          # Luhman 2014: 225-260 K
    assert "2014ApJ...786L..18L" in rows["mass"]["reference_source"]
    assert body["galactic_orbit"]["rv_status"] == "marginalized_envelope"
    assert isinstance(body["galactic_orbit"]["summary"]["d_min_pc"], list)


@respx.mock
def test_crossmatch_planet_x_is_not_a_star(client):
    respx.get(f"{CORE}/api/v1/spectrum").mock(return_value=Response(503))
    body = client.get("/api/v1/missions/crossmatch", params={"ra": 52.1, "dec": 18.4}).json()
    for key in ("age_mass", "galactic_orbit", "validation"):
        assert key in body
    fx = __import__("app.crossmatch", fromlist=["_load_fixtures"])._load_fixtures()["targets"]["px-2026-09"]
    px = client.get("/api/v1/missions/crossmatch", params={"ra": fx["ra_ref"], "dec": fx["dec_ref"]}).json()
    assert px["age_mass"]["status"] == "not_applicable" and px["galactic_orbit"]["regime"] == "solar_system"
    assert px["validation"]["status"] == "not_applicable" and px["kinematics"]["galactic"]["status"] == "not_applicable"
    assert_path_response_schema(px, "/api/v1/missions/crossmatch")


def test_no_live_queries_leak_from_tests():
    assert os.environ.get("AEON_ENABLE_LIVE_SIMBAD") != "1"
    assert simbad.lookup("x", 1.0, 1.0)["status"] == "unavailable"
