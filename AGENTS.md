# AGENTS.md — AEON Constitution for Human and AI Contributors

Every agent (Claude Code, Antigravity, or human) working on this repository MUST read this file,
`PROJECT_SPEC.xml` and `openapi.json` before writing code. These three files are the contract.

## 1. Branches and folder ownership

| Node | Owner | Agent | Branch | May write ONLY in |
|------|-------|-------|--------|-------------------|
| 1 | Alperen (`@alpztel`, repo lead) | Claude Code | `agent/claude-leader-backend` | `backend/` |
| 2 | Mucteba Özdemir | Antigravity 1 | `agent/ag1-frontend` | `frontend/`, `docs-and-reports/` |
| 3 | Ece, Filiz, Asya | Antigravity 2 | `agent/ag2-ai-missions` | `ai-engine/`, `multi-mission-api/` |

Root files (`AGENTS.md`, `PROJECT_SPEC.xml`, `openapi.json`, `README.md`, `.github/`, `deploy/`)
belong to the repo lead and change only through a PR reviewed by `@alpztel`.

`.github/workflows/ci-guard.yml` enforces this: a push or PR from an `agent/*` branch that touches
a path outside that branch's allow-list fails CI.

## 2. Hard rules

1. **No direct pushes to `main`.** After the initial bootstrap commit, everything reaches `main` via PR.
2. **Stay in your folder.** Need something from another node? Open an issue or a PR comment; do not edit their files.
3. **`openapi.json` is frozen.** Implement it exactly: same paths, field names, units, enums. Propose changes via PR to `main`.
4. **Verify before you commit.** Your own checks must exit 0:
   - `backend/`: `cd backend && pytest -q`
   - `frontend/`: `cd frontend && npm run lint && npm run build`
   - `ai-engine/`, `multi-mission-api/`: `pytest -q` in each folder
5. **No placeholders presented as results.** Every number the UI shows comes from a computation.
   When live data is unreachable, use the physical fallback model and label it (`data_mode: "physical_model"`).
6. **Honesty about synthetic objects.** `PX-2026-09` is an *injected* test candidate used to demonstrate
   the pipeline. Anything synthetic carries `is_synthetic: true` and must be labelled as such in the UI and PDF.
7. **Secrets** (GitHub token, MongoDB URI, LLM keys, HF token) live only in environment variables / GitHub
   Secrets. Never commit `.env`.
8. **Bilingual.** User-facing strings exist in both `tr` and `en`. The backend returns bilingual descriptions
   as `{ "tr": ..., "en": ... }`.

## 3. Service topology

```
Browser ── https://a-eon.engineer (Vercel, Next.js)  ──►  https://api.a-eon.engineer (Nginx, DigitalOcean)
                                                       ├─ /api/v1/health, catalog, sky, spectrum,
                                                       │   analysis, orbit          → backend:8000
                                                       ├─ /api/v1/ai/*              → ai-engine:8100
                                                       └─ /api/v1/missions/*, alerts,
                                                           candidates               → multi-mission-api:8200
```

Ports: backend `8000`, ai-engine `8100`, multi-mission-api `8200`. See `deploy/docker-compose.yml`.
Every service exposes its own OpenAPI at `/docs` and must accept CORS from `https://a-eon.engineer` and
`http://localhost:3000`.

## 4. Shared conventions

- Coordinates: ICRS degrees (`ra` 0–360, `dec` −90…+90). Proper motion in arcsec/yr, PA in degrees east of north.
- Epochs: `2026-Q1` … `2026-Q4` → decimal years 2026.125, 2026.375, 2026.625, 2026.875.
- Fluxes: µJy. Wavelengths: µm. Distances: AU (solar system) or pc (stars).
- Images in JSON: row-major flat array, row 0 = south edge, north up, east left.
- 102 bands: 6 SPHEREx-like detector arrays × 17 channels spanning 0.75–5.0 µm
  (see `backend/aeon/bands.py` — the single source of truth for band centres).
- Object classes: `cold_brown_dwarf`, `planet_x_candidate`, `young_variable_star`,
  `main_sequence_star`, `high_z_galaxy`.
- Demo tour targets (ids): `wise-0855`, `rw-aur`, `px-2026-09`.

## 5. Commit and PR style

- Conventional commits: `feat(backend): ...`, `fix(frontend): ...`, `docs: ...`.
- One PR per feature; PR title references the module number from `PROJECT_SPEC.xml`.
- The repo lead merges all PRs into `main`.
