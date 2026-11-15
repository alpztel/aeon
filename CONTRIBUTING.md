# Contributing to AEON

Thank you for your interest in AEON. The project was built for the NASA Space Apps Challenge 2026 and is
now complete: there is no active feature development, but bug reports, questions and focused fixes are
welcome.

## Reporting a problem

- Search the [existing issues](https://github.com/alpztel/aeon/issues) first.
- Open an issue with the **Bug report** form. Include what you ran, what you expected, what happened, and
  the output of `GET /api/v1/health` (it shows the version, engines and data mode).
- For security problems, do not open a public issue; follow [SECURITY.md](SECURITY.md).

## Setting up

The quickest way to run everything is Docker Compose; see [Quick start](README.md#quick-start). Each
service can also run on its own with Python 3.12 (`pip install -r requirements.txt`, then `uvicorn`), and
the frontend with Node.js 20 (`npm ci`, `npm run dev`). The service READMEs give the details.

## Before you open a pull request

1. **Branch from `main`.** Changes reach `main` only through a pull request, and every required check
   must pass.
2. **Run the checks for what you touched:**

   | Part | Command |
   |---|---|
   | `backend/` | `cd backend && pytest -q` |
   | `ai-engine/` | `cd ai-engine && pytest -q` |
   | `multi-mission-api/` | `cd multi-mission-api && pytest -q` |
   | `deploy/azure/` | `cd backend && pytest -q ../deploy/azure` |
   | `frontend/` | `cd frontend && npm run lint && npm run typecheck && npm run build` |

3. **Keep the API contract stable.** [`openapi.json`](openapi.json) has exactly 11 paths. Extend responses
   with optional fields only, and regenerate the frontend types with `npm run gen:api`.
4. **Follow the science rules.**
   - Every number comes from a measurement, a published table or an equation, and its source is named.
     When a value cannot be measured, return `unmeasured` (or an envelope) with the reason; never a
     placeholder.
   - Label synthetic test objects (`is_synthetic: true`) and model data (`data_mode: "physical_model"`).
   - Store published tables unchanged, together with their source and licence.
5. **Never commit secrets** or `.env` files. Services read keys only from the environment.
6. **Write commit messages** in the style of the history: `feat(scope): …`, `fix(scope): …`, `docs: …`,
   `chore: …`.

## House rules

- [`AGENTS.md`](AGENTS.md) describes the rules for human and AI contributors. On `agent/*` branches,
  `ci-guard` limits each branch to its own folders.
- [`CODEOWNERS`](.github/CODEOWNERS) requests a review from the project lead on every pull request.
- Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
