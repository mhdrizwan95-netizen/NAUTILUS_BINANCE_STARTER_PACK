import os
import json
import time
import shutil
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
from joblib import dump, load
from loguru import logger
from .config import settings

# Version directories look like: {REGISTRY_DIR}/2025-10-31T12-00-00Z__hmm4__hash/
# Inside each version dir:
#   - model.joblib
#   - scaler.joblib
#   - metadata.json
# The CURRENT_SYMLINK points to a chosen version dir.
# A version.txt file is touched on promotion to trigger file watchers cleanly.


def _registry() -> Path:
    p = Path(settings.REGISTRY_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _current_symlink() -> Path:
    return Path(settings.CURRENT_SYMLINK)


def save_version(model, scaler, metadata: Dict[str, Any]) -> Path:
    ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    version_id = f"{ts}__hmm{metadata.get('n_states', 'x')}"
    version_dir = _registry() / version_id
    version_dir.mkdir(parents=True, exist_ok=True)

    dump(model, version_dir / "model.joblib")
    dump(scaler, version_dir / "scaler.joblib")
    (version_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    logger.info(f"Saved model version {version_id} -> {version_dir}")
    return version_dir


def read_metadata(version_dir: Path) -> Dict[str, Any]:
    try:
        return json.loads((version_dir / "metadata.json").read_text())
    except Exception:
        return {}


def promote(version_dir: Path) -> str:
    cur = _current_symlink()
    if cur.is_symlink() or cur.exists():
        cur.unlink()
    target = version_dir.resolve()
    cur.symlink_to(target, target_is_directory=True)
    # Touch a file to signal watchers
    (target / "version.txt").write_text(str(time.time()))
    logger.info(f"Promoted {target.name} to current")
    return target.name


def get_current_paths() -> Optional[Tuple[Path, Path, Path]]:
    cur = _current_symlink()
    if not cur.exists():
        return None
    model_p = cur / "model.joblib"
    scaler_p = cur / "scaler.joblib"
    meta_p = cur / "metadata.json"
    if model_p.exists() and scaler_p.exists():
        return model_p, scaler_p, meta_p
    return None


def load_current():
    paths = get_current_paths()
    if not paths:
        return None, None, {}
    from joblib import load
    model = load(paths[0])
    scaler = load(paths[1])
    meta = json.loads(paths[2].read_text()) if paths[2].exists() else {}
    return model, scaler, meta


def registry_size() -> int:
    return len([p for p in _registry().glob("*") if p.is_dir()])


def top_versions(n: int = 1):
    return sorted([p for p in _registry().glob("*") if p.is_dir()], reverse=True)[:n]


def prune_keep_last(n_keep: int = 5):
    all_versions = sorted([p for p in _registry().glob("*") if p.is_dir()])
    to_remove = all_versions[:-n_keep] if len(all_versions) > n_keep else []
    for p in to_remove:
        shutil.rmtree(p, ignore_errors=True)
        logger.info(f"Pruned old model version {p.name}")
