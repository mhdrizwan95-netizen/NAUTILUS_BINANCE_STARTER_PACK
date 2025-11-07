# Secrets Handling

- Keep real credentials out of git. Use `.env` locally and never commit it; rely on `.env.example` for documented defaults.
- Regenerate `.env.example` with `python scripts/generate_env_example.py` whenever configuration keys change.
- Prefer Docker secrets, SSM, or Vault when deploying; never bake API tokens into images or compose files.
- During dry runs (`DRY_RUN=1`), rely on placeholder tokens (see `scripts/dry_run.sh`) and ensure downstream services treat them as read-only.
- `OPS_API_TOKEN` (or `OPS_API_TOKEN_FILE`) is mandatory for `ops`, `ui_api`, and `strategy_router`. Set a deterministic placeholder (e.g., `test-ops-token-1234567890`) for tests and rotate real values via secret stores in production.
- Document any secret rotation or incident response in `audit_state/` alongside mitigation notes.
