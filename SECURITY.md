# Security policy

## Supported versions

AEON is complete and maintained on a best-effort basis. Fixes are made on `main`; there are no maintained
release branches. The hosted demo has been retired, so reports concern the code in this repository.

## Reporting a vulnerability

Please do not report security problems in public issues, pull requests or discussions.

- If GitHub’s private vulnerability reporting is enabled for this repository, use **Security → Report a
  vulnerability**.
- Otherwise contact the project lead privately through the contact details on the
  [@alpztel](https://github.com/alpztel) GitHub profile.

Please include the affected component (backend, ai-engine, multi-mission-api, frontend or deploy), the
steps to reproduce, and the impact you expect. We will acknowledge the report and keep you informed while
we look into it.

## Good to know

- Services read secrets only from environment variables, kept in `deploy/.env`, which is never committed:
  `ANTHROPIC_API_KEY`, `MONGODB_URI`, `GITHUB_TOKEN`, `GCN_CLIENT_ID` and `GCN_CLIENT_SECRET`.
- Archive access (IRSA, Gaia, WISE, MAST, SIMBAD) is read-only and needs no credentials.
- All request parameters are validated against the OpenAPI contract, and the test suites include hostile
  and malformed inputs.
