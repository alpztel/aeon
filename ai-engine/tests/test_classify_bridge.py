"""Coordinate-only classification: what the web UI sends is exactly {"ra": ..., "dec": ...}.

Graded from easy (the happy path the site depends on) to torture (broken upstream answers, outage and
recovery, concurrent callers). The core backend is faked with respx; nothing leaves the process.
"""

from __future__ import annotations

import concurrent.futures as cf
import itertools
import json
import time

import httpx
import pytest
import respx
from httpx import Response

from app import parser
from app.models import OBJECT_CLASSES, synthesize_spectrum
from conftest import CONTRACT, assert_path_response_schema

SPECTRUM = "http://localhost:8000/api/v1/spectrum"
CLASSIFY = "/api/v1/ai/classify"
BROWN_DWARF = synthesize_spectrum("cold_brown_dwarf", 17.2).tolist()


def spectrum_body(flux=None, **extra):
    return {"ra": 133.7596, "dec": -7.2422, "epoch": "2026-Q1", "flux_ujy": BROWN_DWARF if flux is None else flux,
            "snr_median": 12.5, **extra}


# ---------------------------------------------------------------- easy: the request the site sends

@respx.mock
def test_site_request_ra_dec_only_is_classified_from_the_archive(client):
    route = respx.get(SPECTRUM).mock(return_value=Response(200, json=spectrum_body()))
    r = client.post(CLASSIFY, content=json.dumps({"ra": 133.7595813, "dec": -7.2422291}),
                    headers={"Content-Type": "application/json", "Origin": "https://www.a-eon.engineer"})
    assert r.status_code == 200
    body = r.json()
    assert_path_response_schema(body, CLASSIFY, "post", "200")
    assert body["top_class"] == "cold_brown_dwarf"
    assert body["spectrum_source"] == "archive"
    assert body["spectrum_snr_median"] == 12.5
    assert set(body["probabilities"]) == set(OBJECT_CLASSES)
    assert abs(sum(body["probabilities"].values()) - 1.0) < 1e-3
    assert r.headers["access-control-allow-origin"] == "https://www.a-eon.engineer"
    sent = route.calls.last.request.url.params
    assert float(sent["ra"]) == 133.7595813 and float(sent["dec"]) == -7.2422291


def test_empty_body_is_rejected_with_a_readable_reason(client):
    """This is what the site used to send. It must stay a 422 (client error), never look like an outage."""
    r = client.post(CLASSIFY, json={})
    assert r.status_code == 422
    assert "ra, dec" in json.dumps(r.json())


@respx.mock
def test_spectrum_in_the_request_wins_and_the_backend_is_not_called(client):
    route = respx.get(SPECTRUM).mock(return_value=Response(200, json=spectrum_body()))
    r = client.post(CLASSIFY, json={"flux_ujy": BROWN_DWARF, "ra": 10.0, "dec": 5.0})
    assert r.status_code == 200
    assert r.json()["spectrum_source"] == "request" and r.json()["spectrum_snr_median"] is None
    assert route.call_count == 0


def test_contract_documents_coordinates_and_spectrum_source():
    op = CONTRACT["paths"][CLASSIFY]["post"]
    props = op["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert {"flux_ujy", "image", "ra", "dec"} <= set(props)
    out = op["responses"]["200"]["content"]["application/json"]["schema"]["properties"]
    assert out["spectrum_source"]["enum"] == ["request", "archive", "none"]


# ---------------------------------------------------------------- medium: invalid coordinates

@pytest.mark.parametrize("payload", [
    {"ra": 10.0}, {"dec": 5.0}, {"ra": None, "dec": None},
    {"ra": -0.001, "dec": 0}, {"ra": 360.001, "dec": 0}, {"ra": 10, "dec": 90.001}, {"ra": 10, "dec": -90.001},
    {"ra": "abc", "dec": 1}, {"ra": [1], "dec": 1}, {"ra": {"v": 1}, "dec": 1},
])
def test_invalid_coordinates_are_422(client, payload):
    assert client.post(CLASSIFY, json=payload).status_code == 422


@pytest.mark.parametrize("raw", ['{"ra": NaN, "dec": 1}', '{"ra": Infinity, "dec": 1}', '{"ra": 1e999, "dec": 1}',
                                 '{"ra": 10, "dec": 5', "not json", "[]", '"ra"', "null", ""])
def test_malformed_bodies_are_4xx_not_5xx(client, raw):
    r = client.post(CLASSIFY, content=raw, headers={"Content-Type": "application/json"})
    assert 400 <= r.status_code < 500


@pytest.mark.parametrize("ra,dec", [(0, 0), (360, 90), (0, -90), (359.9999999, 89.9999999), (1e-12, -1e-12)])
@respx.mock
def test_edge_coordinates_are_accepted(client, ra, dec):
    respx.get(SPECTRUM).mock(return_value=Response(200, json=spectrum_body()))
    r = client.post(CLASSIFY, json={"ra": ra, "dec": dec})
    assert r.status_code == 200 and r.json()["spectrum_source"] == "archive"


# ---------------------------------------------------------------- hard: a broken backend answer

BROKEN_UPSTREAM = {
    "all_null": Response(200, json=spectrum_body([None] * 102)),
    "some_null": Response(200, json=spectrum_body([1.0] * 50 + [None] * 2 + [2.0] * 50)),
    "nan_inf": Response(200, text='{"flux_ujy": [NaN, Infinity' + ", 1.0" * 100 + "]}"),
    "too_short": Response(200, json=spectrum_body([1.0] * 10)),
    "too_long": Response(200, json=spectrum_body([1.0] * 500)),
    "strings": Response(200, json=spectrum_body(["a"] * 102)),
    "numeric_strings": Response(200, json=spectrum_body(["1.0"] * 102)),
    "booleans": Response(200, json=spectrum_body([True] * 102)),
    "flux_is_string": Response(200, json={"flux_ujy": "oops"}),
    "flux_is_dict": Response(200, json={"flux_ujy": {"a": 1}}),
    "nested_lists": Response(200, json=spectrum_body([[1.0]] * 102)),
    "body_is_list": Response(200, json=[1, 2, 3]),
    "body_is_null": Response(200, json=None),
    "html": Response(200, text="<html>502 Bad Gateway</html>"),
    "empty_text": Response(200, text=""),
    "no_flux_key": Response(200, json={}),
    "not_found": Response(404, json={"detail": "no spectrum"}),
    "unprocessable": Response(422, json={"detail": "bad"}),
    "server_error": Response(500, text="boom"),
    "bad_gateway": Response(502, text="<html>"),
    "rate_limited": Response(429, json={"detail": "slow down"}),
}


@pytest.mark.parametrize("name", sorted(BROKEN_UPSTREAM))
@respx.mock
def test_broken_upstream_answer_never_becomes_an_error(client, name):
    """Whatever the backend answers, the caller gets 200 with an honest 'no spectrum' result."""
    respx.get(SPECTRUM).mock(return_value=BROKEN_UPSTREAM[name])
    r = client.post(CLASSIFY, json={"ra": 10.0, "dec": 5.0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert_path_response_schema(body, CLASSIFY, "post", "200")
    assert body["spectrum_source"] == "none" and body["spectrum_snr_median"] is None
    assert body["physics_diagnostics"] is None
    assert len(set(body["probabilities"].values())) == 1          # uniform prior, no invented class


@pytest.mark.parametrize("snr", ["high", None, float("nan"), True, [1], {"v": 1}])
@respx.mock
def test_unusable_snr_is_dropped_but_the_spectrum_is_kept(client, snr):
    text = json.dumps(spectrum_body(snr_median=snr))                 # json.dumps writes NaN as a bare token
    respx.get(SPECTRUM).mock(return_value=Response(200, text=text))
    r = client.post(CLASSIFY, json={"ra": 10.0, "dec": 5.0})
    assert r.status_code == 200
    assert r.json()["spectrum_source"] == "archive" and r.json()["spectrum_snr_median"] is None


@pytest.mark.parametrize("flux", [[0.0] * 102, [-5.0] * 102, [1e300] * 102, [1e-300] * 102, [-1e300, 1e300] * 51])
@respx.mock
def test_extreme_but_finite_archive_spectra_do_not_crash(client, flux):
    respx.get(SPECTRUM).mock(return_value=Response(200, json=spectrum_body(flux)))
    r = client.post(CLASSIFY, json={"ra": 10.0, "dec": 5.0})
    assert r.status_code == 200
    assert_path_response_schema(r.json(), CLASSIFY, "post", "200")


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("reset"),
                                 httpx.PoolTimeout("pool"), RuntimeError("unexpected")])
@respx.mock
def test_backend_transport_failure_is_still_a_200(client, exc):
    respx.get(SPECTRUM).mock(side_effect=exc)
    r = client.post(CLASSIFY, json={"ra": 10.0, "dec": 5.0})
    assert r.status_code == 200 and r.json()["spectrum_source"] == "none"


# ---------------------------------------------------------------- torture: outage, recovery, concurrency

@respx.mock
def test_outage_then_recovery(client, monkeypatch):
    """Backend dies -> one probe then back-off (no hammering) -> backend returns -> archive spectra again."""
    monkeypatch.setattr(parser, "_UPSTREAM_BACKOFF_S", 0.4)
    route = respx.get(SPECTRUM).mock(side_effect=httpx.ConnectError("down"))
    for _ in range(20):
        r = client.post(CLASSIFY, json={"ra": 133.76, "dec": -7.24})
        assert r.status_code == 200 and r.json()["spectrum_source"] == "none"
    assert route.call_count == 1

    route.side_effect = None
    route.return_value = Response(200, json=spectrum_body())
    time.sleep(0.5)                                               # back-off window passes
    r = client.post(CLASSIFY, json={"ra": 133.76, "dec": -7.24})
    assert r.status_code == 200 and r.json()["spectrum_source"] == "archive"
    assert r.json()["top_class"] == "cold_brown_dwarf"
    assert route.call_count == 2


@respx.mock
def test_flapping_backend_under_concurrent_callers(client):
    """80 callers on 16 threads while the backend alternates good / 503 / garbage / timeout answers."""
    answers = itertools.cycle([
        Response(200, json=spectrum_body()), Response(503), Response(200, text="<html>"),
        httpx.ReadTimeout("slow"), Response(200, json=spectrum_body([None] * 102)), Response(200, json=spectrum_body()),
    ])

    def reply(request):
        nxt = next(answers)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    respx.get(SPECTRUM).mock(side_effect=reply)
    coords = [(round(1.0 + i * 4.4, 3), round(-80.0 + i * 2.0, 3)) for i in range(80)]

    def call(c):
        r = client.post(CLASSIFY, json={"ra": c[0], "dec": c[1]})
        return r.status_code, r.json().get("spectrum_source")

    with cf.ThreadPoolExecutor(16) as ex:
        results = list(ex.map(call, coords))
    assert [code for code, _ in results] == [200] * len(coords)
    assert {src for _, src in results} <= {"archive", "none"}


@respx.mock
def test_mixed_valid_and_hostile_requests_in_parallel(client):
    respx.get(SPECTRUM).mock(return_value=Response(200, json=spectrum_body()))
    payloads = [{"ra": 133.76, "dec": -7.24}, {}, {"ra": 999, "dec": 0}, {"flux_ujy": BROWN_DWARF},
                {"flux_ujy": [1.0] * 5}, {"ra": "x", "dec": "y"}, {"ra": 76.95, "dec": 30.4}] * 12
    with cf.ThreadPoolExecutor(12) as ex:
        codes = list(ex.map(lambda p: client.post(CLASSIFY, json=p).status_code, payloads))
    expected = [200, 422, 422, 200, 422, 422, 200] * 12
    assert codes == expected


@respx.mock
def test_oversized_and_unknown_fields_are_ignored_or_rejected_cleanly(client):
    respx.get(SPECTRUM).mock(return_value=Response(200, json=spectrum_body()))
    r = client.post(CLASSIFY, json={"ra": 10.0, "dec": 5.0, "junk": "x" * 200_000, "__proto__": {"a": 1}})
    assert r.status_code == 200 and r.json()["spectrum_source"] == "archive"
    r = client.post(CLASSIFY, json={"ra": 10.0, "dec": 5.0, "flux_ujy": [1.0] * 100_000})
    assert r.status_code == 422
