# Secrets & Environment Policy

This repository treats runtime credentials as ephemeral configuration that must never land in git history.

## Golden rules

- **.env files stay local.** Copy `env.example` to `.env`, override values, and keep the file untracked. The root `.gitignore` already excludes `.env`, `.env.*`, and `secrets/`.
- **Prefer files over inline literals.** When Docker Compose services need credentials (e.g., `OPS_API_TOKEN`), point `*_FILE` variables at `./secrets/*.txt` so operators can rotate tokens without editing source.
- **Document every knob.** Extend `env.example` plus `docs/` whenever you introduce a new `FOO_URL`/`FOO_TOKEN`.
- **Use DRY_RUN defaults when testing.** Scripts such as `scripts/dry_run.sh` and CI set `OPS_API_TOKEN=test-ops-token-1234567890` and `DRY_RUN=1` so no live venues are touched.
- **Baseline secret scans.** `pre-commit` runs `detect-secrets` with `.secrets.baseline`; refresh it (`detect-secrets scan > .secrets.baseline`) whenever legit tokens move or are renamed.

## Recommended workflow

```bash
cp env.example .env
mkdir -p secrets
echo "my-real-token" > secrets/ops_api_token
echo "OPS_API_TOKEN_FILE=secrets/ops_api_token" >> .env
# Produce a scrubbed dry-run env for scripts/audit + scripts/dry_run
cp env.example .env.dryrun
printf "\nDRY_RUN=1\nOPS_API_TOKEN=dry-run-token\n" >> .env.dryrun
```

Compose picks up `.env` automatically, and the application reads the token lazily from disk. For Kubernetes or other orchestrators, mount secrets through the platform’s secret manager and mirror the same environment variable names.

## Auditing tips

- Run `ops/repo_sync_audit.sh` to diff frontend API usage against backend routes and to flag config drift between `.env` and actual code.
- Before committing, run `git status --ignored` to ensure no new secret paths slipped past `.gitignore`.
- `detect-secrets scan` before release branches to confirm `.secrets.baseline` matches reality; CI fails if the baseline is missing or stale.

When in doubt, assume anything committed to git will eventually become public. Keep secrets in a dedicated secret manager (AWS Secrets Manager, Doppler, 1Password CLI, etc.) and inject them at runtime.***
