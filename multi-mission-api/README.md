# AEON `multi-mission-api` (port 8200)

FastAPI service for the `missions`, `alerts` and `candidates` paths of [`openapi.json`](../openapi.json).
Its main endpoint cross-matches a position with Gaia DR3, AllWISE and MAST, builds a 0.4–22 µm SED that
includes the target’s own SPHEREx bands, and runs stages 2 and 4 of the AEON chain: **age and mass**, and
the **validation scorecard**. Stage 3 (the Galactic orbit) is computed by the core backend and summarised
here.

## `GET /api/v1/missions/crossmatch?ra=…&dec=…&radius_arcsec=6`

| Response block | Content |
|---|---|
| `gaia`, `wise`, `mast_overlap` | Archive rows: the stored snapshot for catalog targets, live Gaia TAP / IRSA TAP / MAST queries elsewhere |
| `sed`, `sed_physics` | Gaia + SPHEREx + WISE SED in µJy; colour temperature, bolometric flux and infrared ratio; the equilibrium temperature for solar-system bodies |
| `kinematics.galactic` | U, V, W relative to the local standard of rest and population membership; three solutions (RV −30, 0, +30 km/s) and their envelope when no radial velocity is measured |
| `age_mass` | Spectral, kinematic and joint age (16–84 %), mass, model temperature, log g and radius, the mass–age degeneracy track, assumptions and references |
| `galactic_orbit` | Summary of the galpy orbit and solar encounter from the core backend (`POST /api/v1/orbit/simulate`) |
| `validation` | Scorecard rows (AEON value, reference, verdict, cause), SIMBAD status, literature sources and a rule-based summary in English and Turkish |
| `provenance` | Where each block came from: snapshot or live query, SPHEREx epoch and blend checks |

SPHEREx points enter the SED only from real frames (`data_mode: "fits_archive"`): bands the backend
measured, not interpolated, not blended with a neighbour, and with S/N ≥ 3. When Gaia finds no optical
source but SPHEREx shows bright flux below 1.05 µm, that flux belongs to a neighbour and the SPHEREx points
below 2.5 µm are left out. Results are cached for 24 hours; a result missing SIMBAD or the orbit is
retried after 30 minutes.

### Stage 2: age and mass ([`app/age_mass.py`](app/age_mass.py), [`app/kinematics.py`](app/kinematics.py))

- **Spectral channel.** Sources without a Gaia parallax are fitted as substellar objects: absolute W2 (from
  the SPHEREx 4.2–5.0 µm bands, or AllWISE) against the Sonora Bobcat evolution tracks and atmosphere
  magnitudes. Stars with a Gaia parallax are fitted with luminosity and temperature against the BHAC15
  tracks. Priors are flat in age (1 Myr–12 Gyr) and in log mass.
- **Kinematic channel.** p(U, V, W | age) from the age–velocity dispersion relation of Aumer & Binney
  (2009, Table 6); populations from Bensby, Feltzing & Oey (2014, Table A.1); solar motion from
  Schönrich, Binney & Dehnen (2010).
- **Disks.** A mid-infrared excess (W3 or W4 above three times the photosphere) is left out of the
  luminosity, and the disk-lifetime prior exp(−t / 2.5 Myr) of Mamajek (2009) is applied.
- **No forced answers.** Values the models cannot reach (best χ² > 9) give no age or mass, only the
  reason; a channel without data reports `unmeasured`.

### Stage 4: validation ([`app/validation.py`](app/validation.py), [`app/simbad.py`](app/simbad.py))

- **Reference.** The SIMBAD row of the object, from CDS Strasbourg, then the Harvard-Smithsonian CfA
  mirror, then the stored snapshot, pushed through the same kinematics and the same galpy orbit as AEON’s
  own inputs. Literature values come from
  [`fixtures/validation_reference.json`](fixtures/validation_reference.json), each with its bibcode.
- **Verdict.** *Consistent* when the two intervals overlap (velocities and orbit values also within 1 km/s,
  0.05 kpc, 0.02 kpc in z, 0.01 in eccentricity, 0.02 pc or 0.2 kyr); *partly consistent* when they miss by
  less than 25 % of the reference value; *discrepant* otherwise.
- **Summary.** The written summary is assembled from the rows only; no language model is involved.

## Other endpoints

- `GET /api/v1/alerts/gcn?limit=20` returns NASA GCN Circulars received over Kafka when
  `GCN_CLIENT_ID` and `GCN_CLIENT_SECRET` are set (or from `AEON_GCN_ARCHIVE_URL`). Without a source it
  returns an empty list, never invented alerts.
- `GET` and `POST /api/v1/candidates` keep a candidate list in MongoDB (`MONGODB_URI`) or in memory. Entries
  within 3″ are merged. When `GITHUB_TOKEN` is set, candidates with `anomaly_score ≥ 0.90` and S/N ≥ 5 open
  a GitHub issue labelled `discovery` and `automated` (`synthetic-test` for synthetic objects).

## Data in this folder

| Path | Content |
|---|---|
| [`fixtures/crossmatch_fixtures.json`](fixtures/crossmatch_fixtures.json) | Gaia DR3, AllWISE and MAST rows for catalog targets ([`scripts/build_fixtures.py`](scripts/build_fixtures.py), [`scripts/extend_fixtures_datalab.py`](scripts/extend_fixtures_datalab.py)) |
| [`fixtures/validation_reference.json`](fixtures/validation_reference.json) | Peer-reviewed values with bibcodes and the SIMBAD snapshot ([`scripts/build_validation_fixtures.py`](scripts/build_validation_fixtures.py)) |
| [`app/data/`](app/data/README.md) | Sonora Bobcat and BHAC15 tables, stored unchanged |

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AEON_CORE_URL` | `http://localhost:8000` | Core backend (spectra and orbits) |
| `AEON_AI_URL` | `http://localhost:8100` | ai-engine |
| `AEON_SIMBAD_TAP` | CDS, then the Harvard mirror | Comma-separated SIMBAD TAP endpoints, tried in order |
| `AEON_SIMBAD_TIMEOUT_S` | `8` | Timeout per SIMBAD server |
| `AEON_CORE_SPECTRUM_TIMEOUT_S`, `AEON_CORE_ORBIT_TIMEOUT_S` | `12`, `20` | Timeouts for calls to the core backend |
| `AEON_CACHE_DIR` | `.cache_crossmatch` | Result and SIMBAD cache |
| `MONGODB_URI` | — | Candidate store; in memory when unset |
| `GCN_CLIENT_ID`, `GCN_CLIENT_SECRET`, `AEON_GCN_ARCHIVE_URL` | — | GCN sources |
| `GITHUB_TOKEN`, `GITHUB_REPO` | —, `alpztel/aeon` | Optional issue creation for strong candidates |
| `AEON_CORS_ORIGINS` | see `.env.example` | Allowed browser origins |

## Run and test

```bash
cd multi-mission-api
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8200
pytest -q
```

The tests never contact an archive: archive calls are mocked, and SIMBAD stays offline unless
`AEON_ENABLE_LIVE_SIMBAD=1` is set.
