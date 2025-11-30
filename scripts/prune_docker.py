import yaml
import sys
from pathlib import Path

# Services to REMOVE
REMOVE_SERVICES = {
    "executor",
    "strategy_runtime",
    "backfill",
    "slip_trainer",
    "research_scrubber",
    "data_backfill"
}

def prune_docker():
    print("✂️ STARTING DOCKER PRUNE...")
    
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
    removed_count = 0
    
    for service_name in REMOVE_SERVICES:
        if service_name in services:
            del services[service_name]
            print(f"   - Removed: {service_name}")
            removed_count += 1
        else:
            print(f"   - Not found (already clean): {service_name}")

    if removed_count == 0:
        print("✅ No services needed pruning in docker-compose.yml.")
    else:
        # Write back
        with open(dc_path, "w") as f:
            yaml.dump(data, f, sort_keys=False, default_flow_style=False)
        print(f"✅ Pruned {removed_count} services from docker-compose.yml.")

    # Check override file
    override_path = Path("docker-compose.override.yml")
    if override_path.exists():
        print("🔎 Checking docker-compose.override.yml...")
        try:
            with open(override_path, "r") as f:
                over_data = yaml.safe_load(f)
            
            if "services" in over_data:
                over_services = over_data["services"]
                over_removed = 0
                for s in REMOVE_SERVICES:
                    if s in over_services:
                        del over_services[s]
                        print(f"   - Removed from override: {s}")
                        over_removed += 1
                
                if over_removed > 0:
                    with open(override_path, "w") as f:
                        yaml.dump(over_data, f, sort_keys=False, default_flow_style=False)
                    print(f"✅ Pruned {over_removed} services from docker-compose.override.yml.")
                else:
                    print("✅ Override file is clean.")
        except Exception as e:
            print(f"⚠️ Failed to process override file: {e}")

if __name__ == "__main__":
    prune_docker()
