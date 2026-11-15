"""Every catalog entry is usable end to end: searchable by id and alias, valid against the contract,
and its physical-model spectrum is as bright at W2 as the catalog says."""

from __future__ import annotations

import math

import numpy as np
import pytest

from aeon import bands, ephem, service
from aeon.catalog import ENTRIES
from aeon.epochs import epoch_year
from conftest import assert_schema


@pytest.fixture(autouse=True)
def model_only(monkeypatch):
    monkeypatch.delenv("AEON_DATA_DIR", raising=False)
    service.reset_archive()
    service._invalidate_archive_caches()
    yield
    service.reset_archive()
    service._invalidate_archive_caches()


def test_ids_are_unique():
    ids = [e.id for e in ENTRIES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e.id)
def test_entry_is_found_by_id_and_alias(entry):
    for q in (entry.id, *entry.aliases[:1]):
        res = service.search_catalog(q, None, None, 1, False, 10, "2026-Q2")
        assert entry.id in [r["id"] for r in res["results"]], q
        for r in res["results"]:
            assert_schema(r, "CatalogObject")


@pytest.mark.parametrize("entry", [e for e in ENTRIES if e.mag_ab_w2 is not None], ids=lambda e: e.id)
def test_model_spectrum_matches_the_catalog_w2(entry):
    ra, dec = ephem.apparent_position(entry, epoch_year("2026-Q2"))      # where it is in that epoch
    s = service.spectrum(ra, dec, "2026-Q2", 9.3)
    assert s["pipeline"]["data_mode"] == "physical_model"
    assert (s.get("matched_object") or {}).get("id") == entry.id
    lam = np.asarray(bands.WAVELENGTH_UM, dtype=float)
    w2 = (lam >= 4.4) & (lam <= 4.8)
    flux = float(np.median(np.asarray(s["flux_ujy"])[w2]))
    assert flux > 0
    mag = 23.9 - 2.5 * math.log10(flux)
    assert abs(mag - entry.mag_ab_w2) < 0.6, (entry.id, mag, entry.mag_ab_w2)
