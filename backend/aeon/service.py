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
from .archive import FitsArchive, Frame, target_wcs
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
            "archive_spherex_frames": str(get_archive().n_spherex),
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


def image_payload(img: np.ndarray, w: WCS, epoch: str | None, band: int | None, unit: str = "uJy/pixel",
                  provenance: dict | None = None) -> dict:
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
        **({"provenance": provenance} if provenance else {}),
    }


def _psf_sigma_px(band: int | None, scale: float) -> float:
    fwhm = sky.BROADBAND_FWHM_ARCSEC if band is None else float(sky.psf_fwhm_arcsec(bands.WAVELENGTH_UM[band]))
    return fwhm / 2.3548 / scale


MIN_ARCHIVE_COVERAGE = 0.5      # fraction of the requested cutout that must hold real pixels


def _frame_info(f: Frame) -> dict:
    img = f.image
    return {"file": img.path.name, "obs_id": img.obs_id, "detector": img.detector, "date_obs": img.date_obs,
            "wavelength_um": None if f.wavelength_um is None else round(f.wavelength_um, 5),
            "bandwidth_um": None if f.bandwidth_um is None else round(f.bandwidth_um, 5), "band": f.band}


def archive_stack(frames: list[Frame], ra: float, dec: float, size_px: int, scale: float, epoch: str,
                  band: int | None) -> tuple[np.ndarray, WCS, dict] | None:
    """Mean of the archive frames resampled onto the requested north-up grid (uJy/pixel).

    band=None on SPHEREx data is the contract's "all-band mean": the plain mean over every frame
    (each frame sees one LVF wavelength at the target). Returns None if the frames cover less than
    MIN_ARCHIVE_COVERAGE of the cutout or miss its centre."""
    arch = get_archive()
    imgs, used = [], []
    for f in frames:
        im, _, w = arch.resampled(f.image, ra, dec, size_px, scale)
        if np.isfinite(im).any():
            imgs.append(im)
            used.append(f)
    if not imgs:
        return None
    with np.errstate(all="ignore"):
        stack = np.nanmean(np.array(imgs), axis=0) if len(imgs) > 1 else imgs[0]
    cov = float(np.isfinite(stack).mean())
    c = size_px // 2
    if cov < MIN_ARCHIVE_COVERAGE or not np.isfinite(stack[c - 1:c + 1, c - 1:c + 1]).all():
        return None
    n_fill = int((~np.isfinite(stack)).sum())
    stack = np.where(np.isfinite(stack), stack, np.nanmedian(stack))
    fwhms = [f.image.psf_fwhm_arcsec for f in used if f.image.psf_fwhm_arcsec]
    fwhm = float(np.median(fwhms)) if fwhms else (sky.BROADBAND_FWHM_ARCSEC if band is None else float(sky.psf_fwhm_arcsec(bands.WAVELENGTH_UM[band])))
    # Resampling to a coarser/finer grid broadens the PSF by ~the larger of the two pixel sizes.
    native = float(np.median([f.image.scale_arcsec for f in used]))
    fwhm_eff = math.hypot(fwhm, 0.5 * max(native, scale))
    spherex = [f for f in used if f.image.kind == "spherex"]
    years = [f.image.decimal_year for f in used if f.image.decimal_year is not None]
    lams = [f.wavelength_um for f in spherex]
    prov = {
        "source": "IRSA SPHEREx Level 2 spectral images" if spherex else "FITS archive",
        "n_frames": len(used), "epoch_rule": "calendar quarter of the observation date",
        "obs_date_range": [min(f.image.date_obs for f in used if f.image.date_obs), max(f.image.date_obs for f in used if f.image.date_obs)] if years else None,
        "obs_decimal_year_mean": round(float(np.mean(years)), 4) if years else None,
        "wavelength_range_um": [round(min(lams), 4), round(max(lams), 4)] if lams else None,
        "combine": "mean of frames resampled to the requested north-up TAN grid (bilinear, surface brightness conserving)",
        "masked_flags": "TRANSIENT OVERFLOW SUR_ERROR NONFUNC MISSING_DATA HOT COLD NONLINEAR PERSIST OUTLIER CROSSTALK GHOST* STREAK BLOOM SNOWBALL HALO" if spherex else None,
        "filled_pixels": n_fill, "coverage": round(cov, 4), "native_pixel_scale_arcsec": round(native, 4),
        "frames": [_frame_info(f) for f in used[:12]],
    }
    meta = {"source": "fits_archive", "file": used[0].image.path.name, "psf_sigma_px": fwhm_eff / 2.3548 / scale,
            "pixel_scale_arcsec": scale, "provenance": prov, "decimal_year": prov["obs_decimal_year_mean"]}
    return stack, target_wcs(ra, dec, size_px, scale), meta


def epoch_image(ra: float, dec: float, epoch: str, size_px: int, scale: float, band: int | None,
                allowed_bands: set[int] | None = None, use_archive: bool = True) -> tuple[np.ndarray, WCS, dict]:
    """Raw (background-included) image for one epoch from the archive or the sky model."""
    arch = get_archive()
    if use_archive and arch.available:
        frames = arch.frames(ra, dec, epoch, band, allowed_bands)
        if frames:
            got = archive_stack(frames, ra, dec, size_px, scale, epoch, band)
            if got is not None:
                return got
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
        extra = {"AEONEPOC": epoch, "BKGLEVEL": bkg, "BKGSTD": std, "DATAMODE": meta["source"],
                 "BAND": -1 if band is None else band}
        prov = meta.get("provenance")
        if prov:
            extra.update({"TELESCOP": "SPHEREx" if prov["wavelength_range_um"] else "unknown",
                          "ORIGIN": "AEON from IRSA SPHEREx L2" if prov["wavelength_range_um"] else "AEON FITS archive",
                          "NFRAMES": prov["n_frames"], "DATEOBS1": (prov["obs_date_range"] or ["", ""])[0],
                          "DATEOBS2": (prov["obs_date_range"] or ["", ""])[1]})
            if prov["wavelength_range_um"]:
                extra.update({"WAVEMIN": prov["wavelength_range_um"][0], "WAVEMAX": prov["wavelength_range_um"][1]})
        hdul = sky.to_fits(sub, w, extra)
        buf = io.BytesIO()
        hdul.writeto(buf)
        return buf.getvalue()
    out = image_payload(sub, w, epoch, band, provenance=meta.get("provenance"))
    out["background"] = {"level": bkg, "std": std}
    out["data_mode"] = meta["source"]
    return out


MIN_REAL_SPECTRUM_BANDS = 34     # a real spectrum needs >= 1/3 of the 102 AEON bands
SPECTRUM_STAMP_PX = 25


def _archive_spectrum(ra: float, dec: float, epoch: str, aperture_arcsec: float, hit) -> tuple[dict | None, str]:
    """Real SPHEREx spectrum: forced photometry at the target on every LVF frame of the epoch that
    covers it, binned onto the AEON bands. Returns (result or None, reason)."""
    arch = get_archive()
    if not arch.n_spherex:
        return None, "no SPHEREx frames in AEON_DATA_DIR"
    frames = [f for f in arch.frames(ra, dec, epoch) if f.image.kind == "spherex"]
    if not frames:
        return None, f"no SPHEREx frame covers this position in {epoch}"
    ra_c, dec_c = ra, dec
    if hit:     # moving targets: put the aperture where the object was when SPHEREx looked
        t_obs = float(np.median([f.image.decimal_year for f in frames if f.image.decimal_year is not None]))
        ra_c, dec_c = ephem.apparent_position(hit[0], t_obs)
        frames = [f for f in arch.frames(ra_c, dec_c, epoch) if f.image.kind == "spherex"]
    meas = []
    rejected = 0
    phot = None
    for f in frames:
        scale = f.image.scale_arcsec
        stamp, x, y = arch.native_stamp(f.image, ra_c, dec_c, SPECTRUM_STAMP_PX // 2)
        sigma = (f.image.psf_fwhm_arcsec or float(sky.psf_fwhm_arcsec(f.wavelength_um))) / 2.3548 / scale
        res = photometry.forced_point(stamp, x, y, aperture_arcsec / scale, sigma)
        fl, er = float(res["flux"]), float(res["err"])
        if not (np.isfinite(fl) and np.isfinite(er) and er > 0):
            rejected += 1           # flagged pixel in the aperture, or annulus off the frame
            continue
        phot = res
        meas.append((f.band, f.wavelength_um, f.bandwidth_um, fl, er, f))
    by_band: dict[int, list] = {}
    for m in meas:
        if m[0] is not None:
            by_band.setdefault(m[0], []).append(m)
    if len(by_band) < MIN_REAL_SPECTRUM_BANDS:
        return None, (f"only {len(by_band)} of 102 bands covered by unflagged SPHEREx frames in {epoch} "
                      f"(need {MIN_REAL_SPECTRUM_BANDS}; {len(frames)} frames, {rejected} rejected)")
    rows = []
    for b, ms in sorted(by_band.items()):
        wts = np.array([1.0 / m[4] ** 2 for m in ms])
        fl = float(np.sum(wts * np.array([m[3] for m in ms])) / wts.sum())
        rows.append((float(np.mean([m[1] for m in ms])), float(np.mean([m[2] for m in ms])), fl,
                     float(1.0 / math.sqrt(wts.sum())), b, len(ms)))
    rows.sort()
    lam_m = np.array([r[0] for r in rows])
    flux_m = np.array([r[2] for r in rows])
    err_m = np.array([r[3] for r in rows])
    # The contract fixes 102 bands. Measured bands carry the real photometry; the others are filled
    # by log-wavelength interpolation between the nearest measured bands (nearest value outside the
    # measured range) with an inflated error, and are flagged in pipeline.measured.
    measured = np.zeros(bands.N_BANDS, dtype=bool)
    lam = bands.WAVELENGTH_UM.astype(float).copy()
    bw = bands.BANDWIDTH_UM.astype(float).copy()
    flux = np.empty(bands.N_BANDS)
    err = np.empty(bands.N_BANDS)
    for r in rows:
        measured[r[4]] = True
        lam[r[4]], bw[r[4]], flux[r[4]], err[r[4]] = r[0], r[1], r[2], r[3]
    miss = ~measured
    if miss.any():
        ll = np.log(lam_m)
        flux[miss] = np.interp(np.log(lam[miss]), ll, flux_m)
        e_interp = np.interp(np.log(lam[miss]), ll, err_m)
        # neighbour spread as extra uncertainty
        idx = np.clip(np.searchsorted(ll, np.log(lam[miss])), 1, len(ll) - 1)
        spread = np.abs(flux_m[idx] - flux_m[idx - 1])
        err[miss] = np.hypot(e_interp, spread) * 2.0
    t = epoch_year(epoch)
    used = [m[5] for m in meas]
    dates = sorted(f.image.date_obs for f in used if f.image.date_obs)
    return {
        "ra": round(ra_c, 7), "dec": round(dec_c, 7), "epoch": epoch,
        "wavelength_um": [round(float(v), 5) for v in lam],
        "bandwidth_um": [round(float(v), 5) for v in bw],
        "flux_ujy": [round(float(v), 4) for v in flux],
        "flux_err_ujy": [round(float(v), 4) for v in err],
        "snr_median": round(float(np.median(flux_m / np.maximum(err_m, 1e-12))), 3),
        "matched_object": entry_public(hit[0], t, _sep_arcsec(ra, dec, ra_c, dec_c)) if hit else None,
        "absorption_features": photometry.absorption_features(flux_m, err_m, lam_m),
        "pipeline": {
            "data_mode": "fits_archive",
            "source": "IRSA SPHEREx Level 2 spectral images (linear variable filter)",
            "method": ("photutils forced aperture photometry on the native (unresampled) pixels of each LVF frame "
                       "at the target, annulus background, Gaussian aperture correction from the frame's "
                       "PSF_FWHM; inverse-variance mean of the frames falling in each AEON band"),
            "wavelength_note": ("measured bands: wavelength_um is the mean real LVF wavelength at the target "
                                "(WCS-WAVE); unmeasured bands: AEON band centre"),
            "measured": [bool(v) for v in measured],
            "n_bands_measured": int(measured.sum()),
            "unmeasured_fill": ("log-wavelength interpolation between nearest measured bands (nearest value "
                                "outside the measured range), error = 2 x hypot(interpolated error, neighbour "
                                "difference); NOT a measurement"),
            "n_frames": len(frames), "n_frames_used": len(meas), "n_frames_rejected": rejected,
            "n_bands_total": bands.N_BANDS,
            "frames_per_band": [int(next((r[5] for r in rows if r[4] == k), 0)) for k in range(bands.N_BANDS)],
            "obs_date_range": [dates[0], dates[-1]] if dates else None,
            "aperture_px": round(phot["aperture_px"], 3) if phot else None,
            "annulus_px": [round(v, 3) for v in phot["annulus_px"]] if phot else None,
            "recentered": bool(hit) and _sep_arcsec(ra, dec, ra_c, dec_c) > 0.01,
            "pixel_scale_arcsec": round(float(np.median([f.image.scale_arcsec for f in used])), 4),
            "limitations": ("SPHEREx PSF is undersampled and non-Gaussian; the Gaussian aperture correction is "
                            "approximate; 6.15\" pixels blend nearby sources into the aperture. absorption_features and "
                            "snr_median use measured bands only."),
        },
    }, "ok"


def spectrum(ra: float, dec: float, epoch: str, aperture_arcsec: float) -> dict:
    return _spectrum_cached(round(float(ra), 7), round(float(dec), 7), epoch, round(float(aperture_arcsec), 3))


@lru_cache(maxsize=256)
def _spectrum_cached(ra: float, dec: float, epoch: str, aperture_arcsec: float) -> dict:
    t = epoch_year(epoch)
    hit = resolve_target(ra, dec, t, tol_arcsec=max(aperture_arcsec, 2 * sky.NATIVE_PIXEL_SCALE))
    archive_note = None
    if get_archive().available:
        real, why = _archive_spectrum(ra, dec, epoch, aperture_arcsec, hit)
        if real is not None:
            return real
        archive_note = why
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
            **({"archive_fallback_reason": archive_note} if archive_note else {}),
        },
    }


PARALLAX_STEP_PX = 1.5          # parallax-amplitude grid spacing for the distance axis
BLIND_STAMP_PX = 25             # stamp size used to score blind-search hypotheses
BLIND_SEARCH_RADIUS_PX = 4.0    # hypotheses are scored near the requested reference position
MAX_FRAME_PX = 640


def _frame_times(n_frames: int, cadence: str = "uniform", ra: float | None = None, dec: float | None = None) -> np.ndarray:
    """Exposure mid-times over the 2026 survey year.

    uniform: evenly spaced (idealised). spherex: only when the field is in the SPHEREx-like
    observing band (solar elongation ~90 deg, see ephem.spherex_visible_times), spread evenly over
    the visible times."""
    if cadence == "spherex":
        vis = ephem.spherex_visible_times(ra, dec, SURVEY_START, SURVEY_END)
        if len(vis) < n_frames:
            raise RequestError("Field is visible for too short a time in 2026 for the requested n_frames.")
        idx = np.round(np.linspace(0, len(vis) - 1, n_frames)).astype(int)
        return vis[idx]
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
    size = int(math.ceil(size / 64.0) * 64)          # quantised so slider changes reuse the cache
    if size > MAX_FRAME_PX:
        raise RequestError(f"Track spans {max_offset_px:.0f} px; reduce rates or raise the minimum distance.")
    return size


@lru_cache(maxsize=6)
def _tracker_cached(ra: float, dec: float, n: int, fsize: int, scale: float, band: int | None, cadence: str):
    times = _frame_times(n, cadence, ra, dec)
    frames, w = _render_frames(ra, dec, times, fsize, scale, band)
    c = (fsize - 1) / 2.0
    return analysis.Tracker(analysis.remove_static_sky(frames, times), _psf_sigma_px(band, scale), c, c), w, times


def _tracker(ra: float, dec: float, n: int, fsize: int, scale: float, band: int | None, cadence: str = "uniform"):
    return _tracker_cached(round(float(ra), 7), round(float(dec), 7), int(n), int(fsize), float(scale), band, cadence)


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
        "cadence": "spherex" if np.ptp(np.diff(times)) > 1e-6 else "uniform",
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


def _difference_archive_plan(ra: float, dec: float, e1: str, e2: str, band: int | None) -> tuple[bool, set[int] | None]:
    """Use the archive only if it covers both epochs. For SPHEREx all-band images restrict both
    epochs to the AEON bands observed in both, so the two means see the same wavelengths."""
    arch = get_archive()
    if not arch.available:
        return False, None
    f1, f2 = arch.frames(ra, dec, e1, band), arch.frames(ra, dec, e2, band)
    if not f1 or not f2:
        return False, None
    b1 = {f.band for f in f1 if f.band is not None}
    b2 = {f.band for f in f2 if f.band is not None}
    if band is None and b1 and b2:
        common = b1 & b2
        return (True, common) if common else (False, None)
    return True, None


def _shift_stack(req: dict) -> dict:
    ra, dec = req["ra"], req["dec"]
    size, scale, band = req.get("size_px", 64), req.get("pixel_scale_arcsec", sky.NATIVE_PIXEL_SCALE), req.get("band")
    n = int(req.get("n_frames", 24))
    rate, pa = float(req.get("rate_arcsec_yr", 0.0)), float(req.get("pa_deg", 0.0))
    dist = req.get("distance_au")
    cadence = req.get("cadence") or "uniform"
    times = _frame_times(n, cadence, round(float(ra), 7), round(float(dec), 7))
    t_ref = MID_SURVEY            # the (ra, dec) of a hypothesis refers to mid-survey 2026.5
    dx, dy, tra, tdec = _hypothesis(ra, dec, t_ref, times, rate, pa, dist, scale)
    fsize = _frame_size(float(np.max(np.abs(np.concatenate([dx, dy])))), size)
    tracker, w, _ = _tracker(ra, dec, n, fsize, scale, band, cadence)
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
    cadence = req.get("cadence") or "uniform"
    times = _frame_times(n, cadence, round(float(ra), 7), round(float(dec), 7))
    t_ref = MID_SURVEY            # the (ra, dec) of a hypothesis refers to mid-survey 2026.5

    hyps = {}
    max_off = 0.0
    for k, dist in enumerate(distances):
        for i, rate in enumerate(rates):
            for j, pa in enumerate(pas):
                dx, dy, _, _ = _hypothesis(ra, dec, t_ref, times, rate, pa, dist, scale)
                hyps[(k, i, j)] = (dx, dy)
                max_off = max(max_off, float(np.max(np.abs(np.concatenate([dx, dy])))))
    fsize = _frame_size(max_off + 2.0, max(size, BLIND_STAMP_PX))
    tracker, w, _ = _tracker(ra, dec, n, fsize, scale, band, cadence)
    c = tracker.cx

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
        use_arch, allowed = _difference_archive_plan(ra, dec, e1, e2, band)
        i1, w, m1 = epoch_image(ra, dec, e1, size, scale, band, allowed, use_arch)
        i2, w2, m2 = epoch_image(ra, dec, e2, size, scale, band, allowed, use_arch)
        if m1["source"] != m2["source"]:          # never difference real data against the model
            i1, w, m1 = epoch_image(ra, dec, e1, size, scale, band, use_archive=False)
            i2, w2, m2 = epoch_image(ra, dec, e2, size, scale, band, use_archive=False)
        if i1.shape != i2.shape:
            raise RequestError("Epoch images have different shapes; cannot difference.")
        ps = m1.get("psf_sigma_px", _psf_sigma_px(band, scale))
        d = analysis.difference(i1, i2, w, ps)
        a, b = d["background_subtracted"]
        out = {
            "method": "difference",
            "image_1": image_payload(a, w, e1, band, provenance=m1.get("provenance")),
            "image_2": image_payload(b, w, e2, band, provenance=m2.get("provenance")),
            "difference": image_payload(d["difference"], w, None, band),
            "detections": d["detections"], "noise_sigma": round(d["noise_sigma"], 5),
            "dt_years": round(epoch_year(e2) - epoch_year(e1), 4), "data_mode": m1["source"],
        }
        if m1.get("decimal_year") is not None and m2.get("decimal_year") is not None:
            # Real observation dates differ from the nominal quarter centres; report the true baseline.
            out["dt_years_observed"] = round(m2["decimal_year"] - m1["decimal_year"], 4)
        return out
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
