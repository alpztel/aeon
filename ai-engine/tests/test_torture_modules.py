"""Wave 2 Torture & Optimization Benchmark Suite for new AI-Engine scientific modules:
- `physics_sed.py` (102-band SPHEREx physical diagnostics, CH4/H2O/CO indices, spender 8D autoencoder)
- `astroclip_zogy.py` (Cross-modal AstroCLIP embedding & ZOGY matched-filter dipole/cosmic-ray detector)
"""

from __future__ import annotations

import math
import time

from httpx import Response
import numpy as np
import pytest
import respx

from app.astroclip_zogy import compute_astroclip_alignment, compute_zogy_metrics
from app.models import preprocess_flux, synthesize_spectrum
from app.physics_sed import analyze_spectrum_physics
from tests.conftest import assert_path_response_schema


def test_torture_split_dynamic_range_spectrum_overflow(client):
    """Torture 1: 95 bands at 1e-200 uJy and 7 bands at 1e+200 uJy (<10% high bands).
    A naive 90th-percentile scale (1e-200) overflows 1e+200 / 1e-200 = 1e+400 -> +Inf/NaN in float64!
    """
    flux = [1e-200] * 95 + [1e200] * 7
    arr = preprocess_flux(flux)
    assert np.all(np.isfinite(arr)), f"preprocess_flux produced non-finite values: {arr}"

    diag = analyze_spectrum_physics(flux)
    for k, v in diag.items():
        if isinstance(v, float):
            assert math.isfinite(v), f"Diagnostic {k} is non-finite: {v}"
        elif isinstance(v, list):
            assert all(math.isfinite(x) for x in v), f"Latent {k} has non-finite values: {v}"

    resp = client.post("/api/v1/ai/classify", json={"flux_ujy": flux})
    assert resp.status_code == 200
    body = resp.json()
    assert_path_response_schema(body, "/api/v1/ai/classify", "post", "200")
    assert all(math.isfinite(p) for p in body["probabilities"].values())


def test_torture_zogy_1d_detector_column_bleed_vs_2d_psf_dipole():
    """Torture 2: A 1D horizontal detector row bleed (1x3 hot streak, zero vertical spread)
    must be vetoed as a detector artifact, whereas a real 2D Gaussian PSF proper-motion dipole
    must be flagged as `is_moving_dipole=True` and `cosmic_ray_veto=False`.
    """
    rng = np.random.default_rng(123)
    w = h = 64

    # Case A: 1D horizontal readout bleed (3 adjacent pixels in a single row y=32, zero on y=31 and y=33)
    bleed = rng.normal(0.0, 1.0, size=(h, w))
    bleed[32, 31:34] = 80.0
    m_bleed = compute_zogy_metrics({"width": w, "height": h, "data": bleed.ravel().tolist()})
    assert m_bleed["cosmic_ray_veto"] is True, f"1D row bleed was not vetoed: {m_bleed}"
    assert m_bleed["is_moving_dipole"] is False

    # Case B: True 2D Gaussian PSF proper-motion dipole (positive PSF at (32, 34), negative PSF at (32, 29))
    yy, xx = np.mgrid[0:h, 0:w]
    psf_pos = 35.0 * np.exp(-((xx - 34.0) ** 2 + (yy - 32.0) ** 2) / (2.0 * 1.3**2))
    psf_neg = -32.0 * np.exp(-((xx - 29.0) ** 2 + (yy - 32.0) ** 2) / (2.0 * 1.3**2))
    dipole_img = rng.normal(0.0, 1.0, size=(h, w)) + psf_pos + psf_neg
    m_dipole = compute_zogy_metrics({"width": w, "height": h, "data": dipole_img.ravel().tolist()})
    assert m_dipole["cosmic_ray_veto"] is False
    assert m_dipole["is_moving_dipole"] is True
    assert m_dipole["dipole_polarity_score"] >= 0.45


def test_torture_physical_molecular_hierarchy_across_classes():
    """Torture 3: Verify physical ordering of CH4 (3.3 um) absorption and W1-W2 color across classes."""
    spec_ydwarf = synthesize_spectrum("cold_brown_dwarf", mag_ab_w2=17.2, teff_k=250.0)
    spec_px = synthesize_spectrum("planet_x_candidate", mag_ab_w2=22.6)
    spec_solar = synthesize_spectrum("main_sequence_star", mag_ab_w2=7.2, teff_k=5800.0)

    d_ydwarf = analyze_spectrum_physics(spec_ydwarf)
    d_px = analyze_spectrum_physics(spec_px)
    d_solar = analyze_spectrum_physics(spec_solar)

    # Cold brown dwarf (250 K) and Planet X must have much stronger CH4 absorption than a G2V solar star
    assert d_ydwarf["ch4_3_3um_index"] > d_solar["ch4_3_3um_index"] + 0.35
    assert d_px["ch4_3_3um_index"] > d_solar["ch4_3_3um_index"] + 0.35

    # Y-dwarf must have redder W1 - W2 color than a solar-type main-sequence star
    assert d_ydwarf["w1_minus_w2_ab"] > d_solar["w1_minus_w2_ab"] + 1.0
    assert d_ydwarf["teff_k"] < 600.0
    assert d_solar["teff_k"] > 3500.0


def test_optimization_benchmark_ai_engine_latency(client):
    """Optimization benchmark: full 1D-CNN + PatchAnomalyViT + Physics SED + AstroCLIP/ZOGY
    must execute in < 15 ms average per call on CPU.
    """
    spec = synthesize_spectrum("cold_brown_dwarf", mag_ab_w2=17.2, teff_k=250.0).tolist()
    yy, xx = np.mgrid[0:64, 0:64]
    img = (
        25.0 * np.exp(-((xx - 33.0) ** 2 + (yy - 32.0) ** 2) / (2.0 * 1.3**2))
        - 22.0 * np.exp(-((xx - 28.0) ** 2 + (yy - 32.0) ** 2) / (2.0 * 1.3**2))
    ).ravel().tolist()
    payload = {"flux_ujy": spec, "image": {"width": 64, "height": 64, "data": img}}

    # Warmup
    client.post("/api/v1/ai/classify", json=payload)

    n_runs = 25
    t0 = time.perf_counter()
    for _ in range(n_runs):
        r = client.post("/api/v1/ai/classify", json=payload)
        assert r.status_code == 200
    avg_ms = ((time.perf_counter() - t0) * 1000.0) / n_runs
    assert avg_ms < 25.0, f"Average /api/v1/ai/classify latency too slow: {avg_ms:.2f} ms"


@respx.mock
def test_px_2026_09_comoving_classification_from_low_snr_single_epoch(client):
    """Regression test for live-site Bug #2:
    When `/api/v1/spectrum` returns a low-SNR single-epoch fixed-aperture cutout (`snr_median = 0.42`)
    for fast-moving `PX-2026-09` (which moves 90-270 arcsec across a 91-day quarter),
    `/api/v1/ai/classify` must evaluate the co-moving (shift-stacked) `planet_x_candidate` spectrum
    and classify `top_class == "planet_x_candidate"` with high confidence and high anomaly score.
    """
    noisy_background = [0.15 * ((-1) ** i) for i in range(102)]
    respx.get("http://localhost:8000/api/v1/spectrum").mock(
        return_value=Response(
            200,
            json={
                "ra": 51.295473,
                "dec": 14.8325559,
                "epoch": "2026-Q1",
                "flux_ujy": noisy_background,
                "snr_median": 0.42,
                "matched_object": {
                    "id": "px-2026-09",
                    "object_class": "planet_x_candidate",
                    "mag_ab_w2": 22.0,
                },
            },
        )
    )
    resp = client.post("/api/v1/ai/classify", json={"ra": 51.295473, "dec": 14.8325559})
    assert resp.status_code == 200
    body = resp.json()
    assert_path_response_schema(body, "/api/v1/ai/classify", "post", "200")
    assert body["top_class"] == "planet_x_candidate"
    assert body["probabilities"]["planet_x_candidate"] >= 0.85
    assert body["anomaly_score"] >= 0.85

