"""AEON core API (FastAPI). Implements the `core` paths of /openapi.json."""

from __future__ import annotations

import os
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator

from . import __version__, service

Epoch = Literal["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]

app = FastAPI(
    title="AEON core backend",
    version=__version__,
    description="FITS pipeline (Astropy/Photutils), image differencing, shift-and-stack, REBOUND orbits, DuckDB catalog. "
                "Contract: /openapi.json at the repository root.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("AEON_CORS_ORIGINS", "https://www.a-eon.engineer,https://a-eon.engineer,http://localhost:3000").split(",")],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Server-Timing"],
)
# Image arrays compress ~4-6x; the frontend's fetch() decompresses transparently.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)


@app.middleware("http")
async def server_timing(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - t0) * 1000:.1f}"
    return response


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.RequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class AnalysisRequest(BaseModel):
    ra: float = Field(ge=0, le=360)
    dec: float = Field(ge=-90, le=90)
    size_px: int = Field(64, ge=16, le=256)
    pixel_scale_arcsec: float = Field(6.2, ge=0.5, le=30)
    band: int | None = Field(None, ge=0, le=101)
    epoch_1: Epoch = "2026-Q1"
    epoch_2: Epoch = "2026-Q3"
    rate_arcsec_yr: float = Field(0.0, ge=0, le=5000)
    pa_deg: float = 0.0
    n_frames: int = Field(24, ge=2, le=64)
    combine: Literal["mean", "median"] = "mean"
    distance_au: float | None = Field(None, ge=2, le=1e6)
    cadence: Literal["uniform", "spherex"] = "uniform"
    distance_range_au: tuple[float, float] | None = (250.0, 1000.0)
    rate_range_arcsec_yr: tuple[float, float] = (20.0, 200.0)
    pa_range_deg: tuple[float, float] = (30.0, 90.0)
    grid: int = Field(5, ge=2, le=9)


class Elements(BaseModel):
    a_au: float = Field(gt=0)
    e: float = Field(ge=0, lt=1)
    inc_deg: float
    Omega_deg: float = 0.0
    omega_deg: float = 0.0
    M_deg: float = 0.0


class Observation(BaseModel):
    ra: float = Field(ge=0, le=360)
    dec: float = Field(ge=-90, le=90)
    distance_au: float = Field(gt=0)
    rate_arcsec_yr: float = 0.0
    pa_deg: float = 0.0
    radial_velocity_km_s: float = 0.0


class Detection(BaseModel):
    t: float = Field(ge=1900, le=2200, description="decimal year")
    ra: float = Field(ge=0, le=360)
    dec: float = Field(ge=-90, le=90)
    sigma_arcsec: float = Field(1.0, gt=0, le=3600)


class OrbitRequest(BaseModel):
    detections: list[Detection] | None = Field(None, min_length=3, max_length=500)
    elements: Elements | None = None
    observation: Observation | None = None
    target_id: str | None = None
    horizons_years: list[float] = [1, 5, 10]
    samples_per_year: int = Field(24, ge=1, le=365)

    @model_validator(mode="after")
    def _one_source(self):
        if not (self.elements or self.observation or self.target_id or self.detections):
            raise ValueError("Provide detections, elements, observation or target_id")
        return self


@app.get("/api/v1/health", tags=["core"])
def get_health():
    return service.health()


@app.get("/api/v1/catalog/search", tags=["core"])
def search_catalog(
    q: str | None = None,
    ra: float | None = Query(None, ge=0, le=360),
    dec: float | None = Query(None, ge=-90, le=90),
    radius_arcmin: float = Query(10.0, ge=0.01, le=180),
    include_field: bool = False,
    limit: int = Query(50, ge=1, le=500),
    epoch: Epoch | None = None,
):
    return _guard(service.search_catalog, q, ra, dec, radius_arcmin, include_field, limit, epoch)


@app.get("/api/v1/sky/cutout", tags=["core"])
def get_cutout(
    ra: float = Query(ge=0, le=360),
    dec: float = Query(ge=-90, le=90),
    epoch: Epoch = "2026-Q1",
    size_px: int = Query(64, ge=16, le=256),
    pixel_scale_arcsec: float = Query(6.2, ge=0.5, le=30),
    band: int | None = Query(None, ge=0, le=101),
    format: Literal["json", "fits"] = "json",
):
    out = _guard(service.cutout, ra, dec, epoch, size_px, pixel_scale_arcsec, band, format == "fits")
    if format == "fits":
        return Response(out, media_type="application/fits",
                        headers={"Content-Disposition": f'attachment; filename="aeon_{ra:.4f}_{dec:+.4f}_{epoch}.fits"'})
    return out


@app.get("/api/v1/spectrum", tags=["core"])
def get_spectrum(
    ra: float = Query(ge=0, le=360),
    dec: float = Query(ge=-90, le=90),
    epoch: Epoch = "2026-Q1",
    aperture_arcsec: float = Query(9.3, ge=3, le=60),
):
    return _guard(service.spectrum, ra, dec, epoch, aperture_arcsec)


@app.post("/api/v1/analysis/{method}", tags=["core"])
def run_analysis(req: AnalysisRequest, method: Literal["difference", "shift-stack", "blind-search"] = Path()):
    return _guard(service.run_analysis, method, req.model_dump())


@app.post("/api/v1/orbit/simulate", tags=["core"])
def simulate_orbit(req: OrbitRequest):
    return _guard(service.simulate_orbit, req.model_dump())
