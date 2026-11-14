#!/usr/bin/env node
/**
 * Captures real backend responses for the 3 demo targets into
 * frontend/public/demo-cache/ for offline fallback mode.
 *
 * Usage:
 *   AEON_API_BASE=http://localhost:8000 node scripts/capture-demo-cache.mjs
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(__dirname, "../public/demo-cache");
const API_BASE = (process.env.AEON_API_BASE || "http://localhost:8000").replace(/\/+$/, "");

const DEMO_TARGETS = [
  { id: "wise-0855", rate: 8.15, pa: 275, distance_au: null },
  { id: "rw-aur", rate: 0, pa: 0, distance_au: null },
  { id: "px-2026-09", rate: 110, pa: 62, distance_au: 520 },
];

const EPOCHS = ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"];

async function fetchJson(url, init) {
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} for ${url}`);
  }
  return res.json();
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });

  const catalogResults = [];
  for (const target of DEMO_TARGETS) {
    // 1. Mid-survey (2026.5) catalog lookup without epoch parameter
    const cat = await fetchJson(
      `${API_BASE}/api/v1/catalog/search?q=${encodeURIComponent(target.id)}`
    );
    const refEntry = cat.results?.[0];
    if (!refEntry) {
      throw new Error(`Catalog lookup returned no results for ${target.id}`);
    }
    catalogResults.push(refEntry);
    const refRa = refEntry.ra;
    const refDec = refEntry.dec;

    // 2. Per-epoch catalog lookup + cutout + 102-band spectrum at that epoch's apparent position
    for (const epoch of EPOCHS) {
      const epCat = await fetchJson(
        `${API_BASE}/api/v1/catalog/search?q=${encodeURIComponent(target.id)}&epoch=${epoch}`
      );
      const epEntry = epCat.results?.[0] ?? refEntry;
      const epRa = epEntry.ra;
      const epDec = epEntry.dec;

      const cutout = await fetchJson(
        `${API_BASE}/api/v1/sky/cutout?ra=${epRa}&dec=${epDec}&epoch=${epoch}&size_px=64&pixel_scale_arcsec=6.2&format=json`
      );
      await fs.writeFile(
        path.join(OUT_DIR, `cutout-${target.id}-${epoch}.json`),
        JSON.stringify(cutout)
      );

      const spec = await fetchJson(
        `${API_BASE}/api/v1/spectrum?ra=${epRa}&dec=${epDec}&epoch=${epoch}`
      );
      await fs.writeFile(
        path.join(OUT_DIR, `spectrum-${target.id}-${epoch}.json`),
        JSON.stringify(spec)
      );
    }

    // 3. Analysis endpoints use the mid-survey (2026.5) reference position
    const diff = await fetchJson(`${API_BASE}/api/v1/analysis/difference`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ra: refRa,
        dec: refDec,
        epoch_1: "2026-Q1",
        epoch_2: "2026-Q3",
        size_px: 64,
        pixel_scale_arcsec: 6.2,
      }),
    });
    await fs.writeFile(path.join(OUT_DIR, `diff-${target.id}.json`), JSON.stringify(diff));

    const stack = await fetchJson(`${API_BASE}/api/v1/analysis/shift-stack`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ra: refRa,
        dec: refDec,
        rate_arcsec_yr: target.rate,
        pa_deg: target.pa,
        distance_au: target.distance_au,
        cadence: "uniform",
        n_frames: 24,
        combine: "mean",
      }),
    });
    await fs.writeFile(path.join(OUT_DIR, `stack-${target.id}.json`), JSON.stringify(stack));

    const blind = await fetchJson(`${API_BASE}/api/v1/analysis/blind-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ra: refRa,
        dec: refDec,
        n_frames: 24,
        combine: "mean",
        cadence: "uniform",
        rate_range_arcsec_yr: [20, 200],
        pa_range_deg: [30, 90],
        distance_range_au: target.distance_au ? [250, 1000] : null,
        grid: 5,
      }),
    });
    await fs.writeFile(path.join(OUT_DIR, `blind-${target.id}.json`), JSON.stringify(blind));

    // Optional: capture crossmatch response only when the missions service is deployed (HTTP 200)
    try {
      const xm = await fetchJson(
        `${API_BASE}/api/v1/missions/crossmatch?ra=${refRa}&dec=${refDec}&radius_arcsec=10`
      );
      await fs.writeFile(
        path.join(OUT_DIR, `crossmatch-${target.id}.json`),
        JSON.stringify(xm)
      );
    } catch {
      // Missions service not deployed on this host; skip without writing fabricated data
    }

    console.log(`Captured full cache for ${target.id} (ref ${refRa}, ${refDec})`);
  }

  const orbit = await fetchJson(`${API_BASE}/api/v1/orbit/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_id: "px-2026-09",
      horizons_years: [1, 5, 10],
      samples_per_year: 24,
    }),
  });
  await fs.writeFile(path.join(OUT_DIR, "orbit-px-2026-09.json"), JSON.stringify(orbit));
  console.log("Saved orbit-px-2026-09.json");

  await fs.writeFile(
    path.join(OUT_DIR, "catalog-demo.json"),
    JSON.stringify(
      { query: { demo: true }, count: catalogResults.length, results: catalogResults },
      null,
      2
    )
  );
  console.log("Saved catalog-demo.json");
}

main().catch((err) => {
  console.error("Failed to capture demo cache:", err);
  process.exit(1);
});
