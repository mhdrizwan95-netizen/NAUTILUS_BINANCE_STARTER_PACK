# Data Retention & Disposal Policy (Draft)

## Scope
Applies to trading engine operational data, model training artifacts, research datasets, observability telemetry, and operator audit trails stored by the Nautilus stack across `/data`, `/models`, `/shared`, `/research`, and observability volumes.

## Retention Targets
- **Operational trading state (`/data/runtime`, order/fill SQLite, Redis snapshots):** retain 30 days online for incident analysis; archive encrypted snapshots quarterly for regulatory recordkeeping (7 years) when required by venue obligations.
- **Ops command/API audit logs:** retain 90 days hot per `ops/m25_policy.yaml`; export monthly CSVs to the compliance vault with access limited to SRE + Compliance. Purge hot copies after 90 days.
- **Model registry (`/models/registry` + metadata):** retain 180 days to support rollback and reproducibility; hash artifacts prior to archival. Delete superseded models older than 6 months unless under investigation.
- **Research/backtest datasets (`/research`):** default retention 30 days unless a research ticket references longer use. Auto-purge staging data after 30 days or immediately on DSAR request. Never copy customer-provided datasets into production `/data`.
- **Telemetry (Prometheus metrics, Loki logs, Grafana dashboards):** enforce 14-day retention for logs and metrics; aggregated dashboards may store derived metrics up to 90 days.

## Disposal Process
1. Queue data for deletion via scheduled jobs (cron/Argo) with evidence logged in `compliance_disposal.log`.
2. Verify deletion (checksum of directory, Loki query) and retain proof (timestamp, operator, dataset identifier) for audit.
3. For DSAR: acknowledge within 48h, complete purge within 30 days including backups (`/backups`, object storage buckets).

## Controls & Monitoring
- Configure Loki `retention_deletes_enabled=true` and `retention_period=336h` (14 days) and Prometheus `--storage.tsdb.retention.time` ≤ 30 days.
- Add CI check ensuring Grafana admin password is non-empty and sourced from secrets manager.
- Weekly job enumerates `/research` tree, deleting directories older than 30 days unless labeled `retain`.
- Access reviews quarterly; disable credentials of inactive operators (>90 days) and rotate API tokens every 60 days.

## Ownership
- **Data Steward:** Head of Data Engineering
- **Compliance Approver:** Compliance Officer / DPO
- **Ops Implementers:** Platform SRE team
