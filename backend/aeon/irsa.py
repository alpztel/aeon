"""Download real SPHEREx Level 2 spectral images from NASA/IPAC IRSA into AEON_DATA_DIR.

Search: IRSA Simple Image Access v2 (``https://irsa.ipac.caltech.edu/SIA``) with
``COLLECTION=spherex_dr1`` (DR1 wide survey; ``spherex_qr3`` etc. also accepted). Retrieval: the
IRSA IBE cutout service, i.e. ``access_url?center=RA,DEC&size=Npix``, which returns the same
extensions as the full 2040x2040 file (IMAGE, FLAGS, VARIANCE, ZODI, EPSF, WCS-WAVE) cropped
around the target, with WCS-WAVE remapped. By default the EPSF table (~4 MB, unused by AEON) is
dropped before writing, so one cached frame is ~100 kB instead of ~65 MB for the full file.

CLI::

    python -m aeon.irsa list  --ra 133.786 --dec -7.244
    python -m aeon.irsa fetch --ra 133.786 --dec -7.244 --radius-arcmin 0.5 --size-px 96
    python -m aeon.irsa fetch-demo                     # wise-0855, rw-aur, px-2026-09 field

Files go to ``$AEON_DATA_DIR/spherex/<collection>/<tag>/`` together with ``manifest.json``.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.io.votable import parse_single_table
from astropy.time import Time

from . import __version__
from .archive import is_spherex

SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
DEFAULT_COLLECTION = "spherex_dr1"
USER_AGENT = f"AEON-backend/{__version__} (+https://github.com/alpztel/aeon)"
KEEP_EXTENSIONS = ("IMAGE", "FLAGS", "VARIANCE", "ZODI", "WCS-WAVE")

DEFAULT_TIMEOUT_S = 120.0
DEFAULT_RETRIES = 4
DEFAULT_MAX_FILE_MB = 25.0          # per downloaded cutout (EPSF alone is ~4 MB)
DEFAULT_MAX_TOTAL_MB = 3000.0       # per fetch run, counted on downloaded bytes

# Demo targets (AGENTS.md section 4). Positions: apparent geocentric catalog positions at 2026.0.
# px-2026-09 is SYNTHETIC: only the real SPHEREx background of its field is downloaded.
DEMO_TARGETS = ("wise-0855", "rw-aur", "px-2026-09")


class DownloadError(RuntimeError):
    pass


@dataclass
class SiaRecord:
    access_url: str
    obs_id: str
    bandpass: str
    t_min_mjd: float
    t_max_mjd: float
    em_min_um: float
    em_max_um: float
    est_size_kb: float
    collection: str
    publisher_did: str

    @property
    def detector(self) -> int | None:
        tail = self.bandpass.rsplit("D", 1)[-1]
        return int(tail) if tail.isdigit() else None

    @property
    def filename(self) -> str:
        return Path(urllib.parse.urlparse(self.access_url).path).name

    @property
    def date_obs(self) -> str:
        return Time(self.t_min_mjd, format="mjd").isot[:19]


# --------------------------------------------------------------------------------------------
# HTTP with timeout, retry and size limit
# --------------------------------------------------------------------------------------------

def http_get(url: str, timeout: float = DEFAULT_TIMEOUT_S, retries: int = DEFAULT_RETRIES,
             max_bytes: int | None = None, sleep=time.sleep) -> bytes:
    """GET with exponential back-off on network errors and HTTP 429/5xx; refuses bodies larger
    than max_bytes (checked against Content-Length and while streaming)."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                length = resp.headers.get("Content-Length")
                if max_bytes is not None and length is not None and int(length) > max_bytes:
                    raise DownloadError(f"{url}: {int(length) / 1e6:.1f} MB exceeds limit {max_bytes / 1e6:.1f} MB")
                buf = io.BytesIO()
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    buf.write(chunk)
                    if max_bytes is not None and buf.tell() > max_bytes:
                        raise DownloadError(f"{url}: body exceeds limit {max_bytes / 1e6:.1f} MB")
                return buf.getvalue()
        except DownloadError:
            raise
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (408, 429, 500, 502, 503, 504):
                raise DownloadError(f"{url}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = exc
        if attempt < retries:
            sleep(min(2.0 ** attempt, 30.0))
    raise DownloadError(f"{url}: failed after {retries + 1} attempts: {last}")


# --------------------------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------------------------

def sia_url(ra: float, dec: float, radius_deg: float, collection: str = DEFAULT_COLLECTION) -> str:
    q = {"COLLECTION": collection, "POS": f"CIRCLE {ra:.7f} {dec:.7f} {radius_deg:.6f}"}
    return SIA_URL + "?" + urllib.parse.urlencode(q)


def parse_sia(votable_bytes: bytes, collection: str) -> list[SiaRecord]:
    table = parse_single_table(io.BytesIO(votable_bytes)).to_table(use_names_over_ids=True)
    out = []
    for r in table:
        if str(r["dataproduct_type"]) != "image" or str(r["dataproduct_subtype"]) != "science":
            continue
        out.append(SiaRecord(
            access_url=str(r["access_url"]), obs_id=str(r["obs_id"]), bandpass=str(r["energy_bandpassname"]),
            t_min_mjd=float(r["t_min"]), t_max_mjd=float(r["t_max"]),
            em_min_um=float(r["em_min"]) * 1e6, em_max_um=float(r["em_max"]) * 1e6,
            est_size_kb=float(r["access_estsize"]) if r["access_estsize"] is not np.ma.masked else float("nan"),
            collection=str(r["obs_collection"]) if "obs_collection" in table.colnames else collection,
            publisher_did=str(r["obs_publisher_did"]) if "obs_publisher_did" in table.colnames else "",
        ))
    out.sort(key=lambda s: (s.t_min_mjd, s.bandpass))
    return out


def query(ra: float, dec: float, radius_arcmin: float = 0.5, collection: str = DEFAULT_COLLECTION,
          detectors: list[int] | None = None, timeout: float = DEFAULT_TIMEOUT_S) -> list[SiaRecord]:
    recs = parse_sia(http_get(sia_url(ra, dec, radius_arcmin / 60.0, collection), timeout=timeout), collection)
    if detectors:
        recs = [r for r in recs if r.detector in set(detectors)]
    return recs


# --------------------------------------------------------------------------------------------
# Download + slim
# --------------------------------------------------------------------------------------------

def cutout_url(access_url: str, ra: float, dec: float, size_px: int) -> str:
    return f"{access_url}?center={ra:.7f},{dec:.7f}&size={int(size_px)}pix"


def slim_spherex(raw: bytes, keep_psf: bool = False, provenance: dict | None = None) -> fits.HDUList:
    """Validate a downloaded SPHEREx MEF and keep only the extensions AEON reads."""
    hdul = fits.open(io.BytesIO(raw))
    if not is_spherex(hdul):
        raise DownloadError("response is not a SPHEREx Level 2 spectral image (IMAGE/FLAGS/WCS-WAVE missing)")
    keep = KEEP_EXTENSIONS + (("EPSF", "PSF") if keep_psf else ())
    out = fits.HDUList([fits.PrimaryHDU(header=hdul[0].header)])
    for h in hdul[1:]:
        if h.name in keep:
            if isinstance(h, fits.CompImageHDU):
                h = fits.ImageHDU(data=h.data, header=h.header, name=h.name)
            out.append(h)
    if provenance:
        ph = out[0].header
        for k, v in provenance.items():
            ph[k[:8].upper()] = v
        ph["AEONSRC"] = ("IRSA SPHEREx L2 cutout", "Downloaded by aeon.irsa")
    return out


def fetch(ra: float, dec: float, radius_arcmin: float = 0.5, size_px: int = 96,
          collection: str = DEFAULT_COLLECTION, data_dir: str | os.PathLike | None = None, tag: str | None = None,
          detectors: list[int] | None = None, max_files: int | None = None, workers: int = 4,
          timeout: float = DEFAULT_TIMEOUT_S, retries: int = DEFAULT_RETRIES,
          max_file_mb: float = DEFAULT_MAX_FILE_MB, max_total_mb: float = DEFAULT_MAX_TOTAL_MB,
          keep_psf: bool = False, note: str | None = None, log=print) -> dict:
    """Query IRSA and download cutouts of every SPHEREx L2 frame covering (ra, dec). Cached files
    are skipped. Returns the manifest written next to the files."""
    root = Path(data_dir or os.environ.get("AEON_DATA_DIR") or "data")
    tag = tag or f"ra{ra:.4f}_dec{dec:+.4f}"
    out_dir = root / "spherex" / collection / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    recs = query(ra, dec, radius_arcmin, collection, detectors, timeout)
    log(f"[irsa] {len(recs)} SPHEREx frames in {collection} cover ({ra:.5f}, {dec:+.5f}) r={radius_arcmin}'")
    if max_files is not None:
        recs = _spread(recs, max_files)
    budget = {"bytes": 0}
    limit_total = int(max_total_mb * 1e6)

    def one(rec: SiaRecord) -> dict:
        dest = out_dir / rec.filename
        entry = {**asdict(rec), "file": dest.name, "date_obs": rec.date_obs}
        if dest.exists() and dest.stat().st_size > 0:
            return {**entry, "status": "cached"}
        if budget["bytes"] > limit_total:
            return {**entry, "status": "skipped: total size limit"}
        url = cutout_url(rec.access_url, ra, dec, size_px)
        try:
            raw = http_get(url, timeout=timeout, retries=retries, max_bytes=int(max_file_mb * 1e6))
            budget["bytes"] += len(raw)
            slim = slim_spherex(raw, keep_psf, {"AEONURL": rec.access_url, "AEONCOLL": rec.collection})
            tmp = dest.with_suffix(".part")
            slim.writeto(tmp, overwrite=True)
            os.replace(tmp, dest)
            return {**entry, "status": "downloaded", "bytes_downloaded": len(raw), "bytes_stored": dest.stat().st_size}
        except (DownloadError, OSError, ValueError) as exc:
            return {**entry, "status": f"error: {exc}"}

    results = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(one, r): r for r in recs}
        for i, f in enumerate(as_completed(futs), 1):
            res = f.result()
            results.append(res)
            if i % 10 == 0 or not res["status"].startswith(("downloaded", "cached")):
                log(f"[irsa] {i}/{len(recs)} {res['file']}: {res['status']}")
    results.sort(key=lambda r: (r["t_min_mjd"], r["bandpass"]))
    manifest = {
        "service": SIA_URL, "collection": collection, "query": {"ra": ra, "dec": dec, "radius_arcmin": radius_arcmin},
        "cutout_size_px": size_px, "retrieved_utc": Time.now().isot[:19], "note": note,
        "n_frames": len(results), "n_ok": sum(r["status"] in ("downloaded", "cached") for r in results),
        "bytes_downloaded": budget["bytes"], "frames": results,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    log(f"[irsa] {manifest['n_ok']}/{len(results)} frames ready in {out_dir} "
        f"({budget['bytes'] / 1e6:.1f} MB downloaded)")
    return manifest


def _spread(recs: list[SiaRecord], n: int) -> list[SiaRecord]:
    """Keep n records spread evenly over time/detector order (so every visit is represented)."""
    if n >= len(recs):
        return recs
    idx = np.unique(np.linspace(0, len(recs) - 1, n).round().astype(int))
    return [recs[i] for i in idx]


def demo_position(target_id: str, t_year: float = 2026.0) -> tuple[float, float, str]:
    from .catalog import ENTRIES_BY_ID
    from .ephem import apparent_position

    e = ENTRIES_BY_ID[target_id]
    ra, dec = apparent_position(e, t_year)
    note = (f"{e.name}: field of a SYNTHETIC injected candidate; only the real sky background is real"
            if e.is_synthetic else f"{e.name}: real target")
    return ra, dec, note


def fetch_demo(targets=DEMO_TARGETS, **kw) -> list[dict]:
    out = []
    for tid in targets:
        ra, dec, note = demo_position(tid)
        out.append(fetch(ra, dec, tag=tid, note=note, **kw))
    return out


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------

def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--collection", default=DEFAULT_COLLECTION)
    p.add_argument("--radius-arcmin", type=float, default=0.5, help="search radius for frames (default 0.5')")
    p.add_argument("--detectors", type=int, nargs="*", help="restrict to detectors 1-6")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aeon.irsa", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list", help="query IRSA only")
    pl.add_argument("--ra", type=float, required=True)
    pl.add_argument("--dec", type=float, required=True)
    _add_common(pl)
    for name in ("fetch", "fetch-demo"):
        p = sub.add_parser(name)
        if name == "fetch":
            p.add_argument("--ra", type=float, required=True)
            p.add_argument("--dec", type=float, required=True)
            p.add_argument("--tag")
        else:
            p.add_argument("--targets", nargs="*", default=list(DEMO_TARGETS))
        _add_common(p)
        p.add_argument("--size-px", type=int, default=96, help="cutout side in native 6.15\" pixels")
        p.add_argument("--data-dir", default=None, help="default: $AEON_DATA_DIR or ./data")
        p.add_argument("--max-files", type=int, default=None)
        p.add_argument("--workers", type=int, default=4)
        p.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
        p.add_argument("--max-file-mb", type=float, default=DEFAULT_MAX_FILE_MB)
        p.add_argument("--max-total-mb", type=float, default=DEFAULT_MAX_TOTAL_MB)
        p.add_argument("--keep-psf", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        recs = query(a.ra, a.dec, a.radius_arcmin, a.collection, a.detectors, a.timeout)
        for r in recs:
            print(f"{r.date_obs}  {r.bandpass:11s} {r.em_min_um:.3f}-{r.em_max_um:.3f} um  {r.obs_id}  {r.access_url}")
        print(f"{len(recs)} frames")
        return 0
    common = dict(radius_arcmin=a.radius_arcmin, size_px=a.size_px, collection=a.collection, data_dir=a.data_dir,
                  detectors=a.detectors, max_files=a.max_files, workers=a.workers, timeout=a.timeout,
                  retries=a.retries, max_file_mb=a.max_file_mb, max_total_mb=a.max_total_mb, keep_psf=a.keep_psf)
    if a.cmd == "fetch":
        m = [fetch(a.ra, a.dec, tag=a.tag, **common)]
    else:
        m = fetch_demo(a.targets, **common)
    return 0 if all(x["n_ok"] > 0 for x in m) else 1


if __name__ == "__main__":
    sys.exit(main())
