"""Speed paths of the FITS archive must give exactly the results of the straightforward code.

The real-spectrum and cutout paths avoid per-request file work: the WCS-WAVE table is copied at
indexing, small files' pixels are cached (LRU, bounded), large files are read one window at a time,
a footprint pre-filter skips images far from the target, and the aperture sum skips photutils'
result table. Each test below pins one of these against the reference computation.
"""

from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from astropy.io import fits
from photutils.aperture import CircularAperture, aperture_photometry

from aeon import archive as A
from aeon import bands, photometry, service
from spherex_fixture import flag, make_spherex_file

RA, DEC = 133.786, -7.244
EPOCH = "2026-Q2"


def _spectral_archive(root, n_px=40):
    """One frame per second AEON band (51 frames, >= the 34 bands a real spectrum needs)."""
    for i, k in enumerate(range(0, bands.N_BANDS, 2)):
        make_spherex_file(root / f"f{k:03d}.fits", RA + 0.002 * math.sin(k), DEC + 0.002 * math.cos(k), n=n_px,
                          date=f"2026-05-{1 + i % 28:02d}T{i % 24:02d}:00:00", detector=int(bands.ARRAY_ID[k]),
                          wave_um=float(bands.WAVELENGTH_UM[k]), wave_slope_um_per_px=0.0,
                          source=(RA, DEC, 3000.0), noise_mjysr=0.003, seed=k,
                          flags={(3, 4): flag("HOT"), (36, 2): flag("TRANSIENT")})     # away from the aperture
    return root


@pytest.fixture()
def service_archive(tmp_path, monkeypatch):
    _spectral_archive(tmp_path)
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(service, "ARCHIVE_RESCAN_S", 0)
    service.reset_archive()
    service._spectrum_cached.cache_clear()
    yield tmp_path
    service.reset_archive()
    service._spectrum_cached.cache_clear()


# ----------------------------------------------------------------------------- wavelength model

def test_wave_model_matches_astropy_tab_reader(tmp_path):
    make_spherex_file(tmp_path / "a.fits", RA, DEC, n=48, wave_um=2.3647, wave_slope_um_per_px=-0.0005)
    arch = A.FitsArchive(tmp_path)
    (img,) = arch.images
    assert img.wave is not None and arch.wave_check == "ok"
    with fits.open(img.path) as hdul:
        for x, y in [(0, 0), (5.5, 40.2), (23.5, 23.5), (47, 47), (-0.4, 12.0)]:
            ref = A.spherex_wavelength(hdul, x, y)
            got = A.wave_model_eval(img.wave, x, y)
            assert got == pytest.approx(ref, abs=1e-6)


def test_wavelength_at_needs_no_file_access_after_indexing(tmp_path, monkeypatch):
    make_spherex_file(tmp_path / "a.fits", RA, DEC)
    arch = A.FitsArchive(tmp_path)
    (img,) = arch.images
    expect = A.spherex_wavelength(fits.open(img.path), *arch._contains(img, RA + 0.01, DEC)[1:])
    monkeypatch.setattr(A.fits, "open", lambda *a, **k: pytest.fail("file opened"))
    assert arch.wavelength_at(img, RA + 0.01, DEC) == pytest.approx(expect, abs=1e-6)


def test_wave_model_mismatch_falls_back_to_astropy(tmp_path):
    make_spherex_file(tmp_path / "a.fits", RA, DEC)
    make_spherex_file(tmp_path / "b.fits", RA, DEC, seed=1)
    arch = A.FitsArchive(tmp_path)
    img = arch.images[0]
    ref = arch.wavelength_at(img, RA, DEC)
    cd1, cp1, cv1, *rest = img.wave
    img.wave = (cd1, cp1 + 500.0, cv1, *rest)       # a table this implementation misreads
    with pytest.warns(RuntimeWarning, match="WCS-WAVE mismatch"):
        arch._check_wave_model()
    assert arch.wave_check.startswith("mismatch") and all(i.wave is None for i in arch.images)
    assert arch.wavelength_at(img, RA, DEC) == pytest.approx(ref, abs=1e-6)     # astropy path


# ----------------------------------------------------------------------------- pixel reads

def test_large_file_window_reads_match_full_image(tmp_path):
    n = 600                                          # > CACHE_MAX_PIXELS: never cached, read by window
    make_spherex_file(tmp_path / "big.fits", RA, DEC, n=n, source=(RA + 0.01, DEC - 0.005, 5000.0),
                      noise_mjysr=0.01, flags={(300, 301): flag("HOT"), (5, 590): flag("OVERFLOW")})
    arch = A.FitsArchive(tmp_path)
    (img,) = arch.images
    assert img.shape[0] * img.shape[1] > A.CACHE_MAX_PIXELS
    sb_full, var_full, _ = arch.read(img)
    for ra, dec, size, scale in [(RA, DEC, 64, 6.2), (RA + 0.01, DEC - 0.005, 33, 3.1),
                                 (RA + 0.5, DEC + 0.4, 64, 6.2),            # grid half off the frame
                                 (RA, DEC, 128, 12.0), (RA + 5.0, DEC, 32, 6.2)]:   # last: misses the frame
        im, var, w = arch.resampled(img, ra, dec, size, scale)
        ref = A.resample(sb_full, img.wcs, w, (size, size)) * scale * scale
        np.testing.assert_array_equal(np.isnan(im), np.isnan(ref))
        np.testing.assert_allclose(im[~np.isnan(im)], ref[~np.isnan(ref)], rtol=1e-9, atol=1e-12)
        area_in = img.omega_arcsec2
        vref = A.resample(var_full, img.wcs, w, (size, size)) * area_in * scale * scale
        np.testing.assert_array_equal(np.isnan(var), np.isnan(vref))
        np.testing.assert_allclose(var[~np.isnan(var)], vref[~np.isnan(vref)], rtol=1e-9, atol=1e-15)
    for ra, dec in [(RA, DEC), (RA + 0.01, DEC - 0.005)]:
        stamp, x, y = arch.native_stamp(img, ra, dec, 12)
        _, fx, fy = arch._contains(img, ra, dec)
        ix, iy = int(round(fx)), int(round(fy))
        np.testing.assert_array_equal(stamp, sb_full[iy - 12:iy + 13, ix - 12:ix + 13] * img.omega_arcsec2)


def test_stamp_at_frame_edge_matches_full_image(tmp_path):
    make_spherex_file(tmp_path / "a.fits", RA, DEC, n=40, noise_mjysr=0.01)
    arch = A.FitsArchive(tmp_path)
    (img,) = arch.images
    sb_full, _, _ = arch.read(img)
    _, x0, y0 = arch._contains(img, RA, DEC)
    # walk the target to the frame corner: the stamp is partly off the frame
    ra_c, dec_c = img.wcs.wcs_pix2world([[1.2, 38.6]], 0)[0]
    stamp, x, y = arch.native_stamp(img, ra_c, dec_c, 12)
    ix, iy = 1, 39
    ref = np.full((25, 25), np.nan)
    ys, xs = slice(max(iy - 12, 0), min(iy + 13, 40)), slice(max(ix - 12, 0), min(ix + 13, 40))
    ref[ys.start - (iy - 12):ys.stop - (iy - 12), xs.start - (ix - 12):xs.stop - (ix - 12)] = sb_full[ys, xs] * img.omega_arcsec2
    np.testing.assert_array_equal(stamp, ref)


def test_pixel_cache_is_bounded_and_read_only(tmp_path, monkeypatch):
    for k in range(6):
        make_spherex_file(tmp_path / f"a{k}.fits", RA, DEC, n=40, seed=k, noise_mjysr=0.01)
    arch = A.FitsArchive(tmp_path)
    one = sum(a.nbytes for a in arch._read_file(arch.images[0], None) if a is not None)
    monkeypatch.setattr(A, "PIXEL_CACHE_BYTES", int(2.5 * one))
    first = [arch.read(i)[0].copy() for i in arch.images]
    assert len(arch._pix_cache) == 2 and arch._pix_bytes <= A.PIXEL_CACHE_BYTES
    data, bad, var = next(iter(arch._pix_cache.values()))
    assert not data.flags.writeable and not bad.flags.writeable and not var.flags.writeable
    again = [arch.read(i)[0] for i in arch.images]      # evicted entries are re-read, same values
    for a, b in zip(first, again):
        np.testing.assert_array_equal(a, b)
    arch.scan()
    assert not arch._pix_cache and arch._pix_bytes == 0


def test_pixel_cache_can_be_disabled(tmp_path, monkeypatch):
    make_spherex_file(tmp_path / "a.fits", RA, DEC, n=40)
    monkeypatch.setattr(A, "PIXEL_CACHE_BYTES", 0)
    arch = A.FitsArchive(tmp_path)
    arch.read(arch.images[0])
    assert not arch._pix_cache


# ----------------------------------------------------------------------------- coverage pre-filter

def test_footprint_prefilter_never_drops_a_covering_image(tmp_path):
    centres = [(RA, DEC), (RA + 0.08, DEC + 0.05), (359.97, 0.01), (0.02, -0.02), (45.0, 89.6), (225.0, 89.7),
               (10.0, -89.5), (200.0, 30.0)]
    for k, (ra, dec) in enumerate(centres):
        make_spherex_file(tmp_path / f"c{k}.fits", ra, dec, n=48, rot_deg=37.0 * k, seed=k)
    arch = A.FitsArchive(tmp_path)
    rng = np.random.default_rng(3)
    queries = [(ra + dra, dec + ddec) for ra, dec in centres for dra, ddec in rng.uniform(-0.12, 0.12, (25, 2))]
    queries += [(0.0, 0.0), (359.999, 0.0), (123.0, 89.9), (0.0, -90.0), (300.0, 10.0)]
    for ra, dec in queries:
        ra = ra % 360.0
        dec = float(np.clip(dec, -90.0, 90.0))
        brute = {id(i) for i in arch.images if arch._contains(i, ra, dec, margin_px=1.0)[0]}
        cand = {id(i) for i in arch._candidates(ra, dec)}
        assert brute <= cand, (ra, dec)


# ----------------------------------------------------------------------------- aperture sum

def test_aperture_sum_equals_aperture_photometry():
    rng = np.random.default_rng(11)
    for k in range(1500):
        img = rng.normal(0.0, 1.0, (25, 25))
        if k % 2:
            img[rng.integers(0, 25, 8), rng.integers(0, 25, 8)] = np.nan
        ap = CircularAperture((rng.uniform(-2, 26), rng.uniform(-2, 26)), r=rng.uniform(0.3, 4.0))
        ref = float(aperture_photometry(img, ap)["aperture_sum"][0])
        got = photometry._aperture_sum(img, ap)
        if math.isnan(ref):
            assert math.isnan(got)
        else:
            assert got == pytest.approx(ref, rel=1e-12, abs=1e-12)


# ----------------------------------------------------------------------------- whole service

def test_second_position_spectrum_and_cutout_open_no_file(service_archive, monkeypatch):
    first = service.spectrum(RA, DEC, EPOCH, 6.0)
    assert first["pipeline"]["data_mode"] == "fits_archive"
    service.cutout(RA, DEC, EPOCH, 32, 6.2, None, False)
    opened = []
    real_open = A.fits.open
    monkeypatch.setattr(A.fits, "open", lambda *a, **k: opened.append(a[0]) or real_open(*a, **k))
    s = service.spectrum(RA + 0.0015, DEC - 0.001, EPOCH, 6.0)
    c = service.cutout(RA + 0.003, DEC + 0.002, EPOCH, 32, 6.2, None, False)
    assert s["pipeline"]["data_mode"] == "fits_archive" and c["data_mode"] == "fits_archive"
    assert opened == []


def test_concurrent_spectra_equal_serial(service_archive):
    positions = [(RA + 0.0007 * k, DEC - 0.0005 * k) for k in range(8)]
    serial = [service._archive_spectrum(ra, dec, EPOCH, 6.0, None)[0] for ra, dec in positions]
    assert all(s is not None for s in serial)
    service.reset_archive()                       # cold caches: threads race to fill them
    barrier = threading.Barrier(8)

    def run(p):
        barrier.wait()
        return service._archive_spectrum(p[0], p[1], EPOCH, 6.0, None)[0]

    with ThreadPoolExecutor(8) as ex:
        for _ in range(3):
            got = list(ex.map(run, positions))
            assert got == serial
