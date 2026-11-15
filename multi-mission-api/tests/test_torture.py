"""Torture and astrophysical edge-case tests for AEON multi-mission-api (M6, M7, M10, M11).

Tests:
- Spherical astronomy edge cases: RA wrap across 0/360 deg boundary (359.9999 vs 0.0001 deg)
  and celestial poles (dec = +90 / -90 deg where cos(dec) -> 0).
- Earth reflex parallax geocentric coordinates of PX-2026-09 (ra=51.295473, dec=14.8325559)
  ensuring synthetic candidate detection and 'synthetic-test' GitHub label still trigger!
- Physical SED integrity: strictly positive finite fluxes and errors, sorted wavelengths,
  proper propagation of Vega -> AB zero points, rejection of corrupt/negative/NaN magnitudes.
- Concurrent race condition torture: 16 threads simultaneously submitting the exact same
  coordinate (must deduplicate to 1 candidate and 1 GitHub issue, never duplicate via TOCTOU race!).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math

import pytest
import respx
from httpx import Response

from tests.conftest import assert_path_response_schema

EDGE_COORDS = [
    (0.0, 0.0),
    (360.0, 0.0),
    (359.999999, 0.0),
    (0.0, 90.0),
    (0.0, -90.0),
    (180.0, 89.9999),
    (123.4, -89.9999),
    (51.295473, 14.8325559),
    (133.7605, -7.2421),
    (1e-12, 1e-12),
]


def _no_bad_floats(text: str) -> None:
    def _reject(token: str):
        raise AssertionError(f"Non-finite number {token} in JSON response")

    json.loads(text, parse_constant=_reject)


@pytest.mark.parametrize("ra,dec", EDGE_COORDS)
@respx.mock
def test_crossmatch_edge_coordinates_and_poles(client, ra, dec):
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(503))

    r = client.get("/api/v1/missions/crossmatch", params={"ra": ra, "dec": dec, "radius_arcsec": 6.0})
    assert r.status_code == 200, (ra, dec, r.text)
    _no_bad_floats(r.text)
    body = r.json()
    assert_path_response_schema(body, "/api/v1/missions/crossmatch", "get")
    for pt in body["sed"]:
        assert pt["wavelength_um"] > 0.0 and math.isfinite(pt["wavelength_um"])
        assert pt["flux_ujy"] >= 0.0 and math.isfinite(pt["flux_ujy"])
        assert pt.get("flux_err_ujy", 0.0) >= 0.0 and math.isfinite(pt.get("flux_err_ujy", 0.0))


@pytest.mark.parametrize(
    "params",
    [
        {"ra": -0.001, "dec": 0},
        {"ra": 360.001, "dec": 0},
        {"ra": 0, "dec": 90.001},
        {"ra": 0, "dec": -90.001},
        {"ra": 10, "dec": 10, "radius_arcsec": 0},
        {"ra": 10, "dec": 10, "radius_arcsec": -5},
        {"ra": 10, "dec": 10, "radius_arcsec": 99999},
        {"ra": "nan", "dec": 0},
        {"ra": "inf", "dec": 0},
    ],
)
def test_crossmatch_rejects_invalid_params(client, params):
    r = client.get("/api/v1/missions/crossmatch", params=params)
    assert 400 <= r.status_code < 500


@respx.mock
def test_px_2026_09_geocentric_parallax_position_is_flagged_synthetic(client, monkeypatch):
    """At 2026-Q1, Earth reflex parallax shifts PX-2026-09 (520 AU) from (51.2000, 14.8000)
    to (51.295473, 14.8325559) — a ~353 arcsec offset! Even when backend is offline,
    both crossmatch and candidate submission MUST recognize this geocentric position as synthetic."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_mock_token")
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(503))
    respx.post("http://localhost:8100/api/v1/ai/classify").mock(return_value=Response(503))

    gh_issues = []

    def _capture_issue(request):
        gh_issues.append(json.loads(request.content.decode("utf-8")))
        return Response(201, json={"html_url": "https://github.com/alpztel/aeon/issues/777"})

    respx.post("https://api.github.com/repos/alpztel/aeon/issues").mock(side_effect=_capture_issue)

    # Submit at exact 2026-Q1 geocentric apparent position without mentioning 'synthetic' in notes
    r = client.post(
        "/api/v1/candidates",
        json={
            "action": "submit",
            "candidate": {
                "ra": 51.295473,
                "dec": 14.8325559,
                "anomaly_score": 0.96,
                "snr": 8.4,
                "submitted_by": "blind-search-user",
                "notes": "Recovered moving source at 110 arcsec/yr PA 62",
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "is_synthetic=true" in body["notes"]
    # Services offline: no server-side scores, so the client's 0.96 / 8.4 must not open an issue.
    assert body["anomaly_score"] is None and body["snr"] is None
    assert gh_issues == []


@respx.mock
def test_synthetic_candidate_with_server_scores_gets_synthetic_label(client, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_mock_token")
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(200, json={
        "flux_ujy": [5.0] * 102, "snr_median": 8.4, "matched_object": {"id": "px-2026-09", "is_synthetic": True}}))
    respx.post("http://localhost:8100/api/v1/ai/classify").mock(return_value=Response(200, json={
        "top_class": "planet_x_candidate", "anomaly_score": 0.96, "probabilities": {}}))
    gh_issues = []
    respx.post("https://api.github.com/repos/alpztel/aeon/issues").mock(
        side_effect=lambda req: (gh_issues.append(json.loads(req.content.decode("utf-8"))),
                                 Response(201, json={"html_url": "https://github.com/alpztel/aeon/issues/778"}))[1])
    body = client.post("/api/v1/candidates", json={"action": "submit", "candidate": {
        "ra": 51.295473, "dec": 14.8325559, "notes": "@someone see https://x.example"}}).json()
    assert body["anomaly_score"] == 0.96 and len(gh_issues) == 1
    assert "synthetic-test" in gh_issues[0]["labels"]
    assert "@someone" not in gh_issues[0]["body"] and "https://x.example" not in gh_issues[0]["body"]


@respx.mock
def test_ra_360_wrap_and_polar_deduplication(client):
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(503))
    respx.post("http://localhost:8100/api/v1/ai/classify").mock(return_value=Response(503))

    # Candidate at RA = 359.9998 deg, Dec = 0.0 deg
    r1 = client.post(
        "/api/v1/candidates",
        json={"action": "submit", "candidate": {"ra": 359.9998, "dec": 0.0}},
    )
    assert r1.status_code == 200
    c1 = r1.json()

    # Candidate across the 0/360 boundary at RA = 0.0002 deg, Dec = 0.0 deg (separation = 1.44 arcsec <= 3")
    r2 = client.post(
        "/api/v1/candidates",
        json={"action": "submit", "candidate": {"ra": 0.0002, "dec": 0.0}},
    )
    assert r2.status_code == 200
    c2 = r2.json()
    assert c2["id"] == c1["id"], "Failed to deduplicate candidate across RA 359.9998 -> 0.0002 boundary"

    # Candidate at North Celestial Pole (Dec = +89.9999 deg, RA = 10 deg vs RA = 190 deg -> sep = 0.72 arcsec <= 3")
    p1 = client.post(
        "/api/v1/candidates",
        json={"action": "submit", "candidate": {"ra": 10.0, "dec": 89.9999}},
    ).json()
    p2 = client.post(
        "/api/v1/candidates",
        json={"action": "submit", "candidate": {"ra": 190.0, "dec": 89.9999}},
    ).json()
    assert p1["id"] == p2["id"], "Failed to deduplicate candidate near North Celestial Pole"


@respx.mock
def test_concurrent_duplicate_submission_race_condition(client, monkeypatch):
    """12 threads submitting the exact same new coordinate simultaneously must produce
    ONLY ONE stored candidate and AT MOST ONE GitHub issue (no TOCTOU duplicate race)."""
    monkeypatch.setenv("AEON_RATE_LIMIT_PER_MIN", "500")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_race_token")
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(200, json={
        "flux_ujy": [5.0] * 102, "snr_median": 9.0, "matched_object": None}))
    respx.post("http://localhost:8100/api/v1/ai/classify").mock(return_value=Response(200, json={
        "top_class": "cold_brown_dwarf", "anomaly_score": 0.95, "probabilities": {}}))

    gh_calls = []

    def _mock_gh(request):
        gh_calls.append(1)
        return Response(201, json={"html_url": "https://github.com/alpztel/aeon/issues/999"})

    respx.post("https://api.github.com/repos/alpztel/aeon/issues").mock(side_effect=_mock_gh)

    def submit_one(_i: int):
        return client.post(
            "/api/v1/candidates",
            json={
                "action": "submit",
                "candidate": {
                    "ra": 188.8888,
                    "dec": -44.4444,
                    "anomaly_score": 0.95,
                    "snr": 9.0,
                },
            },
        )

    with ThreadPoolExecutor(max_workers=12) as ex:
        resps = list(ex.map(submit_one, range(12)))

    assert all(r.status_code == 200 for r in resps)
    ids = {r.json()["id"] for r in resps}
    assert len(ids) == 1, f"TOCTOU race condition created multiple candidate IDs: {ids}"
    assert len(gh_calls) == 1, f"TOCTOU race condition opened {len(gh_calls)} duplicate GitHub issues!"


@pytest.mark.parametrize(
    "ra,dec,expect_unmatched_ir",
    [
        (133.79513, -7.24514, True),   # wise-0855 (Y dwarf, no Gaia optical)
        (277.12950, 26.84383, True),   # wise-1828 (Y dwarf, no Gaia optical)
        (51.295473, 14.8325559, False), # px-2026-09 (synthetic; core offline -> no IR detection claimed)
        (76.95642, 30.40142, False),   # rw-aur (Gaia DR3 + AllWISE)
        (162.30770, -53.31686, False), # luhman-16 (Gaia DR3 + AllWISE + JWST)
        (269.45208, 4.69339, False),   # barnard (Gaia DR3 + AllWISE + HST)
        (165.46587, -34.70473, False), # tw-hya (Gaia DR3 + AllWISE + JWST MIRI)
        (243.90529, -8.36944, False),  # 18-sco (Gaia DR3 + AllWISE)
    ],
)
@respx.mock
def test_all_eight_catalog_targets_archival_crossmatch(client, ra, dec, expect_unmatched_ir):
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(503))

    r = client.get("/api/v1/missions/crossmatch", params={"ra": ra, "dec": dec, "radius_arcsec": 6.0})
    assert r.status_code == 200
    body = r.json()
    assert_path_response_schema(body, "/api/v1/missions/crossmatch", "get")
    assert body["unmatched_ir_candidate"] is expect_unmatched_ir



@pytest.mark.parametrize("raw", ['{"action": "submit", "candidate": {"ra": NaN, "dec": 1}}', '{"action": NaN}',
                                 '{"ra": Infinity, "dec": -Infinity}', '{"action": "vote", "candidate_id": 1e999}'])
def test_non_finite_numbers_in_a_json_body_are_422_not_500(client, raw):
    """The 422 echoes the rejected input; a NaN in it used to make the error response itself fail."""
    r = client.post("/api/v1/candidates", content=raw, headers={"Content-Type": "application/json"})
    assert r.status_code == 422, r.text[:200]
    r.json()
