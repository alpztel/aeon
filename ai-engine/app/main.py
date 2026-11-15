"""AEON AI Engine FastAPI application (port 8100).

Implements:
- POST /api/v1/ai/command   (Astro-LLM function calling + TR/EN rule-based fallback)
- POST /api/v1/ai/classify  (1D-CNN 102-band spectral classifier + PatchAnomalyViT)
- GET  /healthz             (Docker container health check)
"""

from __future__ import annotations

import math
import os
import threading
import time
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from . import __version__
from .astroclip_zogy import compute_astroclip_alignment
from .models import get_registry
from .parser import http_client, mark_upstream_down, run_command_dispatcher, upstream_available
from .physics_sed import analyze_spectrum_physics, fill_unusable_bands

Lang = Literal["tr", "en"]

app = FastAPI(
    title="AEON AI Engine",
    version=__version__,
    description="Astro-LLM command dispatcher (Claude function calling + bilingual rule-based fallback), "
                "1D-CNN 102-band spectral classifier, and PatchAnomalyViT cutout anomaly detector.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.environ.get("AEON_CORS_ORIGINS", "https://www.a-eon.engineer,https://a-eon.engineer,http://localhost:3000").split(",")
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
    response.headers["Server-Timing"] = f"ai;dur={(time.perf_counter() - t0) * 1000:.1f}"
    return response


def _json_safe(value: Any) -> Any:
    """NaN / Infinity cannot be written as JSON; echo them back as text instead."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # The default handler echoes the rejected input; a NaN / Infinity in it made the 422 itself fail (500).
    return JSONResponse(status_code=422, content={"detail": _json_safe(jsonable_encoder(exc.errors()))})


class CommandRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    lang: Lang | None = None
    context: dict[str, Any] | None = None


class ImageInput(BaseModel):
    width: int = Field(..., gt=0, le=512)
    height: int = Field(..., gt=0, le=512)
    data: list[float]
    unit: str | None = None
    epoch: str | None = None
    ra: float | None = None
    dec: float | None = None
    pixel_scale_arcsec: float | None = None
    band: int | None = None
    wcs: dict[str, Any] | None = None
    stats: dict[str, Any] | None = None
    data_mode: str | None = None
    background: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_length(self):
        if len(self.data) != self.width * self.height:
            raise ValueError(f"Image data length ({len(self.data)}) must equal width*height ({self.width * self.height})")
        return self


class ClassifyRequest(BaseModel):
    flux_ujy: list[float] | None = Field(None, min_length=102, max_length=102)
    image: ImageInput | None = None
    ra: float | None = Field(None, ge=0, le=360)
    dec: float | None = Field(None, ge=-90, le=90)

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.flux_ujy is None and self.image is None and (self.ra is None or self.dec is None):
            raise ValueError("Provide at least one of flux_ujy (102 bands), image, or (ra, dec)")
        return self


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, Any]:
    reg = get_registry()
    return {
        "status": "ok",
        "service": "ai-engine",
        "version": __version__,
        "model_versions": reg.versions,
    }


@app.post("/api/v1/ai/command", tags=["ai"])
def ai_command(req: CommandRequest) -> dict[str, Any]:
    return run_command_dispatcher(req.message, req.lang, req.context)


N_BANDS = 102
# A fresh position over real SPHEREx frames takes the backend a few seconds (measured 3.5 s on the 2-vCPU VM),
# longer than the 2.5 s the command path allows. The browser waits 15 s for a classification.
SPECTRUM_TIMEOUT_S = float(os.environ.get("AEON_SPECTRUM_TIMEOUT_S", "10"))
# Slow spectrum reads may hold at most this many worker threads; the rest are for commands and fast calls.
_SPECTRUM_SLOTS = threading.BoundedSemaphore(int(os.environ.get("AEON_SPECTRUM_CONCURRENCY", "12")))
_SLOT_WAIT_S = 1.0


def fetch_archive_spectrum(ra: float, dec: float) -> tuple[list[float] | None, float | None, str]:
    """102-band spectrum of a sky position from the core backend: (flux_ujy, snr_median, source).
    What the backend says about that spectrum (real SPHEREx or physical model, epoch, observed quarter)
    is in fetch_archive_spectrum_meta.

    source is "archive" (spectrum returned), "none" (the backend answered: nothing usable at this position)
    or "unavailable" (the backend could not be asked or did not answer in time). Whatever the backend does,
    this never raises: a broken upstream answer must not turn into a 4xx/5xx for the caller.
    """
    core_url = os.environ.get("AEON_CORE_URL", "http://localhost:8000").rstrip("/")
    if not upstream_available(core_url):
        return None, None, "unavailable"
    if not _SPECTRUM_SLOTS.acquire(timeout=_SLOT_WAIT_S):
        return None, None, "unavailable"
    try:
        resp = http_client().get(f"{core_url}/api/v1/spectrum", params={"ra": ra, "dec": dec}, timeout=SPECTRUM_TIMEOUT_S)
    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
        return None, None, "unavailable"            # one slow position, not a dead backend: no back-off for others
    except Exception:
        mark_upstream_down(core_url)
        return None, None, "unavailable"
    finally:
        _SPECTRUM_SLOTS.release()
    if resp.status_code >= 500:
        mark_upstream_down(core_url)
        return None, None, "unavailable"
    if resp.status_code == 429:
        return None, None, "unavailable"
    if resp.status_code != 200:
        return None, None, "none"
    try:
        body = resp.json()
    except ValueError:
        return None, None, "unavailable"            # a 200 that is not JSON is a broken gateway, not an empty sky
    if not isinstance(body, dict):
        return None, None, "unavailable"
    flux = body.get("flux_ujy")
    if not isinstance(flux, list) or len(flux) != N_BANDS:
        return None, None, "none"
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in flux):
        return None, None, "none"
    snr = body.get("snr_median")
    snr = float(snr) if isinstance(snr, (int, float)) and not isinstance(snr, bool) and math.isfinite(snr) else None
    _LAST_META.value = _spectrum_meta(body)
    return [float(v) for v in flux], snr, "archive"


_LAST_META = threading.local()


def _spectrum_meta(body: dict) -> dict[str, Any]:
    """Provenance of a backend spectrum: real SPHEREx (fits_archive) or the physical model, and which
    epoch / observed quarter it comes from. Unknown or malformed fields become None."""
    pipe = body.get("pipeline") if isinstance(body.get("pipeline"), dict) else {}
    mode = pipe.get("data_mode")
    epoch = body.get("epoch")
    oq = pipe.get("observed_quarter")
    nb = pipe.get("n_bands_measured")
    measured = pipe.get("measured")
    blended = pipe.get("blended")
    usable = None
    upper = None
    if isinstance(measured, list) and len(measured) == N_BANDS and all(isinstance(v, bool) for v in measured):
        usable = list(measured)
        if isinstance(blended, list) and len(blended) == N_BANDS and all(isinstance(v, bool) for v in blended):
            usable = [a and not b for a, b in zip(measured, blended)]
            upper = [a and b for a, b in zip(measured, blended)]     # target + neighbour >= target
    nbl = pipe.get("n_bands_blended")
    return {
        "usable_mask": usable,
        "upper_limit_mask": upper,
        "n_bands_blended": nbl if isinstance(nbl, int) and not isinstance(nbl, bool) and 0 <= nbl <= N_BANDS else None,
        "data_mode": mode if mode in ("fits_archive", "physical_model") else None,
        "epoch": epoch if isinstance(epoch, str) and len(epoch) <= 16 else None,
        "observed_quarter": oq if isinstance(oq, str) and len(oq) <= 16 else None,
        "n_bands_measured": nb if isinstance(nb, int) and not isinstance(nb, bool) and 0 <= nb <= N_BANDS else None,
    }


def fetch_archive_spectrum_meta(ra: float, dec: float) -> tuple[list[float] | None, float | None, str, dict[str, Any]]:
    """fetch_archive_spectrum plus the spectrum's provenance (see _spectrum_meta)."""
    _LAST_META.value = {}
    flux, snr, source = fetch_archive_spectrum(ra, dec)
    meta = _LAST_META.value if source == "archive" else {}
    return flux, snr, source, meta


@app.post("/api/v1/ai/classify", tags=["ai"])
def ai_classify(req: ClassifyRequest) -> dict[str, Any]:
    try:
        flux = req.flux_ujy
        spectrum_source = "request" if flux is not None else "none"
        snr_median: float | None = None
        meta: dict[str, Any] = {}
        if flux is None and req.ra is not None and req.dec is not None:
            flux, snr_median, spectrum_source, meta = fetch_archive_spectrum_meta(req.ra, req.dec)
        reg = get_registry()
        # Real SPHEREx data: classify on the target's own bands. Bands no frame measured, or where a
        # neighbour inside the aperture dominates, are filled from the template fitted to the rest.
        usable = meta.get("usable_mask")
        cnn_flux = flux
        fill_fit = None
        if flux is not None and usable is not None and not all(usable):
            filled, fill_fit = fill_unusable_bands(flux, usable, meta.get("upper_limit_mask"))
            if fill_fit is not None:
                cnn_flux = [float(v) for v in filled]
        probs, top_class, spec_hint = reg.classify_spectrum(cnn_flux)
        img_dict = req.image.model_dump() if req.image is not None else None
        anomaly_score = reg.score_image_anomaly(img_dict, spec_hint=spec_hint)

        physics_diag = (analyze_spectrum_physics(flux, mask=usable if fill_fit is not None else None,
                                                 upper_limits=meta.get("upper_limit_mask") if fill_fit is not None else None)
                        if flux is not None else None)
        astroclip_zogy = compute_astroclip_alignment(flux, img_dict)
        astroclip_zogy["image_provided"] = img_dict is not None      # without an image the ZOGY numbers are zeros
        if astroclip_zogy.get("is_moving_dipole") and not astroclip_zogy.get("cosmic_ray_veto"):
            anomaly_score = round(float(min(1.0, max(anomaly_score, 0.55 + 0.40 * astroclip_zogy["dipole_polarity_score"]))), 4)

        versions = dict(reg.versions)
        versions["physics_sed"] = "spexpi-sonora-spender-v1.0"
        versions["astroclip_zogy"] = "astroclip-zogy-v1.0"

        return {
            "probabilities": probs,
            "top_class": top_class,
            "anomaly_score": anomaly_score,
            "model_versions": versions,
            "physics_diagnostics": physics_diag,
            "astroclip_zogy": astroclip_zogy,
            "spectrum_source": spectrum_source,
            "spectrum_snr_median": snr_median,
            # archive only: was the classified spectrum real SPHEREx data or the backend's physical model,
            # and from which epoch (the backend picks the epoch with the best real data)
            "spectrum_data_mode": meta.get("data_mode"),
            "spectrum_epoch": meta.get("epoch"),
            "spectrum_observed_quarter": meta.get("observed_quarter"),
            "spectrum_bands_measured": meta.get("n_bands_measured"),
            "spectrum_bands_blended": meta.get("n_bands_blended"),
            "spectrum_bands_used": fill_fit["n_bands"] if fill_fit is not None else None,
            "classification_input": ("measured" if fill_fit is None else
                                     f"{fill_fit['n_bands']} usable bands + template fill ({fill_fit['class']}) for the other "
                                     f"{N_BANDS - fill_fit['n_bands']}"),
            # The 1D-CNN was trained on synthetic spectra; on real data it can be confidently wrong. When its
            # class differs from the physics template fitted to the same bands, say so.
            "physics_agrees": (None if not physics_diag or not physics_diag.get("best_template_class")
                               else physics_diag["best_template_class"] == top_class),
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
