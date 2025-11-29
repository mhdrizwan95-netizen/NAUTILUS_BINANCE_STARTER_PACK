import yaml
import sys
from pathlib import Path

# Services to KEEP
KEEP_SERVICES = {
    "engine_binance",
    "engine_binance_exporter",
    "ops",
    "ml_service",
    "ml_scheduler",
    "param_controller",
    "data_ingester",
    "universe",
    "situations",
    "screener",
    "prometheus",
    "grafana"
}

def clean_docker():
    print("🐳 STARTING DOCKER CLEANUP...")
    
    dc_path = Path("docker-compose.yml")
    if not dc_path.exists():
        print("❌ docker-compose.yml not found!")
        sys.exit(1)

    try:
        with open(dc_path, "r") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Failed to parse YAML: {e}")
        sys.exit(1)

    if "services" not in data:
        print("❌ No 'services' key in docker-compose.yml")
        sys.exit(1)

    services = data["services"]
    to_remove = []
    
    for name in services.keys():
        if name not in KEEP_SERVICES:
            to_remove.append(name)

    if not to_remove:
        print("✅ No zombie containers found. Docker is clean.")
        return

    print(f"🗑️ Removing {len(to_remove)} zombie services:")
    for name in to_remove:
        del services[name]
        print(f"   - Removed: {name}")

    # Write back
    with open(dc_path, "w") as f:
        yaml.dump(data, f, sort_keys=False, default_flow_style=False)
    
    print("✅ DOCKER CLEANUP COMPLETE.")

if __name__ == "__main__":
    clean_docker()
