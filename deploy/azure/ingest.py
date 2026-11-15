"""AEON scheduled data ingest for an Azure VM.

One run:
  1. SPHEREx  — for every target, list the SPHEREx Level 2 spectral images that cover it (IRSA SIA,
                collections spherex_dr1 / spherex_qr3) and download small cutouts through the IRSA
                cutout service. Reuses backend/aeon/irsa.py, so files land exactly where the backend
                reads them: $DATA/spherex/<collection>/<tag>/*.fits + manifest.json. Already
                downloaded frames are skipped, so a weekly run only fetches the new week.
     (opt.)  --full N: also download N complete MEF files per target from the public AWS S3 copy
                (bucket nasa-irsa-spherex, no credentials, no egress fee), falling back to IRSA.
  2. Gaia DR3 — cone search around every target through MAST (astroquery.mast), falling back to the
                ESA Gaia TAP service. Saved as $DATA/catalogs/gaia_dr3/<tag>.json with provenance.
  3. Azure Blob — optional: upload new or changed files with the VM's managed identity
                (no keys or passwords anywhere).
  4. A run report: $DATA/runs/<UTC timestamp>.json.

Run:  python deploy/azure/ingest.py --data-dir /data/aeon [--blob-account-url https://<acct>.blob.core.windows.net]
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from aeon import irsa  # noqa: E402  (backend package, same repository)

S3_BUCKET_URL = "https://nasa-irsa-spherex.s3.amazonaws.com"
IBE_MARKER = "/ibe/data/spherex/"
ESA_GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
GAIA_COLUMNS = ("source_id", "ra", "dec", "parallax", "parallax_error", "pmra", "pmdec",
                "phot_g_mean_mag", "phot_bp_mean_mag", "phot_rp_mean_mag", "ruwe")
USER_AGENT = irsa.USER_AGENT.replace("AEON-backend", "AEON-azure-ingest")

Log = Callable[[str], None]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def decimal_year(now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    return now.year + (now - start).total_seconds() / (end - start).total_seconds()


# ---------------------------------------------------------------------------------------------
# targets
# ---------------------------------------------------------------------------------------------

def load_targets(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    targets = data["targets"] if isinstance(data, dict) else data
    out = []
    for t in targets:
        if "catalog_id" not in t and not ("ra" in t and "dec" in t):
            raise ValueError(f"target needs 'catalog_id' or 'ra'+'dec': {t}")
        if "ra" in t and not (0.0 <= float(t["ra"]) <= 360.0 and -90.0 <= float(t["dec"]) <= 90.0):
            raise ValueError(f"target outside ICRS range: {t}")
        out.append(t)
    return out


def resolve(target: dict[str, Any], t_year: float) -> tuple[str, float, float, str]:
    """(tag, ra, dec, note) — catalog targets are propagated to the run date (proper motion)."""
    if "catalog_id" in target:
        ra, dec, note = irsa.demo_position(target["catalog_id"], t_year)
        return target.get("tag", target["catalog_id"]), ra, dec, note
    ra, dec = float(target["ra"]), float(target["dec"])
    return target.get("tag", f"ra{ra:.4f}_dec{dec:+.4f}"), ra, dec, target.get("note", "user target")


# ---------------------------------------------------------------------------------------------
# SPHEREx
# ---------------------------------------------------------------------------------------------

def s3_url(access_url: str) -> str | None:
    """IRSA IBE file URL -> public S3 object URL (IRSA: S3 key = release prefix + browsable path)."""
    path = urllib.parse.urlparse(access_url).path
    if IBE_MARKER not in path:
        return None
    return f"{S3_BUCKET_URL}/{path.split(IBE_MARKER, 1)[1]}"


def download(url: str, dest: Path, timeout: float = 300.0, max_bytes: int = 200_000_000) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    n = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as fh:
        while chunk := resp.read(1 << 20):
            n += len(chunk)
            if n > max_bytes:
                raise ValueError(f"larger than {max_bytes / 1e6:.0f} MB")
            fh.write(chunk)
    os.replace(tmp, dest)
    return n


def fetch_full_files(ra: float, dec: float, tag: str, collection: str, data_dir: Path, n: int, log: Log) -> list[dict]:
    """Download n complete spectral images (spread over time) — S3 first, IRSA as fallback."""
    recs = irsa._spread(irsa.query(ra, dec, 0.5, collection), n)
    out_dir = data_dir / "spherex_full" / collection / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for rec in recs:
        dest = out_dir / rec.filename
        if dest.exists() and dest.stat().st_size > 0:
            results.append({"file": rec.filename, "status": "cached"})
            continue
        for source, url in (("s3", s3_url(rec.access_url)), ("irsa", rec.access_url)):
            if not url:
                continue
            try:
                size = download(url, dest)
                results.append({"file": rec.filename, "status": "downloaded", "source": source, "bytes": size})
                break
            except (urllib.error.URLError, OSError, ValueError) as exc:
                log(f"[full] {rec.filename} via {source}: {exc}")
        else:
            results.append({"file": rec.filename, "status": "error"})
    return results


def ingest_spherex(targets: list[dict], data_dir: Path, collections: list[str], size_px: int,
                   radius_arcmin: float, max_files: int | None, full: int, t_year: float, log: Log) -> list[dict]:
    summary = []
    for t in targets:
        tag, ra, dec, note = resolve(t, t_year)
        for coll in collections:
            entry: dict[str, Any] = {"target": tag, "collection": coll, "ra": ra, "dec": dec}
            try:
                m = irsa.fetch(ra, dec, radius_arcmin=radius_arcmin, size_px=size_px, collection=coll,
                               data_dir=data_dir, tag=tag, max_files=max_files, note=note, log=log)
                statuses = [f["status"] for f in m["frames"]]
                entry.update(frames=m["n_frames"], ok=m["n_ok"], new=statuses.count("downloaded"),
                             errors=sum(s.startswith("error") for s in statuses), mb=round(m["bytes_downloaded"] / 1e6, 2))
                if full > 0:
                    entry["full"] = fetch_full_files(ra, dec, tag, coll, data_dir, full, log)
            except Exception as exc:  # one bad target or collection must not stop the run
                entry["error"] = f"{type(exc).__name__}: {exc}"
                log(f"[spherex] {tag}/{coll}: {entry['error']}")
            summary.append(entry)
    return summary


# ---------------------------------------------------------------------------------------------
# Gaia DR3
# ---------------------------------------------------------------------------------------------

def _clean(v: Any) -> Any:
    try:
        import numpy as np

        if v is np.ma.masked:
            return None
        if isinstance(v, np.generic):
            v = v.item()
    except ImportError:
        pass
    if isinstance(v, float) and v != v:  # NaN
        return None
    return v


def gaia_mast(ra: float, dec: float, radius_arcsec: float) -> list[dict]:
    from astropy import units as u
    from astropy.coordinates import SkyCoord
    from astroquery.mast import Catalogs

    table = Catalogs.query_region(SkyCoord(ra, dec, unit="deg"), radius=radius_arcsec * u.arcsec,
                                  catalog="Gaia", version=3)
    cols = [c for c in GAIA_COLUMNS if c in table.colnames]
    rows = [{c: _clean(r[c]) for c in cols} for r in table]
    return sorted(rows, key=lambda r: (r.get("phot_g_mean_mag") is None, r.get("phot_g_mean_mag") or 0.0))


def gaia_esa(ra: float, dec: float, radius_arcsec: float, timeout: float = 60.0) -> list[dict]:
    q = (f"SELECT TOP 200 {', '.join(GAIA_COLUMNS)} FROM gaiadr3.gaia_source WHERE 1 = CONTAINS("
         f"POINT(ra, dec), CIRCLE({ra:.7f}, {dec:.7f}, {radius_arcsec / 3600.0:.8f})) ORDER BY phot_g_mean_mag")
    body = urllib.parse.urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": q}).encode()
    req = urllib.request.Request(ESA_GAIA_TAP, data=body, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        row: dict[str, Any] = {}
        for k, v in r.items():
            if v in ("", None):
                row[k] = None
            elif k == "source_id":
                row[k] = int(v)
            else:
                row[k] = float(v)
        rows.append(row)
    return rows


def ingest_gaia(targets: list[dict], data_dir: Path, radius_arcsec: float, t_year: float, log: Log,
                sources: tuple[tuple[str, Callable[..., list[dict]]], ...] | None = None) -> list[dict]:
    sources = sources or (("MAST astroquery.mast Catalogs (Gaia DR3)", gaia_mast), ("ESA Gaia TAP", gaia_esa))
    out_dir = data_dir / "catalogs" / "gaia_dr3"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for t in targets:
        if t.get("gaia", True) is False:
            continue
        tag, ra, dec, _ = resolve(t, t_year)
        entry: dict[str, Any] = {"target": tag}
        for name, fn in sources:
            try:
                rows = fn(ra, dec, radius_arcsec)
            except Exception as exc:
                log(f"[gaia] {tag} via {name}: {type(exc).__name__}: {exc}")
                continue
            doc = {"target": tag, "service": name, "query": {"ra": ra, "dec": dec, "radius_arcsec": radius_arcsec},
                   "retrieved_utc": utc_now(), "n_sources": len(rows), "sources": rows}
            (out_dir / f"{tag}.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
            entry.update(service=name, n_sources=len(rows))
            break
        else:
            entry["error"] = "all Gaia services failed"
        summary.append(entry)
    return summary


# ---------------------------------------------------------------------------------------------
# Azure Blob sync
# ---------------------------------------------------------------------------------------------

def iter_files(root: Path) -> Iterator[tuple[str, Path]]:
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        # skip partial downloads and hidden paths (.ingest.lock, .home caches)
        if p.is_file() and not p.name.endswith(".part") and not any(part.startswith(".") for part in rel.parts):
            yield rel.as_posix(), p


def sync_to_blob(data_dir: Path, container_client: Any, log: Log) -> dict:
    """Upload files that are missing in the container or whose size differs (idempotent)."""
    remote = {b.name: b.size for b in container_client.list_blobs()}
    uploaded = skipped = 0
    for name, path in iter_files(data_dir):
        size = path.stat().st_size
        if remote.get(name) == size:
            skipped += 1
            continue
        with open(path, "rb") as fh:
            container_client.upload_blob(name=name, data=fh, overwrite=True, length=size)
        uploaded += 1
    log(f"[blob] uploaded {uploaded}, unchanged {skipped}")
    return {"uploaded": uploaded, "unchanged": skipped}


def blob_container(account_url: str, container: str) -> Any:
    from azure.core.exceptions import ResourceExistsError
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    svc = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
    client = svc.get_container_client(container)
    with contextlib.suppress(ResourceExistsError):
        client.create_container()
    return client


# ---------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------

@contextlib.contextmanager
def run_lock(data_dir: Path) -> Iterator[None]:
    """Refuse to start while a previous run is still going (timer overlap, manual run)."""
    lock = data_dir / ".ingest.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        age = time.time() - lock.stat().st_mtime
        if age < 12 * 3600:
            raise SystemExit(f"another ingest run is active ({lock}, {age / 60:.0f} min old)") from None
        lock.unlink()  # stale lock from a crashed run
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock.unlink()


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--targets", type=Path, default=Path(__file__).with_name("targets.json"))
    p.add_argument("--data-dir", type=Path, default=Path(os.environ.get("AEON_DATA_DIR", "/data/aeon")))
    p.add_argument("--collection", action="append", dest="collections",
                   help="SPHEREx collection (repeatable); default spherex_dr1 and spherex_qr3")
    p.add_argument("--size-px", type=int, default=96, help="cutout size in pixels (6.2″/px)")
    p.add_argument("--radius-arcmin", type=float, default=0.5)
    p.add_argument("--max-files", type=int, default=int(os.environ.get("AEON_MAX_FILES", "80")),
                   help="cutouts per target and collection, spread over time (default 80, $AEON_MAX_FILES; 0 = all)")
    p.add_argument("--full", type=int, default=0, help="also download N complete spectral images per target (S3)")
    p.add_argument("--gaia-radius-arcsec", type=float, default=30.0)
    p.add_argument("--no-spherex", action="store_true")
    p.add_argument("--no-gaia", action="store_true")
    p.add_argument("--blob-account-url", default=os.environ.get("AEON_BLOB_ACCOUNT_URL"),
                   help="https://<account>.blob.core.windows.net (default $AEON_BLOB_ACCOUNT_URL; empty = no upload)")
    p.add_argument("--blob-container", default=os.environ.get("AEON_BLOB_CONTAINER", "aeon-data"))
    a = p.parse_args(argv)
    a.collections = a.collections or ["spherex_dr1", "spherex_qr3"]
    if a.size_px < 8 or a.size_px > 512:
        p.error("--size-px must be in 8..512")
    if not 0 < a.radius_arcmin <= 10 or not 0 < a.gaia_radius_arcsec <= 600:
        p.error("radius out of range")
    if a.max_files < 0:
        p.error("--max-files must be >= 0")
    a.max_files = a.max_files or None          # 0 = no limit
    if a.full < 0 or a.full > 50:
        p.error("--full must be in 0..50")
    return a


def main(argv: list[str] | None = None, log: Log = print) -> int:
    a = parse_args(argv)
    a.data_dir.mkdir(parents=True, exist_ok=True)
    targets = load_targets(a.targets)
    t_year = decimal_year()
    report: dict[str, Any] = {"started_utc": utc_now(), "epoch_year": round(t_year, 4), "targets": len(targets),
                              "data_dir": str(a.data_dir)}
    with run_lock(a.data_dir):
        t0 = time.time()
        if not a.no_spherex:
            report["spherex"] = ingest_spherex(targets, a.data_dir, a.collections, a.size_px, a.radius_arcmin,
                                               a.max_files, a.full, t_year, log)
        if not a.no_gaia:
            report["gaia"] = ingest_gaia(targets, a.data_dir, a.gaia_radius_arcsec, t_year, log)
        runs = a.data_dir / "runs"
        runs.mkdir(exist_ok=True)
        report["finished_utc"] = utc_now()
        report["seconds"] = round(time.time() - t0, 1)
        stamp = report["started_utc"].replace(":", "").replace("-", "")
        (runs / f"{stamp}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        if a.blob_account_url:
            try:
                report["blob"] = sync_to_blob(a.data_dir, blob_container(a.blob_account_url, a.blob_container), log)
            except Exception as exc:
                report["blob"] = {"error": f"{type(exc).__name__}: {exc}"}
                log(f"[blob] {report['blob']['error']}")
            (runs / f"{stamp}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

    sx = report.get("spherex", [])
    gx = report.get("gaia", [])
    failed = (bool(sx) and all("error" in s for s in sx)) or (bool(gx) and all("error" in g for g in gx)) \
        or ("error" in report.get("blob", {}))
    log(f"[ingest] done in {report['seconds']} s: "
        f"{sum(s.get('new', 0) for s in sx)} new SPHEREx frames, {sum(1 for g in gx if 'error' not in g)}/{len(gx)} Gaia cones"
        + (" — FAILED" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
