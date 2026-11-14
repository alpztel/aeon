# AEON — Astrophysical Discovery OS

**NASA Space Apps Challenge 2026 · Planet X and SPHEREx** · [aeon.tech](https://aeon.tech)

AEON turns SPHEREx-style 102-band near-infrared sky data (0.75–5.0 µm) into discoveries in seconds:
difference imaging, shift-and-stack recovery of faint moving objects, REBOUND N-body orbit forecasts,
multi-mission cross-matching (Gaia, WISE, JWST, HST) and an Astro-LLM copilot that drives the whole UI
in Turkish or English.

> **TR —** AEON, SPHEREx tarzı 102 bantlık yakın-kızılötesi gökyüzü verisini saniyeler içinde keşfe
> dönüştüren açık kaynaklı bir astrofizik keşif işletim sistemidir: görüntü farkı, sönük hareketli
> cisimler için kaydır-ve-yığ, REBOUND N-gövde yörünge tahmini, çoklu görev eşleştirme ve arayüzü
> Türkçe/İngilizce komutlarla yöneten Astro-LLM kopilotu.

## Repository layout

| Folder | Owner (node / branch) | Stack |
|--------|-----------------------|-------|
| `backend/` | Node 1 · `agent/claude-leader-backend` | FastAPI, Astropy, Photutils, REBOUND, DuckDB |
| `frontend/`, `docs-and-reports/` | Node 2 · `agent/ag1-frontend` | Next.js, TypeScript, Aladin Lite, Three.js, Plotly.js |
| `ai-engine/`, `multi-mission-api/` | Node 3 · `agent/ag2-ai-missions` | PyTorch, LLM function calling, MAST, Gaia, GCN, MongoDB |
| `deploy/` | repo lead | Docker Compose + Nginx gateway |

Contract files: [`AGENTS.md`](AGENTS.md) (rules), [`PROJECT_SPEC.xml`](PROJECT_SPEC.xml) (spec),
[`openapi.json`](openapi.json) (11-path API contract).

## Demo tour

| Target | What it proves |
|--------|----------------|
| **WISE 0855−0714** — coldest known brown dwarf (~250 K, 2.3 pc) | ~8.1″/yr proper motion appears as a ± dipole in difference mode |
| **RW Aurigae** — young T Tauri star | 102-band flux changes as you scrub the timeline |
| **PX-2026-09** — *injected synthetic* Planet X test candidate at 520 AU | Invisible in single frames, recovered by shift-and-stack; REBOUND draws its 10-year arc |

PX-2026-09 is a synthetic object injected into the model sky to validate the detection pipeline end to
end; it is flagged `is_synthetic: true` everywhere.

## Data modes

The backend reads real FITS images from `AEON_DATA_DIR` when present (`data_mode: "fits_archive"`).
Without them it renders a physically consistent model sky — Planck/absorption spectral models, real
proper motions, SPHEREx-like PSF and noise — and runs the *same* Astropy/Photutils pipeline on it
(`data_mode: "physical_model"`). The UI must show which mode is active.

## Run locally

```bash
cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn aeon.main:app --reload --port 8000     # docs at http://localhost:8000/docs
pytest -q
```

Full stack: `cd deploy && docker compose --profile full up --build`.

## Team

İstanbul Medeniyet Üniversitesi, Physics Engineering — Alperen (lead), Mucteba Özdemir, Ece, Filiz, Asya.

## License

MIT
