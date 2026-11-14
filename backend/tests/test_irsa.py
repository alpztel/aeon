"""Downloader tests. Offline by default; the real IRSA round trip is @pytest.mark.network."""

import io
import urllib.error

import numpy as np
import pytest
from astropy.io import fits
from astropy.io.votable.tree import Field, Resource, TableElement, VOTableFile

from aeon import archive as A
from aeon import irsa
from spherex_fixture import make_spherex_file

URL = ("https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W19_1B/l2b-v27-2026-197/3/"
       "level2_2025W19_1B_0116_1D3_spx_l2b-v27-2026-197.fits")


def _sia_votable(rows):
    vot = VOTableFile()
    res = Resource()
    vot.resources.append(res)
    t = TableElement(vot)
    res.tables.append(t)
    spec = [("access_url", "char"), ("obs_id", "char"), ("energy_bandpassname", "char"), ("dataproduct_type", "char"),
            ("dataproduct_subtype", "char"), ("obs_collection", "char"), ("obs_publisher_did", "char"),
            ("t_min", "double"), ("t_max", "double"), ("em_min", "double"), ("em_max", "double"),
            ("access_estsize", "long")]
    t.fields.extend([Field(vot, name=n, datatype=d, arraysize="*" if d == "char" else None) for n, d in spec])
    t.create_arrays(len(rows))
    for i, r in enumerate(rows):
        t.array[i] = r
    buf = io.BytesIO()
    vot.to_xml(buf)
    return buf.getvalue()


def test_parse_sia_and_filters():
    rows = [
        (URL, "2025W19_1B_0116_1", "SPHEREx-D3", "image", "science", "spherex_dr1", "ivo://x", 60800.70, 60800.701, 1.6301e-6, 2.4346e-6, 65791),
        (URL.replace("/3/", "/6/").replace("1D3", "1D6"), "2025W19_1B_0116_1", "SPHEREx-D6", "image", "science",
         "spherex_dr1", "ivo://y", 60800.70, 60800.701, 4.4115e-6, 5.0096e-6, 65673),
        (URL, "cal", "SPHEREx-D3", "image", "calibration", "spherex_dr1", "ivo://z", 60000.0, 60000.1, 1e-6, 2e-6, 1),
    ]
    recs = irsa.parse_sia(_sia_votable(rows), "spherex_dr1")
    assert len(recs) == 2                                   # calibration product dropped
    assert recs[0].detector == 3 and recs[1].detector == 6
    assert recs[0].em_min_um == pytest.approx(1.6301) and recs[0].date_obs.startswith("2025-05-05")
    assert recs[0].filename == "level2_2025W19_1B_0116_1D3_spx_l2b-v27-2026-197.fits"


def test_urls():
    u = irsa.sia_url(133.786, -7.244, 0.01)
    assert u.startswith("https://irsa.ipac.caltech.edu/SIA?") and "COLLECTION=spherex_dr1" in u and "CIRCLE" in u
    assert irsa.cutout_url(URL, 133.786, -7.244, 96).endswith("?center=133.7860000,-7.2440000&size=96pix")


def test_slim_keeps_aeon_extensions(tmp_path):
    p = make_spherex_file(tmp_path / "raw.fits", 10.0, 20.0, extra_hdus=True)
    raw = p.read_bytes()
    slim = irsa.slim_spherex(raw, provenance={"AEONURL": URL})
    names = [h.name for h in slim]
    assert names == ["PRIMARY", "IMAGE", "FLAGS", "VARIANCE", "ZODI", "WCS-WAVE"]
    assert slim[0].header["AEONURL"] == URL
    out = tmp_path / "slim.fits"
    slim.writeto(out)
    arch = A.FitsArchive(tmp_path)
    assert {i.kind for i in arch.images} == {"spherex"}
    with fits.open(out) as h:
        assert A.spherex_wavelength(h, 3, 3)[0] > 0


def test_slim_rejects_non_spherex():
    buf = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(np.zeros((4, 4)))]).writeto(buf)
    with pytest.raises(irsa.DownloadError):
        irsa.slim_spherex(buf.getvalue())


class _Resp(io.BytesIO):
    def __init__(self, body, length=True):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))} if length else {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_get_retries_then_succeeds(monkeypatch):
    calls = []

    def fake(req, timeout):
        calls.append(timeout)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
        return _Resp(b"ok")

    monkeypatch.setattr(irsa.urllib.request, "urlopen", fake)
    assert irsa.http_get("https://x", timeout=5, retries=3, sleep=lambda s: None) == b"ok"
    assert calls == [5, 5, 5]


def test_http_get_gives_up_and_does_not_retry_404(monkeypatch):
    n = {"c": 0}

    def busy(req, timeout):
        n["c"] += 1
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(irsa.urllib.request, "urlopen", busy)
    with pytest.raises(irsa.DownloadError, match="3 attempts"):
        irsa.http_get("https://x", retries=2, sleep=lambda s: None)
    assert n["c"] == 3

    def missing(req, timeout):
        n["c"] += 1
        raise urllib.error.HTTPError(req.full_url, 404, "nope", {}, None)

    n["c"] = 0
    monkeypatch.setattr(irsa.urllib.request, "urlopen", missing)
    with pytest.raises(irsa.DownloadError, match="404"):
        irsa.http_get("https://x", retries=5, sleep=lambda s: None)
    assert n["c"] == 1


def test_http_get_size_limit(monkeypatch):
    monkeypatch.setattr(irsa.urllib.request, "urlopen", lambda req, timeout: _Resp(b"x" * 1000))
    with pytest.raises(irsa.DownloadError, match="exceeds"):
        irsa.http_get("https://x", max_bytes=100)
    monkeypatch.setattr(irsa.urllib.request, "urlopen", lambda req, timeout: _Resp(b"x" * 1000, length=False))
    with pytest.raises(irsa.DownloadError, match="exceeds"):
        irsa.http_get("https://x", max_bytes=100)


def test_fetch_caches_and_writes_manifest(tmp_path, monkeypatch):
    raw = make_spherex_file(tmp_path / "src.fits", 133.786, -7.244).read_bytes()
    rec = irsa.SiaRecord(URL, "2025W19_1B_0116_1", "SPHEREx-D3", 60800.70, 60800.701, 1.63, 2.43, 65791.0,
                         "spherex_dr1", "ivo://x")
    monkeypatch.setattr(irsa, "query", lambda *a, **k: [rec])
    got = []
    monkeypatch.setattr(irsa, "http_get", lambda url, **k: got.append(url) or raw)
    m = irsa.fetch(133.786, -7.244, data_dir=tmp_path / "data", tag="t", log=lambda *a: None)
    assert m["n_ok"] == 1 and m["frames"][0]["status"] == "downloaded" and "size=96pix" in got[0]
    m2 = irsa.fetch(133.786, -7.244, data_dir=tmp_path / "data", tag="t", log=lambda *a: None)
    assert m2["frames"][0]["status"] == "cached" and len(got) == 1
    assert (tmp_path / "data" / "spherex" / "spherex_dr1" / "t" / "manifest.json").exists()


def test_demo_positions_label_synthetic():
    ra, dec, note = irsa.demo_position("px-2026-09")
    assert "SYNTHETIC" in note
    ra, dec, note = irsa.demo_position("wise-0855")
    assert abs(ra - 133.760) < 0.005 and abs(dec + 7.242) < 0.005      # 2026.0 (pm ~8"/yr)


@pytest.mark.network
def test_real_irsa_round_trip(tmp_path):
    """Query IRSA SIA for WISE 0855 and download one real SPHEREx DR1 cutout."""
    ra, dec, _ = irsa.demo_position("wise-0855")
    recs = irsa.query(ra, dec, 0.5)
    assert len(recs) > 50 and {r.detector for r in recs} == {1, 2, 3, 4, 5, 6}
    m = irsa.fetch(ra, dec, size_px=32, data_dir=tmp_path, tag="w", max_files=1, workers=1, log=lambda *a: None)
    assert m["n_ok"] == 1
    arch = A.FitsArchive(tmp_path)
    (img,) = arch.images
    assert img.kind == "spherex" and img.unit == "MJy/sr"
    lam, bw = arch.wavelength_at(img, ra, dec)
    assert 0.7 < lam < 5.1 and 0 < bw < 0.2
