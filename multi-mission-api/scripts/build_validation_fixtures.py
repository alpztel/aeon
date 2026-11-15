"""Snapshot the SIMBAD row of every target in fixtures/validation_reference.json.

SIMBAD's own values and bibcodes are stored unchanged, so the validation scorecard still has its
reference when SIMBAD is unreachable. Run when SIMBAD is up:  python scripts/build_validation_fixtures.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import simbad  # noqa: E402

PATH = Path(__file__).resolve().parents[1] / "fixtures" / "validation_reference.json"


def main() -> int:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    done = 0
    for tid, target in data["targets"].items():
        try:
            row = simbad.query_identifier(target["simbad_id"])
        except simbad.SimbadError as exc:
            print(f"{tid}: SIMBAD unreachable ({exc}); snapshot left as it was")
            continue
        utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        target["simbad_snapshot"] = ({"row": row, "retrieved_utc": utc, "server": simbad._last_server.get("url")}
                                     if row else None)
        done += row is not None
        print(f"{tid}: {row['main_id'] if row else 'not found'}")
        time.sleep(1.0)
    if done:
        data["metadata"]["simbad_built_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data["metadata"]["simbad_status"] = f"{done} of {len(data['targets'])} targets snapshotted"
        PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
