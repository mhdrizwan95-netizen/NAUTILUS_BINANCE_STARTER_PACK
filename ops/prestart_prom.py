import os
import pathlib

mp = os.getenv("PROMETHEUS_MULTIPROC_DIR", "/tmp/prom_multiproc")
pathlib.Path(mp).mkdir(parents=True, exist_ok=True)

# Clear stale *.db files so the client doesn’t choke on leftovers
for p in pathlib.Path(mp).glob("*.db"):
    try:
        p.unlink()
    except OSError:
        # Best-effort cleanup; stale files will be overwritten as new workers register.
        continue
