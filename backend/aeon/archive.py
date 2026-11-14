"""Real FITS archive access (AEON_DATA_DIR).

Any 2-D image FITS file with a celestial WCS can be dropped into the archive directory. The epoch
is read from the `AEONEPOC` keyword (e.g. "2026-Q1") or derived from `MJD-OBS` / `DATE-OBS`.
Cutouts are taken with astropy's Cutout2D at the file's native pixel scale. Units are taken as
uJy/pixel unless `BUNIT` says MJy/sr, which is converted using the pixel solid angle.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.nddata import Cutout2D
from astropy.time import Time
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales

from .epochs import EPOCHS


@dataclass
class ArchiveImage:
    path: Path
    epoch: str
    wcs: WCS
    shape: tuple[int, int]
    scale_arcsec: float


def _epoch_of(header: fits.Header) -> str | None:
    if "AEONEPOC" in header and header["AEONEPOC"] in EPOCHS:
        return header["AEONEPOC"]
    t = None
    if "MJD-OBS" in header:
        t = Time(header["MJD-OBS"], format="mjd")
    elif "DATE-OBS" in header:
        try:
            t = Time(header["DATE-OBS"])
        except ValueError:
            return None
    if t is None:
        return None
    year = t.decimalyear
    return min(EPOCHS, key=lambda k: abs(EPOCHS[k] - year))


class FitsArchive:
    def __init__(self, root: str | os.PathLike | None) -> None:
        self.root = Path(root) if root else None
        self.images: list[ArchiveImage] = []
        if self.root and self.root.is_dir():
            self.scan()

    def scan(self) -> None:
        self.images.clear()
        for p in sorted(self.root.glob("**/*.fits")) + sorted(self.root.glob("**/*.fits.gz")):
            try:
                with fits.open(p, memmap=True) as hdul:
                    hdu = next(h for h in hdul if getattr(h, "data", None) is not None and h.data.ndim == 2)
                    w = WCS(hdu.header)
                    epoch = _epoch_of(hdu.header) or _epoch_of(hdul[0].header)
                    if not w.has_celestial or epoch is None:
                        continue
                    scale = float(np.mean(proj_plane_pixel_scales(w.celestial)) * 3600.0)
                    self.images.append(ArchiveImage(p, epoch, w.celestial, hdu.data.shape, scale))
            except (OSError, StopIteration, ValueError):
                continue

    @property
    def available(self) -> bool:
        return bool(self.images)

    def find(self, ra: float, dec: float, epoch: str) -> ArchiveImage | None:
        c = SkyCoord(ra * u.deg, dec * u.deg)
        for img in self.images:
            if img.epoch != epoch:
                continue
            x, y = img.wcs.world_to_pixel(c)
            if 0 <= x < img.shape[1] and 0 <= y < img.shape[0]:
                return img
        return None

    def cutout(self, img: ArchiveImage, ra: float, dec: float, size_px: int) -> tuple[np.ndarray, WCS]:
        with fits.open(img.path) as hdul:
            hdu = next(h for h in hdul if getattr(h, "data", None) is not None and h.data.ndim == 2)
            data = np.asarray(hdu.data, dtype=float)
            if str(hdu.header.get("BUNIT", "")).strip().lower() in ("mjy/sr", "mjy sr-1"):
                data = data * 1e12 * (img.scale_arcsec / 206264.806) ** 2       # MJy/sr -> uJy/pixel
        cut = Cutout2D(data, SkyCoord(ra * u.deg, dec * u.deg), (size_px, size_px), wcs=img.wcs,
                       mode="partial", fill_value=np.nan)
        out = cut.data
        if np.isnan(out).any():
            out = np.where(np.isnan(out), np.nanmedian(out), out)
        return out, cut.wcs
