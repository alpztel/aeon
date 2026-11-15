"""Blend flag of real spectra: bands whose aperture light is centred on a neighbour.

Modelled on WISE 0855 (live 2025-Q4 frames): the Y dwarf is bright only beyond ~3.5 um; a
background star ~7" away inside the 9.3" aperture dominates 0.75-3 um.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from aeon import bands, photometry, service
from spherex_fixture import make_spherex_file

RA, DEC = 133.7589, -7.2421
NEIGHBOUR = (RA - 6.0 / 3600 / math.cos(math.radians(DEC)), DEC + 3.0 / 3600)     # 6" W, 3" N


def target_flux(lam):
    return 600.0 if lam > 3.5 else 2.0


def star_flux(lam):
    return 500.0 * (1.0 / lam) ** 2 if lam < 3.2 else 5.0


@pytest.fixture()
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(service, "ARCHIVE_RESCAN_S", 0)
    service.reset_archive()
    service._invalidate_archive_caches()
    yield tmp_path
    service.reset_archive()
    service._invalidate_archive_caches()


def build(root, with_neighbour):
    for i, k in enumerate(range(0, bands.N_BANDS, 2)):
        lam = float(bands.WAVELENGTH_UM[k])
        extra = [(NEIGHBOUR[0], NEIGHBOUR[1], star_flux(lam))] if with_neighbour else None
        make_spherex_file(root / f"f{k:03d}.fits", RA, DEC, n=40, date=f"2026-05-{1 + i % 27:02d}T00:00:00",
                          detector=int(bands.ARRAY_ID[k]), wave_um=lam, wave_slope_um_per_px=0.0,
                          source=(RA, DEC, target_flux(lam)), extra_sources=extra, noise_mjysr=0.0015, seed=k)


def test_neighbour_inside_the_aperture_flags_the_bands_it_dominates(archive):
    build(archive, with_neighbour=True)
    s = service.spectrum(RA, DEC, "2026-Q2", 9.3)
    p = s["pipeline"]
    assert p["data_mode"] == "fits_archive"
    lam = np.array(s["wavelength_um"])
    blended = np.array(p["blended"])
    measured = np.array(p["measured"])
    short = measured & (lam < 2.5)
    long_ = measured & (lam > 3.8)
    assert blended[short].mean() > 0.8            # neighbour-dominated bands flagged
    assert not blended[long_].any()               # the target's own bands are not
    assert p["n_bands_blended"] == int(blended.sum()) and 4.0 < p["blend_offset_arcsec"] < 9.0
    assert len(p["blended"]) == 102


def test_isolated_target_has_no_blended_band(archive):
    build(archive, with_neighbour=False)
    p = service.spectrum(RA, DEC, "2026-Q2", 9.3)["pipeline"]
    assert p["n_bands_blended"] == 0 and p["blend_offset_arcsec"] is None


def test_centroid_offset_basics():
    yy, xx = np.mgrid[0:25, 0:25]
    on = 100.0 * np.exp(-((xx - 12.0) ** 2 + (yy - 12.0) ** 2) / 2.0)
    assert photometry.centroid_offset_px(on, 12.0, 12.0, 1.5, (4.5, 7.5)) < 0.05
    near = 100.0 * np.exp(-((xx - 13.1) ** 2 + (yy - 12.0) ** 2) / 2.0)
    assert photometry.centroid_offset_px(near, 12.0, 12.0, 1.5, (4.5, 7.5)) > 0.5
    assert math.isnan(photometry.centroid_offset_px(np.zeros((25, 25)), 12.0, 12.0, 1.5, (4.5, 7.5)))
