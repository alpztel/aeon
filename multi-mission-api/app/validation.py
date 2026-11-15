"""Stage 4: validation scorecard. AEON's own result next to an independent reference.

Reference = SIMBAD astrometry and radial velocity (simbad.py), pushed through the same kinematics
and the same galpy orbit as AEON's inputs, plus peer-reviewed age / mass / temperature values
(fixtures/validation_reference.json, each with its source).

Every row holds two measured or modelled numbers and a verdict from a fixed rule (do the two
intervals overlap?). The written summary is assembled from those rows only: it cannot state a
number that is not in the table.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from . import simbad
from .age_mass import MJUP_PER_MSUN
from .kinematics import space_velocity

REFERENCE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "validation_reference.json"
PARTIAL_GAP = 0.25            # intervals that miss each other by < 25 % of the reference value: "partial"
# Two single numbers (no error bar on either side) agree when they differ by less than this: the precision
# to which different astrometric solutions of the same star reproduce a velocity or an orbit.
POINT_TOLERANCE = {"u_lsr_km_s": 1.0, "v_lsr_km_s": 1.0, "w_lsr_km_s": 1.0, "v_tot_km_s": 1.0, "r_peri_kpc": 0.05,
                   "r_apo_kpc": 0.05, "z_max_kpc": 0.02, "eccentricity": 0.01, "d_min_pc": 0.02, "t_min_kyr": 0.2}

LABELS = {
    "teff_k": ("effective temperature", "etkin sıcaklık", "K"),
    "age_gyr": ("age", "yaş", "Gyr"),
    "mass": ("mass", "kütle", ""),
    "u_lsr_km_s": ("U (LSR)", "U (LSR)", "km/s"),
    "v_lsr_km_s": ("V (LSR)", "V (LSR)", "km/s"),
    "w_lsr_km_s": ("W (LSR)", "W (LSR)", "km/s"),
    "v_tot_km_s": ("total space velocity", "toplam uzay hızı", "km/s"),
    "r_peri_kpc": ("Galactic pericentre", "Galaktik enberi", "kpc"),
    "r_apo_kpc": ("Galactic apocentre", "Galaktik enöte", "kpc"),
    "z_max_kpc": ("maximum height above the plane", "düzlemden en büyük yükseklik", "kpc"),
    "eccentricity": ("Galactic eccentricity", "Galaktik dışmerkezlik", ""),
    "d_min_pc": ("closest approach to the Sun", "Güneş'e en yakın geçiş", "pc"),
    "t_min_kyr": ("time of closest approach", "en yakın geçiş zamanı", "kyr"),
}

CAUSES = {
    "rv_envelope": ("AEON has no measured radial velocity for this object: its value is the envelope for RV = -30, 0, +30 km/s",
                    "AEON'da bu cisim için ölçülmüş radyal hız yok: değer, RV = -30, 0, +30 km/s zarfıdır"),
    "ref_rv_missing": ("SIMBAD lists no radial velocity either, so the reference is an envelope too",
                       "SIMBAD'da da radyal hız yok; referans da bir zarftır"),
    "blended_bands": ("part of the SPHEREx aperture flux belongs to a neighbouring source (blended bands were left out)",
                      "SPHEREx açıklığındaki akının bir kısmı komşu kaynağa ait (karışmış bantlar dışarıda bırakıldı)"),
    "binary": ("the literature resolves this object into two components; AEON fits their combined light as one body, which makes it look brighter and so more massive or hotter",
               "literatür bu cismi iki bileşene ayırıyor; AEON birleşik ışığı tek cisim olarak çözer, bu da onu daha parlak, dolayısıyla daha kütleli ya da sıcak gösterir"),
    "disk": ("the SED includes emission from a circumstellar disk and no extinction correction is applied",
             "SED, yıldız çevresi diskin ışımasını içerir ve sönükleşme düzeltmesi uygulanmaz"),
    "assumed_age": ("the literature age is a range the authors assumed, not a measurement",
                    "literatür yaşı ölçüm değil, yazarların varsaydığı bir aralıktır"),
    "model_teff": ("AEON's temperature is the one the evolution model implies for the fitted brightness, not a spectroscopic fit",
                   "AEON sıcaklığı tayf uyumu değil, ölçülen parlaklık için evrim modelinin verdiği değerdir"),
    "colour_teff": ("AEON's temperature is the colour temperature of the SED peak, which differs from the effective temperature of a cool, molecule-rich photosphere",
                    "AEON sıcaklığı SED tepesinin renk sıcaklığıdır; soğuk, molekül zengini bir fotosferin etkin sıcaklığından farklıdır"),
    "kinematic_age_single_star": ("a kinematic age for one star is a probability, not a clock: young and old stars overlap in velocity",
                                  "tek bir yıldız için kinematik yaş bir saat değil olasılıktır: genç ve yaşlı yıldızların hızları örtüşür"),
    "main_sequence": ("a main-sequence star barely changes for billions of years, so its luminosity and temperature do not fix its age",
                      "anakol yıldızı milyarlarca yıl neredeyse değişmez; parlaklığı ve sıcaklığı yaşını belirlemez"),
    "astrometry_source": ("AEON and SIMBAD use different astrometric solutions (see the sources of each)",
                          "AEON ve SIMBAD farklı astrometrik çözümler kullanıyor (kaynaklarına bakın)"),
}


@lru_cache(maxsize=1)
def reference_data() -> dict[str, Any]:
    return json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))


def _interval(v: Any) -> tuple[float, float] | None:
    """A quantity as (lo, hi). Accepts a number, [lo, hi], {value, err}, {lo, hi} (open ends allowed)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return (float(v), float(v)) if math.isfinite(float(v)) else None
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return float(min(v)), float(max(v))
    if isinstance(v, dict):
        if v.get("lo") is not None or v.get("hi") is not None:
            lo = float(v["lo"]) if v.get("lo") is not None else -math.inf
            hi = float(v["hi"]) if v.get("hi") is not None else math.inf
            return lo, hi
        if v.get("value") is not None:
            err = float(v.get("err") or 0.0)
            return float(v["value"]) - err, float(v["value"]) + err
    return None


def compare(aeon: Any, ref: Any, tolerance: float = 0.0) -> str:
    a, r = _interval(aeon), _interval(ref)
    if a is None or r is None:
        return "not_comparable"
    if a[0] <= r[1] and r[0] <= a[1]:
        return "consistent"
    gap = a[0] - r[1] if a[0] > r[1] else r[0] - a[1]
    if gap <= tolerance:
        return "consistent"
    finite = [abs(x) for x in r if math.isfinite(x)]
    scale = max(finite) if finite else 0.0
    return "partial" if scale > 0 and gap / scale < PARTIAL_GAP else "discrepant"


def _fmt(v: Any) -> str:
    iv = _interval(v)
    if iv is None:
        return "-"
    lo, hi = iv
    f = lambda x: f"{x:.3g}"  # noqa: E731
    if lo == hi:
        return f(lo)
    if not math.isfinite(lo):
        return f"< {f(hi)}"
    if not math.isfinite(hi):
        return f"> {f(lo)}"
    if isinstance(v, dict) and v.get("value") is not None and v.get("err"):
        return f"{f(float(v['value']))} +/- {f(float(v['err']))}"
    return f"{f(lo)} to {f(hi)}"


def _row(key: str, aeon: Any, ref: Any, *, unit: str | None = None, aeon_source: str | None = None,
         ref_source: str | None = None, causes: list[str] | None = None, why_missing: str | None = None) -> dict[str, Any]:
    en, tr, default_unit = LABELS[key]
    verdict = compare(aeon, ref, POINT_TOLERANCE.get(key, 0.0))
    used = [c for c in (causes or []) if c in CAUSES]
    return {
        "key": key, "label": {"en": en, "tr": tr}, "unit": default_unit if unit is None else unit,
        "aeon": aeon, "reference": ref, "aeon_text": _fmt(aeon), "reference_text": _fmt(ref),
        "aeon_source": aeon_source, "reference_source": ref_source,
        "agreement": verdict,
        "causes": used if verdict != "not_comparable" else [],
        "explanation": ({"en": "; ".join(CAUSES[c][0] for c in used), "tr": "; ".join(CAUSES[c][1] for c in used)}
                        if used and verdict != "not_comparable" else None),
        "not_comparable_reason": why_missing if verdict == "not_comparable" else None,
    }


def _lit_sources(lit: dict[str, Any] | None) -> str | None:
    if not lit or not lit.get("sources"):
        return None
    return "; ".join(f"{s['ref']} [{s['bibcode']}]" for s in lit["sources"])


def _solutions(galactic: dict[str, Any] | None, key: str) -> Any:
    if not galactic or galactic.get("status") != "ok":
        return None
    if galactic.get("rv_status") == "measured":
        return galactic["solutions"][0][key]
    return list(galactic["envelope"][key])


def build(*, target_id: str | None, name: str | None, ra: float, dec: float, aeon_astrometry: dict[str, Any] | None,
          aeon_galactic: dict[str, Any], age_mass: dict[str, Any], aeon_orbit: dict[str, Any] | None,
          spherex_note: dict[str, Any] | None, orbit_fn: Callable[[dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any]:
    ref_entry = reference_data()["targets"].get(target_id or "", {}) if target_id else {}
    lit = ref_entry.get("literature")
    sim = simbad.lookup(ref_entry.get("simbad_id") or name, ra, dec, ref_entry.get("simbad_snapshot"))
    ref_astro = simbad.astrometry(sim.get("row"))
    ref_galactic = space_velocity(ref_astro) if ref_astro else None
    ref_orbit = orbit_fn(ref_astro) if ref_astro else None
    lit_src = _lit_sources(lit)
    sim_src = None
    if sim.get("row"):
        r = sim["row"]
        sim_src = f"SIMBAD {r.get('main_id')}: parallax [{r.get('plx_bibcode')}], proper motion [{r.get('pm_bibcode')}]"
        if r.get("rvz_radvel") is not None:
            sim_src += f", RV {r['rvz_radvel']:g} km/s [{r.get('rvz_bibcode')}]"
        sim_src += " -> same kinematics / galpy orbit"

    common: list[str] = []
    note = spherex_note or {}
    if note.get("blend_suspected") or (isinstance(note.get("n_bands_blended"), int) and note["n_bands_blended"] > 0):
        common.append("blended_bands")
    if lit and lit.get("binary"):
        common.append("binary")
    inputs = age_mass.get("inputs") or {}
    if inputs.get("disk"):
        common.append("disk")
    mode = age_mass.get("mode")
    rows: list[dict[str, Any]] = []
    no_lit = "no curated literature value for this quantity" if lit else "no curated literature entry for this object"
    am_missing = (age_mass.get("spectral") or {}).get("reason") or age_mass.get("reason")

    # --- temperature
    mass = age_mass.get("mass") or {}
    if mass.get("model_teff_k"):
        m = mass["model_teff_k"]
        teff = {"lo": m["lo"], "hi": m["hi"], "median": m["median"]}
        teff_src = ("Sonora Bobcat" if mode == "substellar_w2" else "BHAC15") + " model at the joint solution"
        teff_cause = "model_teff"
    else:
        teff, teff_src, teff_cause = None, None, None
    rows.append(_row("teff_k", teff, (lit or {}).get("teff_k"), aeon_source=teff_src, ref_source=lit_src,
                     causes=common + ([teff_cause] if teff_cause else []), why_missing=am_missing if teff is None else no_lit))

    # --- age
    joint = age_mass.get("joint") or {}
    age = {"lo": joint["lo_gyr"], "hi": joint["hi_gyr"], "median": joint["median_gyr"]} if joint.get("median_gyr") is not None else None
    lit_age = (lit or {}).get("age_gyr")
    age_causes = list(common)
    if lit_age and lit_age.get("kind") == "assumed":
        age_causes.append("assumed_age")
    if aeon_galactic.get("rv_status") == "marginalized_envelope":
        age_causes.append("rv_envelope")
    age_causes.append("kinematic_age_single_star")
    if mode == "stellar_hr" and not inputs.get("disk"):
        age_causes.append("main_sequence")
    rows.append(_row("age_gyr", age, lit_age, aeon_source=" + ".join(joint.get("channels") or []) or joint.get("method"),
                     ref_source=lit_src, causes=age_causes, why_missing=joint.get("reason") or am_missing if age is None else no_lit))

    # --- mass (M_Jup for substellar fits, M_sun otherwise)
    in_mjup = mode == "substellar_w2" or bool(lit and lit.get("mass_mjup") and not lit.get("mass_msun"))
    unit = "M_Jup" if in_mjup else "M_sun"
    a_mass = None
    if mass.get("median_mjup") is not None:
        suffix = "mjup" if in_mjup else "msun"
        a_mass = {"lo": mass[f"lo_{suffix}"], "hi": mass[f"hi_{suffix}"], "median": mass[f"median_{suffix}"]}
    l_mass = None
    if lit:
        src = lit.get("mass_mjup") if in_mjup else lit.get("mass_msun")
        other = lit.get("mass_msun") if in_mjup else lit.get("mass_mjup")
        if src:
            l_mass = src
        elif other:
            k = MJUP_PER_MSUN if in_mjup else 1.0 / MJUP_PER_MSUN
            l_mass = {a: (round(b * k, 5) if isinstance(b, (int, float)) else b) for a, b in other.items() if a != "components"}
    rows.append(_row("mass", a_mass, l_mass, unit=unit, aeon_source=f"evolution models, {mass.get('from') or 'joint'} solution" if a_mass else None,
                     ref_source=lit_src, causes=common, why_missing=am_missing if a_mass is None else no_lit))

    # --- space velocity
    kin_causes: list[str] = []
    if aeon_galactic.get("rv_status") == "marginalized_envelope":
        kin_causes.append("rv_envelope")
    if ref_galactic and ref_galactic.get("rv_status") == "marginalized_envelope":
        kin_causes.append("ref_rv_missing")
    kin_causes.append("astrometry_source")
    a_src = None
    if aeon_astrometry:
        a_src = f"{aeon_astrometry.get('distance_source')}; PM {aeon_astrometry.get('pm_source')}; RV {aeon_astrometry.get('rv_source') or 'not measured'}"
    if sim.get("status") in ("unavailable", "not_found"):
        why_kin = sim.get("reason") or "SIMBAD has no object at this position"
    elif ref_astro is None:
        why_kin = "SIMBAD lists no parallax or proper motion for this object"
    else:
        why_kin = aeon_galactic.get("reason") or "AEON has no distance or proper motion for this object"
    for key in ("u_lsr_km_s", "v_lsr_km_s", "w_lsr_km_s", "v_tot_km_s"):
        rows.append(_row(key, _solutions(aeon_galactic, key), _solutions(ref_galactic, key), aeon_source=a_src,
                         ref_source=sim_src, causes=kin_causes, why_missing=why_kin))

    # --- Galactic orbit and solar encounter
    a_sum = (aeon_orbit or {}).get("summary") or {}
    r_sum = (ref_orbit or {}).get("summary") or {}
    why_orb = why_kin
    if ref_astro is not None and not r_sum:
        why_orb = "the orbit integrator (core backend) did not answer"
    if not a_sum and aeon_galactic.get("status") == "ok":
        why_orb = "the orbit integrator (core backend) did not answer"
    for key in ("r_peri_kpc", "r_apo_kpc", "z_max_kpc", "eccentricity", "d_min_pc", "t_min_kyr"):
        rows.append(_row(key, a_sum.get(key), r_sum.get(key), aeon_source="galpy MWPotential2014, AEON astrometry" if a_sum else None,
                         ref_source=(sim_src or "") and "galpy MWPotential2014, SIMBAD astrometry", causes=kin_causes, why_missing=why_orb))

    counts = {k: sum(1 for r in rows if r["agreement"] == k) for k in ("consistent", "partial", "discrepant", "not_comparable")}
    return {
        "status": "ok" if counts["consistent"] + counts["partial"] + counts["discrepant"] else "no_reference",
        "target_id": target_id,
        "simbad": {k: v for k, v in sim.items() if k != "row"} | {"object": sim.get("row")},
        "literature": lit, "literature_available": bool(lit),
        "reference_astrometry": ref_astro,
        "reference_kinematics": ref_galactic,
        "reference_orbit": ({k: v for k, v in ref_orbit.items() if k in ("engine", "rv_status", "summary", "rv_note")} if ref_orbit else None),
        "rows": rows, "counts": counts,
        "rule": (f"consistent: the two intervals overlap; partial: they miss by less than {PARTIAL_GAP:.0%} of the reference "
                 "value; discrepant: more. AEON intervals are 16-84 % posteriors or RV envelopes; reference intervals are "
                 "the published errors. Velocities and orbit numbers also count as consistent within "
                 "1 km/s, 0.05 kpc (0.02 kpc in z), 0.01 in eccentricity, 0.02 pc and 0.2 kyr."),
        "point_tolerance": POINT_TOLERANCE,
        "synthesis": _synthesis(rows, counts, sim, lit),
    }


def _synthesis(rows: list[dict[str, Any]], counts: dict[str, int], sim: dict[str, Any], lit: dict[str, Any] | None) -> dict[str, str]:
    """Plain-language summary built from the rows only."""
    n = counts["consistent"] + counts["partial"] + counts["discrepant"]
    en, tr = [], []
    if n == 0:
        en.append("No quantity can be compared yet: there is no reference value for this object.")
        tr.append("Henüz karşılaştırılabilecek bir büyüklük yok: bu cisim için referans değer bulunmuyor.")
    else:
        en.append(f"{n} quantities compared: {counts['consistent']} consistent, {counts['partial']} partly consistent, "
                  f"{counts['discrepant']} discrepant.")
        tr.append(f"{n} büyüklük karşılaştırıldı: {counts['consistent']} tutarlı, {counts['partial']} kısmen tutarlı, "
                  f"{counts['discrepant']} tutarsız.")
    for r in rows:
        if r["agreement"] == "not_comparable":
            continue
        unit = f" {r['unit']}" if r["unit"] else ""
        verdict_en = {"consistent": "consistent", "partial": "partly consistent", "discrepant": "discrepant"}[r["agreement"]]
        verdict_tr = {"consistent": "tutarlı", "partial": "kısmen tutarlı", "discrepant": "tutarsız"}[r["agreement"]]
        s_en = f"{r['label']['en'].capitalize()}: AEON {r['aeon_text']}{unit}, reference {r['reference_text']}{unit} - {verdict_en}"
        s_tr = f"{r['label']['tr'].capitalize()}: AEON {r['aeon_text']}{unit}, referans {r['reference_text']}{unit} - {verdict_tr}"
        if r["agreement"] != "consistent" and r["explanation"]:
            s_en += f" ({r['explanation']['en']})"
            s_tr += f" ({r['explanation']['tr']})"
        en.append(s_en + ".")
        tr.append(s_tr + ".")
    if sim.get("status") == "unavailable":
        en.append(f"Velocity and orbit could not be checked: {sim.get('reason')}.")
        tr.append("Hız ve yörünge doğrulanamadı: SIMBAD yanıt vermedi.")
    elif sim.get("status") == "not_found":
        en.append("SIMBAD has no object at this position, so velocity and orbit have no reference.")
        tr.append("SIMBAD'da bu konumda cisim yok; hız ve yörünge için referans bulunmuyor.")
    if not lit:
        en.append("No curated literature values for this object: age, mass and temperature are AEON's result alone.")
        tr.append("Bu cisim için derlenmiş literatür değeri yok: yaş, kütle ve sıcaklık yalnızca AEON'un sonucudur.")
    return {"en": " ".join(en), "tr": " ".join(tr), "method": "rule-based text from the scorecard rows; no language model"}
