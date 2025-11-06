# Contributing

## Prerequisites
- Python 3.11.x and Node 20.x (align with CI via `pyenv`, `asdf`, or Docker).
- Docker + docker compose v2 for local orchestration.

## Workflow
1. `git checkout -b repo-audit/$(date +%Y%m%d)-short-description`
2. `make bootstrap` to install pinned dependencies and pre-commit hooks.
3. Implement changes with `DRY_RUN=1` unless you have explicit approval to trade.
4. `pre-commit run --all-files` and `make lint typecheck test` before pushing.
5. `make audit` to run the read-only security suite and attach reports as artifacts.

## Pull Requests
- Reference relevant `audit_state/*.json` items when closing findings.
- Add or update tests alongside fixes; prefer deterministic fixtures over sleeps.
- Update docs (README, docs/secrets.md) when behavior or configuration changes.
- Regenerate lockfiles (`pip-compile`, `npm ci --package-lock-only`) whenever dependencies shift and call it out in the PR body.
