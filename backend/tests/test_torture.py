"""Torture tests: hostile, edge-case and concurrent input on the paths the frontend calls.

Every response must be either a schema-valid 200 or a clean 4xx with a JSON `detail` — never a
500, a hang, NaN/Infinity in JSON, or a non-JSON body.
"""

import json
import math
import random
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import assert_schema

HOSTILE_QUERIES = [
    "", " ", "%", "_", "*", "'", "\"", "' OR 1=1 --", "'; DROP TABLE objects; --", "\\", "\\\\%",
    "<script>alert(1)</script>", "../../etc/passwd", "\x00", "‮لعربية",
    "Gezegen X", "WİSE 0855", "wise 0855", "🪐 planet x", "a" * 5000, "%" * 300,
    "NaN", "Infinity", "-0", "1e309", "133.79 -7.24", "{\"$ne\": null}", "${7*7}", "{{7*7}}",
]

EDGE_COORDS = [
    (0.0, 0.0), (360.0, 0.0), (359.999999, 0.0), (0.0, 90.0), (0.0, -90.0), (180.0, 89.9999),
    (123.4, -89.9999), (51.295473, 14.8325559), (133.7605, -7.2421), (1e-12, 1e-12),
]


def _reject(token):
    raise AssertionError(f"non-finite number {token} in JSON")


def no_bad_floats(text: str):
    json.loads(text, parse_constant=_reject)


def ok_or_clean_4xx(r, schema=None):
    assert r.status_code < 500, f"{r.status_code}: {r.text[:300]}"
    body = r.json()
    if r.status_code == 200:
        no_bad_floats(r.text)
        if schema:
            assert_schema(body, schema)
    else:
        assert "detail" in body
    return body


@pytest.mark.parametrize("q", HOSTILE_QUERIES)
def test_catalog_name_search_hostile(client, q):
    ok_or_clean_4xx(client.get("/api/v1/catalog/search", params={"q": q}), "CatalogResponse")


def test_catalog_like_wildcards_do_not_match_everything(client):
    # '%' and '_' are LIKE wildcards; they must be treated as plain text, not "match all".
    for q in ("%", "_", "%%", "%_%"):
        body = client.get("/api/v1/catalog/search", params={"q": q}).json()
        assert body["count"] == 0, q


@pytest.mark.parametrize("ra,dec", EDGE_COORDS)
def test_cone_and_cutout_edges(client, ra, dec):
    ok_or_clean_4xx(client.get("/api/v1/catalog/search", params={"ra": ra, "dec": dec, "radius_arcmin": 5, "include_field": True}),
                    "CatalogResponse")
    img = ok_or_clean_4xx(client.get("/api/v1/sky/cutout", params={"ra": ra, "dec": dec, "size_px": 32}), "Image")
    assert len(img["data"]) == 32 * 32 and all(math.isfinite(v) for v in img["data"])


@pytest.mark.parametrize("params", [
    {"ra": -0.001, "dec": 0}, {"ra": 360.001, "dec": 0}, {"ra": 0, "dec": 90.0001}, {"ra": 0, "dec": -91},
    {"ra": "abc", "dec": 0}, {"ra": "nan", "dec": 0}, {"ra": "inf", "dec": 0}, {"ra": 10, "dec": 10, "size_px": 15},
    {"ra": 10, "dec": 10, "size_px": 10_000}, {"ra": 10, "dec": 10, "epoch": "2026-Q5"}, {"ra": 10, "dec": 10, "band": 102},
    {"ra": 10, "dec": 10, "pixel_scale_arcsec": 0}, {"dec": 10},
])
def test_cutout_rejects_bad_params(client, params):
    r = client.get("/api/v1/sky/cutout", params=params)
    assert 400 <= r.status_code < 500, (params, r.status_code, r.text[:200])


@pytest.mark.parametrize("ra,dec", [(0.0, 0.0), (359.9999, -89.99), (51.295473, 14.8325559)])
def test_spectrum_edges(client, ra, dec):
    body = ok_or_clean_4xx(client.get("/api/v1/spectrum", params={"ra": ra, "dec": dec}), "Spectrum")
    assert all(math.isfinite(v) for v in body["flux_ujy"] + body["flux_err_ujy"])


@pytest.mark.parametrize("body", [
    {}, {"ra": 10}, {"ra": 10, "dec": 10, "rate_arcsec_yr": -5}, {"ra": 10, "dec": 10, "distance_au": 0},
    {"ra": 10, "dec": 10, "distance_au": -1}, {"ra": 10, "dec": 10, "n_frames": 1}, {"ra": 10, "dec": 10, "n_frames": 1000},
    {"ra": 10, "dec": 10, "cadence": "weekly"}, {"ra": 10, "dec": 10, "grid": 100},
    {"ra": 10, "dec": 10, "rate_arcsec_yr": 4999, "pa_deg": 0},             # track far larger than any frame
    {"ra": 10, "dec": 10, "distance_au": 0.5, "rate_arcsec_yr": 10},         # parallax of a body inside 1 AU
])
def test_shift_stack_hostile(client, body):
    r = client.post("/api/v1/analysis/shift-stack", json=body)
    assert r.status_code < 500, (body, r.status_code, r.text[:300])


def test_blind_search_rejects_huge_track(client):
    r = client.post("/api/v1/analysis/blind-search", json={"ra": 10, "dec": 10, "distance_range_au": [1, 2]})
    assert 400 <= r.status_code < 500


@pytest.mark.parametrize("body", [
    {"detections": [{"t": 2026.1, "ra": 10, "dec": 0}] * 3},                  # identical points
    {"detections": [{"t": 2026.1 + i * 1e-6, "ra": 10, "dec": 0} for i in range(3)]},
    {"detections": [{"t": 2026.0 + i * 0.1, "ra": random.uniform(0, 360), "dec": random.uniform(-90, 90)} for i in range(6)]},
    {"elements": {"a_au": 1e-6, "e": 0, "inc_deg": 0}},
    {"elements": {"a_au": 5, "e": 0.999999, "inc_deg": 0}},
    {"elements": {"a_au": 5, "e": 1.0, "inc_deg": 0}},
    {"observation": {"ra": 10, "dec": 10, "distance_au": 1e-9}},
    {"target_id": "../../etc"}, {"horizons_years": [0]}, {"target_id": "px-2026-09", "horizons_years": [1e9]},
])
def test_orbit_hostile(client, body):
    r = client.post("/api/v1/orbit/simulate", json=body)
    assert r.status_code < 500, (body, r.status_code, r.text[:300])
    if r.status_code == 200:
        no_bad_floats(r.text)


def test_concurrent_mixed_load(client):
    """60 mixed requests from 12 threads, as a busy demo would produce (slider + search spam)."""
    rng = random.Random(42)

    def one(i):
        kind = i % 4
        if kind == 0:
            return client.get("/api/v1/catalog/search", params={"q": rng.choice(["wise", "rw aur", "planet x", "%"])})
        if kind == 1:
            return client.get("/api/v1/sky/cutout", params={"ra": 133.7605, "dec": -7.2421,
                                                             "epoch": rng.choice(["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"])})
        if kind == 2:
            return client.get("/api/v1/spectrum", params={"ra": 76.95642, "dec": 30.40142,
                                                           "epoch": rng.choice(["2026-Q1", "2026-Q3"])})
        return client.post("/api/v1/analysis/shift-stack", json={"ra": 51.295473, "dec": 14.8325559, "rate_arcsec_yr": 110,
                                                                  "pa_deg": rng.choice([55, 62, 70]), "distance_au": 520})

    with ThreadPoolExecutor(max_workers=12) as ex:
        responses = list(ex.map(one, range(60)))
    codes = [r.status_code for r in responses]
    assert all(c == 200 for c in codes), codes
    for r in responses:
        json.loads(r.text)


def test_deterministic_under_concurrency(client):
    """Cached and uncached paths return byte-identical bodies for the same request."""
    q = {"ra": 76.95642, "dec": 30.40142, "epoch": "2026-Q2"}
    with ThreadPoolExecutor(max_workers=8) as ex:
        bodies = list(ex.map(lambda _: client.get("/api/v1/spectrum", params=q).text, range(16)))
    assert len(set(bodies)) == 1


@pytest.mark.parametrize("path", ["/api/v1/analysis/difference", "/api/v1/analysis/shift-stack",
                                  "/api/v1/analysis/blind-search", "/api/v1/orbit/simulate"])
@pytest.mark.parametrize("raw", ['{"ra": NaN, "dec": 1}', '{"ra": Infinity, "dec": -Infinity}', '{"ra": 1e999, "dec": 1}'])
def test_non_finite_numbers_in_a_json_body_are_422_not_500(client, path, raw):
    """The 422 echoes the rejected input; a NaN in it used to make the error response itself fail."""
    r = client.post(path, content=raw, headers={"Content-Type": "application/json"})
    assert r.status_code == 422, r.text[:200]
    assert "NaN" not in r.text and "Infinity" not in r.text      # strict JSON: non-finite input is echoed as text
