import json
import shutil
import time
from pathlib import Path
from typing import Any

from joblib import dump, load
from loguru import logger

from .config import settings


def _registry() -> Path:
    p = Path(settings.REGISTRY_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _current_symlink() -> Path:
    return Path(settings.CURRENT_SYMLINK)


def save_version(model, scaler, metadata: dict[str, Any]) -> Path:
    ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    version_id = f"{ts}__hmm{metadata.get('n_states','x')}"
    version_dir = _registry() / version_id
    version_dir.mkdir(parents=True, exist_ok=True)
    metadata = dict(metadata)
    metadata.setdefault("version_id", version_id)
    dump(model, version_dir / "model.joblib")
    dump(scaler, version_dir / "scaler.joblib")
    import pickle

    with open(version_dir / "hmm_model.pkl", "wb") as f:
        pickle.dump({"model": model, "scaler": scaler}, f)
    (version_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    logger.info(f"Saved model version {version_id}")
    return version_dir


def load_current():
    cur = _current_symlink()
    if not cur.exists():
        return None, None, {}
    model_p, scaler_p, meta_p = (
        cur / "model.joblib",
        cur / "scaler.joblib",
        cur / "metadata.json",
    )
    if not model_p.exists() or not scaler_p.exists():
        return None, None, {}
    return (
        load(model_p),
        load(scaler_p),
        json.loads(meta_p.read_text()) if meta_p.exists() else {},
    )


def registry_size() -> int:
    return sum(1 for p in _registry().glob("*") if p.is_dir())


def promote(version_dir: Path) -> str:
    cur = _current_symlink()
    if cur.is_symlink() or cur.exists():
        try:
            cur.unlink()
        except OSError as exc:
            logger.warning("Failed to remove current symlink %s: %s", cur, exc, exc_info=True)
    target = version_dir.resolve()
    # Use relative path for symlink to work across containers with different mount points
    rel_target = target.relative_to(cur.parent)
    cur.symlink_to(rel_target, target_is_directory=True)
    (target / "version.txt").write_text(str(time.time()))
    logger.info(f"Promoted {target.name}")
    return target.name


def prune_keep_last(n: int = 5):
    allv = sorted([p for p in _registry().glob("*") if p.is_dir()])
    for p in allv[:-n]:
        shutil.rmtree(p, ignore_errors=True)
