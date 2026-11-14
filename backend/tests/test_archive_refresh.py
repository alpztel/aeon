"""The archive re-indexes itself when the weekly ingest adds FITS files (no service restart)."""

from __future__ import annotations

import os
import time

import pytest

from aeon import bands, service
from tests.spherex_fixture import make_spherex_file

RA, DEC = 150.0, 2.0


@pytest.fixture()
def fresh_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(service, "ARCHIVE_RESCAN_S", 1e-6)      # re-check on every call
    service.reset_archive()
    yield tmp_path
    service.reset_archive()


def add_frames(root, n, month="05", tag="a"):
    (root / tag).mkdir(parents=True, exist_ok=True)
    for i, k in enumerate(range(10, 10 + 2 * n, 2)):
        make_spherex_file(root / tag / f"{tag}_{k:03d}.fits", RA, DEC, n=40, date=f"2025-{month}-{5 + i:02d}T12:00:00",
                          detector=int(bands.ARRAY_ID[k]), wave_um=float(bands.WAVELENGTH_UM[k]),
                          wave_slope_um_per_px=0.0, source=(RA, DEC, 2000.0), noise_mjysr=0.002, seed=k)


def test_signature_counts_fits_and_ignores_hidden_and_other_files(tmp_path):
    assert service.archive_signature(tmp_path / "missing") == (0, 0, 0)
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "a.fits").write_bytes(b"1" * 10)
    (tmp_path / "x" / "b.fits.gz").write_bytes(b"1" * 5)
    (tmp_path / "x" / "manifest.json").write_text("{}")
    (tmp_path / ".home").mkdir()
    (tmp_path / ".home" / "cache.fits").write_bytes(b"1" * 99)
    n, size, newest = service.archive_signature(tmp_path)
    assert (n, size) == (2, 15) and newest > 0


def test_new_frames_appear_without_restart(fresh_archive, client):
    root = fresh_archive
    first = service.get_archive()
    assert not first.available
    q2 = {"ra": RA, "dec": DEC, "epoch": "2026-Q2", "size_px": 32}
    assert client.get("/api/v1/sky/cutout", params=q2).json()["data_mode"] == "physical_model"

    add_frames(root, 6)                                        # the weekly ingest drops new files
    second = service.get_archive()
    assert second is not first and second.n_spherex == 6
    body = client.get("/api/v1/sky/cutout", params=q2).json()
    assert body["data_mode"] == "fits_archive" and body["provenance"]["n_frames"] == 6
    assert client.get("/api/v1/health").json()["engines"]["archive_spherex_frames"] == "6"


def test_unchanged_directory_keeps_the_same_index(fresh_archive):
    add_frames(fresh_archive, 3)
    a = service.get_archive()
    assert service.get_archive() is a and a.n_spherex == 3


def test_replaced_file_triggers_reindex(fresh_archive):
    add_frames(fresh_archive, 2)
    a = service.get_archive()
    f = next(fresh_archive.rglob("*.fits"))
    later = time.time() + 5
    os.utime(f, (later, later))
    assert service.get_archive() is not a


def test_reindex_drops_cached_spectra_and_trackers(fresh_archive, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_invalidate_archive_caches", lambda: calls.append(1))
    service.get_archive()
    add_frames(fresh_archive, 1)
    service.get_archive()
    assert calls == [1]
    # and the real invalidation clears both caches
    monkeypatch.undo()
    service._spectrum_cached.cache_clear()
    service.spectrum(RA, DEC, "2026-Q1", 6.0)
    assert service._spectrum_cached.cache_info().currsize == 1
    service._TRACKERS[("k",)] = None
    service._invalidate_archive_caches()
    assert service._spectrum_cached.cache_info().currsize == 0 and not service._TRACKERS


def test_rescan_interval_is_respected(fresh_archive, monkeypatch):
    monkeypatch.setattr(service, "ARCHIVE_RESCAN_S", 3600.0)
    a = service.get_archive()
    add_frames(fresh_archive, 1)
    assert service.get_archive() is a                           # not re-checked within the interval
    monkeypatch.setattr(service, "ARCHIVE_RESCAN_S", 0.0)       # 0 = never re-check
    assert service.get_archive() is a


def test_data_dir_change_is_followed(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "ARCHIVE_RESCAN_S", 1e-6)
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    add_frames(tmp_path / "two", 2)
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path / "one"))
    service.reset_archive()
    assert service.get_archive().n_spherex == 0
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path / "two"))
    assert service.get_archive().n_spherex == 2
    service.reset_archive()
