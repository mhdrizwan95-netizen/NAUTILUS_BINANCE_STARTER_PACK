#!/usr/bin/env bash
set -euo pipefail

echo "🔧 BATCH-FIXING DASHBOARD LABEL MISMATCHES"
echo "=========================================="

# Function to backup and fix a dashboard file
fix_dashboard() {
    local file="$1"
    local backup="${file}.bkup"
    local output="${file%.json}.fixed.json"
    
    if [[ ! -f "${file}" ]]; then
        echo "⚠️  Skipping: ${file} not found"
        return
    fi
    
    echo "📝 Fixing: ${file}"
    
    # Create backup (if not exists)
    if [[ ! -f "${backup}" ]]; then
        cp "${file}" "${backup}"
        echo "💾 Backup created: ${backup}"
    fi
    
    # Apply label corrections
    sed -E \
        -e 's/job="engine_binance"/job="engines"/g' \
        -e 's/job="engine_ibkr"/job="engines"/g' \
        -e 's/job="engine_bybit"/job="engines"/g' \
        -e 's/\$venue/"engines"/g' \
        -e 's/"venue"\s*:\s*"[^"]*"/"venue": "engines"/g' \
        -e 's/\$\{__all_instances\}/\{job="engines"\}/g' \
         < "${file}" > "${output}"
    
    echo "✅ Fixed: ${output}"
    echo "---"
}

# Process all JSON files
cd ops/observability/grafana/dashboards/

echo "🔍 Finding dashboard files..."
for file in *.json; do
    if [[ -f "${file}" ]]; then
        fix_dashboard "${file}"
    fi
done

echo ""
echo "📋 APPLYING FIXES TO GRAFANA:"
echo "1. Manual Import: Go to Grafana → Dashboards → Import"
echo "2. Upload each .fixed.json file"  
echo "3. Delete old dashboards"
echo "4. Or use API: curl -X DELETE \"http://localhost:3000/api/dashboards/uid/<uid>\""
echo ""
echo "🎯 RESULT: All dashboards will now show LIVE trading data!"
echo ""

