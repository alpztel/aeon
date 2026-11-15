"""Add Gaia DR3 radial velocities / parallax errors to the cross-match snapshot, and snapshot three
more catalog targets, from the NOIRLab Astro Data Lab copies of Gaia DR3 and AllWISE.

Used when the ESA Gaia and IRSA TAP services that scripts/build_fixtures.py queries are down. Rows
are the archive's own values; nothing is edited. Run:  python scripts/extend_fixtures_datalab.py
"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
import time
from pathlib import Path

import httpx

TAP = "https://datalab.noirlab.edu/tap/sync"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "crossmatch_fixtures.json"
ALLWISE_EPOCH, GAIA_EPOCH = 2010.55, 2016.0

# id: (name, Gaia DR3 position J2016, used to find the source again)
NEW_TARGETS = {
    "trappist-1": ("TRAPPIST-1", 346.6265216, -5.0435283),
    "lhs-1140": ("LHS 1140", 11.2486779, -15.2741913),
}


def tap(query: str, tries: int = 6) -> list[dict[str, str]]:
    err: Exception | None = None
    for _ in range(tries):
        try:
            r = httpx.post(TAP, data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}, timeout=120)
            r.raise_for_status()
            if r.text.lstrip().startswith("<"):
                raise RuntimeError(r.text[:200])
            return list(csv.DictReader(io.StringIO(r.text)))
        except Exception as exc:  # noqa: BLE001
            err = exc
            time.sleep(8)
    raise RuntimeError(f"Data Lab TAP failed: {err}")


def num(v: str | None) -> float | None:
    try:
        x = float(v) if v not in (None, "", "null", "NaN", "nan") else None
    except ValueError:
        return None
    return x if x is not None and math.isfinite(x) else None


def box(ra: float, dec: float, half_arcsec: float) -> str:
    dra = half_arcsec / 3600.0 / max(math.cos(math.radians(dec)), 0.05)
    dd = half_arcsec / 3600.0
    return f"ra BETWEEN {ra - dra} AND {ra + dra} AND dec BETWEEN {dec - dd} AND {dec + dd}"


GAIA_COLS = ("source_id, ra, dec, parallax, parallax_error, pmra, pmdec, phot_g_mean_mag, phot_bp_mean_mag, "
             "phot_rp_mean_mag, radial_velocity, radial_velocity_error")


def gaia_row(r: dict[str, str]) -> dict:
    return {"source_id": r["source_id"], "ra": num(r["ra"]), "dec": num(r["dec"]),
            "phot_g_mean_mag": num(r["phot_g_mean_mag"]), "phot_bp_mean_mag": num(r["phot_bp_mean_mag"]),
            "phot_rp_mean_mag": num(r["phot_rp_mean_mag"]), "parallax_mas": num(r["parallax"]),
            "parallax_error_mas": num(r["parallax_error"]), "pmra_mas_yr": num(r["pmra"]), "pmdec_mas_yr": num(r["pmdec"]),
            "radial_velocity_km_s": num(r["radial_velocity"]), "radial_velocity_error_km_s": num(r["radial_velocity_error"]),
            "catalog": "Gaia DR3 (J2016.0)"}


def main() -> int:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    targets = data["targets"]
    # 1) radial velocity and parallax error for the Gaia rows already in the snapshot
    for tid, t in targets.items():
        for g in t.get("gaia", []):
            rows = tap(f"SELECT {GAIA_COLS} FROM gaia_dr3.gaia_source WHERE source_id = {g['source_id']}")
            if not rows:
                print(f"{tid}: source {g['source_id']} not found", flush=True)
                continue
            new = gaia_row(rows[0])
            for k in ("parallax_error_mas", "radial_velocity_km_s", "radial_velocity_error_km_s"):
                g[k] = new[k]
            print(f"{tid}: RV = {g['radial_velocity_km_s']} +/- {g['radial_velocity_error_km_s']} km/s, "
                  f"parallax error {g['parallax_error_mas']} mas", flush=True)
    # 2) new targets
    for tid, (name, ra, dec) in NEW_TARGETS.items():
        rows = tap(f"SELECT {GAIA_COLS} FROM gaia_dr3.gaia_source WHERE {box(ra, dec, 3)}")
        rows = [r for r in rows if num(r["parallax"]) and num(r["parallax"]) > 50]
        if len(rows) != 1:
            print(f"{tid}: {len(rows)} Gaia candidates, skipped", flush=True)
            continue
        g = gaia_row(rows[0])
        dt = ALLWISE_EPOCH - GAIA_EPOCH
        ra_w = g["ra"] + g["pmra_mas_yr"] / 1000.0 * dt / 3600.0 / math.cos(math.radians(g["dec"]))
        dec_w = g["dec"] + g["pmdec_mas_yr"] / 1000.0 * dt / 3600.0
        aw = tap("SELECT designation, ra, dec, w1mpro, w1sigmpro, w2mpro, w2sigmpro, w3mpro, w3sigmpro, w4mpro, w4sigmpro, "
                 f"cc_flags FROM allwise.source WHERE {box(ra_w, dec_w, 4)}")
        wise = []
        if aw:
            best = min(aw, key=lambda r: math.hypot((num(r["ra"]) - ra_w) * math.cos(math.radians(dec_w)), num(r["dec"]) - dec_w))
            row = {"designation": "J" + best["designation"].strip().lstrip("J"), "ra": num(best["ra"]), "dec": num(best["dec"]),
                   "cc_flags": (best.get("cc_flags") or "").strip(), "catalog": "AllWISE (J2010.5)"}
            for b in ("w1", "w2", "w3", "w4"):
                row[f"{b}mpro"], row[f"{b}sigmpro"] = num(best[f"{b}mpro"]), num(best[f"{b}sigmpro"])
            wise = [row]
        dt26 = 2026.5 - GAIA_EPOCH
        targets[tid] = {
            "id": tid, "name": name, "ra_ref": g["ra"], "dec_ref": g["dec"],
            "ra_2026": round(g["ra"] + g["pmra_mas_yr"] / 1000.0 * dt26 / 3600.0 / math.cos(math.radians(g["dec"])), 7),
            "dec_2026": round(g["dec"] + g["pmdec_mas_yr"] / 1000.0 * dt26 / 3600.0, 7),
            "match_radius_deg": 0.02, "is_synthetic": False, "gaia": [g], "wise": wise, "mast_overlap": [],
            "provenance": {"gaia": {"status": "ok", "query": "gaia_dr3.gaia_source, NOIRLab Astro Data Lab TAP"},
                           "wise": {"status": "ok" if wise else "no source", "query": "allwise.source, NOIRLab Astro Data Lab TAP"},
                           "mast": {"status": "not queried"}},
        }
        print(f"{tid}: Gaia {g['source_id']} plx {g['parallax_mas']} RV {g['radial_velocity_km_s']}; "
              f"AllWISE {wise[0]['designation'] if wise else None} W2 {wise[0]['w2mpro'] if wise else None}", flush=True)
    meta = data["metadata"]
    meta["extended_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    meta["extension"] = ("multi-mission-api/scripts/extend_fixtures_datalab.py: Gaia DR3 radial velocities, parallax "
                         "errors and two more targets from the NOIRLab Astro Data Lab copies of Gaia DR3 / AllWISE")
    if "NOIRLab Astro Data Lab TAP (Gaia DR3, AllWISE copies)" not in meta["sources"]:
        meta["sources"].append("NOIRLab Astro Data Lab TAP (Gaia DR3, AllWISE copies)")
    FIXTURES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
