"""The classification says which spectrum it classified, and never reports a temperature it cannot measure."""

from __future__ import annotations

import math

import numpy as np
import respx
from httpx import Response

from app.models import synthesize_spectrum
from app.physics_sed import analyze_spectrum_physics
from conftest import assert_path_response_schema

SPECTRUM = "http://localhost:8000/api/v1/spectrum"
BD = synthesize_spectrum("cold_brown_dwarf", mag_ab_w2=17.0, teff_k=250.0).tolist()


def body(mode, epoch="2026-Q2", oq="2026-Q2", nb=78):
    return {"ra": 133.7589, "dec": -7.2421, "epoch": epoch, "flux_ujy": BD, "snr_median": 11.4,
            "pipeline": {"data_mode": mode, "observed_quarter": oq, "n_bands_measured": nb}}


@respx.mock
def test_real_spherex_spectrum_is_reported_with_its_epoch(client):
    route = respx.get(SPECTRUM).mock(return_value=Response(200, json=body("fits_archive", "2026-Q4", "2025-Q4", 85)))
    r = client.post("/api/v1/ai/classify", json={"ra": 133.7589, "dec": -7.2421})
    assert r.status_code == 200
    out = r.json()
    assert_path_response_schema(out, "/api/v1/ai/classify", "post")
    assert out["spectrum_source"] == "archive"
    assert out["spectrum_data_mode"] == "fits_archive"
    assert out["spectrum_epoch"] == "2026-Q4" and out["spectrum_observed_quarter"] == "2025-Q4"
    assert out["spectrum_bands_measured"] == 85
    assert "epoch" not in dict(route.calls.last.request.url.params)     # the backend picks the epoch


@respx.mock
def test_physical_model_spectrum_is_not_presented_as_data(client):
    respx.get(SPECTRUM).mock(return_value=Response(200, json=body("physical_model", "2026-Q1", None, None)))
    out = client.post("/api/v1/ai/classify", json={"ra": 10.0, "dec": 10.0}).json()
    assert out["spectrum_source"] == "archive" and out["spectrum_data_mode"] == "physical_model"
    assert out["spectrum_observed_quarter"] is None and out["spectrum_bands_measured"] is None
    assert out["astroclip_zogy"]["image_provided"] is False       # site requests carry no image


@respx.mock
def test_malformed_provenance_fields_become_null(client):
    b = body("fits_archive")
    b["pipeline"] = {"data_mode": "made_up", "observed_quarter": "x" * 500, "n_bands_measured": True}
    b["epoch"] = ["not", "a", "string"]
    respx.get(SPECTRUM).mock(return_value=Response(200, json=b))
    out = client.post("/api/v1/ai/classify", json={"ra": 10.0, "dec": 10.0}).json()
    assert out["spectrum_data_mode"] is None and out["spectrum_epoch"] is None
    assert out["spectrum_observed_quarter"] is None and out["spectrum_bands_measured"] is None


@respx.mock
def test_request_spectrum_has_no_archive_provenance(client):
    out = client.post("/api/v1/ai/classify", json={"flux_ujy": BD}).json()
    assert out["spectrum_source"] == "request" and out["spectrum_data_mode"] is None


def test_planet_x_temperature_is_not_invented():
    """Planet X light in 0.75-5 um is reflected sunlight: no template label (65/85/110 K) is a measurement."""
    d = analyze_spectrum_physics(synthesize_spectrum("planet_x_candidate", mag_ab_w2=22.6))
    assert d["best_template_class"] == "planet_x_candidate"
    assert d["teff_k"] is None and d["log_g_cgs"] is None
    assert d["teff_method"] == "not_measurable_reflected_light" and "520 AU" in d["temperature_note"]


def test_brown_dwarf_temperature_still_measured():
    d = analyze_spectrum_physics(BD)
    assert d["teff_method"] == "template_grid" and d["teff_k"] is not None and d["teff_k"] < 600.0


def test_no_positive_flux_gives_nulls_not_placeholders():
    for flux in (np.zeros(102), -np.ones(102)):
        d = analyze_spectrum_physics(flux)
        assert d["teff_k"] is None and d["best_template_class"] is None and d["w1_ab_mag"] is None
        assert d["teff_method"] == "none"
        assert all(v is None or isinstance(v, (str, list)) or math.isfinite(v) for v in d.values())
