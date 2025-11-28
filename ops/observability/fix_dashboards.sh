#!/usr/bin/env bash
set -euo pipefail

echo "🔧 Dashboard label consistency check (non-destructive by default)"
echo "================================================================"

# Function to backup and fix a dashboard file
fix_dashboard() {
    local file="$1"
    local backup="${file}.bkup"
    local output="${file%.json}.fixed.json"

    if [[ ! -f "${file}" ]]; then
        echo "⚠️  Skipping: ${file} not found"
        return
    fi

    echo "🔍 Scanning: ${file}"
    # Show common mismatches (does not modify)
    # Legacy venues were removed; surfaces help identify stale labels
    if grep -q 'job="engine_' "${file}" 2>/dev/null; then
        echo "  • Found hardcoded engine job labels; ensure they reference hmm_engine_binance.* only."
    fi
    if grep -q '\$venue' "${file}" 2>/dev/null; then
        echo "  • Found templated \$venue; verify your labels match Prometheus jobs."
    fi
    # Detect static venue labels using POSIX classes (portable)
    if grep -Eq '"venue"[[:space:]]*:[[:space:]]*"[^"]+"' "${file}" 2>/dev/null; then
        echo "  • Found static 'venue' values; confirm they match exported labels."
    fi

    if [[ "${APPLY:-0}" == "1" ]]; then
        echo "🛠  APPLY=1 set — generating fixed file ${output} (non-destructive)."
        # Create backup (if not exists)
        if [[ ! -f "${backup}" ]]; then
            cp "${file}" "${backup}"
            echo "  💾 Backup created: ${backup}"
        fi
        # Apply sample label normalizations cautiously to a new file
        sed -E \
            -e 's/job="engine_binance"/job="hmm_engine_binance"/g' \
            -e 's/job="engine_binance_exporter"/job="hmm_engine_binance_exporter"/g' \
            -e 's/\$\{__all_instances\}/\{job=~"hmm_engine_.*"\}/g' \
             < "${file}" > "${output}"
        echo "  ✅ Wrote: ${output} (review before importing to Grafana)"
    else
        echo "  (Dry run: set APPLY=1 to generate a candidate .fixed.json)"
    fi
    echo "---"
}

# Process all JSON files
if [[ -d ops/observability/grafana/dashboards/ ]]; then
  cd ops/observability/grafana/dashboards/
else
  echo "⚠️  dashboards directory not found; skipping."
  exit 0
fi

echo "🔍 Finding dashboard files..."
for file in *.json; do
    if [[ -f "${file}" ]]; then
        fix_dashboard "${file}"
    fi
done

echo ""
echo "📋 Next steps:"
echo "1. If needed, re-run with APPLY=1 to generate .fixed.json candidates."
echo "2. Import .fixed.json in Grafana (Dashboards → Import) or adjust panels manually."
echo "3. Prefer aligning exporters/labels over mass-rewriting dashboard queries."
echo ""
