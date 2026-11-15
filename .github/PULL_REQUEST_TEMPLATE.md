## Summary

<!-- What does this change, and why? -->

## Checks

- [ ] Tests pass for every part I touched (`pytest -q` per service; `npm run lint && npm run typecheck && npm run build` for the frontend)
- [ ] `openapi.json` still has 11 paths and stays backwards compatible (optional fields only)
- [ ] Every new number has a source; anything not measurable is reported as `unmeasured`
- [ ] Synthetic objects and model data are labelled
- [ ] No secrets or `.env` files
