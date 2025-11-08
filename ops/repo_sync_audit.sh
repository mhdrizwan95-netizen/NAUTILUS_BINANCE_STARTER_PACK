#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="${ROOT}/audit/reports"
mkdir -p "${REPORT_DIR}"

REPO_ROOT="${ROOT}" python3 <<'PY'
import json
import os
import re
import subprocess
from pathlib import Path
root = Path(os.environ["REPO_ROOT"]).resolve()
report_dir = root / "audit" / "reports"
report_dir.mkdir(parents=True, exist_ok=True)

def write(path: Path, contents: str) -> None:
    path.write_text(contents.rstrip() + "\n", encoding="utf-8")

# ---------- Frontend vs backend endpoints ----------
fe_endpoints: set[str] = set()
frontend_src = root / "frontend" / "src"
pattern = re.compile(r'"/api/[A-Za-z0-9_./-]*"')
for file in frontend_src.rglob("*.ts*"):
    try:
        text = file.read_text(encoding="utf-8")
    except Exception:
        continue
    for match in pattern.findall(text):
        fe_endpoints.add(match.strip('"'))

backend_routes: set[str] = set()
ops_api = root / "ops" / "ops_api.py"
route_regex = re.compile(r'@APP\.(?:get|post|put|delete|patch)\("([^"]+)"\)')
if ops_api.exists():
    text = ops_api.read_text(encoding="utf-8")
    backend_routes.update(route_regex.findall(text))

missing_on_server = sorted(fe_endpoints - backend_routes)
unused_routes = sorted(backend_routes - fe_endpoints)
fe_be_report = [
    "# Frontend ↔ Backend route diff",
    "",
    "## API paths referenced by the frontend but not exposed by `ops/ops_api.py`",
    "",
]
fe_be_report.extend(f"- `{path}`" for path in missing_on_server or ["(none detected)"])
fe_be_report += ["", "## Backend routes with no frontend caller", ""]
fe_be_report.extend(f"- `{path}`" for path in unused_routes or ["(none detected)"])
write(report_dir / "fe_be_diff.md", "\n".join(fe_be_report))

# ---------- Python orphan heuristic ----------
orphan_modules: list[str] = []
services_dir = root / "services"
py_files = [p for p in services_dir.rglob("*.py") if "__init__" not in p.parts and "tests" not in p.parts]
for file in py_files:
    rel = file.relative_to(root)
    module_name = ".".join(rel.with_suffix("").parts)
    try:
        result = subprocess.run(
            ["rg", "--files-with-matches", module_name, "--iglob", "*.py", "--glob", f"!{rel}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        break
    matches = [Path(line) for line in result.stdout.strip().splitlines() if line.strip()]
    if not matches:
        orphan_modules.append(module_name)
write(
    report_dir / "python_orphans.txt",
    "\n".join(orphan_modules) if orphan_modules else "No obvious orphan modules detected.",
)

# ---------- Config drift ----------
env_example = root / "env.example"
example_keys: set[str] = set()
if env_example.exists():
    for line in env_example.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        example_keys.add(key)

code_keys: set[str] = set()
env_pattern = re.compile(r"os\\.(?:getenv|environ\\.get)\\(\\s*[\"']([^\"']+)[\"']\\)")
for file in root.rglob("*.py"):
    if "venv" in file.parts or "tests" in file.parts:
        continue
    try:
        text = file.read_text(encoding="utf-8")
    except Exception:
        continue
    code_keys.update(env_pattern.findall(text))

missing_in_example = sorted(code_keys - example_keys)
unused_keys = sorted(example_keys - code_keys)
config_lines = [
    "# Config drift report",
    "",
    "## Keys used in code but absent from env.example",
]
config_lines.extend(f"- `{key}`" for key in missing_in_example or ["(none detected)"])
config_lines += ["", "## Keys defined in env.example but not referenced in code", ""]
config_lines.extend(f"- `{key}`" for key in unused_keys or ["(none detected)"])
write(report_dir / "config_drift.md", "\n".join(config_lines))

# ---------- Control plane guardrails ----------
control_gaps: list[str] = []
if ops_api.exists():
    lines = ops_api.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("@APP."):
            decorators = []
            while line.startswith("@"):
                decorators.append(line)
                i += 1
                line = lines[i].strip()
            if line.startswith("async def") or line.startswith("def"):
                func_name = line.split("(")[0].split()[-1]
                guard_present = any(
                    token in dec for dec in decorators for token in ("require_ops_token", "require_role")
                )
                if not guard_present:
                    control_gaps.append(func_name)
        else:
            i += 1
    if not control_gaps:
        control_gaps.append("(all routes enforce an ops token or role guard)")
write(
    report_dir / "control_plane_gaps.md",
    "# Control plane guardrails\n\n" + "\n".join(f"- `{name}`" for name in control_gaps),
)
PY
