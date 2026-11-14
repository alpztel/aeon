# AEON Frontend — Astrophysical Discovery OS (Node 2)

Next.js 16 + TypeScript + Tailwind CSS v4 web interface for **AEON — Astrophysical Discovery OS** (NASA Space Apps Challenge 2026 · Planet X & SPHEREx).

## Features (M1–M11)

- **M1 — 2D Infrared Sky Map & Timeline (`SkyMapPanel.tsx`):**
  - 64×64 SPHEREx cutout viewer (`inferno`, `viridis`, `magma`, `grayscale` colormaps) + optional pinned Aladin Lite v3 (`3.5.1`) sky survey view.
  - Multi-epoch scrubbing across `2026-Q1`, `2026-Q2`, `2026-Q3`, `2026-Q4` with automatic apparent-position tracking (proper motion + Earth reflex parallax).
  - Bilingual (`TR | EN`) UI and keyboard shortcuts (`D`, `S`, `3`, `P`, `⌘K`/`Ctrl+K`, `?`).
- **M2 — Image Differencing (`DifferencePanel.tsx`):**
  - Side-by-side $I(t_1)$, $I(t_2)$, and diverging blue/white/red $I(t_2) - I(t_1)$ difference map with dipole and transient detection overlays.
- **M3 — 102-Band Near-IR Spectrum & Sonification (`SpectrumPanel.tsx`, `sonify.ts`):**
  - Interactive Plotly.js $0.75\text{–}5.0\,\mu\text{m}$ spectrum with $\text{H}_2\text{O}$ ($1.4, 1.9, 2.7, 3.05\,\mu\text{m}$), $\text{CH}_4$ ($1.65, 2.2, 3.3\,\mu\text{m}$), $\text{CO}_2$ ($4.26\,\mu\text{m}$), and $\text{CO}$ ($4.67\,\mu\text{m}$) absorption band markers, reference spectrum pinning, and Web Audio API sonification.
- **M4 — Shift-and-Stack & Blind Parallax Search (`ShiftStackPanel.tsx`):**
  - 24-frame geocentric parallax-aware Shift-and-Stack (`rate_arcsec_yr`, `pa_deg`, `distance_au`, `uniform` / `spherex` cadence), apparent parallax loop visualizer, and 5×5 coarse + refined velocity/distance grid search.
- **M5 — 3D Solar System & REBOUND Orbit Forecast (`SolarSystem3DPanel.tsx`):**
  - Three.js WebGL heliocentric ecliptic visualization with Sun, giant planets (`Jupiter`–`Neptune`), Kuiper Belt (`30–50 AU`), SPHEREx $90^\circ$ scan cone, least-squares astrometric orbit fit summary, and +1 / +5 / +10 yr REBOUND IAS15 forecast table.
- **M6 & M7 — Multi-Mission Cross-Match & JWST/HST PiP (`CrossmatchSedPanel.tsx`, `JwstPipWindow.tsx`):**
  - Broadband $0.4\text{–}22\,\mu\text{m}$ SED (Gaia DR3 + SPHEREx + WISE) and MAST archival overlap Picture-in-Picture window when `/api/v1/missions/crossmatch` is connected.
- **M8 & M9 — Astro-LLM Command Palette & 1D-CNN / ViT Classification (`AstroLlmModal.tsx`, `ClassificationCard.tsx`):**
  - Natural-language TR/EN command execution (`⌘K` / `Ctrl+K`) and 5-class probability bars + PatchAnomalyViT score gauge.
- **M10 — GCN Live Notices & Citizen-Science Candidate Pool (`GcnTicker.tsx`, `CandidatePoolPanel.tsx`):**
  - Live transient notice ticker and community candidate leaderboard with upvote/submission support.
- **M11 — Jury Demo Tour & One-Click PDF Discovery Report (`DemoTourBar.tsx`, `pdf-report.ts`):**
  - Guided 3-step jury tour (`WISE 0855−0714` → `RW Aurigae` → `PX-2026-09`) and client-side `jsPDF` discovery report generator.

## Quick Start

```bash
cd frontend
npm ci
npm run gen:api     # Regenerates src/lib/api-types.ts from ../openapi.json
npm run dev         # Starts Next.js on http://localhost:3000
```

Configure the backend base URL via `.env.local`:

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

## Offline Demo Cache (`public/demo-cache/`)

To capture fresh offline cache responses from a running AEON backend (`http://localhost:8000`):

```bash
AEON_API_BASE=http://localhost:8000 node scripts/capture-demo-cache.mjs
```

## Quality Gates

```bash
npm run gen:api
npm run lint
npm run typecheck
npm run build
```
