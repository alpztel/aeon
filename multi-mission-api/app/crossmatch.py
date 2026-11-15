"""Multi-mission cross-matching (Gaia DR3, WISE, MAST JWST/HST) and SED builder (0.4-22 um).

Vega -> AB magnitude offsets:
  - Gaia DR3 (Evans et al. 2018):
      BP (0.511 um): m_AB = m_Vega + 0.02
      G  (0.622 um): m_AB = m_Vega + 0.12
      RP (0.777 um): m_AB = m_Vega + 0.36
  - WISE (Jarrett et al. 2011):
      W1 (3.35 um):  m_AB = m_Vega + 2.699
      W2 (4.60 um):  m_AB = m_Vega + 3.339
      W3 (11.56 um): m_AB = m_Vega + 5.174
      W4 (22.09 um): m_AB = m_Vega + 6.620
Flux conversion:
  F_nu [uJy] = 3631e6 * 10**(-0.4 * m_AB)
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any

import httpx

from . import age_mass, kinematics, validation
from .sed_fitter import compute_kete_kbmod_kinematics, fit_multi_mission_sed

FIXTURES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "crossmatch_fixtures.json"
CACHE_DIR = Path(os.environ.get("AEON_CACHE_DIR", str(Path(__file__).resolve().parents[1] / ".cache_crossmatch")))
CACHE_TTL_SEC = 86400.0  # 24 hours

GAIA_BANDS: tuple[tuple[str, float, float], ...] = (
    ("phot_bp_mean_mag", 0.511, 0.02),
    ("phot_g_mean_mag", 0.622, 0.12),
    ("phot_rp_mean_mag", 0.777, 0.36),
)

WISE_BANDS: tuple[tuple[str, str, float, float], ...] = (
    ("w1mpro", "w1sigmpro", 3.35, 2.699),
    ("w2mpro", "w2sigmpro", 4.60, 3.339),
    ("w3mpro", "w3sigmpro", 11.56, 5.174),
    ("w4mpro", "w4sigmpro", 22.09, 6.620),
)


def vega_to_ujy(mag_vega: float, vega_to_ab_offset: float) -> float:
    mag_ab = float(mag_vega) + float(vega_to_ab_offset)
    return float(3631e6 * (10.0 ** (-0.4 * mag_ab)))


def angular_sep_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1 = math.radians(ra1), math.radians(dec1)
    r2, d2 = math.radians(ra2), math.radians(dec2)
    sin_d = math.sin((d2 - d1) / 2.0)
    sin_r = math.sin((r2 - r1) / 2.0)
    a = min(1.0, max(0.0, sin_d * sin_d + math.cos(d1) * math.cos(d2) * sin_r * sin_r))
    return math.degrees(2.0 * math.asin(math.sqrt(a))) * 3600.0


@lru_cache(maxsize=1)
def _load_fixtures() -> dict[str, Any]:
    return json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))


def _match_fixture(ra: float, dec: float) -> dict[str, Any] | None:
    fixtures = _load_fixtures().get("targets", {})
    for target in fixtures.values():
        limit_arcsec = float(target.get("match_radius_deg", 0.08)) * 3600.0
        sep_ref = angular_sep_arcsec(ra, dec, float(target["ra_ref"]), float(target["dec_ref"]))
        sep_2026 = angular_sep_arcsec(ra, dec, float(target["ra_2026"]), float(target["dec_2026"]))
        if min(sep_ref, sep_2026) <= limit_arcsec:
            return target
    return None


# The core backend answers a new position in well under a second; the old 2.5 s limit was shorter
# than a cold real-data spectrum and silently dropped SPHEREx from the SED.
CORE_SPECTRUM_TIMEOUT_S = float(os.environ.get("AEON_CORE_SPECTRUM_TIMEOUT_S", "12"))
SED_MIN_SNR = 3.0            # a SPHEREx band enters the SED only as a detection


def _fetch_spherex_spectrum(ra: float, dec: float) -> tuple[dict[str, Any] | None, str]:
    """(spectrum, status). No epoch is sent: the backend picks the epoch with the best real SPHEREx
    data (it used to be pinned to 2026-Q1, where most targets only have the physical model).
    status: "ok" | "unavailable" (no answer / error: the result must not be cached for long)."""
    core_url = os.environ.get("AEON_CORE_URL", "http://localhost:8000").rstrip("/")
    try:
        with httpx.Client(timeout=CORE_SPECTRUM_TIMEOUT_S, verify=not core_url.startswith("http://")) as client:
            resp = client.get(f"{core_url}/api/v1/spectrum", params={"ra": ra, "dec": dec})
            if resp.status_code == 200:
                body = resp.json()
                return (body, "ok") if isinstance(body, dict) else (None, "unavailable")
            return None, "ok" if resp.status_code < 500 else "unavailable"
    except Exception:
        return None, "unavailable"


# Gaia DR3 completeness limit G ~ 20.7 (Vega) ~ 20.8 AB -> ~17 uJy across its 0.33-1.05 um passband.
GAIA_LIMIT_UJY = 17.0
GAIA_RED_EDGE_UM = 1.05
BLEND_CUT_UM = 2.5


def _optical_blend_check(points: list[dict[str, Any]], gaia_rows: list[dict[str, Any]], gaia_queried: bool
                         ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """SPHEREx pixels are 6.2": the aperture blends neighbours. When Gaia was queried and found no
    optical source at the target, SPHEREx detections at <= 1.05 um brighter than 3x the Gaia limit
    cannot come from the target - they are a blended neighbour, which then also dominates the rest
    of the short-wavelength SPHEREx range. Those points (< 2.5 um) are left out of the SED.
    (WISE 0855: ~500 uJy at 0.75-1.3 um from a neighbour, while the Y dwarf is < 1 uJy there; at
    3.4 / 4.6 um SPHEREx agrees with WISE.)"""
    if not points or not gaia_queried or gaia_rows:
        return points, {}
    optical = sorted(p["flux_ujy"] for p in points if p["wavelength_um"] <= GAIA_RED_EDGE_UM)
    if not optical:
        return points, {}
    median = optical[len(optical) // 2]
    if median < 3.0 * GAIA_LIMIT_UJY:
        return points, {}
    kept = [p for p in points if p["wavelength_um"] >= BLEND_CUT_UM]
    return kept, {
        "blend_suspected": True,
        "dropped_short_wavelength_points": len(points) - len(kept),
        "blend_reason": (f"no Gaia DR3 source at the target, yet SPHEREx measures a median {median:.0f} uJy at "
                         f"<= {GAIA_RED_EDGE_UM} um (Gaia limit ~{GAIA_LIMIT_UJY:.0f} uJy): flux from a blended "
                         f"neighbour; SPHEREx points below {BLEND_CUT_UM} um left out of the SED"),
    }


def _spherex_sed_points(spec: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """SED points from a backend spectrum and a provenance note.

    Only real SPHEREx data count (pipeline.data_mode == "fits_archive"): the physical model is a
    prediction from the catalog class, not a measurement. Of those, only bands the backend measured
    (pipeline.measured; the rest are interpolated fill) with S/N >= SED_MIN_SNR."""
    if not spec:
        return [], {"status": "none"}
    pipe = spec.get("pipeline") if isinstance(spec.get("pipeline"), dict) else {}
    note: dict[str, Any] = {"epoch": spec.get("epoch"), "data_mode": pipe.get("data_mode"),
                            "observed_quarter": pipe.get("observed_quarter"),
                            "n_bands_measured": pipe.get("n_bands_measured"), "snr_median": spec.get("snr_median")}
    if pipe.get("data_mode") != "fits_archive":
        note.update(status="excluded: physical model (no real SPHEREx data at this position)", n_points=0)
        return [], note
    wls = spec.get("wavelength_um") or []
    flx = spec.get("flux_ujy") or []
    err = spec.get("flux_err_ujy") or []
    measured = pipe.get("measured")
    if not isinstance(measured, list) or len(measured) != len(flx):
        measured = [True] * len(flx)
    # Bands the backend found centred on a neighbour inside the aperture are not the target's light.
    blended = pipe.get("blended")
    if isinstance(blended, list) and len(blended) == len(flx):
        measured = [m is True and b is not True for m, b in zip(measured, blended)]
    pts = []
    for idx, (lam, f_val) in enumerate(zip(wls, flx)):
        try:
            lam_f, f_f = float(lam), float(f_val)
            e_f = float(err[idx]) if idx < len(err) else float("nan")
        except (TypeError, ValueError):
            continue
        if not (measured[idx] is True and math.isfinite(lam_f) and math.isfinite(f_f) and math.isfinite(e_f)):
            continue
        if lam_f <= 0.0 or e_f <= 0.0 or f_f / e_f < SED_MIN_SNR:
            continue
        pts.append({"wavelength_um": round(lam_f, 4), "flux_ujy": round(f_f, 4),
                    "flux_err_ujy": round(e_f, 4), "survey": "SPHEREx"})
    note.update(status="real", n_points=len(pts),
                rule=f"measured, unblended bands with S/N >= {SED_MIN_SNR:g} of the real-data epoch")
    if isinstance(pipe.get("n_bands_blended"), int):
        note["n_bands_blended"] = pipe["n_bands_blended"]
    return pts, note


def _build_sed(
    gaia_rows: list[dict[str, Any]],
    wise_rows: list[dict[str, Any]],
    spherex_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sed: list[dict[str, Any]] = list(spherex_points)

    if gaia_rows:
        g0 = gaia_rows[0]
        for col, lam_um, ab_off in GAIA_BANDS:
            val = g0.get(col)
            if val is not None:
                flux = vega_to_ujy(float(val), ab_off)
                sed.append(
                    {
                        "wavelength_um": round(lam_um, 4),
                        "flux_ujy": round(flux, 4),
                        "flux_err_ujy": round(flux * 0.02, 4),
                        "survey": "Gaia DR3",
                    }
                )

    if wise_rows:
        w0 = wise_rows[0]
        for col, err_col, lam_um, ab_off in WISE_BANDS:
            val = w0.get(col)
            if val is not None:
                flux = vega_to_ujy(float(val), ab_off)
                mag_err = float(w0.get(err_col) or 0.05)
                flux_err = flux * (math.log(10.0) * 0.4 * mag_err)
                sed.append(
                    {
                        "wavelength_um": round(lam_um, 4),
                        "flux_ujy": round(flux, 4),
                        "flux_err_ujy": round(flux_err, 4),
                        "survey": "WISE",
                    }
                )

    sed.sort(key=lambda item: item["wavelength_um"])
    return sed


def _query_live_archives(ra: float, dec: float, radius_arcsec: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Live Gaia DR3 + AllWISE + MAST queries (each bounded by a timeout). A failed archive yields an
    empty list and a 'failed' provenance entry - never substitute values."""
    prov: dict[str, Any] = {}
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("AEON_ENABLE_LIVE_ASTROQUERY") != "1":
        return [], [], [], {"live_queries": "disabled under pytest"}
    from .archives import ArchiveError, allwise_cone, gaia_cone, mast_overlap

    results: dict[str, list[dict[str, Any]]] = {}
    for key, fn, rad in (("gaia", gaia_cone, radius_arcsec), ("wise", allwise_cone, max(radius_arcsec, 3.0)),
                         ("mast", mast_overlap, max(radius_arcsec, 5.0))):
        try:
            rows, query = fn(ra, dec, rad)
            results[key] = rows
            prov[key] = {"status": "ok", "query": query}
        except ArchiveError as exc:
            results[key] = []
            prov[key] = {"status": f"failed: {exc}"}
    return results["gaia"][:1], results["wise"][:1], results["mast"], prov


CORE_ORBIT_TIMEOUT_S = float(os.environ.get("AEON_CORE_ORBIT_TIMEOUT_S", "20"))
DEGRADED_TTL_SEC = 1800.0      # a result missing SIMBAD or the orbit integrator is retried after 30 min


def _aeon_astrometry(ra: float, dec: float, gaia_rows: list[dict[str, Any]], matched: dict[str, Any]) -> dict[str, Any] | None:
    """The astrometry AEON's own chain has for the source, with the origin of every value.

    Gaia DR3 (parallax, proper motion, radial velocity when Gaia measured one) if the cross-match
    found the source with a parallax; otherwise the catalog entry the spectrum was matched to.
    No radial velocity is ever filled in."""
    g = gaia_rows[0] if gaia_rows else {}
    plx, pmra, pmdec = g.get("parallax_mas"), g.get("pmra_mas_yr"), g.get("pmdec_mas_yr")
    if isinstance(plx, (int, float)) and plx > 0 and pmra is not None and pmdec is not None:
        d = 1000.0 / float(plx)
        err = g.get("parallax_error_mas")
        rv = g.get("radial_velocity_km_s")
        return {
            "ra": float(g.get("ra") if g.get("ra") is not None else ra), "dec": float(g.get("dec") if g.get("dec") is not None else dec),
            "distance_pc": d, "distance_err_pc": d * float(err) / float(plx) if isinstance(err, (int, float)) else None,
            "distance_source": f"Gaia DR3 parallax (source {g.get('source_id')})",
            "pm_ra_cosdec_mas_yr": float(pmra), "pm_dec_mas_yr": float(pmdec), "pm_source": "Gaia DR3",
            "radial_velocity_km_s": float(rv) if isinstance(rv, (int, float)) else None,
            "rv_source": "Gaia DR3 radial_velocity" if isinstance(rv, (int, float)) else None,
        }
    d_pc = matched.get("distance_pc")
    pmr, pmd = matched.get("pm_ra_cosdec_arcsec_yr"), matched.get("pm_dec_arcsec_yr")
    if isinstance(d_pc, (int, float)) and d_pc > 0 and isinstance(pmr, (int, float)) and isinstance(pmd, (int, float)):
        src = f"AEON catalog entry {matched.get('id')}"
        return {"ra": ra, "dec": dec, "distance_pc": float(d_pc), "distance_err_pc": None, "distance_source": src,
                "pm_ra_cosdec_mas_yr": float(pmr) * 1000.0, "pm_dec_mas_yr": float(pmd) * 1000.0, "pm_source": src,
                "radial_velocity_km_s": None, "rv_source": None}
    return None


def _core_galactic_orbit(astro: dict[str, Any] | None) -> dict[str, Any] | None:
    """Galactic orbit and solar encounter from the core backend (galpy); None if it cannot answer."""
    need = ("ra", "dec", "distance_pc", "pm_ra_cosdec_mas_yr", "pm_dec_mas_yr")
    if not astro or any(not isinstance(astro.get(k), (int, float)) for k in need):
        return None
    core_url = os.environ.get("AEON_CORE_URL", "http://localhost:8000").rstrip("/")
    body = {"galactic": {k: astro[k] for k in need} | {"radial_velocity_km_s": astro.get("radial_velocity_km_s")}}
    try:
        with httpx.Client(timeout=CORE_ORBIT_TIMEOUT_S, verify=not core_url.startswith("http://")) as client:
            resp = client.post(f"{core_url}/api/v1/orbit/simulate", json=body)
            if resp.status_code != 200:
                return None
            gal = resp.json().get("galactic")
    except Exception:
        return None
    if not isinstance(gal, dict) or not isinstance(gal.get("summary"), dict):
        return None
    out = {k: gal.get(k) for k in ("engine", "potential", "rv_status", "rv_note", "span_myr", "encounter_window_kyr", "summary")}
    out["encounters"] = [{k: e.get(k) for k in ("rv_km_s", "status", "t_min_kyr", "d_min_pc")} for e in gal.get("encounters") or []]
    out["orbits"] = [{k: o.get(k) for k in ("rv_km_s", "r_peri_kpc", "r_apo_kpc", "z_max_kpc", "eccentricity")} for o in gal.get("orbits") or []]
    return out


def run_crossmatch(ra: float, dec: float, radius_arcsec: float = 6.0) -> dict[str, Any]:
    """Perform Gaia DR3 + WISE + MAST crossmatch with 24h disk cache and archival fixture fallback."""
    cache_key = hashlib.sha256(f"{ra:.5f}_{dec:.5f}_{radius_arcsec:.2f}".encode()).hexdigest()[:16]
    # "xm3_": results cached before the age / orbit / validation blocks existed are ignored
    cache_file = CACHE_DIR / f"xm3_{cache_key}.json"

    if not os.environ.get("PYTEST_CURRENT_TEST") and cache_file.is_file():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if time.time() - float(cached.get("_ts", 0)) < float(cached.pop("_ttl", CACHE_TTL_SEC)):
                cached.pop("_ts", None)
                return cached
        except Exception:
            pass

    fixture = _match_fixture(ra, dec)
    spherex_spec, spherex_status = _fetch_spherex_spectrum(ra, dec)
    spherex_points, spherex_note = _spherex_sed_points(spherex_spec)
    if spherex_status != "ok":
        spherex_note = {"status": "unavailable: the core backend did not answer"}

    if fixture is not None:
        gaia_rows = [dict(g) for g in fixture.get("gaia", [])]
        wise_rows = [dict(w) for w in fixture.get("wise", [])]
        mast_rows = [dict(m) for m in fixture.get("mast_overlap", [])]
        provenance = {"source": "archive snapshot built by scripts/build_fixtures.py", **fixture.get("provenance", {})}
    else:
        gaia_rows, wise_rows, mast_rows, live_prov = _query_live_archives(ra, dec, radius_arcsec)
        provenance = {"source": "live archive queries", **live_prov}

    gaia_queried = fixture is not None or str((provenance.get("gaia") or {}).get("status", "")) == "ok"
    spherex_points, blend_note = _optical_blend_check(spherex_points, gaia_rows, gaia_queried)
    if blend_note:
        spherex_note = {**spherex_note, **blend_note, "n_points": len(spherex_points)}
    provenance["spherex"] = spherex_note
    sed = _build_sed(gaia_rows, wise_rows, spherex_points)

    has_ir = bool(wise_rows) or bool(spherex_points)
    unmatched_ir = bool(has_ir and len(gaia_rows) == 0)

    parallax_mas = None
    if gaia_rows and gaia_rows[0].get("parallax_mas") is not None:
        parallax_mas = float(gaia_rows[0]["parallax_mas"])
    matched = (spherex_spec or {}).get("matched_object") or {}
    dist_au = matched.get("distance_au") if isinstance(matched.get("distance_au"), (int, float)) else None
    if dist_au is None and fixture and fixture.get("id") == "px-2026-09":
        dist_au = 520.0

    sed_physics = fit_multi_mission_sed(sed, distance_au=dist_au)
    kin = compute_kete_kbmod_kinematics(ra, dec, parallax_mas=parallax_mas, distance_au=dist_au)

    # Stage 2-4: space velocity, age and mass, Galactic orbit, validation against SIMBAD / literature.
    target_id = matched.get("id") or (fixture or {}).get("id")
    object_class = matched.get("object_class")
    solar_system = dist_au is not None or object_class == "planet_x_candidate"
    astro = None if solar_system else _aeon_astrometry(ra, dec, gaia_rows, matched)
    if solar_system:
        galactic = {"status": "not_applicable", "reason": "solar-system body: it orbits the Sun, not the Galactic centre"}
    else:
        galactic = kinematics.space_velocity(astro)
    kin["galactic"] = galactic
    ages = age_mass.estimate(sed=sed, sed_physics=sed_physics, gaia_rows=gaia_rows, wise_rows=wise_rows,
                             spherex_points=spherex_points, astrometry=astro or {}, galactic=galactic,
                             object_class=object_class, distance_au=dist_au if solar_system else None)
    extragalactic = object_class == "high_z_galaxy"
    core_up = spherex_status == "ok"          # a core backend that did not answer the spectrum is not asked again
    orbit = _core_galactic_orbit(astro) if core_up and not (solar_system or extragalactic) else None
    if solar_system:
        galactic_orbit: dict[str, Any] = {"status": "not_applicable", "regime": "solar_system",
                                          "reason": "solar-system body: use the heliocentric REBOUND orbit (/api/v1/orbit/simulate)"}
        checks: dict[str, Any] = {"status": "not_applicable", "reason": "solar-system candidate: no stellar reference to compare with"}
    elif extragalactic:
        galactic_orbit = {"status": "not_applicable", "reason": "extragalactic source: no orbit in the Milky Way"}
        checks = {"status": "not_applicable", "reason": "extragalactic source: the stellar age / orbit chain does not apply"}
    else:
        if orbit is not None:
            galactic_orbit = {"status": "ok", "regime": "galactic", **orbit}
        elif galactic.get("status") == "ok":
            galactic_orbit = {"status": "unavailable", "regime": "galactic", "reason": "the orbit integrator (core backend) did not answer"}
        else:
            galactic_orbit = {"status": "unmeasured", "regime": "galactic", "reason": galactic.get("reason")}
        checks = validation.build(target_id=target_id, name=matched.get("name") or (fixture or {}).get("name"), ra=ra, dec=dec,
                                  aeon_astrometry=astro, aeon_galactic=galactic, age_mass=ages, aeon_orbit=orbit,
                                  spherex_note=spherex_note,
                                  orbit_fn=_core_galactic_orbit if core_up else (lambda _a: None))

    result: dict[str, Any] = {
        "gaia": gaia_rows,
        "wise": wise_rows,
        "sed": sed,
        "unmatched_ir_candidate": unmatched_ir,
        "mast_overlap": mast_rows,
        "provenance": provenance,
        "sed_physics": sed_physics,
        "kinematics": kin,
        "age_mass": ages,
        "galactic_orbit": galactic_orbit,
        "validation": checks,
    }

    if not os.environ.get("PYTEST_CURRENT_TEST") and spherex_status == "ok":   # never keep a degraded answer
        degraded = galactic_orbit.get("status") == "unavailable" or (checks.get("simbad") or {}).get("status") == "unavailable"
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            to_save = dict(result, _ts=time.time(), _ttl=DEGRADED_TTL_SEC if degraded else CACHE_TTL_SEC)
            cache_file.write_text(json.dumps(to_save, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    return result
