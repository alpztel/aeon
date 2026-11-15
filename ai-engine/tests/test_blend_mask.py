"""Classification on the target's own bands when the backend flags blended / unmeasured bands."""

from __future__ import annotations

import numpy as np
import respx
from httpx import Response

from app.models import WAVELENGTH_UM, synthesize_spectrum
from app.physics_sed import analyze_spectrum_physics, fill_unusable_bands, masked_template_fit
from conftest import assert_path_response_schema

SPECTRUM = "http://localhost:8000/api/v1/spectrum"
LAM = np.asarray(WAVELENGTH_UM, dtype=float)


def test_masked_fit_recovers_the_class_from_partial_bands():
    for cls, teff in (("main_sequence_star", 5800.0), ("young_variable_star", 4100.0), ("cold_brown_dwarf", 250.0)):
        sp = synthesize_spectrum(cls, 12.0, teff_k=teff)
        mask = LAM >= 2.0
        fit = masked_template_fit(sp, mask)
        assert fit is not None and fit["class"] == cls and fit["n_bands"] == int(mask.sum())


def test_fill_replaces_only_unusable_bands():
    sp = synthesize_spectrum("main_sequence_star", 12.0, teff_k=5800.0)
    dirty = sp.copy()
    dirty[LAM < 1.5] *= 30.0                        # a neighbour's light
    mask = LAM >= 1.5
    filled, fit = fill_unusable_bands(dirty, mask)
    np.testing.assert_array_equal(filled[mask], dirty[mask])
    assert np.allclose(filled[~mask], sp[~mask], rtol=0.15)       # back to the target's own level


def test_upper_limits_reject_a_template_brighter_than_the_blended_bands():
    bd = synthesize_spectrum("cold_brown_dwarf", 16.0, teff_k=250.0)
    mask = LAM >= 3.0
    ul = ~mask
    obs = bd.copy()
    obs[ul] = np.maximum(bd[ul], 0.0) + 1e-3 * float(np.max(bd))      # tiny neighbour: a tight upper limit
    fit = masked_template_fit(obs, mask, ul)
    assert fit is not None
    assert np.all(fit["template_flux"][ul] <= obs[ul] * 10 ** 0.5)    # never far above the limits


def test_too_few_usable_bands_gives_no_fit():
    sp = synthesize_spectrum("main_sequence_star", 12.0, teff_k=5800.0)
    assert masked_template_fit(sp, LAM > 4.9) is None


def test_physics_with_mask_nulls_diagnostics_outside_the_usable_bands():
    sp = synthesize_spectrum("cold_brown_dwarf", 16.0, teff_k=300.0)
    mask = (LAM < 3.0) | (LAM > 3.7)                  # the 3.1-3.6 um (W1 / CH4) window is unusable
    d = analyze_spectrum_physics(sp, mask=mask)
    assert d["w1_ab_mag"] is None and d["ch4_3_3um_index"] is None and d["w1_minus_w2_ab"] is None
    assert d["w2_ab_mag"] is not None and d["bands_used"] == int(mask.sum())
    assert "usable bands" in d["temperature_note"]


def _body(blended_below_um):
    sp = synthesize_spectrum("main_sequence_star", 12.0, teff_k=5800.0)
    flux = sp.copy()
    blended = (LAM < blended_below_um).tolist()
    flux[LAM < blended_below_um] *= 20.0
    return {"ra": 10.0, "dec": 10.0, "epoch": "2026-Q2", "flux_ujy": flux.tolist(), "snr_median": 20.0,
            "pipeline": {"data_mode": "fits_archive", "measured": [True] * 102, "blended": blended,
                         "n_bands_blended": int(sum(blended)), "n_bands_measured": 102}}


@respx.mock
def test_classify_reports_blended_bands_and_what_was_classified(client):
    respx.get(SPECTRUM).mock(return_value=Response(200, json=_body(1.6)))
    out = client.post("/api/v1/ai/classify", json={"ra": 10.0, "dec": 10.0}).json()
    assert_path_response_schema(out, "/api/v1/ai/classify", "post")
    n_bl = int((LAM < 1.6).sum())
    assert out["spectrum_bands_blended"] == n_bl and out["spectrum_bands_used"] == 102 - n_bl
    assert out["classification_input"].startswith(f"{102 - n_bl} usable bands")
    assert out["physics_diagnostics"]["best_template_class"] == "main_sequence_star"
    assert isinstance(out["physics_agrees"], bool)


@respx.mock
def test_clean_spectrum_is_classified_as_served(client):
    b = _body(0.0)
    respx.get(SPECTRUM).mock(return_value=Response(200, json=b))
    out = client.post("/api/v1/ai/classify", json={"ra": 10.0, "dec": 10.0}).json()
    assert out["classification_input"] == "measured" and out["spectrum_bands_used"] is None
    assert out["spectrum_bands_blended"] == 0


@respx.mock
def test_malformed_blend_lists_are_ignored(client):
    b = _body(1.6)
    b["pipeline"]["blended"] = ["yes"] * 102
    b["pipeline"]["measured"] = [True] * 50
    respx.get(SPECTRUM).mock(return_value=Response(200, json=b))
    out = client.post("/api/v1/ai/classify", json={"ra": 10.0, "dec": 10.0}).json()
    assert out["classification_input"] == "measured"
