"""Comprehensive offline test suite for AEON multi-mission-api (M6, M7, M10, M11)."""

from __future__ import annotations

import json
import respx
from httpx import Response

from tests.conftest import assert_path_response_schema


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@respx.mock
def test_crossmatch_wise_0855_unmatched_ir_and_sed(client):
    respx.get("http://localhost:8000/api/v1/spectrum").mock(
        return_value=Response(
            200,
            json={
                "wavelength_um": [float(0.75 + i * 0.04) for i in range(102)],
                "flux_ujy": [12.5] * 102,
                "flux_err_ujy": [0.8] * 102,
                "snr_median": 15.6,
                "matched_object": {"id": "wise-0855", "object_class": "cold_brown_dwarf"},
            },
        )
    )

    resp = client.get("/api/v1/missions/crossmatch", params={"ra": 133.79513, "dec": -7.24514, "radius_arcsec": 6.0})
    assert resp.status_code == 200
    body = resp.json()
    assert_path_response_schema(body, "/api/v1/missions/crossmatch", "get")

    # WISE 0855 has WISE detection and JWST/HST overlap, but NO Gaia optical counterpart
    assert body["gaia"] == []
    assert len(body["wise"]) == 1
    assert body["unmatched_ir_candidate"] is True
    missions = {m["mission"] for m in body["mast_overlap"]}
    assert "JWST" in missions
    assert "HST" in missions
    surveys = {pt["survey"] for pt in body["sed"]}
    assert "WISE" in surveys
    assert "SPHEREx" in surveys


@respx.mock
def test_crossmatch_rw_aur_matched_gaia_and_wise(client):
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(503))

    resp = client.get("/api/v1/missions/crossmatch", params={"ra": 76.95642, "dec": 30.40142, "radius_arcsec": 6.0})
    assert resp.status_code == 200
    body = resp.json()
    assert_path_response_schema(body, "/api/v1/missions/crossmatch", "get")

    assert len(body["gaia"]) == 1
    assert len(body["wise"]) == 1
    assert body["unmatched_ir_candidate"] is False
    surveys = {pt["survey"] for pt in body["sed"]}
    assert "Gaia DR3" in surveys
    assert "WISE" in surveys


@respx.mock
def test_crossmatch_synthetic_px_2026_09(client):
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(503))

    resp = client.get("/api/v1/missions/crossmatch", params={"ra": 51.20000, "dec": 14.80000, "radius_arcsec": 6.0})
    assert resp.status_code == 200
    body = resp.json()
    assert_path_response_schema(body, "/api/v1/missions/crossmatch", "get")
    # Synthetic object has no real-sky Gaia or WISE archival entries
    assert body["gaia"] == []
    assert body["wise"] == []
    assert body["unmatched_ir_candidate"] is True


def test_gcn_alerts_cached_fallback(client, monkeypatch):
    monkeypatch.delenv("AEON_GCN_ARCHIVE_URL", raising=False)
    resp = client.get("/api/v1/alerts/gcn", params={"limit": 3})
    assert resp.status_code == 200
    alerts = resp.json()
    assert_path_response_schema(alerts, "/api/v1/alerts/gcn", "get")
    assert len(alerts) == 3
    assert alerts[0]["time_utc"] >= alerts[1]["time_utc"]
    assert all("önbellek" in a["title"].lower() for a in alerts)


@respx.mock
def test_candidates_list_vote_dedup_and_github_issue_bot(client, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_mock_token")
    monkeypatch.setenv("GITHUB_REPO", "alpztel/aeon")

    respx.get("http://localhost:8000/api/v1/spectrum").mock(
        return_value=Response(
            200,
            json={
                "wavelength_um": [float(0.75 + i * 0.04) for i in range(102)],
                "flux_ujy": [15.0] * 102,
                "flux_err_ujy": [1.0] * 102,
                "snr_median": 9.4,
                "matched_object": None,
            },
        )
    )
    respx.post("http://localhost:8100/api/v1/ai/classify").mock(
        return_value=Response(
            200,
            json={
                "probabilities": {
                    "cold_brown_dwarf": 0.91,
                    "planet_x_candidate": 0.03,
                    "young_variable_star": 0.02,
                    "main_sequence_star": 0.02,
                    "high_z_galaxy": 0.02,
                },
                "top_class": "cold_brown_dwarf",
                "anomaly_score": 0.95,
                "model_versions": {"spectral_1d_cnn": "test"},
            },
        )
    )

    gh_requests: list[dict] = []

    def _mock_gh_issue(request):
        payload = json.loads(request.content.decode("utf-8"))
        gh_requests.append(payload)
        return Response(201, json={"html_url": f"https://github.com/alpztel/aeon/issues/{100 + len(gh_requests)}"})

    respx.post("https://api.github.com/repos/alpztel/aeon/issues").mock(side_effect=_mock_gh_issue)

    # 1. Submit a real high-anomaly candidate -> triggers GitHub Issue with ['discovery', 'automated']
    sub_resp = client.post(
        "/api/v1/candidates",
        json={
            "action": "submit",
            "candidate": {
                "ra": 210.1234,
                "dec": -12.3456,
                "submitted_by": "asya",
                "notes": "High proper motion dipole candidate",
            },
        },
    )
    assert sub_resp.status_code == 200
    created = sub_resp.json()
    assert_path_response_schema(created, "/api/v1/candidates", "post")
    assert created["object_class"] == "cold_brown_dwarf"
    assert created["anomaly_score"] == 0.95
    assert created["github_issue_url"] == "https://github.com/alpztel/aeon/issues/101"
    assert gh_requests[0]["labels"] == ["discovery", "automated"]

    # 2. Submit within <= 3 arcsec -> deduplicated (no second record or issue created)
    dup_resp = client.post(
        "/api/v1/candidates",
        json={
            "action": "submit",
            "candidate": {
                "ra": 210.1234 + (1.0 / 3600.0),
                "dec": -12.3456,
                "submitted_by": "another-user",
            },
        },
    )
    assert dup_resp.status_code == 200
    assert dup_resp.json()["id"] == created["id"]
    assert len(gh_requests) == 1

    # 3. Vote on the candidate
    vote_resp = client.post(
        "/api/v1/candidates",
        json={"action": "vote", "candidate_id": created["id"]},
    )
    assert vote_resp.status_code == 200
    voted = vote_resp.json()
    assert_path_response_schema(voted, "/api/v1/candidates", "post")
    assert voted["votes"] == created["votes"] + 1

    # 4. Submit a synthetic test candidate -> MUST attach 'synthetic-test' label and warning
    synth_resp = client.post(
        "/api/v1/candidates",
        json={
            "action": "submit",
            "candidate": {
                "ra": 51.2500,
                "dec": 14.8200,
                "object_class": "planet_x_candidate",
                "anomaly_score": 0.96,
                "snr": 7.8,
                "submitted_by": "pipeline-test",
                "notes": "Injected synthetic test candidate near PX-2026-09",
            },
        },
    )
    assert synth_resp.status_code == 200
    synth_body = synth_resp.json()
    assert_path_response_schema(synth_body, "/api/v1/candidates", "post")
    assert "synthetic-test" in gh_requests[1]["labels"]
    assert "is_synthetic" in gh_requests[1]["body"]

    # 5. List candidates sorted by anomaly, votes, recent
    for sort_mode in ("anomaly", "votes", "recent"):
        list_resp = client.get("/api/v1/candidates", params={"sort": sort_mode, "limit": 10})
        assert list_resp.status_code == 200
        cand_list = list_resp.json()
        assert_path_response_schema(cand_list, "/api/v1/candidates", "get")
        assert len(cand_list) >= 3
        if sort_mode == "anomaly":
            assert cand_list[0]["anomaly_score"] >= cand_list[1]["anomaly_score"]
        elif sort_mode == "votes":
            assert cand_list[0]["votes"] >= cand_list[1]["votes"]


def test_candidates_error_handling_and_rate_limit(client, monkeypatch):
    # Missing candidate_id on vote -> 422
    r1 = client.post("/api/v1/candidates", json={"action": "vote"})
    assert r1.status_code == 422

    # Unknown candidate_id on vote -> 404
    r2 = client.post("/api/v1/candidates", json={"action": "vote", "candidate_id": "nonexistent-id"})
    assert r2.status_code == 404

    # Missing candidate payload on submit -> 422
    r3 = client.post("/api/v1/candidates", json={"action": "submit"})
    assert r3.status_code == 422

    # Rate limit exceeded -> 429 (r2 above consumed 1 hit, so 2 more hits reach 3)
    monkeypatch.setenv("AEON_RATE_LIMIT_PER_MIN", "3")
    assert client.post("/api/v1/candidates", json={"action": "vote", "candidate_id": "cand-wise-0855"}).status_code == 200
    assert client.post("/api/v1/candidates", json={"action": "vote", "candidate_id": "cand-wise-0855"}).status_code == 200
    assert client.post("/api/v1/candidates", json={"action": "vote", "candidate_id": "cand-wise-0855"}).status_code == 429

