"""SIMBAD (CDS, Strasbourg) reference data for the validation scorecard.

One TAP query per object: the `basic` row found through an identifier, or the nearest object in a
cone. The values returned are SIMBAD's own, with SIMBAD's bibcodes.

Servers, tried in order until one answers: CDS Strasbourg, then the official SIMBAD mirror at the
Harvard-Smithsonian CfA (same database, same TAP service). AEON_SIMBAD_TAP replaces the list
(comma-separated URLs ending in /sync).

Order of sources:
  1. a live query (cached on disk for 24 h),
  2. the snapshot in fixtures/validation_reference.json (built by scripts/build_validation_fixtures.py),
  3. nothing: status "unavailable" - no value is substituted.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import time
from pathlib import Path
from typing import Any

import httpx

DEFAULT_SERVERS = (
    "https://simbad.cds.unistra.fr/simbad/sim-tap/sync",      # CDS, Strasbourg
    "https://simbad.cfa.harvard.edu/simbad/sim-tap/sync",     # official mirror, Harvard-Smithsonian CfA
)
SIMBAD_SERVERS = tuple(u.strip() for u in os.environ.get("AEON_SIMBAD_TAP", ",".join(DEFAULT_SERVERS)).split(",") if u.strip())
SIMBAD_TAP = SIMBAD_SERVERS[0]
TIMEOUT_S = float(os.environ.get("AEON_SIMBAD_TIMEOUT_S", "8"))
CACHE_TTL_SEC = 86400.0
FIELDS = ("main_id", "otype", "sp_type", "sp_bibcode", "ra", "dec", "plx_value", "plx_err", "plx_bibcode",
          "pmra", "pmdec", "pm_bibcode", "rvz_radvel", "rvz_err", "rvz_type", "rvz_bibcode")
NUMERIC = ("ra", "dec", "plx_value", "plx_err", "pmra", "pmdec", "rvz_radvel", "rvz_err")


class SimbadError(RuntimeError):
    pass


def _cache_dir() -> Path:
    return Path(os.environ.get("AEON_CACHE_DIR", str(Path(__file__).resolve().parents[1] / ".cache_crossmatch")))


def _num(v: Any) -> float | None:
    try:
        x = float(v) if v not in (None, "", "null", "NaN") else None
    except (TypeError, ValueError):
        return None
    return x if x is not None and math.isfinite(x) else None


_last_server: dict[str, str] = {}


def _tap(query: str) -> list[dict[str, str]]:
    """Run the query on the first SIMBAD server that answers with a table."""
    errors = []
    for url in SIMBAD_SERVERS:
        try:
            r = httpx.post(url, data={"request": "doQuery", "lang": "adql", "format": "csv", "query": query},
                           timeout=TIMEOUT_S)
        except httpx.HTTPError as exc:
            errors.append(f"{_host(url)}: {type(exc).__name__}")
            continue
        if r.status_code != 200 or r.text.lstrip().startswith("<"):
            errors.append(f"{_host(url)}: HTTP {r.status_code}")
            continue
        _last_server["url"] = url
        return list(csv.DictReader(io.StringIO(r.text)))
    raise SimbadError("; ".join(errors) or "no SIMBAD server configured")


def _host(url: str) -> str:
    return url.split("/")[2] if "//" in url else url


def _row(raw: dict[str, str], query: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in FIELDS:
        v = raw.get(k)
        if isinstance(v, str):
            v = v.strip().strip('"')
        out[k] = _num(v) if k in NUMERIC else (v or None)
    out["query"] = query
    return out


def query_identifier(identifier: str) -> dict[str, Any] | None:
    ident = identifier.replace("'", "''")
    q = f"SELECT TOP 1 b.* FROM basic AS b JOIN ident AS i ON i.oidref = b.oid WHERE i.id = '{ident}'"
    rows = _tap(q)
    return _row(rows[0], q) if rows else None


def query_cone(ra: float, dec: float, radius_arcsec: float) -> dict[str, Any] | None:
    q = (f"SELECT TOP 1 b.*, DISTANCE(POINT('ICRS', b.ra, b.dec), POINT('ICRS', {ra:.7f}, {dec:.7f})) AS sep "
         f"FROM basic AS b WHERE CONTAINS(POINT('ICRS', b.ra, b.dec), CIRCLE('ICRS', {ra:.7f}, {dec:.7f}, "
         f"{radius_arcsec / 3600.0:.8f})) = 1 ORDER BY sep")
    rows = _tap(q)
    return _row(rows[0], q) if rows else None


def lookup(identifier: str | None, ra: float, dec: float, snapshot: dict[str, Any] | None = None,
           radius_arcsec: float = 5.0) -> dict[str, Any]:
    """{"status": "live" | "cached" | "snapshot" | "not_found" | "unavailable", "row": ..., "source": ...}"""
    key = hashlib.sha256(f"{identifier}|{ra:.5f}|{dec:.5f}".encode()).hexdigest()[:16]
    cache_file = _cache_dir() / f"simbad_{key}.json"
    testing = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    if not testing and cache_file.is_file():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if time.time() - float(cached.get("_ts", 0)) < CACHE_TTL_SEC:
                return {"status": "cached", "row": cached["row"], "source": "SIMBAD TAP (cached)", "retrieved_utc": cached.get("utc")}
        except Exception:
            pass
    if testing and os.environ.get("AEON_ENABLE_LIVE_SIMBAD") != "1":
        err: str | None = "live SIMBAD queries are disabled under pytest"
    else:
        err = None
        try:
            row = query_identifier(identifier) if identifier else None
            if row is None:
                row = query_cone(ra, dec, radius_arcsec)
            utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if row is None:
                return {"status": "not_found", "row": None, "source": "SIMBAD TAP", "retrieved_utc": utc}
            if not testing:
                try:
                    _cache_dir().mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps({"_ts": time.time(), "utc": utc, "row": row}), encoding="utf-8")
                except Exception:
                    pass
            return {"status": "live", "row": row, "source": f"SIMBAD TAP ({_host(_last_server.get('url', SIMBAD_TAP))})",
                    "retrieved_utc": utc}
        except SimbadError as exc:
            err = f"SIMBAD did not answer ({exc})"
        except Exception as exc:  # a malformed answer is an outage too, never a guess
            err = f"SIMBAD answer unusable ({type(exc).__name__})"
    if snapshot:
        return {"status": "snapshot", "row": snapshot.get("row", snapshot), "source": "SIMBAD snapshot (fixtures)",
                "retrieved_utc": snapshot.get("retrieved_utc"), "live_error": err}
    return {"status": "unavailable", "row": None, "source": "SIMBAD TAP", "reason": err}


def astrometry(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """SIMBAD row -> the astrometry record kinematics.space_velocity expects (None if not enough)."""
    if not row or not row.get("plx_value") or row["plx_value"] <= 0 or row.get("pmra") is None or row.get("pmdec") is None:
        return None
    d = 1000.0 / row["plx_value"]
    return {
        "ra": row["ra"], "dec": row["dec"], "distance_pc": d,
        "distance_err_pc": d * row["plx_err"] / row["plx_value"] if row.get("plx_err") else None,
        "distance_source": f"SIMBAD parallax ({row.get('plx_bibcode') or 'no bibcode'})",
        "pm_ra_cosdec_mas_yr": row["pmra"], "pm_dec_mas_yr": row["pmdec"],
        "pm_source": f"SIMBAD ({row.get('pm_bibcode') or 'no bibcode'})",
        "radial_velocity_km_s": row.get("rvz_radvel") if row.get("rvz_type") in (None, "v") else None,
        "rv_source": f"SIMBAD ({row.get('rvz_bibcode') or 'no bibcode'})" if row.get("rvz_radvel") is not None else None,
    }
