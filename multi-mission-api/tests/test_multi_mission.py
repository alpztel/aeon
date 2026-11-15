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
                "epoch": "2026-Q2",
                "pipeline": {"data_mode": "fits_archive", "measured": [True] * 102, "n_bands_measured": 102,
                             "observed_quarter": "2026-Q2"},
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
    assert missions and missions <= {"JWST", "HST"}          # from the real MAST snapshot
    assert body["provenance"]["source"].startswith("archive snapshot")
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
    # Synthetic object has no real-sky Gaia or WISE archival entries; with the core offline there is
    # no IR detection either, so it must not be called an unmatched IR candidate.
    assert body["gaia"] == []
    assert body["wise"] == []
    assert body["unmatched_ir_candidate"] is False


@respx.mock
def test_crossmatch_synthetic_px_with_core_detection(client):
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(200, json={
        "wavelength_um": [0.75 + i * 0.04 for i in range(102)], "flux_ujy": [5.0] * 102,
        "flux_err_ujy": [1.0] * 102, "snr_median": 4.0, "epoch": "2026-Q1",
        "pipeline": {"data_mode": "fits_archive", "measured": [True] * 102, "n_bands_measured": 102},
        "matched_object": {"id": "px-2026-09", "is_synthetic": True, "distance_au": 520.0}}))
    body = client.get("/api/v1/missions/crossmatch", params={"ra": 51.295473, "dec": 14.8325559}).json()
    assert body["unmatched_ir_candidate"] is True
    # a solar-system body: equilibrium temperature at 520 AU, never the reflected-light colour temperature
    sp = body["sed_physics"]
    assert sp["teff_method"] == "equilibrium" and sp["spectral_regime"] == "reflected_sunlight"
    assert 10.0 < sp["teff_sed_k"] < 13.0
    assert sp["reflected_color_temperature_k"] is None or sp["reflected_color_temperature_k"] > 1000.0


@respx.mock
def test_crossmatch_never_puts_the_physical_model_into_the_sed(client):
    """The backend's physical model is a prediction from the catalog class, not a SPHEREx measurement."""
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(200, json={
        "wavelength_um": [0.75 + i * 0.04 for i in range(102)], "flux_ujy": [50.0] * 102,
        "flux_err_ujy": [1.0] * 102, "snr_median": 50.0, "epoch": "2026-Q1",
        "pipeline": {"data_mode": "physical_model", "archive_fallback_reason": "no SPHEREx frame covers this position"},
        "matched_object": {"id": "wise-0855"}}))
    body = client.get("/api/v1/missions/crossmatch", params={"ra": 133.79513, "dec": -7.24514}).json()
    assert "SPHEREx" not in {pt["survey"] for pt in body["sed"]}
    assert body["provenance"]["spherex"]["status"].startswith("excluded")


@respx.mock
def test_crossmatch_sed_uses_only_measured_detected_spherex_bands(client):
    flux = [10.0] * 102
    err = [1.0] * 102
    measured = [True] * 102
    for i in range(0, 102, 2):
        measured[i] = False                  # interpolated fill: not a measurement
    flux[1], flux[3] = 2.0, -4.0             # S/N 2 and negative: not detections
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(200, json={
        "wavelength_um": [0.75 + i * 0.04 for i in range(102)], "flux_ujy": flux, "flux_err_ujy": err,
        "snr_median": 10.0, "epoch": "2026-Q4",
        "pipeline": {"data_mode": "fits_archive", "measured": measured, "n_bands_measured": 51,
                     "observed_quarter": "2025-Q4"},
        "matched_object": {"id": "wise-0855"}}))
    body = client.get("/api/v1/missions/crossmatch", params={"ra": 133.79513, "dec": -7.24514}).json()
    spx = [pt for pt in body["sed"] if pt["survey"] == "SPHEREx"]
    assert len(spx) == 51 - 2
    note = body["provenance"]["spherex"]
    assert note["status"] == "real" and note["n_points"] == 49 and note["observed_quarter"] == "2025-Q4"


def _wise0855_like(short_flux):
    """Real-data spectrum: short_flux uJy below 1.4 um (a blended neighbour when large), the Y dwarf's
    own rising flux beyond 3 um (agrees with WISE)."""
    lam = [0.75 + i * 0.0422 for i in range(102)]
    flux = [short_flux if w < 1.4 else (5.0 if w < 3.0 else 100.0 + 250.0 * (w - 3.0)) for w in lam]
    err = [max(1.0, f / 10.0) for f in flux]
    return {"wavelength_um": lam, "flux_ujy": flux, "flux_err_ujy": err, "snr_median": 6.0, "epoch": "2026-Q4",
            "pipeline": {"data_mode": "fits_archive", "measured": [True] * 102, "n_bands_measured": 102,
                         "observed_quarter": "2025-Q4"},
            "matched_object": {"id": "wise-0855", "object_class": "cold_brown_dwarf"}}


@respx.mock
def test_blended_neighbour_is_kept_out_of_a_gaia_dark_sed(client):
    """WISE 0855 has no Gaia source; ~500 uJy at 0.75-1.3 um is a neighbour, not the Y dwarf."""
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(200, json=_wise0855_like(500.0)))
    body = client.get("/api/v1/missions/crossmatch", params={"ra": 133.79513, "dec": -7.24514}).json()
    assert body["gaia"] == []
    spx = [pt for pt in body["sed"] if pt["survey"] == "SPHEREx"]
    assert spx and min(pt["wavelength_um"] for pt in spx) >= 2.5
    note = body["provenance"]["spherex"]
    assert note["blend_suspected"] is True and note["dropped_short_wavelength_points"] > 0
    assert note["n_points"] == len(spx)
    sp = body["sed_physics"]
    assert sp["spectral_regime"] == "ultracool_or_substellar" and sp["teff_sed_k"] < 600.0


@respx.mock
def test_faint_short_wavelength_flux_is_not_called_a_blend(client):
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(200, json=_wise0855_like(20.0)))
    body = client.get("/api/v1/missions/crossmatch", params={"ra": 133.79513, "dec": -7.24514}).json()
    assert "blend_suspected" not in body["provenance"]["spherex"]


@respx.mock
def test_bands_the_backend_flags_as_blended_stay_out_of_the_sed(client):
    body_ = _wise0855_like(20.0)
    body_["pipeline"]["blended"] = [w < 3.3 for w in body_["wavelength_um"]]
    body_["pipeline"]["n_bands_blended"] = sum(body_["pipeline"]["blended"])
    respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(200, json=body_))
    body = client.get("/api/v1/missions/crossmatch", params={"ra": 133.79513, "dec": -7.24514}).json()
    spx = [pt for pt in body["sed"] if pt["survey"] == "SPHEREx"]
    assert spx and min(pt["wavelength_um"] for pt in spx) >= 3.3
    assert body["provenance"]["spherex"]["n_bands_blended"] == body_["pipeline"]["n_bands_blended"]


def test_blend_check_needs_a_gaia_non_detection():
    from app.crossmatch import _optical_blend_check
    pts = [{"wavelength_um": w, "flux_ujy": 500.0, "flux_err_ujy": 10.0, "survey": "SPHEREx"} for w in (0.8, 1.0, 2.0, 3.0, 4.0)]
    assert _optical_blend_check(pts, [{"source_id": 1}], True) == (pts, {})       # Gaia sees a source: trust it
    assert _optical_blend_check(pts, [], False) == (pts, {})                      # Gaia not asked: cannot tell
    kept, note = _optical_blend_check(pts, [], True)
    assert [p["wavelength_um"] for p in kept] == [3.0, 4.0] and note["dropped_short_wavelength_points"] == 3


@respx.mock
def test_crossmatch_asks_the_backend_for_the_best_epoch_with_a_real_timeout(client):
    route = respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(503))
    body = client.get("/api/v1/missions/crossmatch", params={"ra": 133.79513, "dec": -7.24514}).json()
    sent = dict(route.calls.last.request.url.params)
    assert "epoch" not in sent                       # the backend chooses the epoch with real data
    from app import crossmatch
    assert crossmatch.CORE_SPECTRUM_TIMEOUT_S >= 10.0
    assert body["provenance"]["spherex"]["status"].startswith("unavailable")


def test_gcn_alerts_no_source_returns_empty(client, monkeypatch):
    """Without Kafka credentials or an archive URL there are no alerts - never invented ones."""
    monkeypatch.delenv("AEON_GCN_ARCHIVE_URL", raising=False)
    resp = client.get("/api/v1/alerts/gcn", params={"limit": 3})
    assert resp.status_code == 200
    assert resp.json() == []


def test_gcn_circular_mapping():
    from app.gcn import circular_to_alert

    a = circular_to_alert({"circularId": 40000, "subject": "GRB 250101A: Swift-BAT detection", "createdOn": 1735689600000})
    assert a == {"id": "GCN-40000", "kind": "GRB", "time_utc": "2025-01-01T00:00:00Z",
                 "title": "GRB 250101A: Swift-BAT detection", "url": "https://gcn.nasa.gov/circulars/40000"}
    assert circular_to_alert({"subject": "no id"}) is None


@respx.mock
def test_gcn_archive_url(client, monkeypatch):
    monkeypatch.setenv("AEON_GCN_ARCHIVE_URL", "https://example.test/gcn.json")
    respx.get("https://example.test/gcn.json").mock(return_value=Response(200, json=[
        {"id": "GCN-2", "kind": "GRB", "time_utc": "2025-02-02T00:00:00Z"},
        {"id": "GCN-1", "kind": "SN", "time_utc": "2025-01-01T00:00:00Z"},
        {"bad": "row"}]))
    alerts = client.get("/api/v1/alerts/gcn").json()
    assert [a["id"] for a in alerts] == ["GCN-2", "GCN-1"]
    assert_path_response_schema(alerts, "/api/v1/alerts/gcn", "get")


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
        assert len(cand_list) >= 2            # the pool starts empty; two real submissions above
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

    # Rate limit exceeded -> 429 (r2, the setup submit and the first vote fill a limit of 3)
    monkeypatch.setenv("AEON_RATE_LIMIT_PER_MIN", "3")
    cid = client.post("/api/v1/candidates", json={"action": "submit", "candidate": {"ra": 1.0, "dec": 2.0}}).json()["id"]
    assert client.post("/api/v1/candidates", json={"action": "vote", "candidate_id": cid}).status_code == 200
    assert client.post("/api/v1/candidates", json={"action": "vote", "candidate_id": cid}).status_code == 429

