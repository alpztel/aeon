"""Quarter (epoch) handling of real SPHEREx data.

* A caller that only knows a position (AI classifier, multi-mission SED) gets the epoch whose real
  data measure the most bands - not 2026-Q1, where most targets only have the physical model.
* A moving catalog object (PX-2026-09 moves ~0.1 deg per quarter) is followed to each epoch.
* Archive frames are filed by calendar quarter whatever the year; the year really observed is
  reported (observed_quarter / epoch_folded) so 2025 frames are never shown as 2026 data.
"""

from __future__ import annotations

import pytest

from aeon import bands, ephem, service
from aeon.catalog import ENTRIES_BY_ID
from aeon.epochs import epoch_year
from conftest import assert_schema
from spherex_fixture import make_spherex_file

WISE = (133.7589, -7.2421)


def frames(root, tag, ra, dec, n_bands, month, year=2026, src=3000.0):
    """One frame per AEON band k = 0, 2, 4, ... (n_bands frames) centred on (ra, dec)."""
    (root / tag).mkdir(parents=True, exist_ok=True)
    for i, k in enumerate(range(0, 2 * n_bands, 2)):
        make_spherex_file(root / tag / f"{tag}_{k:03d}.fits", ra, dec, n=40,
                          date=f"{year}-{month:02d}-{1 + i % 27:02d}T{i % 24:02d}:00:00",
                          detector=int(bands.ARRAY_ID[k]), wave_um=float(bands.WAVELENGTH_UM[k]),
                          wave_slope_um_per_px=0.0, source=(ra, dec, src), noise_mjysr=0.002, seed=k)


@pytest.fixture()
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(service, "ARCHIVE_RESCAN_S", 0)
    service.reset_archive()
    service._invalidate_archive_caches()
    yield tmp_path
    service.reset_archive()
    service._invalidate_archive_caches()


def test_auto_epoch_picks_the_real_epoch_with_most_bands(archive):
    frames(archive, "q2", *WISE, n_bands=40, month=5)                 # 2026-Q2: 40 bands
    frames(archive, "q4", *WISE, n_bands=48, month=11, year=2025)     # 2025-11 -> filed as "2026-Q4": 48 bands
    s = service.spectrum(*WISE, None, 9.3)
    sel = s["pipeline"]["epoch_selection"]
    assert s["pipeline"]["data_mode"] == "fits_archive"
    assert s["epoch"] == sel["chosen"] == "2026-Q4"
    assert sel["candidates"]["2026-Q2"]["n_bands_measured"] == 40
    assert sel["candidates"]["2026-Q1"]["data_mode"] == "physical_model"
    # the 2026-Q4 data were observed in 2025: said so, never presented as 2026
    assert s["pipeline"]["observed_quarter"] == "2025-Q4" and s["pipeline"]["epoch_folded"] is True
    q2 = service.spectrum(*WISE, "2026-Q2", 9.3)
    assert q2["pipeline"]["observed_quarter"] == "2026-Q2" and q2["pipeline"]["epoch_folded"] is False


def test_explicit_epoch_is_unchanged_and_has_no_selection(archive):
    frames(archive, "q2", *WISE, n_bands=40, month=5)
    s = service.spectrum(*WISE, "2026-Q1", 9.3)
    assert s["epoch"] == "2026-Q1" and s["pipeline"]["data_mode"] == "physical_model"
    assert "epoch_selection" not in s["pipeline"]


def test_no_real_data_anywhere_keeps_the_default_epoch_model(archive):
    frames(archive, "q2", *WISE, n_bands=40, month=5)
    s = service.spectrum(10.0, 10.0, None, 9.3)
    assert s["epoch"] == "2026-Q1" and s["pipeline"]["data_mode"] == "physical_model"
    assert set(s["pipeline"]["epoch_selection"]["candidates"]) == {"2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"}


def test_moving_target_is_followed_to_the_epoch_with_data(archive):
    px = ENTRIES_BY_ID["px-2026-09"]
    q1 = ephem.apparent_position(px, epoch_year("2026-Q1"))
    q2 = ephem.apparent_position(px, epoch_year("2026-Q2"))
    frames(archive, "px", *q1, n_bands=40, month=2)                   # real data only in 2026-Q1
    s = service.spectrum(q2[0], q2[1], None, 9.3)                      # the caller knows the Q2 position
    assert s["epoch"] == "2026-Q1" and s["pipeline"]["data_mode"] == "fits_archive"
    assert s["matched_object"]["id"] == "px-2026-09"


def test_cutout_provenance_reports_the_observed_quarter(archive):
    frames(archive, "q4", *WISE, n_bands=10, month=11, year=2025)
    c = service.cutout(*WISE, "2026-Q4", 32, 6.2, None, False)
    assert c["data_mode"] == "fits_archive"
    assert c["provenance"]["observed_quarter"] == "2025-Q4" and c["provenance"]["epoch_folded"] is True


def test_rescan_forgets_auto_choices(archive):
    frames(archive, "q2", *WISE, n_bands=40, month=5)
    assert service.spectrum(*WISE, None, 9.3)["epoch"] == "2026-Q2"
    frames(archive, "q3", *WISE, n_bands=50, month=8)
    service.reset_archive()
    service.get_archive()                                              # re-index -> caches invalidated
    service._invalidate_archive_caches()
    assert service.spectrum(*WISE, None, 9.3)["epoch"] == "2026-Q3"


def test_api_spectrum_without_epoch_matches_the_contract(archive, client):
    frames(archive, "q2", *WISE, n_bands=40, month=5)
    r = client.get("/api/v1/spectrum", params={"ra": WISE[0], "dec": WISE[1]})
    assert r.status_code == 200
    assert_schema(r.json(), "Spectrum")
    assert r.json()["epoch"] == "2026-Q2"


def test_observed_quarter_helper():
    assert service.observed_quarter(["2025-10-31T17:21:36", "2025-11-20T00:00:00", "2025-12-13T08:51:01"]) == "2025-Q4"
    assert service.observed_quarter(["2026-01-01T00:00:00"]) == "2026-Q1"
    assert service.observed_quarter([]) is None
