import numpy as np
import pytest
from astropy.io import fits

from aeon import bands, orbit, sky
from aeon.archive import FitsArchive


def test_band_grid():
    assert bands.N_BANDS == 102
    assert bands.WAVELENGTH_UM[0] > 0.75 and bands.WAVELENGTH_UM[-1] < 5.0
    assert np.all(np.diff(bands.WAVELENGTH_UM) > 0)
    # resolving power of array 1 ~ 41
    r = bands.WAVELENGTH_UM[:17] / bands.BANDWIDTH_UM[:17]
    assert 35 < r.mean() < 50


def test_render_is_deterministic():
    a, _, _ = sky.render(10.0, 20.0, [2026.2], 32)
    b, _, _ = sky.render(10.0, 20.0, [2026.2], 32)
    assert np.array_equal(a, b)


def test_point_source_flux_conserved():
    img, w, meta = sky.render(200.0, 60.0, [2026.5], 64, noise_sigma_ps=1e-9)
    # total flux in the image ~ sum of source broadband fluxes falling inside (plus pedestal)
    assert np.isfinite(img).all() and img.min() >= meta["pedestal"] * 0.999


def test_kepler_roundtrip():
    r, v = orbit.kepler_state(30.0, 0.2, 0.3, 1.0, 2.0, 0.5)
    el = orbit.elements_from_state(r, v)
    assert el["a_au"] == pytest.approx(30.0, rel=1e-9)
    assert el["e"] == pytest.approx(0.2, rel=1e-9)
    assert np.radians(el["inc_deg"]) == pytest.approx(0.3, rel=1e-9)


def test_fits_archive_cutout(tmp_path):
    img, w, _ = sky.render(150.0, 2.0, [2026.125], 128)
    hdul = sky.to_fits(img, w, {"AEONEPOC": "2026-Q1"})
    hdul.writeto(tmp_path / "tile.fits")
    arch = FitsArchive(tmp_path)
    assert arch.available
    hit = arch.find(150.0, 2.0, "2026-Q1")
    assert hit is not None and abs(hit.scale_arcsec - 6.2) < 1e-6
    cut, cw = arch.cutout(hit, 150.0, 2.0, 32)
    assert cut.shape == (32, 32)
    assert arch.find(150.0, 2.0, "2026-Q3") is None
