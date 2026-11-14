"""End-to-end tests through the Nginx gateway (AEON_GATEWAY_URL, default http://localhost).

Core paths must answer. Paths owned by ai-engine / multi-mission-api are skipped while those
services are not deployed (gateway returns 502/503/504), and schema-checked once they are.
"""

import json
import os
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator

BASE = os.environ.get("AEON_GATEWAY_URL", "http://localhost").rstrip("/")
CONTRACT = json.loads((Path(__file__).resolve().parents[2] / "openapi.json").read_text(encoding="utf-8"))
PX = (51.295473, 14.8325559)


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url=BASE, timeout=120) as c:
        try:
            c.get("/api/v1/health")
        except httpx.HTTPError as exc:
            pytest.skip(f"gateway not reachable at {BASE}: {exc}")
        yield c


def check(payload, schema):
    v = Draft202012Validator({**CONTRACT, "$ref": f"#/components/schemas/{schema}"})
    errors = list(v.iter_errors(payload))
    assert not errors, "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5])


def optional(resp):
    if resp.status_code in (404, 502, 503, 504):
        pytest.skip("service not deployed behind the gateway yet")
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()


def test_health(http):
    r = http.get("/api/v1/health")
    assert r.status_code == 200
    check(r.json(), "Health")


def test_catalog_and_spectrum(http):
    cat = http.get("/api/v1/catalog/search", params={"q": "WISE 0855"}).json()
    check(cat, "CatalogResponse")
    o = cat["results"][0]
    spec = http.get("/api/v1/spectrum", params={"ra": o["ra"], "dec": o["dec"]}).json()
    check(spec, "Spectrum")


def test_cutout_is_gzipped(http):
    r = http.get("/api/v1/sky/cutout", params={"ra": 10, "dec": 20}, headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"
    check(r.json(), "Image")


def test_difference(http):
    r = http.post("/api/v1/analysis/difference", json={"ra": 133.7605, "dec": -7.2421})
    check(r.json(), "DifferenceResult")


def test_discovery_chain(http):
    stack = http.post("/api/v1/analysis/shift-stack", json={
        "ra": PX[0], "dec": PX[1], "rate_arcsec_yr": 110, "pa_deg": 62, "distance_au": 520}).json()
    check(stack, "ShiftStackResult")
    assert stack["snr_stacked"] > 5
    orbit = http.post("/api/v1/orbit/simulate", json={"target_id": "px-2026-09"}).json()
    check(orbit, "OrbitResult")


def test_ai_command(http):
    body = optional(http.post("/api/v1/ai/command", json={"message": "WISE 0855'e git", "lang": "tr"}))
    assert "actions" in body


def test_ai_classify(http):
    optional(http.post("/api/v1/ai/classify", json={"flux_ujy": [1.0] * 102}))


CLASSES = CONTRACT["components"]["schemas"]["ObjectClass"]["enum"]
SITE = "https://www.a-eon.engineer"


def test_ai_classify_by_coordinates_like_the_site(http):
    """The web UI sends only (ra, dec); ai-engine reads the spectrum from the backend through the compose network."""
    body = optional(http.post("/api/v1/ai/classify", json={"ra": 133.7586977, "dec": -7.2420576}, headers={"Origin": SITE}))
    assert body["spectrum_source"] == "archive", body
    assert body["top_class"] in CLASSES and set(body["probabilities"]) == set(CLASSES)
    assert abs(sum(body["probabilities"].values()) - 1.0) < 1e-3
    assert 0.0 <= body["anomaly_score"] <= 1.0
    assert body["physics_diagnostics"] is not None


def test_ai_classify_rejects_what_the_site_used_to_send(http):
    """An empty body is a client error (422) with a readable reason; a NaN coordinate is too (it used to be a 500)."""
    r = http.post("/api/v1/ai/classify", json={})
    if r.status_code in (404, 502, 503, 504):
        pytest.skip("service not deployed behind the gateway yet")
    assert r.status_code == 422 and "ra, dec" in r.text
    r = http.post("/api/v1/ai/classify", content='{"ra": NaN, "dec": 1}', headers={"Content-Type": "application/json"})
    assert r.status_code == 422, r.text[:200]


def test_ai_paths_allow_the_site_origin(http):
    """The browser preflights the JSON POST; without these headers the UI reports the engine as unreachable."""
    for path in ("/api/v1/ai/classify", "/api/v1/ai/command"):
        r = http.options(path, headers={"Origin": SITE, "Access-Control-Request-Method": "POST",
                                        "Access-Control-Request-Headers": "content-type"})
        if r.status_code in (404, 502, 503, 504):
            pytest.skip("service not deployed behind the gateway yet")
        assert r.status_code == 200 and r.headers.get("access-control-allow-origin") == SITE, (path, dict(r.headers))


def test_missions(http):
    optional(http.get("/api/v1/missions/crossmatch", params={"ra": 133.7605, "dec": -7.2421}))
    optional(http.get("/api/v1/alerts/gcn"))
    optional(http.get("/api/v1/candidates"))
