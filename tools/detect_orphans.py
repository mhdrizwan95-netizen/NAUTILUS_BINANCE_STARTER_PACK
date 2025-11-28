import os
import ast
import sys
from pathlib import Path

# 1. Define the "Roots" of your application (Entry Points)
# These are the files that kick off the processes.
ROOTS = [
    "engine/app.py",
    "ops/main.py",
    "services/ml_service/app/main.py",
    "services/param_controller/app/main.py",
    "services/data_ingester/app/main.py",
    "scripts/verify_live_readiness.py",  # Keep your verification script
    "sitecustomize.py", # Keep python startup file
]

# 2. Define "Dynamic Zones" (Folders where files are loaded dynamically, not imported)
# Strategies are often loaded by string name from config, so static analysis might miss them.
KEEP_PREFIXES = {
    "engine/strategies",  # Keep all strategies
    "engine/db/migrations", # Keep DB migrations
    "tests",              # Keep tests
    "tools",              # Keep tools (including this one)
}

def get_imports(file_path):
    """Parse a Python file and extract all imported module names."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=file_path)
    except Exception:
        return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
                for alias in node.names:
                    imports.add(f"{node.module}.{alias.name}")
    return imports

def resolve_path(module_name, base_path):
    """Convert a module name (engine.core.risk) to a file path (engine/core/risk.py)."""
    parts = module_name.split(".")
    
    # Try as a file
    candidate = Path(*parts).with_suffix(".py")
    if candidate.exists(): return candidate
    
    # Try as a package
    candidate_pkg = Path(*parts) / "__init__.py"
    if candidate_pkg.exists(): return candidate_pkg
    
    return None

def scan_codebase():
    print("🔍 Scanning codebase dependencies...")
    queue = [Path(r) for r in ROOTS if Path(r).exists()]
    visited = set(queue)
    
    # BFS to find all reachable code
    while queue:
        current = queue.pop(0)
        
        # If it's a package __init__, consider the parent dir reached
        if current.name == "__init__.py":
            search_dir = current.parent
        else:
            search_dir = current.parent

        # Naive import resolution
        raw_imports = get_imports(current)
        for imp in raw_imports:
            # Resolve local imports relative to project root
            target = resolve_path(imp, Path("."))
            if target and target not in visited:
                visited.add(target)
                queue.append(target)

    # Find all Python files on disk
    all_files = set(Path(".").rglob("*.py"))
    
    # Calculate Orphans
    orphans = []
    for file in all_files:
        # Skip hidden folders and venv
        if any(part.startswith(".") for part in file.parts): continue
        if "venv" in file.parts or "node_modules" in file.parts: continue
        
        # Check if visited
        if file not in visited:
            # Check if in a "Keep" zone
            str_path = str(file).replace("\\", "/")
            if any(str_path.startswith(k) for k in KEEP_PREFIXES):
                continue
            orphans.append(file)

    return sorted(list(visited)), sorted(orphans)

if __name__ == "__main__":
    kept, orphans = scan_codebase()
    
    print(f"\n✅ KEPT {len(kept)} active files.")
    print(f"\n💀 FOUND {len(orphans)} ORPHAN FILES (Dead Code):")
    for o in orphans:
        print(f"  {o}")

    if orphans:
        # Check for non-interactive mode via env var or just wait for input
        # Modified for automation: check if input is piped or just proceed if env var set
        if os.environ.get("AUTO_PURGE") == "true":
            confirm = "PURGE"
        else:
            try:
                confirm = input("\nType 'PURGE' to delete these files: ")
            except EOFError:
                confirm = ""
                
        if confirm == "PURGE":
            for o in orphans:
                os.remove(o)
                print(f"  Deleted {o}")
            print("✨ Cleanup complete.")
