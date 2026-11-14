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
  { id: "wise-0855", ra: 133.79513, dec: -7.24514, rate: 8.15, pa: 275 },
  { id: "rw-aur", ra: 76.9564, dec: 30.4013, rate: 0, pa: 0 },
  { id: "px-2026-09", ra: 51.2, dec: 14.8, rate: 110, pa: 62 },
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
    const cat = await fetchJson(
      `${API_BASE}/api/v1/catalog/search?q=${encodeURIComponent(target.id)}`
    );
    if (cat.results?.[0]) {
      catalogResults.push(cat.results[0]);
    }

    for (const epoch of EPOCHS) {
      const cutout = await fetchJson(
        `${API_BASE}/api/v1/sky/cutout?ra=${target.ra}&dec=${target.dec}&epoch=${epoch}&size_px=64&pixel_scale_arcsec=6.2&format=json`
      );
      await fs.writeFile(
        path.join(OUT_DIR, `cutout-${target.id}-${epoch}.json`),
        JSON.stringify(cutout)
      );

      const spec = await fetchJson(
        `${API_BASE}/api/v1/spectrum?ra=${target.ra}&dec=${target.dec}&epoch=${epoch}`
      );
      await fs.writeFile(
        path.join(OUT_DIR, `spectrum-${target.id}-${epoch}.json`),
        JSON.stringify(spec)
      );
    }

    const diff = await fetchJson(`${API_BASE}/api/v1/analysis/difference`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ra: target.ra,
        dec: target.dec,
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
        ra: target.ra,
        dec: target.dec,
        rate_arcsec_yr: target.rate,
        pa_deg: target.pa,
        n_frames: 24,
        combine: "mean",
      }),
    });
    await fs.writeFile(path.join(OUT_DIR, `stack-${target.id}.json`), JSON.stringify(stack));

    const blind = await fetchJson(`${API_BASE}/api/v1/analysis/blind-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ra: target.ra,
        dec: target.dec,
        n_frames: 24,
        combine: "mean",
        rate_range_arcsec_yr: [20, 200],
        pa_range_deg: [30, 90],
        grid: 5,
      }),
    });
    await fs.writeFile(path.join(OUT_DIR, `blind-${target.id}.json`), JSON.stringify(blind));
    console.log(`Captured full cache for ${target.id}`);
  }

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
