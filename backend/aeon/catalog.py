"""In-memory DuckDB catalog of named objects (demo targets + real reference sources).

Positions are stored at a reference epoch with proper motions and propagated linearly to the
requested epoch. Cone searches use the haversine great-circle distance inside DuckDB.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

import duckdb


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str
    ra: float                      # deg, at ref_epoch
    dec: float                     # deg, at ref_epoch
    object_class: str
    mag_ab_w2: float | None
    ref_epoch: float = 2016.0
    pm_ra_cosdec_arcsec_yr: float = 0.0
    pm_dec_arcsec_yr: float = 0.0
    distance_au: float | None = None
    distance_pc: float | None = None
    teff_k: float | None = None
    redshift: float | None = None
    is_demo: bool = False
    is_synthetic: bool = False
    aliases: tuple[str, ...] = ()
    description: dict[str, str] = field(default_factory=dict)


ENTRIES: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        id="wise-0855", name="WISE J085510.83-071442.5", ra=133.79513, dec=-7.24514,
        object_class="cold_brown_dwarf", mag_ab_w2=17.23, ref_epoch=2010.5,
        pm_ra_cosdec_arcsec_yr=-8.118, pm_dec_arcsec_yr=0.680, distance_pc=2.28, teff_k=250.0,
        is_demo=True, aliases=("WISE 0855", "WISE 0855-0714", "W0855"),
        description={
            "en": "Coldest known brown dwarf (~250 K) at 2.3 pc. Its ~8.1\"/yr proper motion makes a "
                  "clear +/- dipole between survey epochs in difference mode; water-ice clouds and "
                  "strong CH4/H2O absorption shape its 4-5 um peak.",
            "tr": "Bilinen en soğuk kahverengi cüce (~250 K), 2,3 pc uzaklıkta. ~8,1\"/yıl özdevinimi, "
                  "Görüntü Farkı modunda tarama dönemleri arasında belirgin bir +/- dipol oluşturur; "
                  "güçlü CH4/H2O soğurması 4-5 µm tepesini şekillendirir.",
        },
    ),
    CatalogEntry(
        id="rw-aur", name="RW Aurigae", ra=76.95642, dec=30.40142,
        object_class="young_variable_star", mag_ab_w2=8.7, ref_epoch=2016.0,
        distance_pc=183.0, teff_k=4100.0, is_demo=True, aliases=("RW Aur", "RW Aur A", "HD 240764"),
        description={
            "en": "Young T Tauri star with a disrupted disk. Variable circumstellar extinction dims the "
                  "short-wavelength bands while the warm inner disk brightens beyond 3 um, so the 102-band "
                  "spectrum changes from quarter to quarter.",
            "tr": "Diski bozulmuş genç bir T Tauri yıldızı. Değişken çevresel sönümleme kısa dalga "
                  "bantlarını karartırken sıcak iç disk 3 µm ötesinde parlar; 102 bantlık tayf çeyrekten "
                  "çeyreğe değişir.",
        },
    ),
    CatalogEntry(
        id="px-2026-09", name="PX-2026-09", ra=51.20000, dec=14.80000,
        object_class="planet_x_candidate", mag_ab_w2=22.6, ref_epoch=2026.0,
        pm_ra_cosdec_arcsec_yr=110.0 * 0.8829476, pm_dec_arcsec_yr=110.0 * 0.4694716,  # 110"/yr at PA 62 deg
        distance_au=520.0, is_demo=True, is_synthetic=True,
        aliases=("Planet X", "Planet 9", "Planet Nine", "PX-2026-09", "Gezegen X"),
        description={
            "en": "Injected synthetic test candidate: a methane-rich ice giant at ~520 AU moving ~110\"/yr "
                  "(PA 62 deg). Below 3 sigma in every single frame; shift-and-stack along its motion recovers it. "
                  "It does not exist on the real sky - it validates the detection pipeline end to end.",
            "tr": "Sisteme enjekte edilmiş sentetik test adayı: ~520 AU uzaklıkta, ~110\"/yıl (KA 62°) hızla "
                  "hareket eden metan zengini bir buz devi. Tekil karelerde 3 sigmanın altında; hareket yönünde "
                  "kaydır-ve-yığ ile ortaya çıkar. Gerçek gökyüzünde yoktur - algılama hattını uçtan uca doğrular.",
        },
    ),
    CatalogEntry(
        id="luhman-16", name="WISE J104915.57-531906.1", ra=162.32820, dec=-53.31840,
        object_class="cold_brown_dwarf", mag_ab_w2=10.6, ref_epoch=2010.5,
        pm_ra_cosdec_arcsec_yr=-2.759, pm_dec_arcsec_yr=0.354, distance_pc=2.0, teff_k=1300.0,
        aliases=("Luhman 16", "Luhman 16AB"),
        description={"en": "Nearest brown dwarf binary (L/T transition), 2.0 pc.",
                     "tr": "En yakın kahverengi cüce çifti (L/T geçişi), 2,0 pc."},
    ),
    CatalogEntry(
        id="wise-1828", name="WISEPA J182831.08+265037.8", ra=277.12950, dec=26.84383,
        object_class="cold_brown_dwarf", mag_ab_w2=17.6, ref_epoch=2010.5,
        pm_ra_cosdec_arcsec_yr=1.020, pm_dec_arcsec_yr=0.174, distance_pc=9.9, teff_k=325.0,
        aliases=("WISE 1828", "WISE 1828+2650"),
        description={"en": "Archetypal Y dwarf with extremely red near- to mid-IR colours.",
                     "tr": "Yakın-orta kızılötesinde aşırı kırmızı renkleriyle örnek bir Y cücesi."},
    ),
    CatalogEntry(
        id="barnard", name="Barnard's Star", ra=269.45208, dec=4.69339, ref_epoch=2000.0,
        object_class="main_sequence_star", mag_ab_w2=7.3,
        pm_ra_cosdec_arcsec_yr=-0.798, pm_dec_arcsec_yr=10.328, distance_pc=1.83, teff_k=3200.0,
        aliases=("GJ 699", "Barnard"),
        description={"en": "M4 dwarf with the largest proper motion of any star (10.4\"/yr).",
                     "tr": "Bilinen en büyük özdevinime (10,4\"/yıl) sahip M4 cücesi."},
    ),
    CatalogEntry(
        id="tw-hya", name="TW Hydrae", ra=165.46587, dec=-34.70473, ref_epoch=2016.0,
        object_class="young_variable_star", mag_ab_w2=10.2, distance_pc=60.1, teff_k=4000.0,
        aliases=("TW Hya",),
        description={"en": "Nearest classical T Tauri star with a face-on protoplanetary disk.",
                     "tr": "Yüzü bize dönük ön-gezegen diskine sahip en yakın klasik T Tauri yıldızı."},
    ),
    CatalogEntry(
        id="18-sco", name="18 Scorpii", ra=243.90529, dec=-8.36944, ref_epoch=2016.0,
        object_class="main_sequence_star", mag_ab_w2=7.2, distance_pc=14.1, teff_k=5810.0,
        aliases=("HD 146233", "18 Sco"),
        description={"en": "Solar twin; a reference main-sequence spectrum.",
                     "tr": "Güneş ikizi; referans anakol tayfı."},
    ),
)

ENTRIES_BY_ID = {e.id: e for e in ENTRIES}


class Catalog:
    def __init__(self) -> None:
        self._con = duckdb.connect(":memory:")
        self._lock = threading.Lock()
        self._con.execute(
            """
            CREATE TABLE objects (
                id VARCHAR PRIMARY KEY, name VARCHAR, aliases VARCHAR,
                ra DOUBLE, dec DOUBLE, ref_epoch DOUBLE,
                pm_ra DOUBLE, pm_dec DOUBLE, object_class VARCHAR, payload VARCHAR
            )
            """
        )
        rows = [
            (e.id, e.name, " | ".join(e.aliases), e.ra, e.dec, e.ref_epoch,
             e.pm_ra_cosdec_arcsec_yr, e.pm_dec_arcsec_yr, e.object_class, json.dumps(asdict(e)))
            for e in ENTRIES
        ]
        self._con.executemany("INSERT INTO objects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    # Position of each object at epoch t, computed in SQL.
    _POS = """
        SELECT *,
          ra + pm_ra * (? - ref_epoch) / 3600.0 / cos(radians(dec)) AS ra_t,
          dec + pm_dec * (? - ref_epoch) / 3600.0 AS dec_t
        FROM objects
    """

    def cone(self, ra: float, dec: float, radius_arcmin: float, t_year: float, limit: int = 50) -> list[dict[str, Any]]:
        sql = f"""
            WITH p AS ({self._POS})
            SELECT payload, ra_t, dec_t,
              7200.0 * degrees(asin(sqrt(
                pow(sin(radians(dec_t - ?) / 2), 2) +
                cos(radians(?)) * cos(radians(dec_t)) * pow(sin(radians(ra_t - ?) / 2), 2)
              ))) AS sep_arcsec
            FROM p
            WHERE sep_arcsec <= ?
            ORDER BY sep_arcsec
            LIMIT ?
        """
        with self._lock:
            rows = self._con.execute(sql, [t_year, t_year, dec, dec, ra, radius_arcmin * 60.0, limit]).fetchall()
        return [self._row(payload, ra_t, dec_t, sep) for payload, ra_t, dec_t, sep in rows]

    def by_name(self, q: str, t_year: float, limit: int = 50) -> list[dict[str, Any]]:
        key = "".join(ch for ch in q.lower() if ch.isalnum())
        if not key:
            return []
        sql = f"""
            WITH p AS ({self._POS})
            SELECT payload, ra_t, dec_t,
              CASE WHEN lower(id) = ? THEN 0
                   WHEN regexp_replace(lower(name), '[^a-z0-9]', '', 'g') = ? THEN 1
                   ELSE 2 END AS rank
            FROM p
            WHERE lower(id) = ?
               OR regexp_replace(lower(name), '[^a-z0-9]', '', 'g') LIKE '%' || ? || '%'
               OR regexp_replace(lower(aliases), '[^a-z0-9|]', '', 'g') LIKE '%' || ? || '%'
            ORDER BY rank, name
            LIMIT ?
        """
        with self._lock:
            rows = self._con.execute(sql, [t_year, t_year, q.lower(), key, q.lower(), key, key, limit]).fetchall()
        return [self._row(payload, ra_t, dec_t, None) for payload, ra_t, dec_t, _ in rows]

    @staticmethod
    def _row(payload: str, ra_t: float, dec_t: float, sep: float | None) -> dict[str, Any]:
        d = json.loads(payload)
        d["ra"] = round(ra_t % 360.0, 7)
        d["dec"] = round(dec_t, 7)
        d["aliases"] = list(d["aliases"])
        d["separation_arcsec"] = None if sep is None else round(sep, 3)
        d["source"] = "catalog"
        return d


def position_at(entry: CatalogEntry, t_year: float) -> tuple[float, float]:
    """Linear proper-motion propagation (adequate for |dt| of decades at these rates)."""
    import math

    dt = t_year - entry.ref_epoch
    dec = entry.dec + entry.pm_dec_arcsec_yr * dt / 3600.0
    ra = entry.ra + entry.pm_ra_cosdec_arcsec_yr * dt / 3600.0 / math.cos(math.radians(entry.dec))
    return ra % 360.0, dec


_catalog: Catalog | None = None


def get_catalog() -> Catalog:
    global _catalog
    if _catalog is None:
        _catalog = Catalog()
    return _catalog
