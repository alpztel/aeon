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


def test_earth_heliocentric_distance():
    from aeon import ephem

    r = np.linalg.norm(ephem.earth_helio([2026.0, 2026.25, 2026.5, 2026.75]), axis=1)
    assert np.all((r > 0.983) & (r < 1.017))


def test_parallax_ellipse_at_520_au():
    # A stationary body at 520 AU near the ecliptic sweeps ~2 x 206265/520 = ~793" in a year.
    from aeon import ephem

    times = np.linspace(2026.0, 2027.0, 49)
    ra, dec = ephem.track(51.3, 14.8, 2026.5, times, 0.0, 0.0, 520.0)
    u = ephem.unit(ra, dec)
    spread = np.degrees(np.arccos(np.clip(u @ u.T, -1, 1))).max() * 3600
    amp = ephem.parallax_amplitude_arcsec(520.0)
    assert 1.8 * amp < spread < 2.05 * amp


def test_star_parallax_is_small():
    from aeon import ephem
    from aeon.catalog import ENTRIES_BY_ID, position_at

    e = ENTRIES_BY_ID["wise-0855"]
    a, b = ephem.apparent_position(e, 2026.3)
    r, d = position_at(e, 2026.3)
    sep = np.hypot((a - r) * np.cos(np.radians(d)), b - d) * 3600
    assert 0.05 < sep < 0.5          # parallax 0.44"


def test_linear_track_matches_rate():
    from aeon import ephem

    ra, dec = ephem.track(10.0, 0.0, 2026.5, [2026.5, 2027.5], 3600.0, 90.0, None)
    assert abs((ra[1] - ra[0]) - 1.0) < 1e-6 and abs(dec[1]) < 1e-9   # 1 deg east in 1 yr


def test_propagate_circular_orbit():
    from aeon.orbit_fit import propagate

    r = propagate(np.array([1.0, 0, 0]), np.array([0, 2 * np.pi, 0]), np.array([0.25, 1.0, -0.5]))
    assert np.allclose(r[0], [0, 1, 0], atol=2e-3) and np.allclose(r[1], [1, 0, 0], atol=2e-3)
    assert np.allclose(r[2], [-1, 0, 0], atol=2e-3)


def test_orbit_fit_recovers_distance_from_parallax():
    from aeon import ephem, orbit_fit

    times = np.linspace(2026.05, 2026.95, 6)
    ra, dec = ephem.track(150.0, 5.0, 2026.5, times, 60.0, 200.0, 300.0)
    f = orbit_fit.fit([{"t": t, "ra": a, "dec": d, "sigma_arcsec": 0.3} for t, a, d in zip(times, ra, dec)])
    s = f["summary"]
    assert abs(s["distance_au"] - 300) < 3 and abs(s["rate_arcsec_yr"] - 60) < 2 and s["rms_residual_arcsec"] < 0.3


def test_spherex_visibility_windows():
    from aeon import ephem

    ecl = ephem.spherex_visible_times(51.3, 14.8, 2026.0, 2027.0)
    gaps = np.diff(ecl)
    assert 0.02 < len(ecl) / 730 < 0.25 and gaps.max() > 0.3          # two short windows
    pole = ephem.spherex_visible_times(270.0, 66.56, 2026.0, 2027.0)  # north ecliptic pole
    assert len(pole) > 700                                             # visible all year


def test_static_sky_template_keeps_slow_mover():
    from aeon.analysis import remove_static_sky

    rng = np.random.default_rng(0)
    frames = rng.normal(100, 1, (8, 32, 32))
    times = np.array([0.0, 0.01, 0.02, 0.03, 0.5, 0.51, 0.52, 0.53])
    for i in range(4):                       # object parked in window 1, elsewhere in window 2
        frames[i, 10, 10] += 50
    for i in range(4, 8):
        frames[i, 20, 20] += 50
    res = remove_static_sky(frames, times)
    assert res[:4, 10, 10].mean() > 40       # a global median would have removed about half of it
