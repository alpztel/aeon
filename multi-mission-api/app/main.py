"""AEON Multi-Mission API FastAPI application (port 8200).

Implements:
- GET  /api/v1/missions/crossmatch
- GET  /api/v1/alerts/gcn
- GET  /api/v1/candidates
- POST /api/v1/candidates
- GET  /healthz
"""

from __future__ import annotations

import os
import time
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .candidates import get_store
from .crossmatch import run_crossmatch
from .gcn import fetch_gcn_alerts

ObjectClass = Literal[
    "cold_brown_dwarf",
    "planet_x_candidate",
    "young_variable_star",
    "main_sequence_star",
    "high_z_galaxy",
]

app = FastAPI(
    title="AEON Multi-Mission API",
    version=__version__,
    description="Gaia DR3 + WISE + MAST (JWST/HST) cross-matching and SED builder, "
                "NASA GCN alert ticker, citizen-science candidate pool, and autonomous GitHub Issue discovery bot.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.environ.get("AEON_CORS_ORIGINS", "https://aeon.tech,http://localhost:3000").split(",")
        if o.strip()
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Server-Timing"],
)


@app.middleware("http")
async def server_timing(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["Server-Timing"] = f"missions;dur={(time.perf_counter() - t0) * 1000:.1f}"
    return response


class CandidateInput(BaseModel):
    id: str | None = None
    ra: float = Field(..., ge=0.0, le=360.0)
    dec: float = Field(..., ge=-90.0, le=90.0)
    object_class: ObjectClass | None = None
    anomaly_score: float | None = Field(None, ge=0.0, le=1.0)
    snr: float | None = None
    votes: int | None = None
    submitted_by: str | None = None
    created_utc: str | None = None
    github_issue_url: str | None = None
    notes: str | None = None


class CandidateActionRequest(BaseModel):
    action: Literal["submit", "vote"]
    candidate_id: str | None = None
    candidate: CandidateInput | None = None


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, Any]:
    return {"status": "ok", "service": "multi-mission-api", "version": __version__}


@app.get("/api/v1/missions/crossmatch", tags=["missions"])
def missions_crossmatch(
    ra: float = Query(..., ge=0.0, le=360.0),
    dec: float = Query(..., ge=-90.0, le=90.0),
    radius_arcsec: float = Query(6.0, gt=0.0, le=3600.0),
) -> dict[str, Any]:
    return run_crossmatch(ra=ra, dec=dec, radius_arcsec=radius_arcsec)


@app.get("/api/v1/alerts/gcn", tags=["missions"])
def gcn_alerts(limit: int = Query(20, ge=1, le=200)) -> list[dict[str, Any]]:
    return fetch_gcn_alerts(limit=limit)


@app.get("/api/v1/candidates", tags=["missions"])
def list_candidates(
    sort: Literal["votes", "recent", "anomaly"] = Query("votes"),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    return get_store().list_candidates(sort=sort, limit=limit)


@app.post("/api/v1/candidates", tags=["missions"])
def submit_or_vote_candidate(req: CandidateActionRequest, request: Request) -> dict[str, Any]:
    if req.action == "vote" and not req.candidate_id:
        raise HTTPException(status_code=422, detail="candidate_id is required when action='vote'")
    if req.action == "submit" and req.candidate is None:
        raise HTTPException(status_code=422, detail="candidate payload is required when action='submit'")

    store = get_store()
    client_ip = request.client.host if request.client else "127.0.0.1"
    if not store.check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    if req.action == "vote":
        updated = store.vote(str(req.candidate_id))
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Candidate '{req.candidate_id}' not found")
        return updated

    assert req.candidate is not None
    return store.submit(req.candidate.model_dump())
