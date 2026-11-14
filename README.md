# AEON — Astrophysical Discovery OS

**NASA Space Apps Challenge 2026 · Planet X and SPHEREx** · [aeon.tech](https://aeon.tech) · API: `https://api.aeon.tech`

AEON turns SPHEREx 102-band near-infrared sky data (0.75–5.0 µm) into discoveries in seconds. It reads
**real SPHEREx DR1 spectral images from NASA/IPAC IRSA**, finds faint moving objects with
**Earth-parallax digital tracking**, fits their orbits from its own astrometry and forecasts them with
**REBOUND**, and cross-matches every source with Gaia, WISE, JWST and HST — all driven by an Astro-LLM
copilot in Turkish or English.

> **TR —** AEON, SPHEREx'in 102 bantlık yakın-kızılötesi verisini saniyeler içinde keşfe dönüştürür:
> IRSA'dan **gerçek SPHEREx DR1** görüntülerini okur, sönük hareketli cisimleri **Dünya paralaksını izleyen
> dijital yığınlama** ile bulur, kendi ölçtüğü astrometriden yörünge uydurup **REBOUND** ile ileriye taşır
> ve her kaynağı Gaia, WISE, JWST ve HST ile eşleştirir. Arayüzü Türkçe/İngilizce Astro-LLM yönetir.
> Ayrıntılı Türkçe bölüm aşağıdadır.

---

## What works today

| Capability | How | Status |
|------------|-----|--------|
| **Real SPHEREx data** | IRSA SIA2 search + IBE cutouts of DR1 Level 2 spectral images; IMAGE/FLAGS/VARIANCE/WCS-WAVE, per-pixel LVF wavelength, MJy/sr → µJy/pixel | ✅ `backend/aeon/irsa.py`, `archive.py` |
| **Physical fallback sky** | Planck/molecular-band SEDs, real proper motions + parallax, SPHEREx-like PSF, zodiacal background, depth-calibrated noise — same pipeline as real data | ✅ `sky.py`, `spectra.py` |
| **102-band spectra** | photutils forced photometry; H₂O/CH₄/CO₂/CO band depths | ✅ `/spectrum` |
| **Difference imaging** | I(t₂) − I(t₁), matched-filter S/N, ± detections | ✅ `/analysis/difference` |
| **Planet X search with parallax** | Digital tracking along the apparent (geocentric) path: linear motion + Earth's reflex parallax; blind search over distance × rate × PA | ✅ `/analysis/shift-stack`, `/analysis/blind-search` |
| **Realistic cadence** | `cadence: "spherex"` — frames only in the field's SPHEREx-like visit windows (solar elongation ≈ 90°) | ✅ |
| **Discovery → orbit** | Sub-stack astrometry → least-squares heliocentric state (parallax included) → REBOUND 1/5/10-yr forecast with errors | ✅ `/orbit/simulate` with `detections` |
| **N-body forecasts** | REBOUND IAS15: Sun + Jupiter, Saturn, Uranus, Neptune + particle | ✅ |
| **Catalog** | DuckDB; apparent positions per epoch | ✅ `/catalog/search` |
| **Web observatory** | Next.js, TR/EN, sky map + timeline, spectrum, difference, shift-stack, 3D orbit, SED/JWST panels | 🔄 PR #6 in review |
| **Astro-LLM, classifiers, Gaia/WISE/MAST, GCN, candidates, GitHub bot** | `ai-engine/`, `multi-mission-api/` | ⏳ Node 3 |
| **Production** | Docker Compose + Nginx TLS on DigitalOcean, deploy + e2e workflows | ✅ config (`deploy/`), ⏳ droplet |

### Headline results (PX-2026-09, injected synthetic test object at 520 AU)

| Method | Stacked S/N | Outcome |
|--------|-------------|---------|
| Straight-line shift-and-stack | 2.3 | missed — the ~400″ annual parallax smears it |
| Parallax-tracked stack at 520 AU | **10.0** | recovered (single exposure S/N ≈ 2) |
| Blind search, ~1,700 hypotheses, ~4 s | **7.9** | finds 110″/yr, PA 60°, **519.7 AU** |
| Orbit from the stack's own astrometry | — | **521 ± 1 AU**, 110 ± 3″/yr, PA 62° |
| Same with SPHEREx-like cadence (2 windows) | 9.2 | 524 ± 12 AU (two windows constrain less) |

PX-2026-09 does not exist on the sky; it is injected to validate the detection chain end to end and is
flagged `is_synthetic: true` everywhere. WISE 0855 (coldest known brown dwarf, 8.1″/yr) and RW Aurigae
(variable T Tauri star) are real.

## Demo tour

| Target | What it proves |
|--------|----------------|
| **WISE 0855−0714** — ~250 K brown dwarf, 2.3 pc | ± dipole in difference mode; CH₄ and CO₂ absorption in the 102-band spectrum; real SPHEREx frames |
| **RW Aurigae** — young T Tauri star | 102-band flux changes as you scrub the timeline |
| **PX-2026-09** — *synthetic* Planet X test object | invisible in single frames → recovered by parallax tracking → orbit fitted → 10-year arc in 3D |

## Architecture

```
Browser ── aeon.tech (Vercel, Next.js) ──► api.aeon.tech (Nginx, DigitalOcean)
                                             ├─ health, catalog, sky, spectrum,
                                             │  analysis, orbit            → backend :8000
                                             ├─ /api/v1/ai/*               → ai-engine :8100
                                             └─ missions, alerts,
                                                candidates                  → multi-mission-api :8200
```

The contract is [`openapi.json`](openapi.json) (11 paths). Key request options added since v1:
`distance_au`, `distance_range_au`, `cadence` (analysis), `detections` (orbit); responses add `track`,
`astrometry`, `distance_profile`, `fit`, and per-request `data_mode` (`fits_archive` | `physical_model`).

## Repository layout

| Folder | Owner (node / branch) | Stack |
|--------|-----------------------|-------|
| `backend/` | Node 1 · `agent/claude-leader-backend` | FastAPI, Astropy, Photutils, REBOUND, DuckDB, IRSA |
| `frontend/`, `docs-and-reports/` | Node 2 · `agent/ag1-frontend` | Next.js, TypeScript, Three.js, Plotly.js |
| `ai-engine/`, `multi-mission-api/` | Node 3 · `agent/ag2-ai-missions` | PyTorch, LLM function calling, MAST, Gaia, GCN, MongoDB |
| `deploy/` | repo lead | Docker Compose, Nginx TLS, droplet bootstrap, e2e tests |
| `docs/agents/` | repo lead | team workflow and agent prompts (Turkish) |

Rules: [`AGENTS.md`](AGENTS.md) · Spec: [`PROJECT_SPEC.xml`](PROJECT_SPEC.xml) ·
Backend roadmap: [`backend/ROADMAP.md`](backend/ROADMAP.md) · Deploy guide: [`deploy/README.md`](deploy/README.md) ·
SPHEREx L2 notes: [`backend/docs/spherex-l2-notes.md`](backend/docs/spherex-l2-notes.md)

## Quality gates

- `ci-guard` on every PR: folder isolation per agent branch, `openapi.json` validation (exactly 11 paths),
  backend pytest, frontend lint + build, Python service tests. `main` is protected; all six must pass.
- **146 backend tests**, including schema validation of every response against `openapi.json` and an
  80-case **torture suite** (hostile strings, LIKE wildcards, coordinate edges, invalid parameters,
  sun-grazing orbits, 60 concurrent mixed requests, byte-identical determinism). It found and fixed two
  request hangs and two 500 errors.
- `e2e` workflow: the whole stack in Docker, every contract path tested through the gateway.

## Run locally

```bash
cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: keep the venv on a short path
pip install -r requirements.txt
uvicorn aeon.main:app --reload --port 8000     # http://localhost:8000/docs
pytest -q
```

Real SPHEREx data (optional):

```bash
export AEON_DATA_DIR=/srv/aeon-data
python -m aeon.irsa fetch-demo        # WISE 0855, RW Aur, PX-2026-09 field (~1 GB transfer, ~55 MB per target on disk)
```

Full stack: `docker compose -f deploy/docker-compose.yml up -d --build`, then
`AEON_GATEWAY_URL=http://localhost pytest -q deploy/e2e`.

---

## Türkçe

### Bugün çalışanlar
- **Gerçek SPHEREx verisi:** IRSA'dan DR1 Level 2 spektral görüntüler indirilir; maskeli pikseller atılır,
  her pikselin dalga boyu (LVF) okunur, `data_mode: "fits_archive"` döner. Veri yoksa aynı hat fiziksel
  model gökyüzünde çalışır (`physical_model`).
- **Paralaksa duyarlı Planet X araması:** 520 AU'daki bir cismin görünür hareketine yıllık ~±400″ paralaks
  hâkimdir. AEON kareleri öngörülen görünür ize göre yığar; kör tarama uzaklık × hız × yön uzayını tarar.
- **Keşiften yörüngeye:** yığının kendi astrometrisinden en küçük kareler ile yörünge uydurulur ve REBOUND
  ile 1/5/10 yıl ileriye taşınır (PX-2026-09: 521 ± 1 AU).
- **Gerçekçi takvim:** `cadence: "spherex"` ile kareler yalnız alanın SPHEREx görünürlük pencerelerinde alınır.
- **Sağlamlık:** 146 backend testi, 80 senaryolu işkence testi; bulunan 2 kilitlenme ve 2 adet 500 hatası düzeltildi.
- **Dağıtım:** Docker Compose + Nginx TLS + otomatik deploy ve uçtan uca test iş akışları hazır.

### Sırada
- Frontend (PR #6) incelemesi ve birleştirilmesi
- AI ekibinin servisleri: Astro-LLM, 1D-CNN/ViT, Gaia/WISE/MAST, GCN, aday havuzu, GitHub botu
- DigitalOcean droplet + `api.aeon.tech` DNS, Vercel'de `aeon.tech`

### Ekip
İstanbul Medeniyet Üniversitesi Fizik Mühendisliği — Alperen (lider), Mucteba Özdemir, Ece, Filiz, Asya.

## License

MIT
