"""Live archive queries: ESA Gaia DR3 (TAP), NASA/IPAC IRSA AllWISE (TAP) and STScI MAST (CAOM).

Every function returns the archive's own rows (no edits) plus the exact query that produced them, or
raises ArchiveError. Callers decide how to degrade; nothing here invents values.

Epochs: Gaia DR3 positions are J2016.0, AllWISE ~J2010.5. A caller that knows a source's proper
motion should propagate the search position to those epochs (see `propagate`); otherwise
high-proper-motion stars can fall outside a small search radius.
"""

from __future__ import annotations

import csv
import io
import math
from typing import Any

import httpx

GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
IRSA_TAP = "https://irsa.ipac.caltech.edu/TAP/sync"
TIMEOUT_S = 8.0


class ArchiveError(RuntimeError):
    pass


def propagate(ra: float, dec: float, pm_ra_cosdec_as_yr: float, pm_dec_as_yr: float, dt_yr: float) -> tuple[float, float]:
    """Linear proper-motion propagation (arcsec/yr) by dt years."""
    d = dec + pm_dec_as_yr * dt_yr / 3600.0
    r = ra + pm_ra_cosdec_as_yr * dt_yr / 3600.0 / max(math.cos(math.radians(dec)), 1e-9)
    return r % 360.0, d


def _tap_csv(url: str, query: str, extra: dict[str, str] | None = None, timeout: float = TIMEOUT_S) -> list[dict[str, str]]:
    params = {"QUERY": query, "FORMAT": "csv", **(extra or {})}
    try:
        r = httpx.get(url, params=params, timeout=timeout)
    except httpx.HTTPError as exc:
        raise ArchiveError(f"{url}: {type(exc).__name__}") from exc
    if r.status_code != 200 or r.text.lstrip().startswith("<"):
        raise ArchiveError(f"{url}: HTTP {r.status_code}")
    return list(csv.DictReader(io.StringIO(r.text)))


def _num(v: str | None) -> float | None:
    try:
        x = float(v) if v not in (None, "", "null", "NaN") else None
    except ValueError:
        return None
    return x if x is not None and math.isfinite(x) else None


def gaia_cone(ra: float, dec: float, radius_arcsec: float, top: int = 5, timeout: float = TIMEOUT_S) -> tuple[list[dict[str, Any]], str]:
    q = (
        f"SELECT TOP {int(top)} source_id, ra, dec, parallax, parallax_error, pmra, pmdec, radial_velocity, "
        f"radial_velocity_error, phot_g_mean_mag, phot_bp_mean_mag, "
        f"phot_rp_mean_mag, DISTANCE(POINT(ra, dec), POINT({ra:.7f}, {dec:.7f})) * 3600 AS sep_arcsec "
        f"FROM gaiadr3.gaia_source WHERE 1 = CONTAINS(POINT(ra, dec), CIRCLE({ra:.7f}, {dec:.7f}, {radius_arcsec / 3600.0:.8f})) "
        f"ORDER BY sep_arcsec"
    )
    rows = _tap_csv(GAIA_TAP, q, {"REQUEST": "doQuery", "LANG": "ADQL"}, timeout)
    out = []
    for r in rows:
        out.append({
            "source_id": r["source_id"], "ra": _num(r["ra"]), "dec": _num(r["dec"]),
            "phot_g_mean_mag": _num(r["phot_g_mean_mag"]), "phot_bp_mean_mag": _num(r["phot_bp_mean_mag"]),
            "phot_rp_mean_mag": _num(r["phot_rp_mean_mag"]), "parallax_mas": _num(r["parallax"]),
            "parallax_error_mas": _num(r.get("parallax_error")),
            "pmra_mas_yr": _num(r["pmra"]), "pmdec_mas_yr": _num(r["pmdec"]),
            "radial_velocity_km_s": _num(r.get("radial_velocity")),
            "radial_velocity_error_km_s": _num(r.get("radial_velocity_error")),
            "sep_arcsec": _num(r["sep_arcsec"]), "catalog": "Gaia DR3 (J2016.0)",
        })
    return out, q


def allwise_cone(ra: float, dec: float, radius_arcsec: float, top: int = 5, timeout: float = TIMEOUT_S) -> tuple[list[dict[str, Any]], str]:
    q = (
        f"SELECT TOP {int(top)} designation, ra, dec, w1mpro, w1sigmpro, w2mpro, w2sigmpro, w3mpro, w3sigmpro, "
        f"w4mpro, w4sigmpro, cc_flags FROM allwise_p3as_psd "
        f"WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.7f}, {dec:.7f}, {radius_arcsec / 3600.0:.8f})) = 1"
    )
    rows = _tap_csv(IRSA_TAP, q, None, timeout)
    out = []
    for r in rows:
        row = {"designation": "J" + r["designation"].strip().lstrip("J"), "ra": _num(r["ra"]), "dec": _num(r["dec"]),
               "cc_flags": (r.get("cc_flags") or "").strip(), "catalog": "AllWISE (J2010.5)"}
        for b in ("w1", "w2", "w3", "w4"):
            row[f"{b}mpro"] = _num(r[f"{b}mpro"])
            row[f"{b}sigmpro"] = _num(r[f"{b}sigmpro"])
        out.append(row)
    return out, q


def mast_overlap(ra: float, dec: float, radius_arcsec: float, limit: int = 4) -> tuple[list[dict[str, Any]], str]:
    """JWST/HST science observations covering the position (MAST CAOM), with real preview images."""
    query = f"astroquery.mast.Observations.query_region('{ra:.6f} {dec:.6f}', radius='{radius_arcsec:.1f} arcsec')"
    try:
        from astroquery.mast import Observations
    except Exception as exc:  # pragma: no cover - dependency missing
        raise ArchiveError(f"astroquery unavailable: {exc}") from exc
    try:
        tbl = Observations.query_region(f"{ra} {dec}", radius=f"{radius_arcsec} arcsec")
    except Exception as exc:
        raise ArchiveError(f"MAST: {type(exc).__name__}") from exc
    out: list[dict[str, Any]] = []
    for row in tbl:
        coll = str(row["obs_collection"])
        if coll not in ("JWST", "HST") or str(row["intentType"]) != "science":
            continue
        jpeg = str(row["jpegURL"]) if row["jpegURL"] not in (None, "") and str(row["jpegURL"]) != "--" else ""
        if jpeg.startswith("mast:"):
            jpeg = f"https://mast.stsci.edu/api/v0.1/Download/file?uri={jpeg}"
        out.append({
            "mission": coll, "obs_id": str(row["obs_id"]), "instrument": str(row["instrument_name"]),
            "filter": str(row["filters"]),
            "preview_url": jpeg or f"https://mast.stsci.edu/portal/Mashup/Clients/Mast/Portal.html?searchQuery={ra:.5f}%20{dec:.5f}",
            "has_preview_image": bool(jpeg),
        })
    out.sort(key=lambda o: (not o["has_preview_image"], o["mission"] != "JWST"))
    return out[:limit], query
