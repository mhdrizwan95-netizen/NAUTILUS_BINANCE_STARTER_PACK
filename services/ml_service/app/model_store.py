"""Model storage and registry for HMM models."""

import json
import os
import pickle
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


# Model storage paths
MODELS_DIR = Path(os.getenv("MODELS_DIR", "/models"))
ACTIVE_LINK = MODELS_DIR / "active_hmm_policy.pkl"
REGISTRY_FILE = MODELS_DIR / "registry.json"


def _ensure_dirs() -> None:
    """Ensure model directories exist."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)


def load_current() -> tuple[Any, Any, dict | None]:
    """Load the currently active model, scaler, and metadata.
    
    Returns:
        Tuple of (model, scaler, metadata). May return (None, None, None) if no model.
    """
    _ensure_dirs()
    
    if not ACTIVE_LINK.exists():
        return None, None, None
    
    try:
        with open(ACTIVE_LINK, "rb") as f:
            data = pickle.load(f)
        
        if isinstance(data, dict):
            return data.get("model"), data.get("scaler"), data.get("metadata", {})
        
        # Legacy format: just the model
        return data, None, {"version_id": "legacy"}
    except Exception:
        return None, None, None


def save_model(
    model: Any,
    scaler: Any = None,
    metadata: dict | None = None,
    tag: str = "v1",
    promote: bool = True,
) -> str:
    """Save a trained model to the registry.
    
    Args:
        model: The trained HMM model
        scaler: Optional feature scaler
        metadata: Optional training metadata
        tag: Version tag
        promote: If True, make this the active model
        
    Returns:
        Version directory path
    """
    _ensure_dirs()
    
    # Create version directory
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    version_id = f"{tag}_{timestamp}"
    version_dir = MODELS_DIR / version_id
    version_dir.mkdir(parents=True, exist_ok=True)
    
    # Save model bundle
    bundle = {
        "model": model,
        "scaler": scaler,
        "metadata": metadata or {},
    }
    bundle["metadata"]["version_id"] = version_id
    bundle["metadata"]["created_at"] = timestamp
    
    model_path = version_dir / "model.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(bundle, f)
    
    # Update registry
    registry = _load_registry()
    registry["versions"].append({
        "version_id": version_id,
        "path": str(model_path),
        "created_at": timestamp,
        "metrics": metadata.get("metrics", {}) if metadata else {},
    })
    _save_registry(registry)
    
    # Promote to active if requested
    if promote:
        promote_version(version_id)
    
    return str(version_dir)


def promote_version(version_id: str) -> bool:
    """Promote a version to be the active model.
    
    Args:
        version_id: The version to promote
        
    Returns:
        True if successful
    """
    version_dir = MODELS_DIR / version_id
    model_path = version_dir / "model.pkl"
    
    if not model_path.exists():
        return False
    
    # Copy to active link location
    shutil.copy(model_path, ACTIVE_LINK)
    
    # Update registry
    registry = _load_registry()
    registry["active"] = version_id
    _save_registry(registry)
    
    return True


def registry_size() -> int:
    """Get the number of models in the registry."""
    registry = _load_registry()


def get_history(limit: int = 50, cursor: str | None = None) -> list[dict]:
    """Get model history from registry.
    
    Args:
        limit: Max number of items
        cursor: Pagination cursor (simple offset logic or timestamp)
        
    Returns:
        List of version dicts
    """
    registry = _load_registry()
    versions = registry.get("versions", [])
    # Sort by created_at descending (newest first)
    versions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    # Basic pagination logic (slice)
    # If cursor provided, find index? For now, just slice.
    return versions[:limit]


def _load_registry() -> dict:
    """Load the model registry."""
    _ensure_dirs()
    
    if not REGISTRY_FILE.exists():
        return {"versions": [], "active": None}
    
    try:
        with open(REGISTRY_FILE) as f:
            return json.load(f)
    except Exception:
        return {"versions": [], "active": None}


def _save_registry(registry: dict) -> None:
    """Save the model registry."""
    _ensure_dirs()
    
    with open(REGISTRY_FILE, "w") as f:
        json.dump(registry, f, indent=2)
