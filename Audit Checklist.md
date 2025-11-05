🧭 Codex Autonomous System Audit Checklist

Purpose: Full-stack dynamic audit — backend, frontend, ML↔Backtesting, config, observability, control plane, and dry-run rehearsal.
Tool: Codex with context-limited step-wise execution and persistent JSON state.

⚙️ Codex Execution Rules

Before every prompt, Codex must paste:

# STATE_LOAD
{ ...output of the latest saved JSON (see below)... }
# END_STATE


This allows Codex to recover its audit memory between slices.

After every response, Codex must:

Copy the STATE_UPDATE JSON block it produced.

Save it locally by running:

cat > audit_state/STATE_<slice>.json
# paste STATE_UPDATE JSON here
# then Ctrl+D


The next prompt must reload this JSON via STATE_LOAD at the top.

To reload the latest audit memory, Codex must run:

ls -t audit_state/STATE_*.json | head -1 | xargs cat


Then paste the resulting JSON into the next prompt before continuing.

To merge all saved slices (before roll-ups):

jq -s 'reduce .[] as $x ({}; . * $x )' audit_state/STATE_*.json > audit_state/STATE_ROLLUP.json

🧱 Audit Workflow Overview

T-00 — Recon: Identify components and slice plan.

Slice Tickets: Run each [T-*] sequentially, inserting STATE_LOAD at top and saving new JSONs.

Interim Roll-Up [R-INTERIM]: Merge progress and generate quick fixes.

Final Roll-Up [R-FINAL]: Generate global report, diagram, and launch checklist.

🧩 State Memory Reference

Codex maintains a unified JSON structure (STATE):

{
  "slices": [ { "name": "", "paths": [] } ],
  "arch_components": [],
  "broken_links": [],
  "env_map": {},
  "ports": [],
  "datastores": [],
  "topics": [],
  "control_api": [],
  "ops_actions": [],
  "rbac": {},
  "policy_guards": [],
  "budgets": {},
  "alloc_constraints": {},
  "selector": "",
  "gates": {},
  "universe_policy": {},
  "tiers": {},
  "closed_loop": false,
  "gates_live": {},
  "hitl": {},
  "cooldowns": {},
  "shadow_mode": false,
  "smoke_checks": [],
  "ci_jobs": [],
  "gates_ci": [],
  "slis": [],
  "slos": [],
  "alerts": [],
  "dep_risks": 0,
  "perf_hotspots": []
}

✅ Ticketed Prompts

Each prompt below must begin with:

# STATE_LOAD
{ ...contents of latest STATE_*.json... }
# END_STATE


Then Codex must append its own STATE_UPDATE block at the end of the answer and save it using the cat > audit_state/STATE_<slice>.json command.

[T-00] Recon & Slice Plan

Purpose: Identify repo structure, define ≤12 slices.

TASK: Build a component map and ≤12-slice audit plan.

INPUTS:
- FILE_LIST: <<<first ~120 lines>>>
- BIGFILES: <<<top ~30 lines>>>
- TOP_CONFIGS: <<<first ~120 lines>>>

OUTPUT: Output Contract + STATE_UPDATE { "slices": [ { "name": "...", "paths": ["..."] } ] }

[T-ARCH] Architecture ↔ Code Alignment

Ensure code and architecture map match.

TASK: Verify diagrams ↔ code/configs.
INPUTS:
- MERMAID: <<<system diagrams>>>
- FILE_LIST: <<<~80 lines>>>
- TOP_CONFIGS: <<<~120 lines>>>
OUTPUT: Output Contract + table + STATE_UPDATE { "arch_components": [...], "broken_links": [...] }

[T-CFG] Config & Settings

Map environment and config precedence.

TASK: Canonical config map (defaults, precedence, required).
INPUTS:
- ENV_USAGE_CODE: <<<audit_inputs/ENV_USAGE_CODE.txt>>>
- CONFIG_FILES: <<<audit_inputs/CONFIG_FILES.txt>>>
OUTPUT: Output Contract + config.schema.json + config.example.env
STATE_UPDATE: { "env_map": {...}, "config_files": [...] }

[T-CTRL-API] Control Plane API

Audit intervention endpoints.

TASK: Authoritative control endpoints with guardrails.
INPUTS: BK_CONTROL_SNIPPETS + POLICY_SNIPPETS + CONFIG_SNIPPETS
OUTPUT: Output Contract + OpenAPI + middleware code
STATE_UPDATE: { "ctrl_endpoints": [...], "policy_guards": [...] }

[T-CTRL-UI] Ops Dashboard

Ensure frontend mirrors backend & enables safe interventions.

TASK: Ops UI mirrors backend state & safe actions.
INPUTS:
- FE_FILES
- FE_OPS_SNIPPETS
- FE_STREAMS
- BK_CONTROL_SNIPPETS
OUTPUT: Output Contract + Control API contract + OpsPanel skeleton + audit log schema
STATE_UPDATE: { "control_api": [...], "ops_actions": [...], "rbac": {...} }

[T-FUNDS] Dynamic Fund Management
TASK: Dynamic budgets & allocation.
INPUTS:
- STRATEGY_SNIPPETS
- POLICY_SNIPPETS
OUTPUT: Output Contract + funds.yaml + rebalance.py + smoke_funds.sh
STATE_UPDATE: { "budgets": {...}, "alloc_constraints": {...} }

[T-SELECT] Dynamic Strategy Selection
TASK: Selector (bandit/UCB/Thompson) with gates.
INPUTS: STRATEGY_SNIPPETS + BT_ML_SNIPPETS
OUTPUT: Output Contract + strategy_registry.md + selector.py + selector_smoke.sh
STATE_UPDATE: { "selector": "thompson|ucb", "gates": {...} }

[T-CFG-DYN] Dynamic Config Management
TASK: Remote, auditable config.
INPUTS: CONFIG_SNIPPETS
OUTPUT: Output Contract + config.schema.json + configctl CLI sketch + watcher
STATE_UPDATE: { "config_store": "...", "audit_trail": true }

[T-SYMBOLS] Dynamic Symbol Universe
TASK: Universe from filters + ML/backtest penalties.
INPUTS: SYMBOL_SNIPPETS + BT_ML_SNIPPETS
OUTPUT: Output Contract + symbols_policy.yaml + universe.py + universe_smoke.sh
STATE_UPDATE: { "universe_policy": {...}, "tiers": {...} }

[T-LOOP-LEARN] ML ↔ Backtesting Closed Loop
TASK: Integrate ML with backtesting feedback.
INPUTS: BT_ML_SNIPPETS
OUTPUT: Output Contract + orchestrator.yaml + trainer.py + candidate_config.json
STATE_UPDATE: { "closed_loop": true, "gates_live": {...} }

[T-HITL] Human-in-the-Loop Safety
TASK: Two-man rule + cooling-off + rollback.
INPUTS: POLICY_SNIPPETS
OUTPUT: Output Contract + approval_flow.md + middleware stub
STATE_UPDATE: { "hitl": { "two_man": true, "cooldowns": ... } }

Appendix: Additional Slices
🔁 Required ritual for every slice in this appendix

At the very top of the prompt you send to Codex, paste the latest JSON:

# STATE_LOAD
{ ...contents of the latest audit_state/STATE_*.json... }
# END_STATE


After Codex responds, copy the STATE_UPDATE JSON it produced and save it:

cat > audit_state/STATE_<slice>.json
# paste STATE_UPDATE JSON here
# Ctrl+D


(Optional) Merge all STATEs for interim or final roll‑ups:

jq -s 'reduce .[] as $x ({}; . * $x )' audit_state/STATE_*.json > audit_state/STATE_ROLLUP.json

[T-AUTHZ] Authentication, Authorization & RBAC
TASK: Audit authn/authz & RBAC across backend + frontend.

CONTEXT (≤200 lines):
- Login/session/JWT/OIDC handlers, role checks in handlers/components, token refresh/rotation, permission enums.

REQUESTS:
1) Map roles→permissions; identify missing server-side checks (do not trust client).
2) Validate session/JWT lifetimes, rotation, revocation, clock skew.
3) Emit: permission matrix, middleware for authz decision, and test cases.

OUTPUT: Output Contract + permission_matrix.md + authz_middleware snippet + tests.
STATE_UPDATE: { "rbac": { "roles": ["..."], "permissions": ["..."] }, "policy_guards": ["authz_enforced"] }

[T-API] API Design, Versioning & Pagination
TASK: Audit API consistency (naming, versioning, pagination, filters).

CONTEXT (≤200 lines):
- Representative handlers/routes/OpenAPI parts.

REQUESTS:
1) Ensure resource naming, error shapes, idempotency for mutations.
2) Define versioning policy (path or header) and deprecation rules.
3) Standardize pagination + filtering + sorting contracts.

OUTPUT: Output Contract + api_guidelines.md + OpenAPI patch.
STATE_UPDATE: { "policy_guards": ["api_versioning_policy","pagination_standardized"] }

[T-FE-SEC] Frontend Security (CSP, SRI, XSS, CSRF, CORS)
TASK: Harden frontend security.

CONTEXT (≤200 lines):
- index.html/meta headers, fetch/Axios, CSRF tokens, any HTML injection sites, build config.

REQUESTS:
1) Emit CSP (script-src 'self' + hashes), SRI on static bundles, strict MIME types.
2) CSRF defense (double submit or SameSite+token), output encoding patterns.
3) CORS correctness (origins, credentials).

OUTPUT: Output Contract + security_headers.md + CSP example + CSRF middleware.
STATE_UPDATE: { "policy_guards": ["csp_enabled","csrf_enabled","cors_correct"] }

[T-CACHE] HTTP/CDN/App Caching
TASK: Cache strategy audit (HTTP validators, CDN, in-app caches).

CONTEXT (≤200 lines):
- Responses with static assets/data, ETag/Last-Modified usage, cache-control headers, CDN config if any.

REQUESTS:
- Propose caching tiers; add ETag/Last-Modified; safe TTLs; stale-while-revalidate; invalidation.
OUTPUT: Output Contract + cache_guidelines.md + header patches.
STATE_UPDATE: { "policy_guards": ["http_cache_etag","cdn_cache_tiered"] }

[T-BOOT] Startup Ordering & Readiness
TASK: Audit service startup & readiness gates.

CONTEXT (≤200 lines):
- Entrypoints, health/readiness probes, migrations at boot.

REQUESTS:
- Start order, blocking on dependencies, readiness with explicit checks; fail-fast vs retry policy.
OUTPUT: Output Contract + readiness checklist + probe diffs.
STATE_UPDATE: { "policy_guards": ["readiness_gates"], "gates_ci": ["boot_checks"] }

[T-RESILIENCE] Backpressure, Bulkheads, Timeouts
TASK: Resilience pattern audit.

CONTEXT (≤200 lines):
- Calls between services, queue sizes, thread/connection pools.

REQUESTS:
- Add bulkheads, bounded queues, backpressure signals, fallback modes.
OUTPUT: Output Contract + diffs + resilience_checklist.md.
STATE_UPDATE: { "policy_guards": ["bulkheads","bounded_queues"], "gates_ci": ["resilience_smoke"] }

[T-CHAOS] Fault Injection / Chaos
TASK: Minimal chaos experiments.

CONTEXT (≤200 lines):
- Toggle points to inject latency/errors; retry configs.

REQUESTS:
- Define 2–3 safe chaos probes; add chaos toggle; write chaos_smoke.sh with assertions.
OUTPUT: Output Contract + chaos_toggles.md + chaos_smoke.sh.
STATE_UPDATE: { "gates_ci": ["chaos_smoke_available"] }

[T-TRACE] Trace Propagation & Correlation IDs
TASK: Verify trace context across boundaries.

CONTEXT (≤200 lines):
- Logging formatters, HTTP clients/servers, async tasks.

REQUESTS:
- Ensure trace-id/span-id injection, log correlation, baggage for user/request.
OUTPUT: Output Contract + tracing_patch.diff + logs_contract.md update.
STATE_UPDATE: { "policy_guards": ["trace_correlation"], "alerts": [...merge...] }

[T-SBOM] Supply Chain: SBOM, Signing, SLSA-lite
TASK: Build provenance & SBOM.

CONTEXT (≤200 lines):
- CI scripts, container build pipeline.

REQUESTS:
- Add SBOM generation (CycloneDX/SPDX), sign images/artifacts, verify in CI, record provenance.
OUTPUT: Output Contract + CI jobs + sbom_policy.md.
STATE_UPDATE: { "gates_ci": ["sbom_generated","artifacts_signed"] }

[T-SECRETS-SCAN] Secret Scanning & Pre-Commit
TASK: Repo secret scanning.

CONTEXT (≤200 lines):
- Existing hooks/CI jobs.

REQUESTS:
- Add gitleaks/trufflehog in pre-commit + CI; baseline & allowlist policy.
OUTPUT: Output Contract + .pre-commit-config.yaml + CI job.
STATE_UPDATE: { "gates_ci": ["secrets_scan_enabled"] }

[T-I18N] Internationalization & Time/Locale
TASK: i18n audit.

CONTEXT (≤200 lines):
- i18n libraries usage, date/number formatting, timezone handling.

REQUESTS:
- Locale-aware formatting; language negotiation; timezone correctness; RTL support checklist.
OUTPUT: Output Contract + i18n_checklist.md + patches.
STATE_UPDATE: { "policy_guards": ["i18n_sane_defaults"] }

[T-TEST] Test Health (unit/integration/e2e/property/fuzz)
TASK: Testing strategy audit.

CONTEXT (≤200 lines):
- Test layout, coverage summary, flakiness indicators.

REQUESTS:
- Add property tests for critical invariants; e2e happy-paths; fuzz for parsers.
OUTPUT: Output Contract + test_plan.md + sample tests.
STATE_UPDATE: { "gates_ci": ["coverage_target","property_tests_added"] }

[T-LOAD] Load/Soak/Stress Testing
TASK: Performance validation under load.

CONTEXT (≤200 lines):
- Current k6/Locust/JMeter scripts (if any).

REQUESTS:
- Define realistic scenarios; SLO-based thresholds; soak test schedule.
OUTPUT: Output Contract + load_tests/ + CI job snippet.
STATE_UPDATE: { "perf_hotspots": [...merge...], "gates_ci": ["load_tests_added"] }

[T-RUNBOOK] Ops Runbooks & Incident Response
TASK: Runbooks & on-call readiness.

CONTEXT (≤200 lines):
- Existing docs, escalation paths.

REQUESTS:
- Author runbooks for top incidents; add pager policy; drill checklist.
OUTPUT: Output Contract + runbooks/*.md + escalation.md.
STATE_UPDATE: { "alerts": [...merge...], "policy_guards": ["runbooks_present"] }

[T-WEBHOOK] Webhooks (in/out) & Signatures
TASK: Webhook correctness & security.

CONTEXT (≤200 lines):
- Handlers & signing code.

REQUESTS:
- Verify signatures (HMAC/ED25519), replay protection (timestamp+nonce); retry/backoff; idempotency.
OUTPUT: Output Contract + webhook_contract.md + middleware.
STATE_UPDATE: { "policy_guards": ["webhook_sig_verify","webhook_replay_protect"] }

[T-NOTIFY] Notifications (Email/SMS/Push)
TASK: Notification pipeline.

CONTEXT (≤200 lines):
- Providers, templates, retries, dedupe.

REQUESTS:
- Template safety; rate limits; suppression; bounce handling; audit events.
OUTPUT: Output Contract + notify_checklist.md + diffs.
STATE_UPDATE: { "policy_guards": ["notify_dedupe","notify_rate_limits"] }

[T-API-RATE] Rate Limiting & Quotas
TASK: Enforce fair use & protection.

CONTEXT (≤200 lines):
- Gateways/middlewares, per-user keys.

REQUESTS:
- Sliding window / token bucket; headers for remaining quota; per-actor limits.
OUTPUT: Output Contract + limiter middleware + tests.
STATE_UPDATE: { "policy_guards": ["rate_limit_enabled"] }

[T-CERTS] TLS, Certificates & Rotation
TASK: TLS posture & rotation.

CONTEXT (≤200 lines):
- Cert locations, TLS settings, trust stores, pinning.

REQUESTS:
- mTLS where needed; rotation runbook; minimum TLS version; strong ciphers; cert reload.
OUTPUT: Output Contract + tls_policy.md + config diffs.
STATE_UPDATE: { "policy_guards": ["tls_min_version","cert_rotation_runbook"] }

[T-CORS] CORS Configuration Correctness
TASK: CORS audit.

CONTEXT (≤200 lines):
- Server CORS config & FE fetch patterns.

REQUESTS:
- Explicit allowlist; credentials rules; preflight caching; reject wildcards in prod.
OUTPUT: Output Contract + cors_policy.md + diffs.
STATE_UPDATE: { "policy_guards": ["cors_strict"] }

[T-PROF] Server Profiling (CPU/Heap)
TASK: Profiling setup.

CONTEXT (≤200 lines):
- Profiling toggles; endpoints; symbol maps.

REQUESTS:
- Add on-demand CPU/heap profiler; sampling plan; safe production guardrails.
OUTPUT: Output Contract + profiling_runbook.md + profile scripts.
STATE_UPDATE: { "perf_hotspots": [...merge...] }

[T-FE-PERF] Frontend Performance Budget & Build
TASK: FE bundle & web vitals budget.

CONTEXT (≤200 lines):
- Build config, route-level bundles, lazy loading.

REQUESTS:
- Define KB/time budgets; code-splitting; prefetch policies; vitals thresholds.
OUTPUT: Output Contract + perf_budget.md + build diffs.
STATE_UPDATE: { "gates_ci": ["fe_perf_budget"] }

[T-EDGE] Edge/CDN Configuration
TASK: CDN controls & edge logic.

CONTEXT (≤200 lines):
- CDN rules, edge functions, caching keys.

REQUESTS:
- Normalize cache keys; purge strategy; security headers at edge.
OUTPUT: Output Contract + cdn_rules.md.
STATE_UPDATE: { "policy_guards": ["cdn_rules_defined"] }

[T-MIGRATE] Migration Dry-Run & Rollback
TASK: Safe schema evolution.

CONTEXT (≤200 lines):
- Migration scripts & tooling.

REQUESTS:
- Shadow tables/backfills; online migrations; rollback; preflight checks in CI.
OUTPUT: Output Contract + migrate_runbook.md + migrate_smoke.sh.
STATE_UPDATE: { "policy_guards": ["migration_safety"], "gates_ci": ["migration_preflight"] }

[T-DATA-GOV] Data Governance & Lineage
TASK: Data catalog & lineage.

CONTEXT (≤200 lines):
- Schemas, ETL/ELT scripts, analytics events.

REQUESTS:
- Classify PII; owner per dataset; lineage diagram; retention by class.
OUTPUT: Output Contract + data_map.csv + lineage.md.
STATE_UPDATE: { "data_classes": ["..."], "retentions": ["..."] }

Quick Roll-Ups (unchanged)

Use your existing [R-INTERIM] and [R-FINAL] sections; they work with these slices as-is. Remember to run:

jq -s 'reduce .[] as $x ({}; . * $x )' audit_state/STATE_*.json > audit_state/STATE_ROLLUP.json


…and paste that into the roll‑up prompts under # STATE_LOAD.

[T-DRYRUN] Dry-Run / Shadow Mode
TASK: Full shadow rehearsal.
INPUTS: DRYRUN_SNIPPETS + control_api snippet
OUTPUT: Output Contract + compose.override.yaml + smoke_shadow.sh
STATE_UPDATE: { "shadow_mode": true, "smoke_checks": [...] }

🧩 Roll-Ups
[R-INTERIM]
# STATE_LOAD
{ ...contents of audit_state/STATE_ROLLUP.json... }
# END_STATE

TASK: Merge intermediate slices.
OUTPUT: Output Contract + table + STATE_UPDATE { "top5": ["id1","id2","id3","id4","id5"] }

[R-FINAL]
# STATE_LOAD
{ ...contents of audit_state/STATE_ROLLUP.json... }
# END_STATE

TASK: Full autonomy roll-up & dry-run launch plan.
OUTPUT: Output Contract + mermaid + launch_checklist.md
STATE_UPDATE: { "top10": ["..."], "diagram": "mermaid code" }

🧾 Post-Run Summary

All STATE_*.json are merged into STATE_ROLLUP.json.

Codex generates a launch checklist validating:

Shadow mode parity

Idempotency on all control APIs

Policy guard enforcement

Two-man approval on high-risk actions

Universe/selector gates enforced

Rollback and audit log pass tests