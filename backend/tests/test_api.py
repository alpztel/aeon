"""Contract + science tests for the core backend."""

import io
import math

import numpy as np
from astropy.io import fits

from conftest import assert_schema

PX = (51.295473, 14.8325559)  # PX-2026-09 apparent geocentric position at mid-survey (2026.5)


def test_contract_has_11_paths(contract):
    assert len(contract["paths"]) == 11


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert_schema(body, "Health")
    assert body["engines"]["orbit"].startswith("rebound")


def test_catalog_name_search(client):
    r = client.get("/api/v1/catalog/search", params={"q": "WISE 0855"})
    body = r.json()
    assert_schema(body, "CatalogResponse")
    assert body["results"][0]["id"] == "wise-0855"
    px = client.get("/api/v1/catalog/search", params={"q": "planet x"}).json()["results"][0]
    assert px["id"] == "px-2026-09" and px["is_synthetic"] is True
    assert math.isclose(px["ra"], PX[0], abs_tol=1e-5) and math.isclose(px["dec"], PX[1], abs_tol=1e-5)


def test_catalog_cone_with_field(client):
    r = client.get("/api/v1/catalog/search", params={"ra": 76.9564, "dec": 30.4014, "radius_arcmin": 3, "include_field": True, "limit": 20})
    body = r.json()
    assert_schema(body, "CatalogResponse")
    assert body["results"][0]["id"] == "rw-aur"
    seps = [o["separation_arcsec"] for o in body["results"]]
    assert seps[0] < 5 and any(o["source"] == "field" for o in body["results"])


def test_catalog_requires_query(client):
    assert client.get("/api/v1/catalog/search").status_code == 422


def test_cutout_json_and_fits(client):
    p = {"ra": 133.7605, "dec": -7.2421, "epoch": "2026-Q2", "size_px": 48}
    body = client.get("/api/v1/sky/cutout", params=p).json()
    assert_schema(body, "Image")
    assert body["width"] == body["height"] == 48 and len(body["data"]) == 48 * 48
    assert abs(body["stats"]["median"]) < 3 * body["stats"]["std"]   # background-subtracted
    r = client.get("/api/v1/sky/cutout", params={**p, "format": "fits"})
    assert r.headers["content-type"] == "application/fits"
    with fits.open(io.BytesIO(r.content)) as hdul:
        h = hdul[0].header
        assert h["CTYPE1"] == "RA---TAN" and h["AEONEPOC"] == "2026-Q2"
        assert hdul[0].data.shape == (48, 48)


def test_spectrum_brown_dwarf(client):
    body = client.get("/api/v1/spectrum", params={"ra": 133.7605, "dec": -7.2421, "epoch": "2026-Q1"}).json()
    assert_schema(body, "Spectrum")
    assert body["matched_object"]["id"] == "wise-0855"
    f = np.array(body["flux_ujy"])
    lam = np.array(body["wavelength_um"])
    # Y dwarf: 4-5 um window dominates, short wavelengths are faint.
    assert f[(lam > 4.4) & (lam < 4.9)].mean() > 20 * max(f[lam < 1.2].mean(), 1.0)
    feats = {(x["molecule"], x["center_um"]): x for x in body["absorption_features"]}
    assert feats[("CH4", 3.32)]["detected"] and feats[("CO2", 4.26)]["detected"]


def test_spectrum_rw_aur_variability(client):
    q1 = np.array(client.get("/api/v1/spectrum", params={"ra": 76.95642, "dec": 30.40142, "epoch": "2026-Q1"}).json()["flux_ujy"])
    q3 = np.array(client.get("/api/v1/spectrum", params={"ra": 76.95642, "dec": 30.40142, "epoch": "2026-Q3"}).json()["flux_ujy"])
    ratio = q3 / q1
    assert ratio.max() / ratio.min() > 1.3        # chromatic variability between quarters


def test_difference_wise0855_dipole(client):
    body = client.post("/api/v1/analysis/difference", json={"ra": 133.7605, "dec": -7.2421, "epoch_1": "2026-Q1", "epoch_2": "2026-Q3"}).json()
    assert_schema(body, "DifferenceResult")
    pos = [d for d in body["detections"] if d["sign"] == "positive"]
    neg = [d for d in body["detections"] if d["sign"] == "negative"]
    assert pos and neg and pos[0]["snr"] > 10 and neg[0]["snr"] > 10
    # Moving west (pm_ra < 0): the new (positive) lobe has smaller RA than the old (negative) lobe.
    assert pos[0]["ra"] < neg[0]["ra"]
    assert body["dt_years"] == 0.5


def test_difference_rejects_same_epoch(client):
    r = client.post("/api/v1/analysis/difference", json={"ra": 10, "dec": 10, "epoch_1": "2026-Q2", "epoch_2": "2026-Q2"})
    assert r.status_code == 422


def test_shift_stack_recovers_planet_x_with_parallax(client):
    body = client.post("/api/v1/analysis/shift-stack", json={
        "ra": PX[0], "dec": PX[1], "rate_arcsec_yr": 110, "pa_deg": 62, "distance_au": 520}).json()
    assert_schema(body, "ShiftStackResult")
    assert body["snr_single_frame"] < 3 < 5 < body["snr_stacked"]
    assert body["motion_frame"].startswith("geocentric") and len(body["track"]) == body["n_frames"]
    sep = math.hypot((body["peak"]["ra"] - PX[0]) * math.cos(math.radians(PX[1])), body["peak"]["dec"] - PX[1]) * 3600
    assert sep < 6.2


def test_linear_stack_misses_planet_x(client):
    # Without Earth-parallax tracking the ~400" annual parallax ellipse smears the object out.
    body = client.post("/api/v1/analysis/shift-stack", json={"ra": PX[0], "dec": PX[1], "rate_arcsec_yr": 110, "pa_deg": 62}).json()
    assert body["distance_au"] is None and body["snr_stacked"] < 5


def test_shift_stack_wrong_velocity_fails(client):
    body = client.post("/api/v1/analysis/shift-stack", json={
        "ra": PX[0], "dec": PX[1], "rate_arcsec_yr": 110, "pa_deg": 242, "distance_au": 520}).json()
    assert body["snr_stacked"] < 5


def test_blind_search_finds_velocity_and_distance(client):
    body = client.post("/api/v1/analysis/blind-search", json={"ra": PX[0], "dec": PX[1]}).json()
    assert_schema(body, "BlindSearchResult")
    assert len(body["grid"]) == 5 and len(body["grid"][0]) == 5
    assert len(body["distance_profile"]) == len(body["distances_au"]) > 10
    best = body["best"]
    assert abs(best["rate_arcsec_yr"] - 110) <= 25 and abs(best["pa_deg"] - 62) <= 10
    assert abs(best["distance_au"] - 520) / 520 < 0.05
    assert best["snr_stacked"] > 5


def test_orbit_planet_x(client):
    body = client.post("/api/v1/orbit/simulate", json={"target_id": "px-2026-09"}).json()
    assert_schema(body, "OrbitResult")
    assert body["engine"].startswith("rebound")
    assert body["energy_error"] < 1e-8
    hz = {h["years"]: h for h in body["particle"]["horizons"]}
    assert set(hz) == {1.0, 5.0, 10.0}
    assert abs(hz[10.0]["distance_au"] - 520) < 2
    # ~110"/yr -> about 0.3 deg in 10 years
    moved = math.hypot((hz[10.0]["ra"] - PX[0]) * math.cos(math.radians(PX[1])), hz[10.0]["dec"] - PX[1])
    assert 0.2 < moved < 0.4
    assert {p["name"] for p in body["planets"]} == {"Jupiter", "Saturn", "Uranus", "Neptune"}
    assert body["particle"]["elements"]["e"] < 0.1 and len(body["particle"]["orbit_ellipse"]) > 100


def test_orbit_elements_jupiter_period(client):
    # A massless particle on Jupiter's orbit returns close to its start after one Jovian year.
    body = client.post("/api/v1/orbit/simulate", json={"elements": {"a_au": 5.2026, "e": 0.0, "inc_deg": 0.0}, "horizons_years": [11.862]}).json()
    assert abs(body["particle"]["period_years"] - 11.86) < 0.05
    x, y, z = body["particle"]["horizons"][0]["xyz_au"]
    assert math.hypot(x - 5.2026, y) < 0.5


def test_orbit_rejects_star(client):
    assert client.post("/api/v1/orbit/simulate", json={"target_id": "wise-0855"}).status_code == 422
    assert client.post("/api/v1/orbit/simulate", json={}).status_code == 422


def test_discovery_to_orbit_chain(client):
    # Shift-and-stack -> measured group astrometry -> least-squares orbit -> REBOUND forecast.
    stack = client.post("/api/v1/analysis/shift-stack", json={
        "ra": PX[0], "dec": PX[1], "rate_arcsec_yr": 110, "pa_deg": 62, "distance_au": 520}).json()
    astro = stack["astrometry"]
    assert len(astro) >= 3 and all(a["sigma_arcsec"] > 0 and a["snr"] >= 3 for a in astro)
    body = client.post("/api/v1/orbit/simulate", json={"detections": astro}).json()
    assert_schema(body, "OrbitResult")
    fit = body["fit"]
    assert fit["converged"] and abs(fit["distance_au"] - 520) / 520 < 0.02
    assert abs(fit["rate_arcsec_yr"] - 110) < 10 and abs(fit["pa_deg"] - 62) < 5
    assert fit["distance_err_au"] < 10 and fit["rms_residual_arcsec"] < 3
    assert body["engine"].startswith("rebound")


def test_orbit_fit_needs_three_detections(client):
    r = client.post("/api/v1/orbit/simulate", json={"detections": [{"t": 2026.1, "ra": 10, "dec": 0}, {"t": 2026.2, "ra": 10.01, "dec": 0}]})
    assert r.status_code == 422


def test_gzip_and_server_timing(client):
    r = client.get("/api/v1/sky/cutout", params={"ra": 10.0, "dec": 20.0, "size_px": 64}, headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert r.headers["server-timing"].startswith("app;dur=")


def test_stack_cache_makes_repeat_fast(client):
    import time

    q = {"ra": 33.3, "dec": -5.5, "rate_arcsec_yr": 50, "pa_deg": 10, "distance_au": 800}
    t0 = time.perf_counter()
    client.post("/api/v1/analysis/shift-stack", json=q)
    first = time.perf_counter() - t0
    t0 = time.perf_counter()
    client.post("/api/v1/analysis/shift-stack", json={**q, "pa_deg": 12})     # slider move, same frames
    assert time.perf_counter() - t0 < max(0.5 * first, 0.3)
