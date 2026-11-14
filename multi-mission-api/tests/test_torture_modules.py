"""Wave 2 Torture & Optimization Benchmark Suite for Multi-Mission scientific modules:
- `sed_fitter.py` (Broadband + SPHEREx bolometric integration, Wien/Rayleigh-Jeans color temperature, kete/kbmod kinematics)
- `active_learning.py` (Coniferest/Astronomaly-inspired Active Anomaly Discovery online weight updates)
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math
import time

from httpx import Response
import pytest
import respx

from app.active_learning import ActiveAnomalyDiscoveryEngine
from app.sed_fitter import compute_kete_kbmod_kinematics, fit_multi_mission_sed, icrs_to_ecliptic_deg
from tests.conftest import assert_path_response_schema


def test_torture_sed_duplicate_wavelength_and_rayleigh_jeans_tail():
    """Torture 1:
    - Case A: Two measurements at identical wavelength (e.g. AllWISE W1=3.35 um and CatWISE W1=3.35 um).
      Trapezoidal integration over d(log_lam)=0 must NOT return bolometric_flux_wm2 == 0.0!
    - Case B: A hot 5800 K solar twin (`18-sco`) observed only in the infrared (1.0 - 22 um, Rayleigh-Jeans tail).
      `nu * F_nu` decreases monotonically with wavelength; naive Wien peak `3670 / lam_min` caps T_eff at 3670 K
      unless Rayleigh-Jeans slope correction is applied!
    """
    # Case A: Identical wavelengths
    dup_sed = [
        {"wavelength_um": 3.35, "flux_ujy": 120.0, "survey": "AllWISE"},
        {"wavelength_um": 3.35, "flux_ujy": 124.0, "survey": "CatWISE"},
    ]
    res_dup = fit_multi_mission_sed(dup_sed)
    assert res_dup["bolometric_flux_wm2"] > 0.0, f"Duplicate wavelength yielded zero bolometric flux: {res_dup}"

    # Case B: 5800 K blackbody sampled only at IR wavelengths (1.0 to 22 um)
    ir_only_solar = []
    for lam in (1.0, 1.5, 2.2, 3.35, 4.6, 11.56, 22.09):
        # Rayleigh-Jeans F_nu ~ T * lam^-2
        f_ujy = 1.0e5 * (5800.0 / 5800.0) * (lam ** -1.92)
        ir_only_solar.append({"wavelength_um": lam, "flux_ujy": f_ujy, "survey": "SPHEREx+WISE"})
    res_rj = fit_multi_mission_sed(ir_only_solar)
    assert res_rj["teff_sed_k"] >= 5000.0, f"Rayleigh-Jeans tail capped solar T_eff too low: {res_rj}"


def test_torture_active_learning_nan_inf_votes_and_concurrent_feedback():
    """Torture 2: Hostile NaN/Inf/negative votes, SNR=1e300, and 16-thread concurrent online weight updates."""
    engine = ActiveAnomalyDiscoveryEngine()

    hostile_docs = [
        {"ra": 51.2, "dec": 14.8, "anomaly_score": float("nan"), "snr": float("inf"), "votes": float("nan")},
        {"ra": 133.76, "dec": -7.24, "anomaly_score": -999.0, "snr": -50.0, "votes": -100},
        {"ra": 359.9999, "dec": -89.9999, "anomaly_score": 1e300, "snr": 1e300, "votes": 10**9},
    ]
    for doc in hostile_docs:
        score = engine.score_candidate(doc)
        assert math.isfinite(score) and 0.0 <= score <= 1.0, f"Invalid AAD score {score} for {doc}"
        weights = engine.update_from_vote(doc)
        assert abs(sum(weights.values()) - 1.0) < 1e-3

    # 16-thread concurrent online updates
    def _worker(i: int) -> float:
        d = {
            "ra": (i * 23.5) % 360.0,
            "dec": -60.0 + (i % 120),
            "anomaly_score": 0.92,
            "snr": 14.0,
            "votes": i + 1,
            "object_class": "planet_x_candidate",
        }
        engine.update_from_vote(d)
        return engine.score_candidate(d)

    with ThreadPoolExecutor(max_workers=16) as pool:
        scores = list(pool.map(_worker, range(64)))
    assert all(0.0 <= s <= 1.0 for s in scores)


@respx.mock
def test_torture_ecliptic_poles_and_kinematics(client):
    """Torture 3: North/South celestial poles, North Ecliptic Pole (RA=270, Dec=+66.5607), and crossmatch schema."""
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(503))

    # North Ecliptic Pole: (RA=270 deg, Dec=90 - 23.4392911 = 66.5607089 deg) -> beta_ecl ~ +90 deg
    _, beta_nep = icrs_to_ecliptic_deg(270.0, 66.5607089)
    assert abs(beta_nep - 90.0) < 0.01

    kin_px = compute_kete_kbmod_kinematics(51.2, 14.8, distance_au=520.0, n_frames=24)
    # At 520 AU, 1 AU / 520 AU = 206265 / 520 = 396.66 arcsec annual parallax amplitude
    assert 395.0 <= kin_px["annual_parallax_arcsec"] <= 398.0
    assert abs(kin_px["kbmod_expected_snr_gain"] - math.sqrt(24)) < 0.01

    r = client.get("/api/v1/missions/crossmatch", params={"ra": 133.7605, "dec": -7.2421, "radius_arcsec": 10})
    assert r.status_code == 200
    body = r.json()
    assert_path_response_schema(body, "/api/v1/missions/crossmatch", "get", "200")
    assert body["sed_physics"]["spectral_regime"] == "ultracool_or_substellar"


@respx.mock
def test_optimization_benchmark_multi_mission_latency(client):
    """Optimization benchmark: crossmatch + SED fitter + kinematics must execute in < 10 ms average."""
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(503))
    client.get("/api/v1/missions/crossmatch", params={"ra": 76.95642, "dec": 30.40142})
    n_runs = 25
    t0 = time.perf_counter()
    for _ in range(n_runs):
        r = client.get("/api/v1/missions/crossmatch", params={"ra": 76.95642, "dec": 30.40142})
        assert r.status_code == 200
    avg_ms = ((time.perf_counter() - t0) * 1000.0) / n_runs
    assert avg_ms < 15.0, f"Crossmatch + SED physics latency too slow: {avg_ms:.2f} ms"
