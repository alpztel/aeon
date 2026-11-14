"""Offline tests of the SPHEREx Level 2 archive path (synthetic files with the real L2 layout)."""

import math

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from aeon import archive as A
from aeon import bands, service
from conftest import assert_schema
from spherex_fixture import MJYSR_PER_UJY_PX, flag, make_spherex_file

RA, DEC = 133.786, -7.244


# --------------------------------------------------------------------------------------------
# Reading: HDU, units, mask, epoch, wavelength
# --------------------------------------------------------------------------------------------

def test_index_reads_spherex_structure(tmp_path):
    make_spherex_file(tmp_path / "a.fits", RA, DEC, date="2025-05-05T16:49:00", detector=3)
    arch = A.FitsArchive(tmp_path)
    (img,) = arch.images
    assert img.kind == "spherex" and img.detector == 3
    assert img.unit == "MJy/sr"
    assert img.epoch == "2026-Q2"                      # May -> Q2 (calendar quarter rule)
    assert img.date_obs.startswith("2025-05-05")
    assert abs(img.scale_arcsec - 6.15) < 1e-6
    assert img.psf_fwhm_arcsec == pytest.approx(7.45) and img.omega_arcsec2 == pytest.approx(37.86)


@pytest.mark.parametrize("date,epoch", [("2025-11-20T00:00:00", "2026-Q4"), ("2026-02-01T00:00:00", "2026-Q1"),
                                        ("2026-09-30T23:00:00", "2026-Q3"), ("2026-04-01T00:00:00", "2026-Q2")])
def test_epoch_is_calendar_quarter(date, epoch):
    h = fits.Header()
    h["MJD-AVG"] = A.Time(date).mjd
    assert A._epoch_of(h) == epoch
    h2 = fits.Header()
    h2["DATE-OBS"] = date
    assert A._epoch_of(h2) == epoch


def test_epoch_matches_nominal_rule_for_2026():
    # For 2026 dates the calendar quarter equals the nearest nominal AEON epoch (old behaviour),
    # except within ~1 day of a boundary (2026.25/.50/.75 vs 1 Apr/1 Jul/1 Oct).
    for doy in range(1, 365, 3):
        y = 2026 + (doy - 0.5) / 365.0
        if min(abs(y - b) for b in (2026.25, 2026.5, 2026.75)) < 2.5 / 365:
            continue
        t = A.Time(y, format="decimalyear")
        nearest = min(A.EPOCHS, key=lambda k: abs(A.EPOCHS[k] - t.decimalyear))
        assert A.epoch_for_time(t) == nearest


def test_units_mjysr_to_ujy_per_pixel(tmp_path):
    make_spherex_file(tmp_path / "a.fits", RA, DEC, background_mjysr=1.0)
    arch = A.FitsArchive(tmp_path)
    for scale in (6.15, 3.0, 10.0):
        im, var, w = arch.resampled(arch.images[0], RA, DEC, 16, scale)
        expected = 1e12 / A.ARCSEC2_PER_SR * scale ** 2        # 1 MJy/sr over one output pixel
        assert np.nanmedian(im) == pytest.approx(expected, rel=1e-4)
    assert A.MJY_SR_TO_UJY_ARCSEC2 == pytest.approx(23.5045, rel=1e-5)


def test_flagged_pixels_are_nan_but_source_flag_kept(tmp_path):
    bad = {(10, 11): flag("HOT"), (20, 21): flag("TRANSIENT") | flag("SOURCE"),
           (30, 31): flag("SOURCE"), (5, 6): flag("DICHROIC")}
    make_spherex_file(tmp_path / "a.fits", RA, DEC, flags=bad)
    arch = A.FitsArchive(tmp_path)
    sb, var, mask = arch.read(arch.images[0])
    assert np.isnan(sb[10, 11]) and np.isnan(sb[20, 21]) and np.isnan(var[10, 11])
    assert np.isfinite(sb[30, 31]) and np.isfinite(sb[5, 6])
    assert mask.sum() == 2
    assert A.SPHEREX_REJECT_MASK & flag("SOURCE") == 0


def test_wavelength_lookup_matches_astropy_tab(tmp_path):
    p = make_spherex_file(tmp_path / "a.fits", RA, DEC, wave_um=2.3647, wave_slope_um_per_px=-0.0005)
    with fits.open(p) as hdul:
        hdr = hdul["IMAGE"].header
        sw = WCS(hdr, fobj=hdul, key="W")
        for x, y in [(0, 0), (23.5, 23.5), (10.25, 40.5), (47, 3)]:
            lam_ast, bw_ast = sw.pixel_to_world_values(x, y)
            lam_own, bw_own = A.wave_table_lookup(hdr, hdul["WCS-WAVE"].data, x, y)
            assert lam_own == pytest.approx(float(lam_ast), abs=1e-6)
            assert bw_own == pytest.approx(float(bw_ast), abs=1e-6)
            assert lam_own == pytest.approx(2.3647 - 0.0005 * (x - 23.5), abs=1e-5)
            assert A.spherex_wavelength(hdul, x, y)[0] == pytest.approx(lam_own, abs=1e-6)


def test_frame_wavelength_and_band_at_target(tmp_path):
    k = 40
    make_spherex_file(tmp_path / "a.fits", RA, DEC, wave_um=float(bands.WAVELENGTH_UM[k]), wave_slope_um_per_px=0.0)
    arch = A.FitsArchive(tmp_path)
    (fr,) = arch.frames(RA, DEC, "2026-Q2")
    assert fr.band == k and fr.wavelength_um == pytest.approx(bands.WAVELENGTH_UM[k], abs=1e-5)
    assert arch.frames(RA, DEC, "2026-Q2", band=k) and not arch.frames(RA, DEC, "2026-Q2", band=k + 1)
    assert arch.frames(RA + 1.0, DEC, "2026-Q2") == []        # off the frame


def test_band_of_wavelength():
    for k in (0, 16, 17, 50, 101):
        assert A.band_of_wavelength(float(bands.WAVELENGTH_UM[k])) == k
    assert A.band_of_wavelength(0.3) is None and A.band_of_wavelength(7.0) is None


def test_resampled_is_north_up_east_left(tmp_path):
    # Point source 30" east and 18" north of centre in a frame rotated by 162.5 deg.
    dra = 30.0 / 3600 / math.cos(math.radians(DEC))
    src = (RA + dra, DEC + 18.0 / 3600, 5e4)
    make_spherex_file(tmp_path / "a.fits", RA, DEC, source=src, background_mjysr=0.0)
    arch = A.FitsArchive(tmp_path)
    im, _, w = arch.resampled(arch.images[0], RA, DEC, 32, 6.15)
    iy, ix = np.unravel_index(np.nanargmax(im), im.shape)
    c = (32 - 1) / 2
    assert ix < c and iy > c                    # east = left (smaller x), north = up (larger y)
    assert ix == pytest.approx(c - 30 / 6.15, abs=1) and iy == pytest.approx(c + 18 / 6.15, abs=1)
    # Flux conservation: the resampled point source keeps its total flux.
    assert np.nansum(im) == pytest.approx(5e4, rel=0.05)


def test_visit_selection_prefers_nominal_year(tmp_path):
    make_spherex_file(tmp_path / "a.fits", RA, DEC, date="2025-05-05T00:00:00", seed=1)
    make_spherex_file(tmp_path / "b.fits", RA, DEC, date="2026-05-01T00:00:00", seed=2)
    arch = A.FitsArchive(tmp_path)
    fr = arch.frames(RA, DEC, "2026-Q2")
    assert [f.image.path.name for f in fr] == ["b.fits"]


def test_generic_archive_still_supported(tmp_path):
    from aeon import sky
    img, w, _ = sky.render(150.0, 2.0, [2026.125], 64)
    sky.to_fits(img, w, {"AEONEPOC": "2026-Q1"}).writeto(tmp_path / "tile.fits")
    arch = A.FitsArchive(tmp_path)
    assert arch.images[0].kind == "generic"
    cut, _ = arch.cutout(arch.images[0], 150.0, 2.0, 32)
    # uJy/pixel in, uJy/pixel out at the same scale: identical pixels at the centre.
    assert cut[16, 16] == pytest.approx(img[32, 32], rel=1e-6) or abs(cut[16, 16] - img[32, 32]) < 1e-3 * abs(img).max()


# --------------------------------------------------------------------------------------------
# Service / API on a SPHEREx archive
# --------------------------------------------------------------------------------------------

@pytest.fixture()
def spherex_archive(tmp_path, monkeypatch):
    """Two visits (May and November 2025) of a field with a moving source, plus LVF coverage of
    40 AEON bands in May for the spectrum."""
    flux = 2000.0
    for i, k in enumerate(range(10, 90, 2)):              # 40 bands in Q2
        make_spherex_file(tmp_path / f"q2_{k:03d}.fits", RA, DEC, n=40, date=f"2025-05-{5 + i % 20:02d}T12:00:00",
                          detector=int(bands.ARRAY_ID[k]), wave_um=float(bands.WAVELENGTH_UM[k]),
                          wave_slope_um_per_px=0.0, source=(RA, DEC, flux), noise_mjysr=0.002, seed=k)
    for i, k in enumerate(range(10, 30, 4)):              # 5 bands in Q4, source moved 15" north
        make_spherex_file(tmp_path / f"q4_{k:03d}.fits", RA, DEC, n=40, date=f"2025-11-{5 + i:02d}T12:00:00",
                          detector=int(bands.ARRAY_ID[k]), wave_um=float(bands.WAVELENGTH_UM[k]),
                          wave_slope_um_per_px=0.0, source=(RA, DEC + 15 / 3600, flux), noise_mjysr=0.002, seed=100 + k)
    arch = A.FitsArchive(tmp_path)
    monkeypatch.setattr(service, "get_archive", lambda: arch)
    return arch, flux


def test_cutout_uses_spherex_frames(client, spherex_archive):
    body = client.get("/api/v1/sky/cutout", params={"ra": RA, "dec": DEC, "epoch": "2026-Q2", "size_px": 32}).json()
    assert_schema(body, "Image")
    assert body["data_mode"] == "fits_archive"
    prov = body["provenance"]
    assert prov["n_frames"] == 40 and prov["obs_date_range"][0].startswith("2025-05")
    assert prov["source"].startswith("IRSA SPHEREx")
    # Model fallback where the archive has no data (Q1).
    q1 = client.get("/api/v1/sky/cutout", params={"ra": RA, "dec": DEC, "epoch": "2026-Q1", "size_px": 32}).json()
    assert q1["data_mode"] == "physical_model" and "provenance" not in q1


def test_cutout_band_selects_lvf_frame(client, spherex_archive):
    body = client.get("/api/v1/sky/cutout", params={"ra": RA, "dec": DEC, "epoch": "2026-Q2", "size_px": 32, "band": 20}).json()
    assert body["data_mode"] == "fits_archive" and body["provenance"]["n_frames"] == 1
    assert body["provenance"]["frames"][0]["band"] == 20
    odd = client.get("/api/v1/sky/cutout", params={"ra": RA, "dec": DEC, "epoch": "2026-Q2", "size_px": 32, "band": 21}).json()
    assert odd["data_mode"] == "physical_model"


def test_cutout_fits_header_labels_real_data(client, spherex_archive):
    import io
    r = client.get("/api/v1/sky/cutout", params={"ra": RA, "dec": DEC, "epoch": "2026-Q2", "size_px": 32, "format": "fits"})
    with fits.open(io.BytesIO(r.content)) as hdul:
        h = hdul[0].header
        assert h["DATAMODE"] == "fits_archive" and h["TELESCOP"] == "SPHEREx" and h["NFRAMES"] == 40


def test_difference_on_archive_matches_bands(client, spherex_archive):
    body = client.post("/api/v1/analysis/difference",
                       json={"ra": RA, "dec": DEC, "epoch_1": "2026-Q2", "epoch_2": "2026-Q4", "size_px": 32}).json()
    assert_schema(body, "DifferenceResult")
    assert body["data_mode"] == "fits_archive"
    # Only the 5 bands seen in both visits enter each epoch image.
    assert body["image_1"]["provenance"]["n_frames"] == 5 == body["image_2"]["provenance"]["n_frames"]
    assert body["dt_years_observed"] == pytest.approx(0.5, abs=0.05)
    signs = {d["sign"] for d in body["detections"]}
    assert {"positive", "negative"} <= signs          # the moving source leaves a +/- pair


def test_difference_never_mixes_archive_and_model(client, spherex_archive):
    body = client.post("/api/v1/analysis/difference",
                       json={"ra": RA, "dec": DEC, "epoch_1": "2026-Q2", "epoch_2": "2026-Q3", "size_px": 32}).json()
    assert body["data_mode"] == "physical_model"
    assert "provenance" not in body["image_1"]


def test_spectrum_from_lvf_frames(client, spherex_archive):
    _, flux = spherex_archive
    body = client.get("/api/v1/spectrum", params={"ra": RA, "dec": DEC, "epoch": "2026-Q2"}).json()
    assert_schema(body, "Spectrum")
    p = body["pipeline"]
    assert p["data_mode"] == "fits_archive" and p["n_bands_measured"] == 40
    m = np.array(p["measured"])
    assert m.sum() == 40 and m[10] and not m[11] and m[88]
    assert np.all(np.diff(body["wavelength_um"]) > 0)
    f, e = np.array(body["flux_ujy"]), np.array(body["flux_err_ujy"])
    assert np.median(f[m]) == pytest.approx(flux, rel=0.1)
    assert np.all(e[~m] > np.median(e[m]))                     # filled bands are visibly less certain


def test_spectrum_falls_back_with_reason(client, spherex_archive):
    body = client.get("/api/v1/spectrum", params={"ra": RA, "dec": DEC, "epoch": "2026-Q4"}).json()
    assert_schema(body, "Spectrum")
    p = body["pipeline"]
    assert p["data_mode"] == "physical_model" and len(body["flux_ujy"]) == 102
    assert "only 5 of 102 bands" in p["archive_fallback_reason"]


def test_health_counts_spherex_frames(client, spherex_archive):
    body = client.get("/api/v1/health").json()
    assert_schema(body, "Health")
    assert body["engines"]["archive_spherex_frames"] == "45"
