# Secrets Handling

- Keep real credentials out of git. Use `.env` locally and never commit it; rely on `.env.example` for documented defaults.
- Regenerate `.env.example` with `python scripts/generate_env_example.py` whenever configuration keys change.
- Prefer Docker secrets, SSM, or Vault when deploying; never bake API tokens into images or compose files.
- During dry runs (`DRY_RUN=1`), rely on placeholder tokens (see `scripts/dry_run.sh`) and ensure downstream services treat them as read-only.
- Document any secret rotation or incident response in `audit_state/` alongside mitigation notes.
