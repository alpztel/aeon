"""Offline tests for deploy/azure/ingest.py (no network: archives and Azure are faked)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest  # noqa: E402


def write_targets(tmp_path: Path, targets) -> Path:
    p = tmp_path / "targets.json"
    p.write_text(json.dumps({"targets": targets}), encoding="utf-8")
    return p


# ---------------------------------------------------------------- targets
def test_repo_targets_file_is_valid_and_resolves():
    targets = ingest.load_targets(Path(ingest.__file__).with_name("targets.json"))
    assert len(targets) >= 3
    for t in targets:
        tag, ra, dec, note = ingest.resolve(t, 2026.9)
        assert 0 <= ra <= 360 and -90 <= dec <= 90 and tag and note


def test_synthetic_target_is_labelled_and_skips_gaia():
    t = next(t for t in ingest.load_targets(Path(ingest.__file__).with_name("targets.json")) if t["catalog_id"] == "px-2026-09")
    assert t.get("gaia") is False
    assert "SYNTHETIC" in ingest.resolve(t, 2026.9)[3]


@pytest.mark.parametrize("bad", [{"name": "x"}, {"ra": 400, "dec": 0}, {"ra": 10, "dec": -95}])
def test_bad_targets_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        ingest.load_targets(write_targets(tmp_path, [bad]))


def test_proper_motion_moves_catalog_target():
    a = ingest.resolve({"catalog_id": "barnard"}, 2026.0)
    b = ingest.resolve({"catalog_id": "barnard"}, 2027.0)
    shift_arcsec = ((a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5 * 3600
    assert 5 < shift_arcsec < 15          # Barnard's star: ~10.4″/yr


def test_decimal_year_bounds():
    from datetime import datetime, timezone

    assert ingest.decimal_year(datetime(2026, 1, 1, tzinfo=timezone.utc)) == 2026.0
    assert 2026.99 < ingest.decimal_year(datetime(2026, 12, 31, 23, tzinfo=timezone.utc)) < 2027.0


# ---------------------------------------------------------------- S3 mapping (verified live: HTTP 200)
def test_s3_url_maps_ibe_path():
    ibe = ("https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W19_1B/l2b-v27-2026-197/3/"
           "level2_2025W19_1B_0116_1D3_spx_l2b-v27-2026-197.fits")
    assert ingest.s3_url(ibe) == ("https://nasa-irsa-spherex.s3.amazonaws.com/dr1/level2/2025W19_1B/"
                                  "l2b-v27-2026-197/3/level2_2025W19_1B_0116_1D3_spx_l2b-v27-2026-197.fits")
    assert ingest.s3_url(ibe + "?center=1,2&size=96pix").endswith(".fits")
    assert ingest.s3_url("https://example.org/other.fits") is None


# ---------------------------------------------------------------- SPHEREx orchestration
def test_spherex_one_failing_target_does_not_stop_the_run(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(ra, dec, **kw):
        calls.append(kw["tag"])
        if kw["tag"] == "rw-aur":
            raise ConnectionError("IRSA down")
        frames = [{"status": "downloaded"}, {"status": "cached"}, {"status": "error: bad"}]
        return {"n_frames": 3, "n_ok": 2, "bytes_downloaded": 2_500_000, "frames": frames}

    monkeypatch.setattr(ingest.irsa, "fetch", fake_fetch)
    out = ingest.ingest_spherex([{"catalog_id": "wise-0855"}, {"catalog_id": "rw-aur"}], tmp_path,
                                ["spherex_dr1"], 96, 0.5, None, 0, 2026.9, lambda m: None)
    assert calls == ["wise-0855", "rw-aur"]
    assert out[0] == {"target": "wise-0855", "collection": "spherex_dr1", "ra": out[0]["ra"], "dec": out[0]["dec"],
                      "frames": 3, "ok": 2, "new": 1, "errors": 1, "mb": 2.5}
    assert "IRSA down" in out[1]["error"]


def test_full_files_prefer_s3_then_fall_back_to_irsa(tmp_path, monkeypatch):
    rec = SimpleNamespace(access_url="https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/w/v/1/f1.fits",
                          filename="f1.fits")
    monkeypatch.setattr(ingest.irsa, "query", lambda *a, **k: [rec])
    monkeypatch.setattr(ingest.irsa, "_spread", lambda recs, n: recs[:n])
    tried = []

    def fake_download(url, dest, **kw):
        tried.append(url)
        if "amazonaws" in url:
            raise OSError("S3 throttled")
        dest.write_bytes(b"x" * 10)
        return 10

    monkeypatch.setattr(ingest, "download", fake_download)
    res = ingest.fetch_full_files(1.0, 2.0, "t", "spherex_dr1", tmp_path, 1, lambda m: None)
    assert [u.split("/")[2] for u in tried] == ["nasa-irsa-spherex.s3.amazonaws.com", "irsa.ipac.caltech.edu"]
    assert res == [{"file": "f1.fits", "status": "downloaded", "source": "irsa", "bytes": 10}]
    # second run: cached, nothing downloaded
    tried.clear()
    assert ingest.fetch_full_files(1.0, 2.0, "t", "spherex_dr1", tmp_path, 1, lambda m: None)[0]["status"] == "cached"
    assert tried == []


def test_download_enforces_size_limit(tmp_path, monkeypatch):
    class Resp:
        def __init__(self):
            self.left = 5

        def read(self, n):
            if self.left:
                self.left -= 1
                return b"y" * 1000
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ingest.urllib.request, "urlopen", lambda req, timeout: Resp())
    with pytest.raises(ValueError):
        ingest.download("https://x/y.fits", tmp_path / "y.fits", max_bytes=2500)
    assert not (tmp_path / "y.fits").exists()
    assert ingest.download("https://x/z.fits", tmp_path / "z.fits", max_bytes=10_000) == 5000


# ---------------------------------------------------------------- Gaia
def test_gaia_falls_back_and_records_provenance(tmp_path):
    def mast(ra, dec, r):
        raise TimeoutError("MAST slow")

    def esa(ra, dec, r):
        return [{"source_id": 1, "ra": ra, "dec": dec, "phot_g_mean_mag": 12.0}]

    logs = []
    out = ingest.ingest_gaia([{"catalog_id": "wise-0855"}, {"catalog_id": "px-2026-09", "gaia": False}],
                             tmp_path, 30.0, 2026.9, logs.append, sources=(("MAST", mast), ("ESA", esa)))
    assert out == [{"target": "wise-0855", "service": "ESA", "n_sources": 1}]
    doc = json.loads((tmp_path / "catalogs" / "gaia_dr3" / "wise-0855.json").read_text())
    assert doc["service"] == "ESA" and doc["query"]["radius_arcsec"] == 30.0 and doc["retrieved_utc"].endswith("Z")
    assert any("MAST slow" in m for m in logs)
    assert not (tmp_path / "catalogs" / "gaia_dr3" / "px-2026-09.json").exists()


def test_gaia_all_services_failing_is_reported(tmp_path):
    def boom(*a):
        raise OSError("down")

    out = ingest.ingest_gaia([{"catalog_id": "rw-aur"}], tmp_path, 30.0, 2026.9, lambda m: None,
                             sources=(("A", boom), ("B", boom)))
    assert out == [{"target": "rw-aur", "error": "all Gaia services failed"}]


def test_esa_csv_parsing(monkeypatch):
    csv_text = ("source_id,ra,dec,parallax,parallax_error,pmra,pmdec,phot_g_mean_mag,phot_bp_mean_mag,phot_rp_mean_mag,ruwe\n"
                "5756956644387831296,133.758,-7.241,0.3,0.06,-6.2,1.9,16.3,,15.9,1.01\n")

    class Resp:
        def read(self):
            return csv_text.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ingest.urllib.request, "urlopen", lambda req, timeout: Resp())
    rows = ingest.gaia_esa(133.758, -7.241, 30.0)
    assert rows[0]["source_id"] == 5756956644387831296 and rows[0]["phot_bp_mean_mag"] is None
    assert rows[0]["ruwe"] == pytest.approx(1.01)


def test_clean_masked_and_nan():
    import numpy as np

    assert ingest._clean(np.ma.masked) is None
    assert ingest._clean(float("nan")) is None
    assert ingest._clean(np.float32(1.5)) == 1.5 and isinstance(ingest._clean(np.int64(3)), int)


# ---------------------------------------------------------------- Blob sync
class FakeContainer:
    def __init__(self, existing=None):
        self.blobs = dict(existing or {})
        self.uploads = []

    def list_blobs(self):
        return [SimpleNamespace(name=k, size=v) for k, v in self.blobs.items()]

    def upload_blob(self, name, data, overwrite, length):
        assert overwrite is True
        self.blobs[name] = len(data.read())
        self.uploads.append(name)


def test_blob_sync_is_incremental_and_skips_hidden_and_partial(tmp_path):
    (tmp_path / "spherex" / "spherex_dr1" / "wise-0855").mkdir(parents=True)
    (tmp_path / "spherex" / "spherex_dr1" / "wise-0855" / "a.fits").write_bytes(b"a" * 100)
    (tmp_path / "spherex" / "spherex_dr1" / "wise-0855" / "b.fits.part").write_bytes(b"b")
    (tmp_path / ".home" / ".astropy").mkdir(parents=True)
    (tmp_path / ".home" / ".astropy" / "cache").write_bytes(b"c")
    (tmp_path / ".ingest.lock").write_text("1")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "r.json").write_text("{}")

    box = FakeContainer({"runs/r.json": 2})
    res = ingest.sync_to_blob(tmp_path, box, lambda m: None)
    assert box.uploads == ["spherex/spherex_dr1/wise-0855/a.fits"]
    assert res == {"uploaded": 1, "unchanged": 1}
    # second sync uploads nothing; a changed file is re-uploaded
    assert ingest.sync_to_blob(tmp_path, box, lambda m: None) == {"uploaded": 0, "unchanged": 2}
    (tmp_path / "runs" / "r.json").write_text('{"x": 1}')
    assert ingest.sync_to_blob(tmp_path, box, lambda m: None)["uploaded"] == 1


# ---------------------------------------------------------------- main / CLI
def test_main_writes_report_and_uploads(tmp_path, monkeypatch):
    targets = write_targets(tmp_path, [{"catalog_id": "wise-0855"}])
    monkeypatch.setattr(ingest, "ingest_spherex", lambda *a, **k: [{"target": "wise-0855", "new": 4}])
    monkeypatch.setattr(ingest, "ingest_gaia", lambda *a, **k: [{"target": "wise-0855", "n_sources": 2}])
    box = FakeContainer()
    monkeypatch.setattr(ingest, "blob_container", lambda url, c: box)
    data = tmp_path / "data"
    rc = ingest.main(["--targets", str(targets), "--data-dir", str(data), "--blob-account-url", "https://a.blob.core.windows.net"],
                     log=lambda m: None)
    assert rc == 0
    report = json.loads(next((data / "runs").glob("*.json")).read_text())
    assert report["spherex"][0]["new"] == 4 and report["blob"]["uploaded"] >= 1
    assert not (data / ".ingest.lock").exists()


def test_main_fails_when_everything_failed(tmp_path, monkeypatch):
    targets = write_targets(tmp_path, [{"catalog_id": "wise-0855"}])
    monkeypatch.setattr(ingest, "ingest_spherex", lambda *a, **k: [{"target": "wise-0855", "error": "x"}])
    monkeypatch.setattr(ingest, "ingest_gaia", lambda *a, **k: [{"target": "wise-0855", "n_sources": 1}])
    assert ingest.main(["--targets", str(targets), "--data-dir", str(tmp_path / "d")], log=lambda m: None) == 1


def test_blob_failure_is_reported_not_raised(tmp_path, monkeypatch):
    targets = write_targets(tmp_path, [{"catalog_id": "wise-0855"}])
    monkeypatch.setattr(ingest, "ingest_spherex", lambda *a, **k: [])
    monkeypatch.setattr(ingest, "ingest_gaia", lambda *a, **k: [])

    def no_identity(url, c):
        raise PermissionError("role assignment not propagated yet")

    monkeypatch.setattr(ingest, "blob_container", no_identity)
    rc = ingest.main(["--targets", str(targets), "--data-dir", str(tmp_path / "d"), "--blob-account-url", "https://a"],
                     log=lambda m: None)
    assert rc == 1
    report = json.loads(next((tmp_path / "d" / "runs").glob("*.json")).read_text())
    assert "role assignment" in report["blob"]["error"]


def test_concurrent_run_refused_and_stale_lock_recovered(tmp_path):
    import os
    import time

    with ingest.run_lock(tmp_path):
        with pytest.raises(SystemExit):
            with ingest.run_lock(tmp_path):
                pass
    lock = tmp_path / ".ingest.lock"
    lock.write_text("999")
    old = time.time() - 13 * 3600
    os.utime(lock, (old, old))
    with ingest.run_lock(tmp_path):
        assert lock.exists()
    assert not lock.exists()


@pytest.mark.parametrize("args", [["--max-files", "-1"], ["--size-px", "4"], ["--size-px", "4096"], ["--radius-arcmin", "0"],
                                  ["--gaia-radius-arcsec", "9999"], ["--full", "-1"], ["--full", "500"]])
def test_cli_rejects_bad_parameters(args):
    with pytest.raises(SystemExit):
        ingest.parse_args(args)


def test_cli_defaults(monkeypatch):
    monkeypatch.delenv("AEON_BLOB_ACCOUNT_URL", raising=False)
    monkeypatch.delenv("AEON_MAX_FILES", raising=False)
    a = ingest.parse_args([])
    assert a.collections == ["spherex_dr1", "spherex_qr3"] and a.blob_account_url is None and a.full == 0
    assert a.max_files == 80
    assert ingest.parse_args(["--max-files", "0"]).max_files is None
