"""Business logic behind the core endpoints. Chooses the FITS archive when it covers the request
and the physical sky model otherwise, then runs the same Astropy/Photutils pipeline."""

from __future__ import annotations

import io
import math
import os
from functools import lru_cache

import numpy as np
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales

from . import __version__, analysis, bands, orbit, photometry, sky
from .archive import FitsArchive
from .catalog import ENTRIES, ENTRIES_BY_ID, CatalogEntry, get_catalog, position_at
from .epochs import DEFAULT_EPOCH, SURVEY_END, SURVEY_START, epoch_year

MID_SURVEY = 0.5 * (SURVEY_START + SURVEY_END)


class RequestError(ValueError):
    """Raised for semantically invalid requests (mapped to HTTP 422)."""


@lru_cache(maxsize=1)
def get_archive() -> FitsArchive:
    return FitsArchive(os.environ.get("AEON_DATA_DIR"))


def data_mode() -> str:
    return "fits_archive" if get_archive().available else "physical_model"


def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "data_mode": data_mode(),
        "engines": {
            "orbit": f"rebound-{orbit.REBOUND_VERSION}" if orbit.REBOUND_VERSION else "numpy-leapfrog",
            "catalog": "duckdb",
            "photometry": "photutils",
            "fits": "astropy",
            "archive_images": str(len(get_archive().images)),
        },
    }


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------

def _sep_arcsec(ra1, dec1, ra2, dec2) -> float:
    return float(sky._angsep_deg(ra1, dec1, ra2, dec2) * 3600.0)


def resolve_target(ra: float, dec: float, t_year: float, tol_arcsec: float) -> tuple[CatalogEntry, float, float] | None:
    """Catalog object the user pointed at: within tolerance of its position at t, or of its
    mid-survey catalog position (what /catalog/search returns by default)."""
    best = None
    for e in ENTRIES:
        ra_t, dec_t = position_at(e, t_year)
        ra_m, dec_m = position_at(e, MID_SURVEY)
        s = min(_sep_arcsec(ra, dec, ra_t, dec_t), _sep_arcsec(ra, dec, ra_m, dec_m))
        if s <= tol_arcsec and (best is None or s < best[0]):
            best = (s, e, ra_t, dec_t)
    return None if best is None else best[1:]


def entry_public(e: CatalogEntry, t_year: float, sep: float | None = None) -> dict:
    ra, dec = position_at(e, t_year)
    return {
        "id": e.id, "name": e.name, "aliases": list(e.aliases), "ra": round(ra, 7), "dec": round(dec, 7),
        "object_class": e.object_class, "mag_ab_w2": e.mag_ab_w2,
        "pm_ra_cosdec_arcsec_yr": e.pm_ra_cosdec_arcsec_yr, "pm_dec_arcsec_yr": e.pm_dec_arcsec_yr,
        "distance_au": e.distance_au, "distance_pc": e.distance_pc, "teff_k": e.teff_k,
        "is_demo": e.is_demo, "is_synthetic": e.is_synthetic, "description": dict(e.description),
        "separation_arcsec": None if sep is None else round(sep, 3), "source": "catalog",
    }


def image_payload(img: np.ndarray, w: WCS, epoch: str | None, band: int | None, unit: str = "uJy/pixel") -> dict:
    scale = float(np.mean(proj_plane_pixel_scales(w.celestial)) * 3600.0)
    ny, nx = img.shape
    ra, dec = w.all_pix2world([[(nx - 1) / 2, (ny - 1) / 2]], 0)[0]
    finite = img[np.isfinite(img)]
    return {
        "width": int(nx), "height": int(ny),
        "data": [float(v) for v in np.round(img.astype(float).ravel(), 4)],
        "unit": unit, "epoch": epoch, "ra": round(float(ra) % 360, 7), "dec": round(float(dec), 7),
        "pixel_scale_arcsec": round(scale, 4), "band": band,
        "wcs": {k: (v if isinstance(v, (int, float, str)) else str(v)) for k, v in w.to_header().items()
                if k.startswith(("CTYPE", "CRVAL", "CRPIX", "CDELT", "CUNIT", "PC", "RADESYS"))},
        "stats": {"min": float(finite.min()), "max": float(finite.max()), "median": float(np.median(finite)),
                  "std": float(np.std(finite))},
    }


def _psf_sigma_px(band: int | None, scale: float) -> float:
    fwhm = sky.BROADBAND_FWHM_ARCSEC if band is None else float(sky.psf_fwhm_arcsec(bands.WAVELENGTH_UM[band]))
    return fwhm / 2.3548 / scale


def epoch_image(ra: float, dec: float, epoch: str, size_px: int, scale: float, band: int | None) -> tuple[np.ndarray, WCS, dict]:
    """Raw (background-included) image for one epoch from the archive or the sky model."""
    arch = get_archive()
    if band is None and arch.available:
        hit = arch.find(ra, dec, epoch)
        if hit is not None:
            img, w = arch.cutout(hit, ra, dec, size_px)
            return img, w, {"source": "fits_archive", "file": hit.path.name, "psf_sigma_px": _psf_sigma_px(None, hit.scale_arcsec),
                            "pixel_scale_arcsec": hit.scale_arcsec}
    img, w, meta = sky.render(ra, dec, sky.epoch_subtimes(epoch_year(epoch)), size_px, scale, band, seed_tag=f"epoch-{epoch}")
    meta.update(source="physical_model", pixel_scale_arcsec=scale)
    return img, w, meta


# --------------------------------------------------------------------------------------------
# Endpoint implementations
# --------------------------------------------------------------------------------------------

def search_catalog(q: str | None, ra: float | None, dec: float | None, radius_arcmin: float,
                   include_field: bool, limit: int, epoch: str | None) -> dict:
    t = epoch_year(epoch) if epoch else MID_SURVEY
    cat = get_catalog()
    if q:
        results = cat.by_name(q, t, limit)
        for r in results:
            r.pop("ref_epoch", None)
            r.pop("redshift", None)
        return {"query": {"q": q, "epoch_year": t}, "count": len(results), "results": results}
    if ra is None or dec is None:
        raise RequestError("Provide either q or both ra and dec.")
    results = cat.cone(ra, dec, radius_arcmin, t, limit)
    for r in results:
        r.pop("ref_epoch", None)
        r.pop("redshift", None)
    if include_field and len(results) < limit:
        f = sky.field_sources(ra, dec, min(radius_arcmin, 30.0) / 60.0)
        seps = sky._angsep_deg(ra, dec, f["ra"], f["dec"]) * 3600.0
        for i in np.argsort(seps)[: limit - len(results)]:
            fra, fdec = float(f["ra"][i]), float(f["dec"][i])
            gal = bool(f["is_galaxy"][i])
            results.append({
                "id": f"field-{fra:.5f}{fdec:+.5f}",
                "name": "AEON J{:08.4f}{:+08.4f}".format(fra, fdec),
                "aliases": [], "ra": round(fra, 7), "dec": round(fdec, 7),
                "object_class": "high_z_galaxy" if gal else "main_sequence_star",
                "mag_ab_w2": round(float(f["mag"][i]), 3), "teff_k": None if gal else round(float(f["teff"][i]), 0),
                "pm_ra_cosdec_arcsec_yr": 0.0, "pm_dec_arcsec_yr": 0.0, "distance_au": None, "distance_pc": None,
                "is_demo": False, "is_synthetic": True, "description": {},
                "separation_arcsec": round(float(seps[i]), 3), "source": "field",
            })
    return {"query": {"ra": ra, "dec": dec, "radius_arcmin": radius_arcmin, "epoch_year": t},
            "count": len(results), "results": results}


def cutout(ra: float, dec: float, epoch: str, size_px: int, scale: float, band: int | None, as_fits: bool):
    img, w, meta = epoch_image(ra, dec, epoch, size_px, scale, band)
    sub, bkg, std = photometry.background_subtract(img)
    if as_fits:
        hdul = sky.to_fits(sub, w, {"AEONEPOC": epoch, "BKGLEVEL": bkg, "BKGSTD": std, "DATAMODE": meta["source"],
                                     "BAND": -1 if band is None else band})
        buf = io.BytesIO()
        hdul.writeto(buf)
        return buf.getvalue()
    out = image_payload(sub, w, epoch, band)
    out["background"] = {"level": bkg, "std": std}
    out["data_mode"] = meta["source"]
    return out


def spectrum(ra: float, dec: float, epoch: str, aperture_arcsec: float) -> dict:
    t = epoch_year(epoch)
    hit = resolve_target(ra, dec, t, tol_arcsec=max(aperture_arcsec, 2 * sky.NATIVE_PIXEL_SCALE))
    ra_c, dec_c = (hit[1], hit[2]) if hit else (ra, dec)
    cube, w, meta = sky.render_cube(ra_c, dec_c, sky.epoch_subtimes(t), seed_tag=f"cube-{epoch}")
    phot = photometry.extract_spectrum(cube, w, ra_c, dec_c, aperture_arcsec, meta["psf_sigma_px"])
    flux, err = phot["flux"], phot["err"]
    snr = flux / np.maximum(err, 1e-12)
    return {
        "ra": round(ra_c, 7), "dec": round(dec_c, 7), "epoch": epoch,
        "wavelength_um": [round(float(v), 5) for v in bands.WAVELENGTH_UM],
        "bandwidth_um": [round(float(v), 5) for v in bands.BANDWIDTH_UM],
        "flux_ujy": [round(float(v), 4) for v in flux],
        "flux_err_ujy": [round(float(v), 4) for v in err],
        "snr_median": round(float(np.median(snr)), 3),
        "matched_object": entry_public(hit[0], t, _sep_arcsec(ra, dec, ra_c, dec_c)) if hit else None,
        "absorption_features": photometry.absorption_features(flux, err),
        "pipeline": {
            "data_mode": "physical_model", "method": "photutils forced aperture photometry, annulus background, Gaussian aperture correction",
            "aperture_px": round(phot["aperture_px"], 3), "annulus_px": [round(v, 3) for v in phot["annulus_px"]],
            "recentered": bool(hit) and _sep_arcsec(ra, dec, ra_c, dec_c) > 0.01,
            "pixel_scale_arcsec": sky.NATIVE_PIXEL_SCALE,
        },
    }


def _frames(ra: float, dec: float, n_frames: int, size_px: int, scale: float, band: int | None):
    times = np.array([SURVEY_START + (i + 0.5) * (SURVEY_END - SURVEY_START) / n_frames for i in range(n_frames)])
    frames = []
    w = None
    for t in times:
        img, w, _ = sky.render(ra, dec, [float(t)], size_px, scale, band, seed_tag="frame")
        frames.append(img)
    return np.array(frames), times, w


def _stack_payload(r: dict, w: WCS, band: int | None, n_frames: int, times: np.ndarray) -> dict:
    return {
        "method": "shift-stack",
        "stacked": image_payload(r["stacked"], w, None, band),
        "single_frame": image_payload(r["single_frame"], w, None, band),
        "snr_single_frame": round(r["snr_single_frame"], 3) if math.isfinite(r["snr_single_frame"]) else None,
        "snr_stacked": round(r["snr_stacked"], 3),
        "snr_gain": None if r["snr_gain"] is None else round(r["snr_gain"], 3),
        "n_frames": n_frames,
        "frame_times": [round(float(t), 5) for t in times],
        "t_ref": round(r["t_ref"], 5),
        "rate_arcsec_yr": round(float(r["rate_arcsec_yr"]), 4),
        "pa_deg": round(float(r["pa_deg"]), 4),
        "motion_frame": "heliocentric (Earth-reflex parallax removed for the trial distance)",
        "peak": r["peak"],
    }


def run_analysis(method: str, req: dict) -> dict:
    ra, dec = req["ra"], req["dec"]
    size, scale, band = req.get("size_px", 64), req.get("pixel_scale_arcsec", sky.NATIVE_PIXEL_SCALE), req.get("band")
    if method == "difference":
        e1, e2 = req.get("epoch_1") or DEFAULT_EPOCH, req.get("epoch_2") or "2026-Q3"
        if e1 == e2:
            raise RequestError("epoch_1 and epoch_2 must differ.")
        i1, w, m1 = epoch_image(ra, dec, e1, size, scale, band)
        i2, w2, m2 = epoch_image(ra, dec, e2, size, scale, band)
        if i1.shape != i2.shape:
            raise RequestError("Epoch images have different shapes; cannot difference.")
        ps = m1.get("psf_sigma_px", _psf_sigma_px(band, scale))
        d = analysis.difference(i1, i2, w, ps)
        a, b = d["background_subtracted"]
        return {
            "method": "difference",
            "image_1": image_payload(a, w, e1, band), "image_2": image_payload(b, w, e2, band),
            "difference": image_payload(d["difference"], w, None, band),
            "detections": d["detections"], "noise_sigma": round(d["noise_sigma"], 5),
            "dt_years": round(epoch_year(e2) - epoch_year(e1), 4), "data_mode": m1["source"],
        }
    n = int(req.get("n_frames", 24))
    frames, times, w = _frames(ra, dec, n, size, scale, band)
    ps = _psf_sigma_px(band, scale)
    combine = req.get("combine", "mean")
    if method == "shift-stack":
        r = analysis.run_shift_stack(frames, times, w, ps, scale, float(req.get("rate_arcsec_yr", 0.0)),
                                     float(req.get("pa_deg", 0.0)), combine)
        return _stack_payload(r, w, band, n, times)
    if method == "blind-search":
        rr = tuple(req.get("rate_range_arcsec_yr") or (20.0, 200.0))
        pr = tuple(req.get("pa_range_deg") or (30.0, 90.0))
        b = analysis.blind_search(frames, times, w, ps, scale, rr, pr, int(req.get("grid", 5)), combine)
        return {"method": "blind-search", "rates_arcsec_yr": b["rates"], "pas_deg": b["pas"], "grid": b["grid"],
                "refined": b["refined"], "best": _stack_payload(b["best"], w, band, n, times)}
    raise RequestError(f"Unknown method {method!r}")


def simulate_orbit(req: dict) -> dict:
    horizons = sorted({float(h) for h in (req.get("horizons_years") or [1, 5, 10])})
    if not horizons or horizons[0] <= 0 or horizons[-1] > 1000:
        raise RequestError("horizons_years must be in (0, 1000].")
    spy = int(req.get("samples_per_year") or 24)
    obs, el = req.get("observation"), req.get("elements")
    tid = req.get("target_id")
    if tid:
        e = ENTRIES_BY_ID.get(tid)
        if e is None:
            raise RequestError(f"Unknown target_id {tid!r}")
        if not e.distance_au:
            raise RequestError(f"{e.name} is not a solar-system object; no orbit to simulate.")
        ra, dec = position_at(e, MID_SURVEY)
        rate = math.hypot(e.pm_ra_cosdec_arcsec_yr, e.pm_dec_arcsec_yr)
        pa = math.degrees(math.atan2(e.pm_ra_cosdec_arcsec_yr, e.pm_dec_arcsec_yr)) % 360
        obs = {"ra": ra, "dec": dec, "distance_au": e.distance_au, "rate_arcsec_yr": rate, "pa_deg": pa}
    if obs:
        r0, v0 = orbit.state_from_observation(obs["ra"], obs["dec"], obs["distance_au"], obs.get("rate_arcsec_yr", 0.0),
                                              obs.get("pa_deg", 0.0), obs.get("radial_velocity_km_s", 0.0))
    elif el:
        r0, v0 = orbit.kepler_state(el["a_au"], el["e"], math.radians(el["inc_deg"]), math.radians(el.get("Omega_deg", 0.0)),
                                    math.radians(el.get("omega_deg", 0.0)), math.radians(el.get("M_deg", 0.0)))
    else:
        raise RequestError("Provide observation, elements or target_id.")
    out = orbit.simulate(r0, v0, MID_SURVEY, horizons, spy)
    if obs:
        out["input"] = {"observation": obs}
    return out
