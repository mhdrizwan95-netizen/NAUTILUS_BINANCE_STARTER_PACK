# Security Posture

This repository carries a non‑negotiable requirement that the dependency tree is free
of known vulnerabilities and that we actively surface coding patterns Bandit/Ruff flag
as unsafe.

## 2025-11-08 dependency remediation

| Package | Former | Current | CVE(s) | Notes |
|---------|--------|---------|--------|-------|
| `jinja2` | 3.1.4 | 3.1.6 | GHSA-q2x7-8rv6-6q7h,<br>GHSA-gmj6-6f8f-6699,<br>GHSA-cpwx-vrp4-4pq7 | Sandboxed template rendering inherits the upstream escape fixes; all FastAPI responses now use the patched runtime. |
| `requests` | 2.32.3 | 2.32.4 | GHSA-9hjg-9r4m-mvj7 | The HTTP client follows the upstream redirect hardening advisory. |
| `python-jose` | 3.3.0 | — (migrated to `pyjwt[crypto]` 2.9.0) | PYSEC-2024-232,<br>PYSEC-2024-233 | JWT validation now uses PyJWT + `cryptography`; we no longer vendor `ecdsa`. |
| `ecdsa` | 0.19.1 | — (removed) | GHSA-wj6h-64fc-37mp | The only consumer was `python-jose`; removing it eliminates the vulnerable primitive entirely. |

### Pending advisories (front-end toolchain)

| Package | Installed | Advisory | Impact | Mitigation |
|---------|-----------|----------|--------|------------|
| `vite`, `vitest`, `esbuild` (dev dependencies) | 5.x / 2.x / 0.23.x | GHSA-67mh-4wv8-2f99 (esbuild request smuggling) | CI/dev-only tooling; not shipped in production artifacts. Runners are already gated by network egress policies. | Upgrade to the next coordinated Vite/Vitest release train (target: 2025-11-30) once upstream publishes patched bundles. Tracking issue: `SEC-217`. Documented here to keep the exception visible; no allowlist is configured in CI. |

### Verification

```
pip-compile --generate-hashes --output-file=requirements.txt pyproject.toml
pip-compile --constraint=requirements.txt --extra=dev --generate-hashes --output-file=requirements-dev.txt pyproject.toml
pip-audit
```

`pip-audit` must report `0` findings before we ship. The regenerated lock files live under version control to keep hashes aligned.

### Rollback

If the upgraded packages cause a regression, revert to the previous commit and pin the CVE backport in `pyproject.toml`. Document the reason, open a Sev‑2 ticket, and add an `allowlist.toml` entry to `pip-audit` with an expiry date.

## Runtime hardening

Bandit flagged hundreds of `try/except/pass` sites. We are systematically replacing bare handlers with structured logging + retries. Any remaining `B110` findings must be accompanied by a comment that links to a tracking issue and the `# nosec` rationale.
