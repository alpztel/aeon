# Third-party notices

AEON’s own source code is released under the [MIT License](LICENSE). This file lists the data, models,
software and fonts AEON uses that come from others, with their licences or terms of use. Licences are
taken from each project’s package metadata or publisher; follow the links for the full texts. Dependency
versions are not pinned here; see each service’s `requirements.txt` and `frontend/package-lock.json`.

## Data products and services

| Source | Used for | Terms |
|---|---|---|
| **SPHEREx** Level-2 spectral images, via the NASA/IPAC Infrared Science Archive | Cutouts, spectra and differences (`backend/aeon/irsa.py`, `deploy/azure/ingest.py`) | Public NASA data. Published work must include the [SPHEREx acknowledgement](https://irsa.ipac.caltech.edu/Missions/spherex.html) (quoted in the README) |
| **Gaia DR3** (ESA) | Astrometry, photometry and radial velocities; rows stored in `multi-mission-api/fixtures/crossmatch_fixtures.json` | [Gaia credits and acknowledgement](https://www.cosmos.esa.int/web/gaia-users/credits) |
| **AllWISE** and **CatWISE2020** (WISE, NEOWISE) | W1–W4 photometry, positions and proper motions | [WISE acknowledgement](https://irsa.ipac.caltech.edu/Missions/wise.html) |
| **SIMBAD** (CDS, Strasbourg; mirror at the Harvard-Smithsonian CfA) | Reference astrometry and radial velocities for the validation scorecard; rows stored in `multi-mission-api/fixtures/validation_reference.json` | Free use under the Open Database License (ODbL); acknowledgement quoted in the README (Wenger et al. 2000, A&AS, 143, 9) |
| **MAST** (STScI) | JWST/HST observation overlap metadata | [MAST acknowledgements](https://archive.stsci.edu/publishing/mission-acknowledgements) |
| **NOIRLab Astro Data Lab** | Copies of Gaia DR3, AllWISE and CatWISE2020 used to build fixtures and catalog entries | [Astro Data Lab acknowledgements](https://datalab.noirlab.edu/acknowledgments.php) |
| **NASA GCN** | Transient notices served by `GET /api/v1/alerts/gcn` | Public NASA service |

Peer-reviewed values in `multi-mission-api/fixtures/validation_reference.json` are quoted from the cited
papers with their bibcodes.

## Model tables (`multi-mission-api/app/data/`)

| Table | Source | Licence |
|---|---|---|
| Sonora Bobcat evolution tracks and photometry, solar metallicity | Marley et al. 2021, ApJ 920, 85; [doi:10.5281/zenodo.5063476](https://doi.org/10.5281/zenodo.5063476) | CC BY 4.0. Stored unchanged |
| BHAC15 evolutionary tracks, 0.01–1.4 M☉ | Baraffe, Homeier, Allard & Chabrier 2015, A&A 577, A42; tables from the authors’ website | Cite the paper. Stored unchanged (first six columns) |

The classifier weights in `ai-engine/app/weights/` were trained by Team AEON on simulated spectra and are
part of this repository (MIT).

## Software

### Python services

| Package | Used by | Licence (main) |
|---|---|---|
| FastAPI | all services | MIT |
| Uvicorn | all services | BSD-3-Clause |
| Pydantic | all services | MIT |
| NumPy | all services | BSD-3-Clause |
| SciPy | backend | BSD-3-Clause |
| Astropy | backend, multi-mission-api | BSD-3-Clause |
| Photutils | backend | BSD-3-Clause |
| **REBOUND** | backend | **GPL-3.0-only** (see note) |
| galpy | backend | BSD-3-Clause |
| DuckDB | backend | MIT |
| HTTPX | all services | BSD-3-Clause |
| astroquery | multi-mission-api | BSD-3-Clause |
| PyMongo | multi-mission-api | Apache-2.0 |
| mongomock | multi-mission-api | ISC |
| PyTorch | ai-engine | BSD-3-Clause; bundled components add Apache-2.0, MIT, BSL-1.0, ISC, Zlib and BSD-2-Clause |
| Anthropic Python SDK | ai-engine | Apache-2.0 |
| huggingface_hub | ai-engine | Apache-2.0 |
| Gradio | `ai-engine/hf-space` | Apache-2.0 |
| pytest, jsonschema, respx | tests | MIT, MIT, BSD-3-Clause |

> **Note on REBOUND.** AEON does not include REBOUND’s source; it installs REBOUND as a dependency.
> REBOUND is licensed under the GNU General Public License v3.0. Anyone who redistributes a build that
> bundles it, such as the backend Docker image, must also meet the GPL-3.0 terms for that distribution.

### Frontend

| Package | Licence |
|---|---|
| Next.js | MIT |
| React, React DOM | MIT |
| Plotly.js (`plotly.js-dist-min`) | MIT |
| three.js | MIT |
| Lucide icons (`lucide-react`) | ISC |
| Tailwind CSS | MIT |
| TypeScript | Apache-2.0 |
| ESLint, `eslint-config-next`, `openapi-typescript` | MIT |

### Fonts

Geist, Geist Mono and Instrument Serif, loaded through Google Fonts (`next/font/google`), are licensed under
the SIL Open Font License 1.1.
