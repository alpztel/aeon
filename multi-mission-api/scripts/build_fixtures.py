"""Rebuild fixtures/crossmatch_fixtures.json from live archive queries (no hand-entered values).

Positions and proper motions mirror backend/aeon/catalog.py. Search positions are propagated to each
catalogue's epoch (Gaia DR3 J2016.0, AllWISE J2010.5) so high-proper-motion stars are found. Rows are
stored exactly as the archives return them, with the query text and UTC timestamp. A query that fails
is recorded as failed with an empty row list. PX-2026-09 is synthetic and is never queried.

Usage:  python scripts/build_fixtures.py               # all targets
        python scripts/build_fixtures.py rw-aur        # refresh only the named targets
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.archives import ArchiveError, allwise_cone, gaia_cone, mast_overlap, propagate  # noqa: E402

# id: (name, ra, dec, ref_epoch, pm_ra_cosdec ["/yr], pm_dec ["/yr]). Luhman 16 and 18 Sco use the
# designation position / SIMBAD proper motion (backend catalog corrected to match).
TARGETS = {
    "wise-0855": ("WISE J085510.83-071442.5", 133.79513, -7.24514, 2010.5, -8.118, 0.680),
    "rw-aur": ("RW Aurigae", 76.95642, 30.40142, 2016.0, 0.0, 0.0),
    "luhman-16": ("WISE J104915.57-531906.1", 162.31488, -53.31836, 2010.5, -2.759, 0.354),  # designation position
    "wise-1828": ("WISEPA J182831.08+265037.8", 277.12950, 26.84383, 2010.5, 1.020, 0.174),
    "barnard": ("Barnard's Star", 269.45208, 4.69339, 2000.0, -0.798, 10.328),
    "tw-hya": ("TW Hydrae", 165.46587, -34.70473, 2016.0, 0.0, 0.0),
    "18-sco": ("18 Scorpii", 243.90529, -8.36944, 2000.0, 0.2322, -0.4952),
}
RADIUS_GAIA = 5.0
RADIUS_WISE = 6.0
RADIUS_MAST = 10.0


def run(fn, *args, **kw):
    """Up to 4 attempts with a generous timeout; a persistent failure is recorded, never filled in."""
    import time
    err = None
    for attempt in range(4):
        try:
            rows, q = fn(*args, **kw)
            return {"rows": rows, "query": q, "status": "ok"}
        except ArchiveError as exc:
            err = exc
            time.sleep(3 * (attempt + 1))
    return {"rows": [], "query": None, "status": f"failed: {err}"}


def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = ROOT / "fixtures" / "crossmatch_fixtures.json"
    only = set(sys.argv[1:])
    if only and path.is_file():
        out = json.loads(path.read_text(encoding="utf-8"))
        out["metadata"]["refreshed_utc"] = now
    else:
        out = {"metadata": {"built_utc": now, "builder": "multi-mission-api/scripts/build_fixtures.py",
                            "sources": ["ESA Gaia DR3 TAP", "NASA/IPAC IRSA AllWISE TAP", "STScI MAST CAOM"]},
               "targets": {}}
    for tid, (name, ra, dec, ep, pmr, pmd) in TARGETS.items():
        if only and tid not in only:
            continue
        g_ra, g_dec = propagate(ra, dec, pmr, pmd, 2016.0 - ep)
        w_ra, w_dec = propagate(ra, dec, pmr, pmd, 2010.5 - ep)
        m_ra, m_dec = propagate(ra, dec, pmr, pmd, 2020.0 - ep)
        a_ra, a_dec = propagate(ra, dec, pmr, pmd, 2026.5 - ep)
        gaia = run(gaia_cone, g_ra, g_dec, RADIUS_GAIA, timeout=40.0)
        wise = run(allwise_cone, w_ra, w_dec, RADIUS_WISE, timeout=60.0)
        mast = run(mast_overlap, m_ra, m_dec, RADIUS_MAST)
        out["targets"][tid] = {
            "id": tid, "name": name, "ra_ref": ra, "dec_ref": dec, "ra_2026": round(a_ra, 7), "dec_2026": round(a_dec, 7),
            "match_radius_deg": 0.08, "is_synthetic": False,
            "gaia": gaia["rows"][:1], "wise": wise["rows"][:1], "mast_overlap": mast["rows"],
            "provenance": {"queried_utc": now,
                           "gaia": {"status": gaia["status"], "query": gaia["query"], "search_epoch": 2016.0},
                           "wise": {"status": wise["status"], "query": wise["query"], "search_epoch": 2010.5},
                           "mast": {"status": mast["status"], "query": mast["query"]}},
        }
        print(f"{tid:10s} gaia={gaia['status']}:{len(gaia['rows'])} wise={wise['status']}:{len(wise['rows'])} mast={mast['status']}:{len(mast['rows'])}")
    out["targets"]["px-2026-09"] = {
        "id": "px-2026-09", "name": "PX-2026-09 (synthetic test candidate)", "ra_ref": 51.2, "dec_ref": 14.8,
        "ra_2026": 51.295473, "dec_2026": 14.8325559, "match_radius_deg": 0.2, "is_synthetic": True,
        "gaia": [], "wise": [], "mast_overlap": [],
        "provenance": {"note": "Injected synthetic object; it does not exist on the sky, so no archive is queried."},
    }
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", path)


if __name__ == "__main__":
    main()
