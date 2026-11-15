"""Regenerate the README figures and the validation scorecard from AEON's own code.

Run from the repository root, with the backend and multi-mission-api requirements installed:

    python docs/figures/make_figures.py

Writes docs/assets/aeon-banner.svg, docs/assets/wise0855-mass-age.svg and
docs/assets/barnard-orbit.svg, and prints the scorecards quoted in README.md.
Everything comes from repository data (published model tables, archive fixtures and the
stored SIMBAD snapshot); no network access is made.
"""

from __future__ import annotations

import math
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "multi-mission-api"), str(ROOT / "backend")]
# The services treat this variable as "offline": no live archive or SIMBAD query, stored snapshots only.
os.environ["PYTEST_CURRENT_TEST"] = "docs/figures (offline)"

from aeon import galactic  # noqa: E402
from app import age_mass, crossmatch, kinematics, validation  # noqa: E402
from app.sed_fitter import fit_multi_mission_sed  # noqa: E402

ASSETS = ROOT / "docs" / "assets"
BG, PANEL, LINE = "#050506", "#0E0E10", "#2A2A2E"
TEXT, SOFT, MUTED = "#ECE8E3", "#C9C3BC", "#8E877F"
SIGNAL, ICE, OK, WARN = "#FF5A1F", "#9DB4F0", "#5FD39A", "#F2B544"
SANS = "'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace"


def text(x, y, s, size=14, fill=TEXT, weight=400, anchor="start", family=SANS, spacing=0):
    s = s.replace("&", "&amp;").replace("<", "&lt;")
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}"{ls}>{s}</text>')


def svg(w, h, body, label):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{label}"><rect width="{w}" height="{h}" rx="18" fill="{BG}"/>{"".join(body)}</svg>\n')


def stars(w, h, n, seed):
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        x, y = rnd.uniform(0, w), rnd.uniform(0, h)
        r = rnd.choice([0.6, 0.8, 1.0, 1.3, 1.7])
        c = rnd.choice([TEXT, TEXT, TEXT, ICE, "#FFD8C2"])
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="{c}" opacity="{rnd.uniform(0.25, 0.85):.2f}"/>')
    return out


# ------------------------------------------------------------------------------------------------ banner

def banner():
    w, h = 1280, 320
    b = stars(w, h, 190, 7)
    b.append(f'<ellipse cx="1010" cy="170" rx="300" ry="104" fill="none" stroke="{SIGNAL}" stroke-width="1.6" '
             f'opacity="0.6" transform="rotate(-16 1010 170)"/>')
    b.append(f'<ellipse cx="1010" cy="170" rx="196" ry="68" fill="none" stroke="{ICE}" stroke-width="1.1" '
             f'opacity="0.45" transform="rotate(-16 1010 170)"/>')
    b.append(f'<circle cx="1010" cy="170" r="6" fill="{WARN}"/>')
    b.append(f'<circle cx="1268" cy="104" r="7" fill="{SIGNAL}"/>')
    b.append(f'<circle cx="826" cy="214" r="4.5" fill="{ICE}"/>')
    b.append(text(64, 82, "NASA SPACE APPS CHALLENGE 2026 · PLANET X & SPHEREX", 15, SIGNAL, 500, family=MONO, spacing=3))
    b.append(text(60, 190, "AEON", 116, TEXT, 700, spacing=-4))
    b.append(text(64, 238, "From raw SPHEREx frames to the age, mass and orbit", 26, SOFT))
    b.append(text(64, 272, "of what moves in the infrared sky.", 26, SOFT))
    return svg(w, h, b, "AEON: from raw SPHEREx frames to the age, mass and orbit of what moves in the infrared sky")


# ------------------------------------------------------------------------------------------------ WISE 0855

def wise0855():
    """Mass-age degeneracy of WISE 0855 and how its Galactic velocity narrows it."""
    g = age_mass.model_grid()
    astro = dict(ra=133.79513, dec=-7.24514, distance_pc=2.28, pm_ra_cosdec_mas_yr=-8118.0, pm_dec_mas_yr=680.0)
    gal = kinematics.space_velocity(astro)
    kin = kinematics.kinematic_age_pdf(gal, 10.0 ** g["log_age"])
    m_abs = 13.704 - 5.0 * math.log10(2.28 / 10.0)          # AllWISE w2mpro (Vega), catalog distance
    r = age_mass.solve({"m_w2": (m_abs, 0.3)}, mode="substellar_w2", kinematic_pdf=kin)
    spec, joint, m, ms = r["spectral"], r["joint"], r["mass"], r["mass_spectral_only"]

    w, h = 960, 540
    L, R, T, B = 86, 40, 118, 92
    x0, x1, y1 = math.log10(0.1), math.log10(12.0), 12.0
    X = lambda a: L + (math.log10(a) - x0) / (x1 - x0) * (w - L - R)
    Y = lambda v: T + (1 - v / y1) * (h - T - B)
    b = [text(36, 52, "Breaking the mass–age degeneracy · WISE 0855−0714", 22, TEXT, 600),
         text(36, 80, "Mass that matches its measured W2 brightness at each age (Sonora Bobcat), and what its Galactic velocity allows",
              14, MUTED)]
    for a in (0.1, 0.3, 1, 3, 10):
        b.append(f'<line x1="{X(a):.1f}" y1="{T}" x2="{X(a):.1f}" y2="{h-B}" stroke="{LINE}"/>')
        b.append(text(X(a), h - B + 22, f"{a:g}", 13, MUTED, anchor="middle", family=MONO))
    for v in range(0, 13, 2):
        b.append(f'<line x1="{L}" y1="{Y(v):.1f}" x2="{w-R}" y2="{Y(v):.1f}" stroke="{LINE}"/>')
        b.append(text(L - 12, Y(v) + 4, str(v), 13, MUTED, anchor="end", family=MONO))
    b.append(text((L + w - R) / 2, h - B + 46, "age (Gyr, log scale)", 13, SOFT, anchor="middle"))
    b.append(f'<text x="28" y="{(T + h - B) / 2:.0f}" font-family="{SANS}" font-size="13" fill="{SOFT}" text-anchor="middle" '
             f'transform="rotate(-90 28 {(T + h - B) / 2:.0f})">mass (M_Jup)</text>')
    b.append(f'<rect x="{L}" y="{Y(ms["hi_mjup"]):.1f}" width="{w-L-R}" height="{Y(ms["lo_mjup"])-Y(ms["hi_mjup"]):.1f}" '
             f'fill="{ICE}" fill-opacity="0.11"/>')
    jx0, jx1 = X(max(joint["lo_gyr"], 0.1)), X(min(joint["hi_gyr"], 12.0))
    b.append(f'<rect x="{jx0:.1f}" y="{Y(m["hi_mjup"]):.1f}" width="{jx1-jx0:.1f}" height="{Y(m["lo_mjup"])-Y(m["hi_mjup"]):.1f}" '
             f'fill="{SIGNAL}" fill-opacity="0.24" stroke="{SIGNAL}" stroke-width="2"/>')
    pts = [(t["age_gyr"], t["mass_mjup"]) for t in r["degeneracy_track"] if 0.1 <= t["age_gyr"] <= 12.0]
    b.append(f'<polyline points="{" ".join(f"{X(a):.1f},{Y(v):.1f}" for a, v in pts)}" fill="none" stroke="{TEXT}" '
             f'stroke-width="3" stroke-linejoin="round"/>')
    b.append(text(L + 14, Y(ms["hi_mjup"]) + 20, f"spectrum alone: {ms['lo_mjup']:.1f}–{ms['hi_mjup']:.1f} M_Jup, "
                  f"age {spec['lo_gyr']:.1f}–{spec['hi_gyr']:.1f} Gyr (unconstrained)", 13, ICE))
    b.append(text(jx0 - 10, Y(m["hi_mjup"]) - 12, f"+ Galactic velocity: {m['lo_mjup']:.1f}–{m['hi_mjup']:.1f} M_Jup, "
                  f"{joint['lo_gyr']:.1f}–{joint['hi_gyr']:.1f} Gyr", 13, SIGNAL, 600, anchor="end"))
    b.append(text(36, h - 20, f"AEON output from repository data · model T_eff at the joint solution ≈ "
                  f"{m['model_teff_k']['median']:.0f} K · Luhman (2014): 225–260 K, 3–10 M_Jup", 12, MUTED))
    return svg(w, h, b, "Mass of WISE 0855 that fits its brightness at each age, narrowed by its Galactic velocity"), r


# ------------------------------------------------------------------------------------------------ Barnard

def barnard_inputs():
    fx = crossmatch._load_fixtures()["targets"]["barnard"]
    return fx, crossmatch._aeon_astrometry(fx["ra_ref"], fx["dec_ref"], fx["gaia"], {"id": "barnard"})


def orbit_fn(a):
    if not a:
        return None
    return galactic.simulate(a["ra"], a["dec"], a["distance_pc"], a["pm_ra_cosdec_mas_yr"], a["pm_dec_mas_yr"],
                             a.get("radial_velocity_km_s"), 250.0, 50.0, 200)


def barnard(res):
    o, e = res["orbits"][0], res["encounters"][0]
    w, h = 960, 510
    b = [text(36, 52, "Past and future orbit · Barnard’s Star", 22, TEXT, 600),
         text(36, 80, "Gaia DR3 astrometry and radial velocity, integrated with galpy in MWPotential2014", 14, MUTED)]
    # left: Galactic plane seen from above
    size, cx0, cy0 = 300, 60, 112
    lim = 16.5
    k = size / 2 / lim
    P = lambda x, y: (cx0 + size / 2 + x * k, cy0 + size / 2 - y * k)
    b.append(f'<rect x="{cx0-18}" y="{cy0-12}" width="{size+36}" height="{size+52}" rx="14" fill="{PANEL}" stroke="{LINE}"/>')
    for rr in (8, 16):
        b.append(f'<circle cx="{cx0+size/2:.1f}" cy="{cy0+size/2:.1f}" r="{rr*k:.1f}" fill="none" stroke="{LINE}"/>')
    sun = " ".join("%.1f,%.1f" % P(x, y) for x, y in zip(res["sun"]["x_kpc"], res["sun"]["y_kpc"]))
    star = " ".join("%.1f,%.1f" % P(x, y) for x, y in zip(o["trajectory"]["x_kpc"], o["trajectory"]["y_kpc"]))
    b.append(f'<polyline points="{sun}" fill="none" stroke="{MUTED}" stroke-width="1.6" stroke-dasharray="5 5"/>')
    b.append(f'<polyline points="{star}" fill="none" stroke="{SIGNAL}" stroke-width="2" stroke-linejoin="round"/>')
    gx, gy = P(0, 0)
    b.append(f'<circle cx="{gx:.1f}" cy="{gy:.1f}" r="6" fill="{WARN}"/>')
    b.append(text(gx, gy + 22, "Galactic centre", 12, SOFT, anchor="middle", family=MONO))
    mid = len(res["sun"]["x_kpc"]) // 2
    sx, sy = P(res["sun"]["x_kpc"][mid], res["sun"]["y_kpc"][mid])
    b.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="5.5" fill="{TEXT}"/>')
    b.append(text(sx + 10, sy - 10, "Sun", 12, SOFT, family=MONO))
    b.append(text(cx0 + size / 2, cy0 + size + 28, f"±{res['span_myr']:.0f} Myr · dashed: the Sun", 12, MUTED, anchor="middle"))
    # right: distance to the Sun
    L, R, T, B = 480, 40, 214, 96
    ts, ds = e["curve"]["t_kyr"], e["curve"]["distance_pc"]
    t0, t1, dmax = min(ts), max(ts), max(ds) * 1.08
    X = lambda t: L + (t - t0) / (t1 - t0) * (w - L - R)
    Y = lambda d: T + (1 - d / dmax) * (h - T - B)
    b.append(text(L, 128, "Closest approach to the Sun", 14, MUTED, family=MONO, spacing=1))
    b.append(text(L, 178, f"{e['d_min_pc']:.2f} pc", 46, SIGNAL, 700))
    b.append(text(L + 190, 178, f"in {e['t_min_kyr'] * 1000:,.0f} years", 22, TEXT))
    for v in range(0, int(dmax) + 1, 2):
        b.append(f'<line x1="{L}" y1="{Y(v):.1f}" x2="{w-R}" y2="{Y(v):.1f}" stroke="{LINE}"/>')
        b.append(text(L - 10, Y(v) + 4, str(v), 12, MUTED, anchor="end", family=MONO))
    b.append(f'<line x1="{X(0):.1f}" y1="{T}" x2="{X(0):.1f}" y2="{h-B}" stroke="{MUTED}" stroke-dasharray="3 4"/>')
    b.append(f'<polyline points="{" ".join(f"{X(t):.1f},{Y(d):.1f}" for t, d in zip(ts, ds))}" fill="none" stroke="{ICE}" '
             f'stroke-width="3" stroke-linejoin="round"/>')
    b.append(f'<circle cx="{X(e["t_min_kyr"]):.1f}" cy="{Y(e["d_min_pc"]):.1f}" r="7" fill="{SIGNAL}"/>')
    for t, lab, anc in ((t0, f"{t0:.0f} kyr", "start"), (0, "today", "middle"), (t1, f"+{t1:.0f} kyr", "end")):
        b.append(text(X(t), h - B + 22, lab, 12, MUTED, anchor=anc, family=MONO))
    b.append(text(L + (w - L - R) / 2, h - B + 46, "distance to the Sun (pc) over ±50 kyr", 13, SOFT, anchor="middle"))
    b.append(text(36, h - 16, f"AEON output from repository data · RV {res['input']['radial_velocity_km_s']:.1f} km/s (Gaia DR3) · "
                  f"{res['engine']}", 12, MUTED))
    return svg(w, h, b, "Barnard's Star orbit around the Galactic centre and its distance to the Sun over 100,000 years")


# ------------------------------------------------------------------------------------------------ scorecards

def scorecard(tid):
    fx = crossmatch._load_fixtures()["targets"][tid]
    gaia, wise = fx["gaia"], fx["wise"]
    sed = crossmatch._build_sed(gaia, wise, [])
    astro = crossmatch._aeon_astrometry(fx["ra_ref"], fx["dec_ref"], gaia, {"id": tid})
    galk = kinematics.space_velocity(astro)
    am = age_mass.estimate(sed=sed, sed_physics=fit_multi_mission_sed(sed), gaia_rows=gaia, wise_rows=wise,
                           spherex_points=[], astrometry=astro, galactic=galk, object_class="main_sequence_star",
                           distance_au=None)
    return validation.build(target_id=tid, name=fx["name"], ra=fx["ra_ref"], dec=fx["dec_ref"], aeon_astrometry=astro,
                            aeon_galactic=galk, age_mass=am, aeon_orbit=orbit_fn(astro), spherex_note={}, orbit_fn=orbit_fn)


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "aeon-banner.svg").write_text(banner(), encoding="utf-8", newline="\n")
    fig, r = wise0855()
    (ASSETS / "wise0855-mass-age.svg").write_text(fig, encoding="utf-8", newline="\n")
    _, astro = barnard_inputs()
    (ASSETS / "barnard-orbit.svg").write_text(barnard(orbit_fn(astro)), encoding="utf-8", newline="\n")
    print("WISE 0855: spectrum alone %.1f-%.1f M_Jup; joint %.1f-%.1f M_Jup, %.1f-%.1f Gyr, model Teff %.0f K" % (
        r["mass_spectral_only"]["lo_mjup"], r["mass_spectral_only"]["hi_mjup"], r["mass"]["lo_mjup"], r["mass"]["hi_mjup"],
        r["joint"]["lo_gyr"], r["joint"]["hi_gyr"], r["mass"]["model_teff_k"]["median"]))
    for tid in ("barnard", "lhs-1140", "trappist-1"):
        v = scorecard(tid)
        print(f"\n{tid}: SIMBAD {v['simbad']['status']} · {v['counts']}")
        print("| Quantity | AEON | Reference | Verdict |\n| --- | --- | --- | --- |")
        for row in v["rows"]:
            unit = f" ({row['unit']})" if row["unit"] else ""
            print(f"| {row['label']['en'].capitalize()}{unit} | {row['aeon_text']} | {row['reference_text']} | {row['agreement']} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
