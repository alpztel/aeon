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

from . import __version__, analysis, bands, ephem, orbit, orbit_fit, photometry, sky
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
        ra_t, dec_t = ephem.apparent_position(e, t_year)
        ra_m, dec_m = ephem.apparent_position(e, MID_SURVEY)
        s = min(_sep_arcsec(ra, dec, ra_t, dec_t), _sep_arcsec(ra, dec, ra_m, dec_m))
        if s <= tol_arcsec and (best is None or s < best[0]):
            best = (s, e, ra_t, dec_t)
    return None if best is None else best[1:]


def entry_public(e: CatalogEntry, t_year: float, sep: float | None = None) -> dict:
    ra, dec = ephem.apparent_position(e, t_year)
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
        results = [entry_public(ENTRIES_BY_ID[r["id"]], t) for r in cat.by_name(q, t, limit)]
        return {"query": {"q": q, "epoch_year": t}, "count": len(results), "results": results}
    if ra is None or dec is None:
        raise RequestError("Provide either q or both ra and dec.")
    # DuckDB pre-selects with a margin covering the largest parallax in the catalog (~0.25 deg for
    # objects at >= 250 AU); exact apparent separations are then computed per object.
    margin_arcmin = 20.0
    results = []
    for r in cat.cone(ra, dec, radius_arcmin + margin_arcmin, t, 500):
        e = ENTRIES_BY_ID[r["id"]]
        a, b = ephem.apparent_position(e, t)
        sep = _sep_arcsec(ra, dec, a, b)
        if sep <= radius_arcmin * 60.0:
            results.append(entry_public(e, t, sep))
    results.sort(key=lambda o: o["separation_arcsec"])
    results = results[:limit]
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


PARALLAX_STEP_PX = 1.5          # parallax-amplitude grid spacing for the distance axis
BLIND_STAMP_PX = 25             # stamp size used to score blind-search hypotheses
BLIND_SEARCH_RADIUS_PX = 4.0    # hypotheses are scored near the requested reference position
MAX_FRAME_PX = 640


def _frame_times(n_frames: int) -> np.ndarray:
    return np.array([SURVEY_START + (i + 0.5) * (SURVEY_END - SURVEY_START) / n_frames for i in range(n_frames)])


def _render_frames(ra: float, dec: float, times: np.ndarray, size_px: int, scale: float, band: int | None):
    frames, w = [], None
    for t in times:
        img, w, _ = sky.render(ra, dec, [float(t)], size_px, scale, band, seed_tag="frame")
        frames.append(img)
    return np.array(frames), w


def _hypothesis(ra, dec, t_ref, times, rate, pa, dist, scale):
    """Track of one hypothesis: apparent RA/Dec per frame and pixel offsets from the reference."""
    tra, tdec = ephem.track(ra, dec, t_ref, times, rate, pa, dist)
    w0 = sky.make_wcs(ra, dec, 1, scale)                 # pixel 0 == reference position
    x, y = w0.all_world2pix(tra, tdec, 0)
    return np.asarray(x), np.asarray(y), tra, tdec


def _frame_size(max_offset_px: float, stamp: int) -> int:
    size = int(2 * math.ceil(max_offset_px) + stamp + 12)
    if size > MAX_FRAME_PX:
        raise RequestError(f"Track spans {max_offset_px:.0f} px; reduce rates or raise the minimum distance.")
    return size


def _stack_payload(r: dict, band: int | None, n_frames: int, times: np.ndarray, rate: float, pa: float,
                   dist: float | None, tra, tdec) -> dict:
    w = r["wcs"]
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
        "rate_arcsec_yr": round(float(rate), 4),
        "pa_deg": round(float(pa), 4),
        "distance_au": None if dist is None else round(float(dist), 3),
        "motion_frame": "geocentric (Earth parallax tracked)" if dist is not None else "heliocentric (no parallax)",
        "track": [{"t": round(float(t), 5), "ra": round(float(a), 7), "dec": round(float(b), 7)}
                  for t, a, b in zip(times, tra, tdec)],
        "peak": r["peak"],
        "astrometry": r.get("astrometry", []),
    }


def _shift_stack(req: dict) -> dict:
    ra, dec = req["ra"], req["dec"]
    size, scale, band = req.get("size_px", 64), req.get("pixel_scale_arcsec", sky.NATIVE_PIXEL_SCALE), req.get("band")
    n = int(req.get("n_frames", 24))
    rate, pa = float(req.get("rate_arcsec_yr", 0.0)), float(req.get("pa_deg", 0.0))
    dist = req.get("distance_au")
    times = _frame_times(n)
    t_ref = float(np.mean(times))
    dx, dy, tra, tdec = _hypothesis(ra, dec, t_ref, times, rate, pa, dist, scale)
    fsize = _frame_size(float(np.max(np.abs(np.concatenate([dx, dy])))), size)
    frames, w = _render_frames(ra, dec, times, fsize, scale, band)
    c = (fsize - 1) / 2.0
    tracker = analysis.Tracker(analysis.remove_static_sky(frames), _psf_sigma_px(band, scale), c, c)
    r = analysis.run_tracked(tracker, w, times, t_ref, dx, dy, size, 6.0, req.get("combine", "mean"))
    return _stack_payload(r, band, n, times, rate, pa, dist, tra, tdec)


def _blind_search(req: dict) -> dict:
    ra, dec = req["ra"], req["dec"]
    size, scale, band = req.get("size_px", 64), req.get("pixel_scale_arcsec", sky.NATIVE_PIXEL_SCALE), req.get("band")
    n = int(req.get("n_frames", 24))
    grid = int(req.get("grid", 5))
    combine = req.get("combine", "mean")
    rr = req.get("rate_range_arcsec_yr") or (20.0, 200.0)
    pr = req.get("pa_range_deg") or (30.0, 90.0)
    dr = req.get("distance_range_au", (250.0, 1000.0))
    rates = np.linspace(rr[0], rr[1], grid)
    pas = np.linspace(pr[0], pr[1], grid)
    if dr:
        d_lo, d_hi = sorted(float(v) for v in dr)
        if d_lo <= 0:
            raise RequestError("distance_range_au must be positive.")
        step = PARALLAX_STEP_PX * scale
        amps = np.arange(ephem.AU_PER_PC / d_hi, ephem.AU_PER_PC / d_lo + step, step)
        distances = [float(ephem.AU_PER_PC / a) for a in amps]
    else:
        distances = [None]
    times = _frame_times(n)
    t_ref = float(np.mean(times))

    hyps = {}
    max_off = 0.0
    for k, dist in enumerate(distances):
        for i, rate in enumerate(rates):
            for j, pa in enumerate(pas):
                dx, dy, _, _ = _hypothesis(ra, dec, t_ref, times, rate, pa, dist, scale)
                hyps[(k, i, j)] = (dx, dy)
                max_off = max(max_off, float(np.max(np.abs(np.concatenate([dx, dy])))))
    fsize = _frame_size(max_off + 2.0, max(size, BLIND_STAMP_PX))
    frames, w = _render_frames(ra, dec, times, fsize, scale, band)
    c = (fsize - 1) / 2.0
    tracker = analysis.Tracker(analysis.remove_static_sky(frames), _psf_sigma_px(band, scale), c, c)

    scores = np.full((len(distances), grid, grid), -np.inf)
    for (k, i, j), (dx, dy) in hyps.items():
        scores[k, i, j] = tracker.score(dx, dy, BLIND_STAMP_PX, BLIND_SEARCH_RADIUS_PX, combine)[0]
    k, i, j = np.unravel_index(int(np.argmax(scores)), scores.shape)
    best = (float(rates[i]), float(pas[j]), distances[k], float(scores[k, i, j]))

    # Local refinement: half the coarse spacing on every axis.
    d_rate = (rates[1] - rates[0]) / 2 if grid > 1 else 0.0
    d_pa = (pas[1] - pas[0]) / 2 if grid > 1 else 0.0
    if distances[k] is None:
        d_cands = [None]
    else:
        a0 = ephem.AU_PER_PC / distances[k]
        half = PARALLAX_STEP_PX * scale / 2
        d_cands = [float(ephem.AU_PER_PC / a) for a in (a0 - half, a0, a0 + half) if a > 0]
    n_refined = 0
    for rate in (best[0] - d_rate, best[0], best[0] + d_rate):
        for pa in (best[1] - d_pa, best[1], best[1] + d_pa):
            for dist in d_cands:
                if rate < 0:
                    continue
                dx, dy, _, _ = _hypothesis(ra, dec, t_ref, times, rate, pa, dist, scale)
                if float(np.max(np.abs(np.concatenate([dx, dy])))) + BLIND_STAMP_PX / 2 > c - 2:
                    continue
                sc = tracker.score(dx, dy, BLIND_STAMP_PX, BLIND_SEARCH_RADIUS_PX, combine)[0]
                n_refined += 1
                if sc > best[3]:
                    best = (rate, pa, dist, sc)
    rate, pa, dist, _ = best
    dx, dy, tra, tdec = _hypothesis(ra, dec, t_ref, times, rate, pa, dist, scale)
    r = analysis.run_tracked(tracker, w, times, t_ref, dx, dy, size, BLIND_SEARCH_RADIUS_PX, combine)
    return {
        "method": "blind-search",
        "rates_arcsec_yr": [round(float(v), 4) for v in rates],
        "pas_deg": [round(float(v), 4) for v in pas],
        "distances_au": None if distances == [None] else [round(d, 3) for d in distances],
        "distance_profile": None if distances == [None] else [round(float(v), 3) for v in scores.max(axis=(1, 2))],
        "grid": scores[k].round(3).tolist(),
        "refined": {"rates_arcsec_yr": [round(float(best[0] + o * d_rate), 4) for o in (-1, 0, 1)],
                    "pas_deg": [round(float(best[1] + o * d_pa), 4) for o in (-1, 0, 1)], "grid": []},
        "n_hypotheses": int(scores.size + n_refined),
        "best": _stack_payload(r, band, n, times, rate, pa, dist, tra, tdec),
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
    if method == "shift-stack":
        return _shift_stack(req)
    if method == "blind-search":
        return _blind_search(req)
    raise RequestError(f"Unknown method {method!r}")


def simulate_orbit(req: dict) -> dict:
    horizons = sorted({float(h) for h in (req.get("horizons_years") or [1, 5, 10])})
    if not horizons or horizons[0] <= 0 or horizons[-1] > 1000:
        raise RequestError("horizons_years must be in (0, 1000].")
    spy = int(req.get("samples_per_year") or 24)
    obs, el = req.get("observation"), req.get("elements")
    tid = req.get("target_id")
    dets = req.get("detections")
    if dets:
        try:
            f = orbit_fit.fit(dets)
        except ValueError as exc:
            raise RequestError(str(exc)) from exc
        out = orbit.simulate(f["r0_ecl_au"], f["v0_ecl_au_yr"], f["t0"], horizons, spy)
        out["fit"] = f["summary"]
        out["input"] = {"detections": len(dets)}
        return out
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
