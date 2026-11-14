"""Comprehensive offline test suite for AEON ai-engine (M8 & M9)."""

from __future__ import annotations

from types import SimpleNamespace
import numpy as np
import pytest
import respx
from httpx import Response

from app.models import OBJECT_CLASSES, synthesize_spectrum
from tests.conftest import assert_path_response_schema

# 20 Turkish command test cases covering all 13 UiAction types + compound commands
TR_COMMAND_CASES: list[tuple[str, list[str]]] = [
    ("WISE 0855'e git ve fark modunu aç", ["FLY_TO", "TOGGLE_DIFF"]),
    ("RW Aurigae yıldızına uç", ["FLY_TO"]),
    ("PX-2026-09 gezegen adayına odaklan", ["FLY_TO"]),
    ("Luhman 16 hedefine git", ["FLY_TO"]),
    ("Barnard yıldızına merkezle", ["FLY_TO"]),
    ("TW Hydrae yıldızını göster", ["FLY_TO"]),
    ("18 Scorpii hedefine git", ["FLY_TO"]),
    ("WISE 1828 kahverengi cücesine git", ["FLY_TO"]),
    ("RA: 133.79, Dec: -7.24 koordinatına git", ["FLY_TO"]),
    ("Dönemi 2026-Q3 yap", ["SET_EPOCH"]),
    ("2026-Q2 dönemine geç", ["SET_EPOCH"]),
    ("Görüntü farkı modunu aç Q1 ve Q3", ["TOGGLE_DIFF"]),
    ("Kaydır ve yığ analizi çalıştır 110 arcsec PA 62", ["RUN_SHIFT_STACK"]),
    ("5x5 kör hız taraması başlat", ["RUN_BLIND_SEARCH"]),
    ("102-bant tayf panelini aç", ["OPEN_SPECTRUM"]),
    ("3D yörünge simülasyonunu göster", ["OPEN_3D_ORBIT"]),
    ("JWST ve Hubble görüntülerini aç", ["OPEN_JWST"]),
    ("Gaia ve WISE çapraz eşleştirme panelini aç", ["OPEN_CROSSMATCH"]),
    ("Renk haritasını viridis yap", ["SET_COLORMAP"]),
    ("Dili Türkçe'ye çevir ve PDF keşif raporu oluştur", ["SET_LANG", "GENERATE_PDF"]),
    ("Jüri demo turunu başlat", ["START_DEMO_TOUR"]),
]

# 20 English command test cases covering all 13 UiAction types + compound commands
EN_COMMAND_CASES: list[tuple[str, list[str]]] = [
    ("Fly to WISE 0855 and toggle difference mode", ["FLY_TO", "TOGGLE_DIFF"]),
    ("Go to RW Aurigae", ["FLY_TO"]),
    ("Focus on Planet X candidate PX-2026-09", ["FLY_TO"]),
    ("Slew to Luhman 16", ["FLY_TO"]),
    ("Center on Barnard's Star", ["FLY_TO"]),
    ("Navigate to TW Hydrae", ["FLY_TO"]),
    ("Point to 18 Scorpii", ["FLY_TO"]),
    ("Fly to WISE 1828", ["FLY_TO"]),
    ("Go to RA=51.2, Dec=14.8", ["FLY_TO"]),
    ("Set epoch to 2026-Q4", ["SET_EPOCH"]),
    ("Switch to 2026-Q1", ["SET_EPOCH"]),
    ("Enable image differencing between Q1 and Q3", ["TOGGLE_DIFF"]),
    ("Run shift and stack at 110 arcsec/yr PA 62", ["RUN_SHIFT_STACK"]),
    ("Start 5x5 blind velocity search", ["RUN_BLIND_SEARCH"]),
    ("Open the 102-band spectrum panel", ["OPEN_SPECTRUM"]),
    ("Show 3D solar system orbit forecast", ["OPEN_3D_ORBIT"]),
    ("Open JWST picture-in-picture overlay", ["OPEN_JWST"]),
    ("Open Gaia and WISE crossmatch SED panel", ["OPEN_CROSSMATCH"]),
    ("Change colormap to magma", ["SET_COLORMAP"]),
    ("Switch to English and generate PDF discovery report", ["SET_LANG", "GENERATE_PDF"]),
    ("Start the guided jury demo tour", ["START_DEMO_TOUR"]),
]


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "spectral_1d_cnn" in body["model_versions"]
    assert "patch_anomaly_vit" in body["model_versions"]


@pytest.mark.parametrize("message,expected_types", TR_COMMAND_CASES)
@respx.mock
def test_tr_rule_based_commands(client, monkeypatch, message, expected_types):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    respx.get("http://localhost:8000/api/v1/catalog/search").mock(return_value=Response(503))

    resp = client.post("/api/v1/ai/command", json={"message": message, "lang": "tr"})
    assert resp.status_code == 200
    data = resp.json()
    assert_path_response_schema(data, "/api/v1/ai/command", "post")
    assert data["lang"] == "tr"
    assert "[Kural tabanlı mod]" in data["reply"]
    actual_types = [a["type"] for a in data["actions"]]
    for exp in expected_types:
        assert exp in actual_types
    if expected_types == ["FLY_TO", "TOGGLE_DIFF"]:
        assert actual_types[:2] == ["FLY_TO", "TOGGLE_DIFF"]


@pytest.mark.parametrize("message,expected_types", EN_COMMAND_CASES)
@respx.mock
def test_en_rule_based_commands(client, monkeypatch, message, expected_types):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    respx.get("http://localhost:8000/api/v1/catalog/search").mock(return_value=Response(503))

    resp = client.post("/api/v1/ai/command", json={"message": message, "lang": "en"})
    assert resp.status_code == 200
    data = resp.json()
    assert_path_response_schema(data, "/api/v1/ai/command", "post")
    assert data["lang"] == "en"
    assert "[Rule-based fallback mode]" in data["reply"]
    actual_types = [a["type"] for a in data["actions"]]
    for exp in expected_types:
        assert exp in actual_types
    if expected_types == ["FLY_TO", "TOGGLE_DIFF"]:
        assert actual_types[:2] == ["FLY_TO", "TOGGLE_DIFF"]


@respx.mock
def test_synthetic_px_honesty_in_command(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    respx.get("http://localhost:8000/api/v1/catalog/search").mock(return_value=Response(503))

    resp = client.post("/api/v1/ai/command", json={"message": "PX-2026-09 hedefine git ve kör tarama başlat"})
    assert resp.status_code == 200
    body = resp.json()
    assert "is_synthetic=true" in body["reply"]
    fly = next(a for a in body["actions"] if a["type"] == "FLY_TO")
    assert fly["params"]["is_synthetic"] is True


@respx.mock
def test_llm_function_calling_and_refusal(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-mock")
    respx.get("http://localhost:8000/api/v1/catalog/search").mock(
        return_value=Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "id": "wise-0855",
                        "name": "WISE J085510.83-071442.5",
                        "ra": 133.7607,
                        "dec": -7.24219,
                        "object_class": "cold_brown_dwarf",
                    }
                ],
            },
        )
    )

    calls = []

    class DummyMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(
                    stop_reason="tool_use",
                    content=[
                        SimpleNamespace(type="tool_use", id="t1", name="search_catalog", input={"q": "wise-0855"}),
                        SimpleNamespace(
                            type="tool_use",
                            id="t2",
                            name="FLY_TO",
                            input={"ra": 133.7607, "dec": -7.24219, "target_id": "wise-0855", "name": "WISE 0855"},
                        ),
                    ],
                )
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Slewed to WISE 0855.")],
            )

    class DummyClient:
        def __init__(self, api_key=None):
            self.messages = DummyMessages()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", DummyClient)

    resp = client.post("/api/v1/ai/command", json={"message": "Fly to WISE 0855", "lang": "en"})
    assert resp.status_code == 200
    body = resp.json()
    assert_path_response_schema(body, "/api/v1/ai/command", "post")
    assert body["actions"] == [
        {"type": "FLY_TO", "params": {"ra": 133.7607, "dec": -7.24219, "target_id": "wise-0855", "name": "WISE 0855"}}
    ]
    assert calls[0]["tool_choice"] == {"type": "auto"}

    # Now test stop_reason == "refusal"
    class RefusalMessages:
        def create(self, **kwargs):
            return SimpleNamespace(stop_reason="refusal", content=[])

    class RefusalClient:
        def __init__(self, api_key=None):
            self.messages = RefusalMessages()

    monkeypatch.setattr(anthropic, "Anthropic", RefusalClient)
    resp_ref = client.post("/api/v1/ai/command", json={"message": "unsafe prompt", "lang": "tr"})
    assert resp_ref.status_code == 200
    body_ref = resp_ref.json()
    assert_path_response_schema(body_ref, "/api/v1/ai/command", "post")
    assert body_ref["actions"] == []


@pytest.mark.parametrize("cls_name", OBJECT_CLASSES)
def test_classify_1d_cnn_all_five_classes(client, cls_name):
    flux = synthesize_spectrum(cls_name, mag_ab_w2=15.5).tolist()
    resp = client.post("/api/v1/ai/classify", json={"flux_ujy": flux})
    assert resp.status_code == 200
    body = resp.json()
    assert_path_response_schema(body, "/api/v1/ai/classify", "post")
    assert body["top_class"] == cls_name
    assert set(body["probabilities"].keys()) == set(OBJECT_CLASSES)
    assert abs(sum(body["probabilities"].values()) - 1.0) < 1e-2
    assert 0.0 <= body["anomaly_score"] <= 1.0


def test_classify_patch_anomaly_vit_cutouts(client):
    rng = np.random.default_rng(123)
    # 1. Flat background noise cutout -> low anomaly score
    bg = rng.normal(0.0, 1.0, size=(64 * 64)).tolist()
    resp_bg = client.post(
        "/api/v1/ai/classify",
        json={"image": {"width": 64, "height": 64, "data": bg}},
    )
    assert resp_bg.status_code == 200
    body_bg = resp_bg.json()
    assert_path_response_schema(body_bg, "/api/v1/ai/classify", "post")

    # 2. Strong dipole + high-S/N point source cutout -> higher anomaly score
    arr = rng.normal(0.0, 1.0, size=(64, 64))
    arr[30:33, 30:33] += 28.0
    arr[25:28, 25:28] -= 22.0
    flux_px = synthesize_spectrum("planet_x_candidate", mag_ab_w2=22.0).tolist()
    resp_anom = client.post(
        "/api/v1/ai/classify",
        json={
            "flux_ujy": flux_px,
            "image": {"width": 64, "height": 64, "data": arr.ravel().tolist()},
        },
    )
    assert resp_anom.status_code == 200
    body_anom = resp_anom.json()
    assert_path_response_schema(body_anom, "/api/v1/ai/classify", "post")
    assert body_anom["anomaly_score"] > body_bg["anomaly_score"]
    assert body_anom["anomaly_score"] >= 0.85


def test_classify_validation_errors(client):
    # Wrong number of bands
    resp_bad_bands = client.post("/api/v1/ai/classify", json={"flux_ujy": [1.0, 2.0, 3.0]})
    assert resp_bad_bands.status_code == 422

    # Mismatched width*height
    resp_bad_img = client.post("/api/v1/ai/classify", json={"image": {"width": 16, "height": 16, "data": [1.0] * 10}})
    assert resp_bad_img.status_code == 422
