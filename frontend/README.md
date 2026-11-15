# AEON frontend

The web observatory of AEON: Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, Plotly.js and
three.js, in English and Turkish. It talks only to the API in [`openapi.json`](../openapi.json).

## The four-step flow

The tool rail on the right follows the AEON science chain. Each tool opens in the inspector panel.

| Step | Tool | Component |
|---|---|---|
| 1 · Target and motion | Example gallery (`G`) | [`ExamplesPanel.tsx`](src/components/ExamplesPanel.tsx): catalog targets grouped by class, with the quarters that hold real SPHEREx data |
| | Motion detection (`D`) | [`DifferencePanel.tsx`](src/components/DifferencePanel.tsx): two epochs and their difference; a moving source appears as a ± dipole |
| | Shift and Stack (`S`) | [`ShiftStackPanel.tsx`](src/components/ShiftStackPanel.tsx): parallax-aware digital tracking and blind search; offered for solar-system candidates and bare field positions |
| 2 · Spectrum and identity | 102-band spectrum | [`SpectrumPanel.tsx`](src/components/SpectrumPanel.tsx): measured, interpolated and blended bands marked separately, molecular bands, pipeline facts |
| | Physical identity | [`ClassificationCard.tsx`](src/components/ClassificationCard.tsx): 1D-CNN class probabilities, physics diagnostics, the age and mass card and the scorecard |
| 3 · Age and orbit | Age and Orbit (`3`) | [`GalacticOrbitPanel.tsx`](src/components/GalacticOrbitPanel.tsx) for stars and brown dwarfs (galpy orbit, solar encounter), [`SolarSystem3DPanel.tsx`](src/components/SolarSystem3DPanel.tsx) for solar-system candidates (REBOUND, 3D) |
| 4 · Validation | Validation scorecard | [`CrossmatchSedPanel.tsx`](src/components/CrossmatchSedPanel.tsx) with [`ValidationScorecard.tsx`](src/components/ValidationScorecard.tsx): AEON next to SIMBAD and the literature, and the Gaia + SPHEREx + WISE SED |

The shell ([`src/components/shell/`](src/components/shell)) holds the top bar and search, the sky view,
the epoch scrubber, the tool rail and inspector, the target card, onboarding and the guided tour. Also
included: a command palette ([`AstroLlmModal.tsx`](src/components/AstroLlmModal.tsx), `Ctrl/⌘ K`),
keyboard shortcuts (`?`) and a client-side PDF report ([`src/lib/pdf-report.ts`](src/lib/pdf-report.ts),
`P`).

## Honest by design

- A data-mode badge shows whether a view comes from real SPHEREx frames, the physical model or the offline
  cache; synthetic objects carry a synthetic badge.
- Values the API does not send are left out, never shown as zero
  ([`DataFacts.tsx`](src/components/DataFacts.tsx)).
- Missing radial velocities are shown as envelopes, and the reason for every unmeasured value is shown
  next to it.

## Getting started

```bash
cd frontend
npm ci
cp .env.example .env.local     # then set NEXT_PUBLIC_API_BASE
npm run dev                    # http://localhost:3000
```

`NEXT_PUBLIC_API_BASE` points at the API gateway. With the Docker Compose stack from the root
[Quick start](../README.md#quick-start) use `http://localhost`. Pointing it straight at the backend
(`http://localhost:8000`) gives the core tools only, because the ai-engine and multi-mission-api are
reached through the gateway.

## Scripts

| Command | Does |
|---|---|
| `npm run dev` | Development server |
| `npm run build`, `npm start` | Production build and server |
| `npm run lint` | ESLint |
| `npm run typecheck` | TypeScript, no emit |
| `npm run gen:api` | Regenerates [`src/lib/api-types.ts`](src/lib/api-types.ts) from `../openapi.json` |

Optional response blocks of the cross-match (age and mass, Galactic orbit, validation) are typed by hand in
[`src/lib/api.ts`](src/lib/api.ts).

## Offline demo cache

[`public/demo-cache/`](public/demo-cache) holds recorded API responses for WISE 0855, RW Aurigae and
PX-2026-09. When the API cannot be reached, these are shown and labelled as offline cache. Refresh them
from a running backend:

```bash
AEON_API_BASE=http://localhost:8000 node scripts/capture-demo-cache.mjs
```

## Deploying

The frontend is a standard Next.js app; on Vercel set the project’s root directory to `frontend`. See
[`docs-and-reports/deploy-vercel.md`](../docs-and-reports/deploy-vercel.md) (Turkish).
