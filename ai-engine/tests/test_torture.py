"""Torture and astrophysical edge-case tests for AEON ai-engine (M8 & M9).

Tests hostile inputs, numerical extremes (1e300 float32 overflow, NaN/Inf, all-negative or zero
spectra), physical edge cases (blank image vs cosmic-ray hot pixel vs multi-pixel PSF dipole,
low-S/N negative bands at AB mag 22.6, geocentric Earth-parallax coordinates of PX-2026-09,
physical bounds on shift-stack velocity/PA/distance), and 12-thread concurrent load.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
import random

import numpy as np
import pytest
import respx
from httpx import Response

from app.models import OBJECT_CLASSES, synthesize_spectrum
from tests.conftest import assert_path_response_schema

HOSTILE_MESSAGES = [
    " ",
    "%",
    "_",
    "*",
    "' OR 1=1 --",
    "'; DROP TABLE candidates; --",
    "<script>alert(1)</script>",
    "../../etc/passwd",
    "\x00",
    "‮لعربية",
    "WİSE 0855",
    "wise\u00a00855",
    "🪐 planet x",
    "a" * 1900,
    "%" * 300,
    "NaN",
    "Infinity",
    "-0",
    "1e309",
    "133.79 -7.24",
    '{"$ne": null}',
    "${7*7}",
    "{{7*7}}",
]


def _no_bad_floats(text: str) -> None:
    def _reject(token: str):
        raise AssertionError(f"Non-finite number {token} in JSON response")

    json.loads(text, parse_constant=_reject)


@pytest.mark.parametrize("msg", HOSTILE_MESSAGES)
@respx.mock
def test_command_hostile_inputs(client, monkeypatch, msg):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    respx.get("http://localhost:8000/api/v1/catalog/search").mock(return_value=Response(503))

    r = client.post("/api/v1/ai/command", json={"message": msg})
    assert r.status_code < 500, (msg, r.status_code, r.text[:200])
    if r.status_code == 200:
        _no_bad_floats(r.text)
        assert_path_response_schema(r.json(), "/api/v1/ai/command", "post")


def test_classify_extreme_float32_overflow_and_non_finite(client):
    # 1e300 overflows float32 to +inf -> must not produce NaN or 500!
    r_huge = client.post("/api/v1/ai/classify", json={"flux_ujy": [1e300] * 102})
    assert r_huge.status_code < 500, r_huge.text
    if r_huge.status_code == 200:
        _no_bad_floats(r_huge.text)
        body = r_huge.json()
        assert_path_response_schema(body, "/api/v1/ai/classify", "post")
        assert all(math.isfinite(v) for v in body["probabilities"].values())
        assert math.isfinite(body["anomaly_score"])

    # Raw NaN / Infinity in JSON must be rejected with 422 (never 500 or NaN out)
    r_nan = client.post(
        "/api/v1/ai/classify",
        content='{"flux_ujy": [' + ",".join(["NaN"] * 102) + "]}",
        headers={"Content-Type": "application/json"},
    )
    assert 400 <= r_nan.status_code < 500


def test_classify_physical_zero_and_all_negative_spectra(client):
    # Empty sky aperture with all zero or negative background-subtracted fluxes
    for val in (0.0, -5.0, 1e-30):
        r = client.post("/api/v1/ai/classify", json={"flux_ujy": [val] * 102})
        assert r.status_code == 200
        _no_bad_floats(r.text)
        body = r.json()
        assert_path_response_schema(body, "/api/v1/ai/classify", "post")
        # Featureless constant/zero spectrum must not claim >90% anomaly score
        assert body["anomaly_score"] < 0.50


def test_classify_physical_low_snr_negative_bands_spectrum(client):
    # At AB mag 20.5-21.5, noisy bands can dip negative due to background subtraction
    rng = np.random.default_rng(2026)
    true_spec = synthesize_spectrum("cold_brown_dwarf", mag_ab_w2=19.0, teff_k=250.0)
    noisy_spec = (true_spec + rng.normal(0.0, 0.25 * np.median(true_spec), size=102)).tolist()
    # Force several short-wavelength bands negative (realistic for Y dwarf at <1.5 um where flux ~ 0)
    for i in range(15):
        noisy_spec[i] = -2.5

    r = client.post("/api/v1/ai/classify", json={"flux_ujy": noisy_spec})
    assert r.status_code == 200
    body = r.json()
    assert_path_response_schema(body, "/api/v1/ai/classify", "post")
    assert body["top_class"] == "cold_brown_dwarf"


def test_image_anomaly_blank_vs_cosmic_ray_vs_psf_dipole(client):
    # 1. Blank/constant cutout has zero spatial variance -> anomaly_score must be very low (<= 0.15)
    r_blank = client.post(
        "/api/v1/ai/classify",
        json={"image": {"width": 64, "height": 64, "data": [0.0] * 4096}},
    )
    assert r_blank.status_code == 200
    score_blank = r_blank.json()["anomaly_score"]
    assert score_blank <= 0.15, f"Blank image had unrealistic anomaly_score={score_blank}"

    # 2. Single isolated 1-pixel cosmic ray / hot detector pixel surrounded by zeros/noise
    rng = np.random.default_rng(7)
    cr_img = rng.normal(0.0, 1.0, size=(64, 64))
    cr_img[32, 32] = 40.0  # 1-pixel spike with no PSF wings
    r_cr = client.post(
        "/api/v1/ai/classify",
        json={"image": {"width": 64, "height": 64, "data": cr_img.ravel().tolist()}},
    )
    score_cr = r_cr.json()["anomaly_score"]

    # 3. Real multi-pixel PSF proper-motion dipole (positive lobe + negative lobe across 3x3 PSF)
    dip_img = rng.normal(0.0, 1.0, size=(64, 64))
    dip_img[30:33, 30:33] += 18.0
    dip_img[25:28, 25:28] -= 18.0
    r_dip = client.post(
        "/api/v1/ai/classify",
        json={"image": {"width": 64, "height": 64, "data": dip_img.ravel().tolist()}},
    )
    score_dip = r_dip.json()["anomaly_score"]

    assert score_dip > score_cr, f"Multi-pixel PSF dipole ({score_dip}) should score higher than 1-px cosmic ray ({score_cr})"
    assert score_dip > score_blank


@respx.mock
def test_command_physical_parameter_bounds_and_bare_coords(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    respx.get("http://localhost:8000/api/v1/catalog/search").mock(return_value=Response(503))

    # Bare coordinate pair "133.79 -7.24" should be recognized as FLY_TO
    r_bare = client.post("/api/v1/ai/command", json={"message": "133.79 -7.24"})
    assert r_bare.status_code == 200
    actions_bare = r_bare.json()["actions"]
    assert any(a["type"] == "FLY_TO" and abs(a["params"]["ra"] - 133.79) < 1e-3 for a in actions_bare)

    # Extreme unphysical shift-stack rate (99999 arcsec/yr, PA 725 deg, 0 AU) must be clamped to valid physical bounds
    r_stack = client.post(
        "/api/v1/ai/command",
        json={"message": "Run shift and stack at 99999 arcsec/yr PA 725 at 0 AU"},
    )
    assert r_stack.status_code == 200
    stack_act = next(a for a in r_stack.json()["actions"] if a["type"] == "RUN_SHIFT_STACK")
    assert 0.0 <= stack_act["params"]["rate_arcsec_yr"] <= 5000.0
    assert 0.0 <= stack_act["params"]["pa_deg"] < 360.0
    assert stack_act["params"]["distance_au"] is None or stack_act["params"]["distance_au"] >= 1.0


@respx.mock
def test_concurrent_mixed_load_ai_engine(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    respx.get("http://localhost:8000/api/v1/catalog/search").mock(return_value=Response(503))
    rng = random.Random(42)
    spec = synthesize_spectrum("planet_x_candidate", mag_ab_w2=21.0).tolist()

    def worker(i: int):
        if i % 2 == 0:
            msg = rng.choice(["WISE 0855'e git", "Fly to PX-2026-09", "133.79 -7.24", "%"])
            return client.post("/api/v1/ai/command", json={"message": msg})
        return client.post("/api/v1/ai/classify", json={"flux_ujy": spec})

    with ThreadPoolExecutor(max_workers=12) as ex:
        resps = list(ex.map(worker, range(60)))

    assert all(r.status_code == 200 for r in resps)
    for r in resps:
        _no_bad_floats(r.text)


def test_training_pipeline_reproducible_metrics():
    from training.train import train_and_evaluate

    metrics = train_and_evaluate(seed=2026)
    assert metrics["accuracy"] >= 0.96, metrics
    for cls_name, f1 in metrics["f1_per_class"].items():
        assert f1 >= 0.90, (cls_name, metrics)


@respx.mock
def test_sexagesimal_hms_dms_and_context_aware_commands(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    respx.get("http://localhost:8000/api/v1/catalog/search").mock(return_value=Response(503))

    # 1. Sexagesimal coordinates of WISE 0855: 08h55m10.83s -07d14m42.5s -> RA=133.795125, Dec=-7.245139
    r_sexag = client.post(
        "/api/v1/ai/command",
        json={"message": "Fly to 08h55m10.83s -07d14m42.5s and open spectrum"},
    )
    assert r_sexag.status_code == 200
    actions = r_sexag.json()["actions"]
    fly = next(a for a in actions if a["type"] == "FLY_TO")
    assert abs(fly["params"]["ra"] - 133.795125) < 1e-3
    assert abs(fly["params"]["dec"] - (-7.245139)) < 1e-3

    # 2. Context-aware target resolution when message omits target name
    r_ctx = client.post(
        "/api/v1/ai/command",
        json={
            "message": "Tayfı aç ve 3D yörüngeyi göster",
            "lang": "tr",
            "context": {"selected_target": "rw-aur"},
        },
    )
    assert r_ctx.status_code == 200
    ctx_actions = r_ctx.json()["actions"]
    spec_act = next(a for a in ctx_actions if a["type"] == "OPEN_SPECTRUM")
    orb_act = next(a for a in ctx_actions if a["type"] == "OPEN_3D_ORBIT")
    assert spec_act["params"]["target_id"] == "rw-aur"
    assert abs(spec_act["params"]["ra"] - 76.95642) < 1e-3
    assert orb_act["params"]["target_id"] == "rw-aur"

    # Coordinate-only classification bridge (when frontend sends {ra, dec})
    respx.get("http://localhost:8000/api/v1/spectrum").mock(
        return_value=Response(200, json={"flux_ujy": synthesize_spectrum("cold_brown_dwarf", 17.2).tolist()})
    )
    r_coord = client.post("/api/v1/ai/classify", json={"ra": 133.7605, "dec": -7.2421})
    assert r_coord.status_code == 200
    assert_path_response_schema(r_coord.json(), "/api/v1/ai/classify", "post", "200")
    assert r_coord.json()["top_class"] == "cold_brown_dwarf"



