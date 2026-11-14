"""Upstream HTTP behaviour: shared client, catalog cache, back-off after failures."""

from __future__ import annotations

import concurrent.futures as cf

import httpx
import respx
from httpx import Response

from app import parser

CATALOG = "http://localhost:8000/api/v1/catalog/search"
HIT = {"count": 1, "results": [{"id": "wise-0855", "name": "WISE J085510.83-071442.5", "ra": 133.7607,
                                "dec": -7.24219, "object_class": "cold_brown_dwarf"}]}


@respx.mock
def test_catalog_lookup_is_cached(monkeypatch):
    monkeypatch.delenv("AEON_CORE_URL", raising=False)
    route = respx.get(CATALOG).mock(return_value=Response(200, json=HIT))
    first = parser._lookup_catalog_remote_or_local("wise-0855")
    second = parser._lookup_catalog_remote_or_local("WISE-0855 ")
    assert first["ra"] == 133.7607 and second == first
    assert route.call_count == 1                         # second call served from the cache
    first["ra"] = 0.0                                    # callers get copies, never the cached dict
    assert parser._lookup_catalog_remote_or_local("wise-0855")["ra"] == 133.7607


@respx.mock
def test_empty_remote_result_falls_back_to_local_and_is_cached():
    route = respx.get(CATALOG).mock(return_value=Response(200, json={"count": 0, "results": []}))
    hit = parser._lookup_catalog_remote_or_local("wise-0855")
    assert hit is not None and hit["ra"] == parser.KNOWN_TARGETS["wise-0855"]["ra"]
    assert parser._lookup_catalog_remote_or_local("wise-0855") == hit
    assert route.call_count == 1


@respx.mock
def test_backend_failure_backs_off_and_uses_local_targets():
    route = respx.get(CATALOG).mock(return_value=Response(503))
    for _ in range(5):
        hit = parser._lookup_catalog_remote_or_local("wise-0855")
        assert hit["ra"] == parser.KNOWN_TARGETS["wise-0855"]["ra"]
    assert route.call_count == 1                         # 503 -> back off instead of hammering the backend


@respx.mock
def test_timeout_backs_off():
    route = respx.get(CATALOG).mock(side_effect=httpx.ReadTimeout("slow"))
    assert parser._lookup_catalog_remote_or_local("wise-0855") is not None
    assert parser._lookup_catalog_remote_or_local("rw aur") is not None
    assert route.call_count == 1


@respx.mock
def test_client_error_does_not_back_off():
    route = respx.get(CATALOG).mock(return_value=Response(422, json={"detail": "bad"}))
    parser._lookup_catalog_remote_or_local("wise-0855")
    parser._lookup_catalog_remote_or_local("wise-0855")
    assert route.call_count == 2                         # a 4xx is about the query, not the backend's health


@respx.mock
def test_back_off_expires(monkeypatch):
    route = respx.get(CATALOG).mock(return_value=Response(503))
    parser._lookup_catalog_remote_or_local("wise-0855")
    assert route.call_count == 1
    parser._down_until.clear()                           # time passes
    route.mock(return_value=Response(200, json=HIT))
    assert parser._lookup_catalog_remote_or_local("wise-0855")["name"] == "WISE J085510.83-071442.5"
    assert route.call_count == 2


@respx.mock
def test_knowledge_tool_respects_back_off():
    spec = respx.get("http://localhost:8000/api/v1/spectrum").mock(side_effect=httpx.ConnectError("down"))
    a = parser._execute_knowledge_tool("get_spectrum", {"ra": 1.0, "dec": 2.0})
    b = parser._execute_knowledge_tool("get_spectrum", {"ra": 1.0, "dec": 2.0})
    assert a["status"] == b["status"] == "offline_fallback"
    assert spec.call_count == 1
    # crossmatch goes to a different upstream and is not blocked by the backend's back-off
    xm = respx.get("http://localhost:8200/api/v1/missions/crossmatch").mock(return_value=Response(200, json={"gaia": []}))
    assert parser._execute_knowledge_tool("crossmatch", {}) == {"gaia": []}
    assert xm.call_count == 1


def test_shared_client_is_one_instance_across_threads():
    with cf.ThreadPoolExecutor(8) as ex:
        clients = list(ex.map(lambda _: parser.http_client(), range(32)))
    assert len({id(c) for c in clients}) == 1


@respx.mock
def test_cache_is_bounded():
    respx.get(CATALOG).mock(return_value=Response(200, json={"count": 0, "results": []}))
    for i in range(parser._CATALOG_MAX + 50):
        parser._lookup_catalog_remote_or_local(f"q{i}")
    assert len(parser._catalog_cache) == parser._CATALOG_MAX


@respx.mock
def test_concurrent_commands_with_slow_backend(client, monkeypatch):
    """Hammer /ai/command while the backend times out: answers stay 200 and the backend sees one call."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    route = respx.get(CATALOG).mock(side_effect=httpx.ReadTimeout("saturated"))
    msgs = ["WISE 0855'e git", "show spectrum of RW Aur", "Planet X için kör tarama yap"] * 10
    with cf.ThreadPoolExecutor(10) as ex:
        codes = list(ex.map(lambda m: client.post("/api/v1/ai/command", json={"message": m}).status_code, msgs))
    assert codes == [200] * len(msgs)
    assert route.call_count <= 10                        # at most the calls already in flight before back-off


@respx.mock
def test_classify_by_coordinates_uses_back_off(client):
    spec = respx.get("http://localhost:8000/api/v1/spectrum").mock(return_value=Response(503))
    for _ in range(3):
        r = client.post("/api/v1/ai/classify", json={"ra": 133.79, "dec": -7.24})
        assert r.status_code in (200, 422)
    assert spec.call_count == 1
