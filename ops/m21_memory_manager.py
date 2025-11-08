#!/usr/bin/env python3
"""
ops/m21_memory_manager.py — Distributed Memory & Model Lineage

Archives every versioned model, policy, and calibration into permanent storage,
creating a complete ancestral chain of evolutionary development.

This provides the organism with:
- Permanent memory of every self-state
- Lineage tracing capabilities
- Performance evolution visualization
- Rollback capabilities to historical configurations
- Learning from ancestral success patterns

Memory Vault Structure:
data/memory_vault/
├── v-20250101T120000/
│   ├── model.joblib
│   └── meta.json
├── v-20250102T150000/
│   ├── model.joblib
│   └── meta.json
└── lineage_index.json (global index)
"""

import hashlib
import json
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

MEMORY_ROOT = os.path.join("data", "memory_vault")
INDEX_PATH = os.path.join(MEMORY_ROOT, "lineage_index.json")
os.makedirs(MEMORY_ROOT, exist_ok=True)


def generate_fingerprint(file_path: str) -> Optional[str]:
    """
    Generate SHA-256 fingerprint for file integrity verification.

    Args:
        file_path: Path to the file to fingerprint

    Returns:
        First 16 hex characters of SHA-256 hash, or None if file not found
    """
    if not os.path.exists(file_path):
        return None

    try:
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read in 64KB chunks to handle large model files efficiently
            for chunk in iter(lambda: f.read(65536), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()[:16]
    except Exception as e:
        print(f"⚠️  Failed to fingerprint {file_path}: {e}")
        return None


def load_lineage_index() -> Dict[str, Any]:
    """
    Load the global lineage index from JSON file.

    Creates default structure if no index exists.

    Returns:
        Lineage index structure with models array
    """
    if os.path.exists(INDEX_PATH):
        try:
            with open(INDEX_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  Failed to load lineage index: {e}")

    # Initialize fresh index
    return {
        "created_at": datetime.utcnow().isoformat(),
        "memory_manager_version": "M21",
        "total_archived": 0,
        "models": [],
    }


def save_lineage_index(index: Dict[str, Any]) -> None:
    """
    Persist the lineage index to disk.

    Args:
        index: Lineage index dictionary to save
    """
    try:
        index["updated_at"] = datetime.utcnow().isoformat()
        index["total_archived"] = len(index.get("models", []))

        with open(INDEX_PATH, "w") as f:
            json.dump(index, f, indent=2, default=str)
    except Exception as e:
        print(f"⚠️  Failed to save lineage index: {e}")


def find_recent_models(model_store_dir: str = None, limit: int = 5) -> List[str]:
    """
    Find recently created model files in the model store.

    Args:
        model_store_dir: Directory to search (defaults to ml_service/model_store)
        limit: Maximum number of files to return

    Returns:
        List of recent .joblib file paths, most recent first
    """
    if model_store_dir is None:
        model_store_dir = os.path.join("ml_service", "model_store")

    if not os.path.exists(model_store_dir):
        print(f"⚠️  Model store not found: {model_store_dir}")
        return []

    # Find all .joblib files
    all_models = []
    for filename in os.listdir(model_store_dir):
        if filename.endswith(".joblib"):
            filepath = os.path.join(model_store_dir, filename)
            if os.path.isfile(filepath):
                # Get modification time for sorting
                mtime = os.path.getmtime(filepath)
                all_models.append((filepath, mtime))

    # Sort by modification time, most recent first
    all_models.sort(key=lambda x: x[1], reverse=True)

    return [path for path, _ in all_models[:limit]]


def extract_model_tag(model_path: str) -> str:
    """
    Extract or generate a model tag from file path.

    Args:
        model_path: Path to the model file

    Returns:
        Model tag (e.g., 'v-20250101T120000')
    """
    basename = os.path.basename(model_path)
    if basename.startswith("policy_"):
        # Extract timestamp from policy_v-YYYYMMDDTHHMMSS.joblib
        tag_part = basename.replace("policy_", "").replace(".joblib", "")
        if tag_part.startswith("v-"):
            return tag_part

    # Generate new tag if not recoverable
    return datetime.utcnow().strftime("v-%Y%m%dT%H%M%S")


def archive_model(source_path: str, metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Create a permanent fossil of the model in memory vault.

    Args:
        source_path: Path to the model file to archive
        metadata: Model metadata (tag, performance metrics, ancestry)

    Returns:
        Enriched metadata with archive paths and fingerprints, or None if failed
    """
    if not os.path.exists(source_path):
        print(f"⚠️  Model source not found: {source_path}")
        return None

    try:
        # Determine archive location
        tag = metadata.get("tag") or extract_model_tag(source_path)
        archive_dir = os.path.join(MEMORY_ROOT, tag)
        os.makedirs(archive_dir, exist_ok=True)

        # Copy model file
        filename = f"{tag}.joblib"
        dest_path = os.path.join(archive_dir, filename)
        shutil.copy2(source_path, dest_path)

        # Generate fingerprint for integrity checking
        fingerprint = generate_fingerprint(dest_path)

        # Create metadata file
        meta_path = os.path.join(archive_dir, "metadata.json")
        meta_info = {
            **metadata,
            "archived_at": datetime.utcnow().isoformat(),
            "file_size_bytes": os.path.getsize(dest_path),
            "fingerprint_sha256_16": fingerprint,
            "original_path": source_path,
            "archived_path": dest_path,
            "metadata_path": meta_path,
        }

        with open(meta_path, "w") as f:
            json.dump(meta_info, f, indent=2, default=str)

        print("✅ Model fossilized:")
        print(f"   Tag: {tag}")
        print(f"   Location: {archive_dir}")
        print(f"   Fingerprint: {fingerprint}")

        return meta_info

    except Exception as e:
        print(f"❌ Failed to archive model {source_path}: {e}")
        return None


def update_lineage(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add the archived model to the global lineage index.

    Args:
        metadata: Archived model metadata

    Returns:
        Updated lineage index
    """
    index = load_lineage_index()

    # Prevent duplicates based on fingerprint
    fingerprint = metadata.get("fingerprint_sha256_16")
    if fingerprint:
        existing = [m for m in index["models"] if m.get("fingerprint_sha256_16") == fingerprint]
        if existing:
            print(f"🔄 Model already archived (fingerprint: {fingerprint})")
            return index

    # Add new entry
    index["models"].append(metadata)
    save_lineage_index(index)

    print(f"🧬 Added to lineage (total: {len(index['models'])} fossils)")

    return index


def collect_model_context() -> Dict[str, Any]:
    """
    Gather context information about the current model training environment.

    Collects performance snapshots, configuration state, and operational metrics.

    Returns:
        Context dictionary with environment and performance data
    """
    context = {
        "timestamp": datetime.utcnow().isoformat(),
        "hostname": os.environ.get("HOSTNAME", "unknown"),
        "training_environment": {},
        "performance_snapshot": {},
        "ancestor_info": {},
    }

    # Training environment context
    context["training_environment"] = {
        "python_version": os.sys.version.split()[0],
        "working_directory": os.getcwd(),
        "environment_variables": {
            k: v
            for k, v in os.environ.items()
            if k.startswith(("M1", "TRAIN", "POLICY", "CALIBRATE"))
        },
    }

    # Performance snapshot from environment or logs
    context["performance_snapshot"] = {
        "pnl_last": float(os.environ.get("PNL_LAST", "0")),
        "winrate_last": float(os.environ.get("WINRATE_LAST", "0")),
        "drawdown_max": float(os.environ.get("DRAWDOWN_MAX", "0")),
        "trade_count": int(os.environ.get("TRADE_COUNT", "0")),
        "sharp_ratio": float(os.environ.get("SHARP_RATIO", "0")),
    }

    # Ancestor lineage information
    context["ancestor_info"] = {
        "parent_tag": os.environ.get("PARENT_TAG", ""),
        "reinforcement_cycles": int(os.environ.get("REINFORCEMENT_CYCLES", "0")),
        "calibration_cycles": int(os.environ.get("CALIBRATION_CYCLES", "0")),
    }

    return context


def archive_new_generation(notes: str = None) -> Optional[Dict[str, Any]]:
    """
    Archive the most recent model as a new evolutionary generation.

    This is the primary entry point for continuous archiving.

    Args:
        notes: Optional human-readable notes about this generation

    Returns:
        Complete fossil record if archived, None if not
    """
    print("🧬 M21 Memory Manager: Archiving new generation...")

    # Find most recent model
    recent_models = find_recent_models()
    if not recent_models:
        print("ℹ️  No models found to archive")
        return None

    latest_model = recent_models[0]
    print(f"📁 Processing: {os.path.basename(latest_model)}")

    # Collect context metadata
    context = collect_model_context()

    # Build complete metadata
    metadata = {
        **context,
        "tag": extract_model_tag(latest_model),
        "source_path": latest_model,
        "memory_system": "M21",
        "notes": notes or os.environ.get("MEMO", "auto archived generation"),
        "generation_type": os.environ.get("GENERATION_TYPE", "unknown"),  # M15/M16/M17/etc.
    }

    # Archive the model
    archived = archive_model(latest_model, metadata)
    if not archived:
        return None

    # Update global lineage
    update_lineage(archived)

    return archived


def find_ancestor(tag_or_fingerprint: str) -> Optional[Dict[str, Any]]:
    """
    Locate a specific ancestral fossil by tag or fingerprint.

    Args:
        tag_or_fingerprint: Tag (e.g., 'v-20250101T120000') or fingerprint

    Returns:
        Ancestor metadata if found, None otherwise
    """
    index = load_lineage_index()

    for model in index["models"]:
        if (
            model.get("tag") == tag_or_fingerprint
            or model.get("fingerprint_sha256_16") == tag_or_fingerprint
        ):
            return model

    return None


def unlock_model_ancestor(tag_or_fingerprint: str, restore_dir: str = None) -> Optional[str]:
    """
    Duplicate an ancestor model for testing or rollback.

    Args:
        tag_or_fingerprint: Which ancestor to unlock
        restore_dir: Directory to restore to (defaults to temp directory)

    Returns:
        Path to unlocked model file, or None if not found
    """
    ancestor = find_ancestor(tag_or_fingerprint)
    if not ancestor:
        print(f"❌ Ancestor not found: {tag_or_fingerprint}")
        return None

    archived_path = ancestor.get("archived_path")
    if not os.path.exists(archived_path):
        print(f"❌ Archived model missing: {archived_path}")
        return None

    # Determine restore location
    if restore_dir is None:
        restore_dir = os.path.join("data", "memory_vault", "unlocked")
    os.makedirs(restore_dir, exist_ok=True)

    # Generate unlocked filename
    original_filename = os.path.basename(archived_path)
    unlocked_filename = f"unlocked_{original_filename}"
    unlocked_path = os.path.join(restore_dir, unlocked_filename)

    # Copy the fossil
    shutil.copy2(archived_path, unlocked_path)

    print(f"🗝  Ancestor unlocked: {tag_or_fingerprint} → {unlocked_path}")
    return unlocked_path


def analyze_lineage() -> Dict[str, Any]:
    """
    Generate analytical insights about the evolutionary lineage.

    Returns:
        Statistics about model evolution and performance trends
    """
    index = load_lineage_index()

    if not index["models"]:
        return {"status": "no_data", "message": "No archived models found"}

    # Basic statistics
    stats = {
        "total_generations": len(index["models"]),
        "time_span_days": None,
        "performance_trends": {},
        "generation_types": {},
        "improvement_rate": None,
    }

    # Calculate time span
    if len(index["models"]) > 1:
        timestamps = [
            datetime.fromisoformat(m.get("timestamp", m.get("archived_at", "")))
            for m in index["models"]
            if m.get("timestamp", m.get("archived_at"))
        ]
        if timestamps:
            time_span = max(timestamps) - min(timestamps)
            stats["time_span_days"] = time_span.days

    # Analyze performance trends
    pnl_values = [m.get("performance_snapshot", {}).get("pnl_last", 0) for m in index["models"]]
    winrate_values = [
        m.get("performance_snapshot", {}).get("winrate_last", 0) for m in index["models"]
    ]

    if pnl_values:
        stats["performance_trends"]["pnl_range"] = [min(pnl_values), max(pnl_values)]
        stats["performance_trends"]["pnl_improvement"] = pnl_values[-1] - pnl_values[0]

    if winrate_values:
        stats["performance_trends"]["winrate_range"] = [min(winrate_values), max(winrate_values)]
        stats["performance_trends"]["winrate_improvement"] = winrate_values[-1] - winrate_values[0]

    # Count generation types (M15/M16/etc.)
    for model in index["models"]:
        gen_type = model.get("generation_type", "unknown")
        stats["generation_types"][gen_type] = stats["generation_types"].get(gen_type, 0) + 1

    return stats


if __name__ == "__main__":
    # Archive new generation when run directly
    notes = " ".join(os.sys.argv[1:]) if len(os.sys.argv) > 1 else None

    result = archive_new_generation(notes)

    if result:
        print("\n--")
        print("✅ Generation archived successfully")
        print(f"   Tag: {result['tag']}")
        print(f"   Fingerprint: {result.get('fingerprint_sha256_16', 'none')}")
        print(f"   Unique ID: {result['fingerprint_sha256_16'] or result['tag']}")
        print(f"   Ancestor: {result.get('ancestor_info', {}).get('parent_tag', 'origin')}")

        # Show lineage stats
        lineage_analysis = analyze_lineage()
        if lineage_analysis.get("total_generations"):
            print("📊 Lineage status:")
            print(f"   Total generations: {lineage_analysis['total_generations']}")
            if lineage_analysis.get("performance_trends", {}).get("pnl_improvement") is not None:
                improvement = lineage_analysis["performance_trends"]["pnl_improvement"]
                print(f"   PnL Evolution: {improvement:+.2f} USD")
    else:
        print("❌ No new generation to archive")
        os.sys.exit(1)
