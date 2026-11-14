"""AEON full-stack stress test through the Nginx gateway.

Phases
  P0 baseline     sequential latency of every endpoint
  P1 ramp         mixed realistic traffic at increasing concurrency
  P2 heavy        concurrent blind searches, large shift-stacks, orbit fits
  P3 abuse        oversized payloads, extreme parameters, candidate flooding
  P4 soak         sustained mixed load (container memory sampled by run.sh)
  P5 resilience   ai-engine stopped mid-load, then restarted (driven by run.sh via --phase)

External archives are never load-tested: cross-match traffic only uses the fixture targets (served
from the snapshot), the AI engine runs without an LLM key, and no GitHub token is configured.

Output: lines prefixed STRESS| (parsed by the workflow) and stress/results.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

BASE = "http://localhost"
TIMEOUT = 60.0
DEMO = [(133.7586977, -7.2420576), (76.9564207, 30.4014199), (51.295473, 14.8325559)]
FIXTURE_TARGETS = [(133.7607, -7.24219), (76.95642, 30.40142), (162.31488, -53.31836), (277.1295, 26.84383),
                   (269.45208, 4.69339), (165.46587, -34.70473), (243.90529, -8.36944), (51.295473, 14.8325559)]
EPOCHS = ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]
RESULTS: dict = {}


@dataclass
class Stats:
    lat: list = field(default_factory=list)
    codes: dict = field(default_factory=dict)
    timeouts: int = 0
    errors: int = 0

    def add(self, code: int | None, dt: float, kind: str = "") -> None:
        if code is None:
            if kind == "timeout":
                self.timeouts += 1
            else:
                self.errors += 1
            return
        self.codes[code] = self.codes.get(code, 0) + 1
        self.lat.append(dt)

    def summary(self) -> dict:
        n = sum(self.codes.values()) + self.timeouts + self.errors
        lat = sorted(self.lat)

        def pct(p):
            return round(lat[min(len(lat) - 1, int(p * len(lat)))] * 1000, 1) if lat else None

        return {"n": n, "codes": {str(k): v for k, v in sorted(self.codes.items())}, "timeouts": self.timeouts,
                "conn_errors": self.errors, "p50_ms": pct(0.50), "p95_ms": pct(0.95), "p99_ms": pct(0.99),
                "max_ms": round(lat[-1] * 1000, 1) if lat else None,
                "mean_ms": round(statistics.mean(lat) * 1000, 1) if lat else None,
                "5xx": sum(v for k, v in self.codes.items() if k >= 500)}


def rnd_sky():
    return round(random.uniform(0, 360), 5), round(random.uniform(-85, 85), 5)


def demo_or_random(p_demo=0.7):
    return random.choice(DEMO) if random.random() < p_demo else rnd_sky()


# ------------------------------------------------------------------ request builders
def req_catalog():
    if random.random() < 0.5:
        return "GET", "/api/v1/catalog/search", {"params": {"q": random.choice(["wise 0855", "rw aur", "planet x", "barnard", "zzz"])}}
    ra, dec = demo_or_random()
    return "GET", "/api/v1/catalog/search", {"params": {"ra": ra, "dec": dec, "radius_arcmin": 10, "include_field": True, "limit": 50}}


def req_cutout():
    ra, dec = demo_or_random()
    return "GET", "/api/v1/sky/cutout", {"params": {"ra": ra, "dec": dec, "epoch": random.choice(EPOCHS), "size_px": 64}}


def req_spectrum():
    ra, dec = demo_or_random()
    return "GET", "/api/v1/spectrum", {"params": {"ra": ra, "dec": dec, "epoch": random.choice(EPOCHS)}}


def req_difference():
    ra, dec = demo_or_random()
    return "POST", "/api/v1/analysis/difference", {"json": {"ra": ra, "dec": dec}}


def req_shift_stack():
    return "POST", "/api/v1/analysis/shift-stack", {"json": {"ra": 51.295473, "dec": 14.8325559, "rate_arcsec_yr": random.choice([100, 110, 120]),
                                                              "pa_deg": random.choice([55, 62, 70]), "distance_au": 520}}


def req_orbit():
    return "POST", "/api/v1/orbit/simulate", {"json": {"target_id": "px-2026-09"}}


def req_ai_command():
    return "POST", "/api/v1/ai/command", {"json": {"message": random.choice(["WISE 0855'e git ve fark modunu aç", "show spectrum of RW Aur",
                                                                             "Planet X için kör tarama yap", "dili İngilizce yap", "generate PDF"])}}


def req_ai_classify():
    flux = [max(0.0, random.gauss(50, 15)) for _ in range(102)]
    return "POST", "/api/v1/ai/classify", {"json": {"flux_ujy": flux}}


def req_ai_classify_coords():
    # What the web UI sends: the engine fetches the spectrum from the backend itself (two services per call).
    ra, dec = demo_or_random()
    return "POST", "/api/v1/ai/classify", {"json": {"ra": ra, "dec": dec}}


def req_crossmatch():
    ra, dec = random.choice(FIXTURE_TARGETS)
    return "GET", "/api/v1/missions/crossmatch", {"params": {"ra": ra, "dec": dec}}


def req_gcn():
    return "GET", "/api/v1/alerts/gcn", {"params": {"limit": 10}}


def req_candidates():
    return "GET", "/api/v1/candidates", {"params": {"sort": random.choice(["votes", "recent", "anomaly"])}}


MIX = [(req_catalog, 15), (req_cutout, 25), (req_spectrum, 20), (req_difference, 8), (req_shift_stack, 6), (req_orbit, 5),
       (req_ai_command, 8), (req_ai_classify, 5), (req_ai_classify_coords, 6), (req_crossmatch, 4), (req_gcn, 2), (req_candidates, 2)]
ALL = [f for f, _ in MIX]


def pick():
    fns, w = zip(*MIX)
    return random.choices(fns, weights=w)[0]


async def call(client: httpx.AsyncClient, builder, bucket: dict):
    method, path, kw = builder()
    key = builder.__name__.replace("req_", "")
    st = bucket.setdefault(key, Stats())
    t0 = time.perf_counter()
    try:
        r = await client.request(method, BASE + path, **kw)
        st.add(r.status_code, time.perf_counter() - t0)
        return r
    except httpx.TimeoutException:
        st.add(None, 0, "timeout")
    except httpx.HTTPError:
        st.add(None, 0, "error")
    return None


async def run_for(seconds: float, concurrency: int, chooser, bucket: dict):
    deadline = time.perf_counter() + seconds
    done = 0
    limits = httpx.Limits(max_connections=concurrency + 10, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=TIMEOUT, limits=limits) as client:
        async def worker():
            nonlocal done
            while time.perf_counter() < deadline:
                await call(client, chooser(), bucket)
                done += 1
        await asyncio.gather(*[worker() for _ in range(concurrency)])
    return done


def report(phase: str, bucket: dict, elapsed: float | None = None, done: int | None = None, extra: dict | None = None):
    out = {k: v.summary() for k, v in sorted(bucket.items())}
    total = sum(s["n"] for s in out.values())
    bad = sum(s["5xx"] + s["timeouts"] + s["conn_errors"] for s in out.values())
    head = {"requests": total, "failures": bad}
    if elapsed:
        head["rps"] = round((done or total) / elapsed, 1)
    head.update(extra or {})
    RESULTS[phase] = {"summary": head, "endpoints": out}
    print(f"STRESS|{phase}|SUMMARY|{json.dumps(head)}", flush=True)
    for k, s in out.items():
        print(f"STRESS|{phase}|{k}|n={s['n']} codes={s['codes']} to={s['timeouts']} err={s['conn_errors']} "
              f"p50={s['p50_ms']} p95={s['p95_ms']} p99={s['p99_ms']} max={s['max_ms']}", flush=True)


# ------------------------------------------------------------------ phases
async def p0_baseline():
    bucket: dict = {}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for fn in ALL:
            for _ in range(15):
                await call(client, fn, bucket)
    report("P0_baseline", bucket)


async def p1_ramp(levels, seconds):
    for c in levels:
        bucket: dict = {}
        t0 = time.perf_counter()
        done = await run_for(seconds, c, pick, bucket)
        report(f"P1_ramp_c{c}", bucket, time.perf_counter() - t0, done)


async def p2_heavy():
    async def burst(name, builder, n):
        bucket: dict = {}
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=180.0) as client:
            await asyncio.gather(*[call(client, builder, bucket) for _ in range(n)])
        report(f"P2_{name}", bucket, time.perf_counter() - t0, n, {"concurrency": n})

    def blind():
        return "POST", "/api/v1/analysis/blind-search", {"json": {"ra": 51.295473, "dec": 14.8325559}}
    blind.__name__ = "req_blind_search"

    def big_stack():
        ra, dec = rnd_sky()
        return "POST", "/api/v1/analysis/shift-stack", {"json": {"ra": ra, "dec": dec, "size_px": 256, "rate_arcsec_yr": 150,
                                                                  "pa_deg": 30, "distance_au": 300, "n_frames": 64}}
    big_stack.__name__ = "req_big_shift_stack"

    def orbit_fit():
        t = [2026.05 + 0.1 * i for i in range(8)]
        dets = [{"t": ti, "ra": 51.29 + 0.01 * i, "dec": 14.83 + 0.003 * i, "sigma_arcsec": 1.0} for i, ti in enumerate(t)]
        return "POST", "/api/v1/orbit/simulate", {"json": {"detections": dets}}
    orbit_fit.__name__ = "req_orbit_fit"

    def uncached_spectrum():
        ra, dec = rnd_sky()
        return "GET", "/api/v1/spectrum", {"params": {"ra": ra, "dec": dec, "epoch": random.choice(EPOCHS)}}
    uncached_spectrum.__name__ = "req_uncached_spectrum"

    await burst("blind_search_x8", blind, 8)
    await burst("big_shift_stack_x10", big_stack, 10)
    await burst("orbit_fit_x20", orbit_fit, 20)
    await burst("uncached_spectrum_x60", uncached_spectrum, 60)


async def p3_abuse():
    bucket: dict = {}
    cases = [
        ("huge_body_classify", "POST", "/api/v1/ai/classify", {"content": b'{"flux_ujy":[' + b"1.0," * 2_500_000 + b'1.0]}',
                                                               "headers": {"content-type": "application/json"}}),
        ("huge_image_classify", "POST", "/api/v1/ai/classify", {"json": {"image": {"width": 512, "height": 512, "data": [0.5] * 262144}}}),
        ("long_command", "POST", "/api/v1/ai/command", {"json": {"message": "WISE " * 400}}),
        ("classify_empty_body", "POST", "/api/v1/ai/classify", {"json": {}}),
        ("classify_nan_coords", "POST", "/api/v1/ai/classify", {"content": b'{"ra": NaN, "dec": Infinity}', "headers": {"content-type": "application/json"}}),
        ("classify_coords_plus_junk", "POST", "/api/v1/ai/classify", {"json": {"ra": 133.76, "dec": -7.24, "junk": "x" * 500_000}}),
        ("catalog_limit_500_wide", "GET", "/api/v1/catalog/search", {"params": {"ra": 270, "dec": -29, "radius_arcmin": 30, "include_field": True, "limit": 500}}),
        ("cutout_256_band", "GET", "/api/v1/sky/cutout", {"params": {"ra": 266.4, "dec": -28.9, "size_px": 256, "band": 101}}),
        ("cutout_fits_256", "GET", "/api/v1/sky/cutout", {"params": {"ra": 10, "dec": 10, "size_px": 256, "format": "fits"}}),
        ("orbit_1000yr", "POST", "/api/v1/orbit/simulate", {"json": {"target_id": "px-2026-09", "horizons_years": [1000], "samples_per_year": 365}}),
        ("malformed_json", "POST", "/api/v1/analysis/shift-stack", {"content": b"{not json", "headers": {"content-type": "application/json"}}),
    ]
    async with httpx.AsyncClient(timeout=180.0) as client:
        for name, m, path, kw in cases:
            st = bucket.setdefault(name, Stats())
            t0 = time.perf_counter()
            try:
                r = await client.request(m, BASE + path, **kw)
                st.add(r.status_code, time.perf_counter() - t0)
            except httpx.TimeoutException:
                st.add(None, 0, "timeout")
            except httpx.HTTPError:
                st.add(None, 0, "error")
        # candidate flood from one client: expect 429s, never 5xx
        st = bucket.setdefault("candidate_flood_300", Stats())

        async def sub(i):
            t0 = time.perf_counter()
            try:
                r = await client.post(BASE + "/api/v1/candidates", json={"action": "submit", "candidate": {"ra": 100 + i * 0.01, "dec": 10.0, "notes": "@x https://y"}})
                st.add(r.status_code, time.perf_counter() - t0)
            except httpx.TimeoutException:
                st.add(None, 0, "timeout")
            except httpx.HTTPError:
                st.add(None, 0, "error")
        await asyncio.gather(*[sub(i) for i in range(300)])
    report("P3_abuse", bucket)


async def p4_soak(seconds, concurrency):
    bucket: dict = {}
    t0 = time.perf_counter()
    done = await run_for(seconds, concurrency, pick, bucket)
    report(f"P4_soak_c{concurrency}_{int(seconds)}s", bucket, time.perf_counter() - t0, done)


async def p5_mixed(label, seconds, concurrency):
    bucket: dict = {}
    t0 = time.perf_counter()
    done = await run_for(seconds, concurrency, pick, bucket)
    report(label, bucket, time.perf_counter() - t0, done)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--seconds", type=float, default=45)
    ap.add_argument("--concurrency", type=int, default=30)
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    random.seed(2026)
    if a.phase == "baseline":
        asyncio.run(p0_baseline())
    elif a.phase == "ramp":
        asyncio.run(p1_ramp([10, 50, 150], a.seconds))
    elif a.phase == "heavy":
        asyncio.run(p2_heavy())
    elif a.phase == "abuse":
        asyncio.run(p3_abuse())
    elif a.phase == "soak":
        asyncio.run(p4_soak(a.seconds, a.concurrency))
    elif a.phase == "mixed":
        asyncio.run(p5_mixed(a.label or "mixed", a.seconds, a.concurrency))
    out = Path(__file__).with_name("results.json")
    prev = json.loads(out.read_text()) if out.exists() else {}
    prev.update(RESULTS)
    out.write_text(json.dumps(prev, indent=1))


if __name__ == "__main__":
    main()
