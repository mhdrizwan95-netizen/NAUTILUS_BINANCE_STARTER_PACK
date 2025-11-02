# Secrets Directory Template

Copy this directory to `secrets/` (which is git-ignored) and populate the files
with real credentials before running hardened compose profiles:

- `ops_api_token` — the Ops API bearer token used for privileged endpoints.
- `grafana_admin_password` — the Grafana admin password consumed by the
  observability stack.

Rotate these secrets regularly and source them from your preferred secrets
manager in non-local environments.
